"""Company and director registry (MCA) linkage for merchant onboarding.

A payment aggregator onboards companies, not just VPAs. A mule network that has been
caught once comes back as a fresh private limited company: new CIN, new settlement
account, same directors, often the same registered address. The transaction graph
cannot see that link until money moves; the registry can see it on day one.

What is loaded (nothing ships with the repo; the registry starts empty):

  companies      MCA company master data, as published per state on data.gov.in
                 ("Company Master Data"). Headers of the data.gov.in download
                 (CORPORATE_IDENTIFICATION_NUMBER, COMPANY_STATUS, PAIDUP_CAPITAL,
                 REGISTERED_OFFICE_ADDRESS, ...) and the newer OGD naming (CIN,
                 CompanyName, CompanyStatus, PaidupCapital, ...) are both read.
  directorships  CIN-DIN pairs with designation and appointment / cessation dates.
                 MCA does not publish these in bulk: they come from MCA21 "View
                 Signatory Details" or a data vendor's export. Common header
                 spellings are accepted (see ALIASES).
  disqualified   DINs disqualified under section 164(2) of the Companies Act, from the
                 lists the ROCs publish.
  accounts       CIN -> settlement VPA / account, from the aggregator's own merchant
                 records. This is the bridge to the rail: onboarding can record it.

    python -m infra.registry load companies     Company_Master_Maharashtra.csv
    python -m infra.registry load directorships signatories.csv
    python -m infra.registry load disqualified  disqualified_directors.csv
    python -m infra.registry load accounts      merchant_settlement_accounts.csv
    python -m infra.registry status
    python -m infra.registry report U72900MH2021PTC123456

Live lookups (MCA_PROVIDER=http): on a cache miss, GET {MCA_API_URL}/companies/{cin}
and GET {MCA_API_URL}/directors/{din}, with Authorization: Bearer MCA_API_KEY. Answers
are stored like a file import (source "api"). The expected JSON is documented on
fetch_company / fetch_director; a vendor whose API differs needs a small shim that maps
to it. No vendor API has been called from this code yet.

Checks, and why each one points at shells (thresholds are constants below):

  company       struck off / dormant / under strike-off; incorporated in the last
                YOUNG_DAYS; paid-up capital at or under LOW_PAID_UP; no annual return
                for STALE_FILING_YEARS; no current director on record.
  director      disqualified under s.164; more current directorships than the
                s.165 limit of 20 (or BUSY_DIRECTOR, a softer signal).
  structure     other companies at the same registered address (ADDRESS_FARM);
                companies sharing two or more current directors with this one
                (common control), especially when incorporated within BATCH_DAYS
                of each other.
  rail          a company linked through a shared director or address whose
                settlement VPA is under alert, held or frozen in the engine.

Severity -> recommendation: any high -> hold; otherwise any medium -> review;
otherwise approve. Low findings are shown but never change the decision on their own.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import requests
from sqlalchemy import Column, Date, Float, Integer, String, Table, Text, and_, func, insert, select, update

from . import settings
from .store import Store, get_store, metadata

YOUNG_DAYS = 180
LOW_PAID_UP = 100_000.0  # rupees
STALE_FILING_YEARS = 2
DIRECTOR_LIMIT = 20  # Companies Act 2013, s.165(1)
BUSY_DIRECTOR = 10
ADDRESS_FARM = 5  # companies at one registered address, this one included
ADDRESS_FARM_HIGH = 20
BATCH_DAYS = 365
API_TTL_SECONDS = 7 * 24 * 3600

INACTIVE = {
    "strike off": "high", "struck off": "high", "under process of striking off": "high", "dormant": "medium",
    "dissolved": "high", "liquidated": "high", "under liquidation": "high", "converted to llp": "low",
    "amalgamated": "low", "not available for efiling": "medium",
}

companies = Table(
    "mca_companies", metadata,
    Column("cin", String(25), primary_key=True),
    Column("name", String(300)),
    Column("status", String(80)),
    Column("company_class", String(40)),
    Column("category", String(80)),
    Column("sub_category", String(80)),
    Column("incorporated_on", Date),
    Column("state", String(60)),
    Column("roc", String(60)),
    Column("authorized_capital", Float),
    Column("paid_up_capital", Float),
    Column("activity", String(300)),
    Column("address", Text),
    Column("address_key", String(300), index=True),
    Column("email", String(200)),
    Column("last_annual_return", Integer),
    Column("source", String(200)),
    Column("updated_at", Float),
)

directors = Table(
    "mca_directors", metadata,
    Column("din", String(12), primary_key=True),
    Column("name", String(200)),
    Column("disqualified", Integer, nullable=False, default=0),
    Column("disqualified_note", String(300)),
    Column("source", String(200)),
    Column("fetched_at", Float),  # last live lookup of this director's companies
    Column("updated_at", Float),
)

directorships = Table(
    "mca_directorships", metadata,
    Column("cin", String(25), primary_key=True),
    Column("din", String(12), primary_key=True, index=True),
    Column("designation", String(80)),
    Column("appointed_on", Date),
    Column("ceased_on", Date),
    Column("source", String(200)),
    Column("updated_at", Float),
)

entity_accounts = Table(
    "mca_entity_accounts", metadata,
    Column("cin", String(25), primary_key=True),
    Column("vpa", String(120), primary_key=True, index=True),
    Column("account_id", String(64)),
    Column("source", String(200)),
    Column("updated_at", Float),
)

imports = Table(
    "mca_imports", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", String(20), nullable=False),
    Column("source", String(300)),
    Column("rows_read", Integer),
    Column("rows_loaded", Integer),
    Column("rows_skipped", Integer),
    Column("errors", Text),
    Column("at", Float, nullable=False),
)

# Header spellings seen in MCA / data.gov.in downloads and vendor exports. Matched after
# lower-casing and dropping everything but letters and digits.
ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "companies": {
        "cin": ("corporateidentificationnumber", "cin", "llpin", "companycin"),
        "name": ("companyname", "name", "nameofcompany"),
        "status": ("companystatus", "status", "companystatusforefiling"),
        "company_class": ("companyclass", "class", "classofcompany"),
        "category": ("companycategory", "category"),
        "sub_category": ("companysubcategory", "subcategory"),
        "incorporated_on": ("dateofregistration", "companyregistrationdatedate", "dateofincorporation", "registrationdate", "incorporationdate"),
        "state": ("registeredstate", "companystatecode", "state"),
        "roc": ("registrarofcompanies", "companyroccode", "roc", "roccode"),
        "authorized_capital": ("authorizedcap", "authorizedcapital", "authorisedcapital", "authorisedcapitalrs"),
        "paid_up_capital": ("paidupcapital", "paidupcap", "paidupcapitalrs"),
        "activity": ("principalbusinessactivityaspercin", "principalbusinessactivity", "companyindustrialclassification", "industrialclass", "niccode"),
        "address": ("registeredofficeaddress", "registeredaddress", "address"),
        "email": ("emailaddr", "email", "emailid"),
        "last_annual_return": ("latestyearannualreturn", "dateoflastagm", "lastannualreturn"),
    },
    "directorships": {
        "cin": ("cin", "corporateidentificationnumber", "llpin", "companycin"),
        "din": ("din", "dinpan", "dpin", "dindpin", "directoridentificationnumber"),
        "name": ("directorname", "name", "fullname", "nameofdirector"),
        "designation": ("designation", "role"),
        "appointed_on": ("dateofappointment", "appointmentdate", "begindate", "appointedon", "originaldateofappointment"),
        "ceased_on": ("cessationdate", "dateofcessation", "enddate", "ceasedon"),
    },
    "disqualified": {
        "din": ("din", "dinpan", "directoridentificationnumber"),
        "name": ("directorname", "name", "nameofdirector"),
        "note": ("section", "reason", "disqualificationperiod", "periodofdisqualification", "remarks"),
    },
    "accounts": {
        "cin": ("cin", "corporateidentificationnumber", "llpin"),
        "vpa": ("vpa", "settlementvpa", "upiid"),
        "account_id": ("accountid", "account", "settlementaccount"),
    },
}
REQUIRED = {"companies": ("cin",), "directorships": ("cin", "din"), "disqualified": ("din",), "accounts": ("cin", "vpa")}

CIN_RE = re.compile(r"^[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$")
LLPIN_RE = re.compile(r"^[A-Z]{3}-\d{4}$")
_DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d/%m/%y", "%Y/%m/%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S")
_ADDRESS_NOISE = re.compile(r"\b(NO|NUMBER|FLAT|FLOOR|FL|OFFICE|OFF|ROAD|RD|STREET|ST|NEAR|NR|OPP|OPPOSITE|INDIA|IN)\b")


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def normalise_cin(value: Any) -> str:
    return re.sub(r"\s", "", str(value or "")).upper()


def normalise_din(value: Any) -> str:
    """DINs are 8 digits; spreadsheets drop the leading zeros."""
    s = re.sub(r"\s", "", str(value or ""))
    if s.endswith(".0"):
        s = s[:-2]
    return s.zfill(8) if s.isdigit() else s.upper()


def address_key(address: str | None) -> str | None:
    """Uppercase alphanumerics with filler words removed, so '12, M.G. Road, Pune' and
    '12 MG RD PUNE' collide. Deliberately conservative: false merges are worse than misses,
    so a different office or floor number in the same building is a different key."""
    if not address:
        return None
    s = re.sub(r"[^A-Z0-9 ]", " ", address.upper().replace(".", ""))
    s = re.sub(r"\b([A-Z])\s+(?=[A-Z]\b)", r"\1", s)  # 'M G ROAD' -> 'MG ROAD'
    s = _ADDRESS_NOISE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:300] or None


def parse_date(value: Any) -> date | None:
    s = str(value or "").strip()
    if not s or s.upper() in ("NA", "N/A", "-", "NULL", "NONE", "NAN"):
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s[:19], fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(value: Any) -> float | None:
    s = re.sub(r"[^0-9.\-]", "", str(value or ""))
    try:
        return float(s) if s else None
    except ValueError:
        return None


def parse_year(value: Any) -> int | None:
    m = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(m.group(0)) if m else None


def cin_facts(cin: str) -> dict[str, Any]:
    """What the CIN itself says: listed or unlisted, state code, year, company type."""
    if not CIN_RE.match(cin):
        return {"valid": bool(LLPIN_RE.match(cin)), "kind": "llp" if LLPIN_RE.match(cin) else "unknown"}
    return {"valid": True, "kind": "company", "listed": cin[0] == "L", "industry": cin[1:6], "state": cin[6:8], "year": int(cin[8:12]), "type": cin[12:15]}


# ---------------------------------------------------------------------- loading


def _is_file(value: Any) -> bool:
    if isinstance(value, Path):
        return value.exists()
    return isinstance(value, str) and "\n" not in value and len(value) < 260 and Path(value).exists()


def _rows(text_or_path: str | Path | io.TextIOBase, kind: str) -> tuple[Iterator[dict[str, Any]], list[str]]:
    """Map a CSV's headers onto our field names; returns rows and the unmapped headers.
    `text_or_path` is a file path, CSV text, or an open text stream."""
    if _is_file(text_or_path):
        handle: Any = open(text_or_path, newline="", encoding="utf-8-sig", errors="replace")
    elif isinstance(text_or_path, str):
        handle = io.StringIO(text_or_path.lstrip("﻿"))
    else:
        handle = text_or_path
    reader = csv.DictReader(handle)
    lookup = {alias: field for field, names in ALIASES[kind].items() for alias in names}
    mapping: dict[str, str] = {}
    for header in reader.fieldnames or []:
        field = lookup.get(_key(header))
        if field and field not in mapping.values():
            mapping[header] = field
    missing = [f for f in REQUIRED[kind] if f not in mapping.values()]
    if missing:
        raise ValueError(f"{kind}: no column for {', '.join(missing)} (headers: {', '.join(reader.fieldnames or [])})")
    unmapped = [h for h in (reader.fieldnames or []) if h not in mapping]

    def gen() -> Iterator[dict[str, Any]]:
        try:
            for raw in reader:
                yield {field: (raw.get(header) or "").strip() for header, field in mapping.items()}
        finally:
            if handle is not text_or_path:
                handle.close()

    return gen(), unmapped


def _upsert(conn, table: Table, rows: list[dict[str, Any]], keys: tuple[str, ...]) -> None:
    if not rows:
        return
    dialect = conn.engine.dialect.name
    if dialect in ("sqlite", "postgresql"):
        mod = __import__(f"sqlalchemy.dialects.{dialect}", fromlist=["insert"])
        stmt = mod.insert(table)
        cols = {c.name: getattr(stmt.excluded, c.name) for c in table.columns if c.name not in keys and c.name in rows[0]}
        conn.execute(stmt.on_conflict_do_update(index_elements=list(keys), set_=cols) if cols else stmt.on_conflict_do_nothing(index_elements=list(keys)), rows)
        return
    for r in rows:  # other databases: row by row
        where = and_(*(table.c[k] == r[k] for k in keys))
        if conn.execute(update(table).where(where).values(**r)).rowcount == 0:
            conn.execute(insert(table).values(**r))


class Registry:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or get_store()
        self.engine = self.store.engine
        metadata.create_all(self.engine, tables=[companies, directors, directorships, entity_accounts, imports])
        self._api_lock = threading.Lock()
        self.api_errors = 0
        self.last_api_error: str | None = None

    # ------------------------------------------------------------------ imports

    def load(self, kind: str, data: str | Path | io.TextIOBase, source: str | None = None, batch: int = 5000) -> dict[str, Any]:
        if kind not in ALIASES:
            raise ValueError(f"kind must be one of {', '.join(ALIASES)}")
        source = source or (Path(str(data)).name if _is_file(data) else f"upload:{kind}")
        rows, unmapped = _rows(data, kind)
        read = loaded = skipped = 0
        errors: list[str] = []
        pending: list[dict[str, Any]] = []
        now = time.time()

        def flush() -> None:
            nonlocal loaded, pending
            with self.engine.begin() as conn:
                self._write(conn, kind, pending, source, now)
            loaded += len(pending)
            pending = []

        for r in rows:
            read += 1
            try:
                pending.append(self._clean(kind, r))
            except ValueError as error:
                skipped += 1
                if len(errors) < 20:
                    errors.append(f"row {read + 1}: {error}")
                continue
            if len(pending) >= batch:
                flush()
        if pending:
            flush()
        with self.engine.begin() as conn:
            conn.execute(insert(imports).values(kind=kind, source=source, rows_read=read, rows_loaded=loaded, rows_skipped=skipped, errors="\n".join(errors) or None, at=now))
        return {"kind": kind, "source": source, "read": read, "loaded": loaded, "skipped": skipped, "errors": errors, "unmappedColumns": unmapped}

    def _clean(self, kind: str, r: dict[str, Any]) -> dict[str, Any]:
        if kind in ("companies", "directorships", "accounts"):
            cin = normalise_cin(r.get("cin"))
            if not cin_facts(cin)["valid"]:
                raise ValueError(f"not a CIN or LLPIN: {r.get('cin')!r}")
            r["cin"] = cin
        if kind in ("directorships", "disqualified"):
            din = normalise_din(r.get("din"))
            if not din:
                raise ValueError("empty DIN")
            r["din"] = din
        if kind == "companies":
            return {
                "cin": r["cin"], "name": r.get("name") or None, "status": r.get("status") or None, "company_class": r.get("company_class") or None,
                "category": r.get("category") or None, "sub_category": r.get("sub_category") or None,
                "incorporated_on": parse_date(r.get("incorporated_on")), "state": r.get("state") or None, "roc": r.get("roc") or None,
                "authorized_capital": parse_amount(r.get("authorized_capital")), "paid_up_capital": parse_amount(r.get("paid_up_capital")),
                "activity": r.get("activity") or None, "address": r.get("address") or None, "address_key": address_key(r.get("address")),
                "email": (r.get("email") or "").lower() or None, "last_annual_return": parse_year(r.get("last_annual_return")),
            }
        if kind == "directorships":
            return {"cin": r["cin"], "din": r["din"], "name": r.get("name") or None, "designation": r.get("designation") or None,
                    "appointed_on": parse_date(r.get("appointed_on")), "ceased_on": parse_date(r.get("ceased_on"))}
        if kind == "disqualified":
            return {"din": r["din"], "name": r.get("name") or None, "note": r.get("note") or "s.164(2)"}
        vpa = (r.get("vpa") or "").strip().lower()
        if "@" not in vpa:
            raise ValueError(f"not a VPA: {r.get('vpa')!r}")
        return {"cin": r["cin"], "vpa": vpa, "account_id": r.get("account_id") or None}

    def _write(self, conn, kind: str, rows: list[dict[str, Any]], source: str, now: float) -> None:
        if kind == "companies":
            _upsert(conn, companies, [{**r, "source": source, "updated_at": now} for r in rows], ("cin",))
        elif kind == "directorships":
            names = {r["din"]: r["name"] for r in rows if r.get("name")}
            self._ensure_directors(conn, names, source, now)
            _upsert(conn, directorships, [{k: r[k] for k in ("cin", "din", "designation", "appointed_on", "ceased_on")} | {"source": source, "updated_at": now} for r in rows], ("cin", "din"))
        elif kind == "disqualified":
            self._ensure_directors(conn, {r["din"]: r["name"] for r in rows}, source, now)
            for r in rows:
                conn.execute(update(directors).where(directors.c.din == r["din"]).values(disqualified=1, disqualified_note=r["note"], updated_at=now))
        else:
            _upsert(conn, entity_accounts, [{**r, "source": source, "updated_at": now} for r in rows], ("cin", "vpa"))

    def _ensure_directors(self, conn, names: dict[str, str | None], source: str, now: float) -> None:
        if not names:
            return
        have = {d: n for d, n in conn.execute(select(directors.c.din, directors.c.name).where(directors.c.din.in_(list(names))))}
        new = [{"din": d, "name": n, "disqualified": 0, "source": source, "updated_at": now} for d, n in names.items() if d not in have]
        if new:
            _upsert(conn, directors, new, ("din",))
        for d, n in names.items():
            if d in have and n and not have[d]:
                conn.execute(update(directors).where(directors.c.din == d).values(name=n))

    def link_accounts(self, cin: str, vpas: Iterable[str], source: str = "onboarding") -> int:
        rows = [{"cin": normalise_cin(cin), "vpa": v.strip().lower(), "account_id": None, "source": source, "updated_at": time.time()} for v in vpas if "@" in v]
        with self.engine.begin() as conn:
            _upsert(conn, entity_accounts, rows, ("cin", "vpa"))
        return len(rows)

    # ------------------------------------------------------------------ live provider

    def _api(self, path: str) -> dict[str, Any] | None:
        if settings.MCA_PROVIDER != "http" or not settings.MCA_API_URL:
            return None
        headers = {"Accept": "application/json"}
        if settings.MCA_API_KEY:
            headers["Authorization"] = f"Bearer {settings.MCA_API_KEY}"
        try:
            response = requests.get(f"{settings.MCA_API_URL}{path}", headers=headers, timeout=10)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as error:
            self.api_errors += 1
            self.last_api_error = f"{path}: {type(error).__name__}: {error}"[:300]
            return None

    def fetch_company(self, cin: str) -> bool:
        """GET /companies/{cin} ->
            {"company": {"cin", "name", "status", "companyClass", "category", "subCategory",
                         "incorporatedOn" (YYYY-MM-DD), "state", "roc", "authorizedCapital",
                         "paidUpCapital", "activity", "address", "email", "lastAnnualReturn"},
             "directors": [{"din", "name", "designation", "appointedOn", "ceasedOn", "disqualified"}]}
        Stored with source "api"."""
        body = self._api(f"/companies/{cin}")
        if not body or not body.get("company"):
            return False
        c = body["company"]
        company = {
            "cin": normalise_cin(c.get("cin") or cin), "name": c.get("name"), "status": c.get("status"), "company_class": c.get("companyClass"),
            "category": c.get("category"), "sub_category": c.get("subCategory"), "incorporated_on": parse_date(c.get("incorporatedOn")),
            "state": c.get("state"), "roc": c.get("roc"), "authorized_capital": parse_amount(c.get("authorizedCapital")),
            "paid_up_capital": parse_amount(c.get("paidUpCapital")), "activity": c.get("activity"), "address": c.get("address"),
            "address_key": address_key(c.get("address")), "email": (c.get("email") or "").lower() or None,
            "last_annual_return": parse_year(c.get("lastAnnualReturn")), "source": "api", "updated_at": time.time(),
        }
        self._store_directorships(company["cin"], body.get("directors") or [])
        with self.engine.begin() as conn:
            _upsert(conn, companies, [company], ("cin",))
        return True

    def fetch_director(self, din: str) -> bool:
        """GET /directors/{din} ->
            {"director": {"din", "name", "disqualified"},
             "companies": [{"cin", "name", "designation", "appointedOn", "ceasedOn"}]}"""
        body = self._api(f"/directors/{din}")
        if not body:
            return False
        now = time.time()
        d = body.get("director") or {}
        with self.engine.begin() as conn:
            self._ensure_directors(conn, {din: d.get("name")}, "api", now)
            conn.execute(update(directors).where(directors.c.din == din).values(fetched_at=now, **({"disqualified": 1, "disqualified_note": "api"} if d.get("disqualified") else {})))
            rows = []
            for c in body.get("companies") or []:
                cin = normalise_cin(c.get("cin"))
                if not cin_facts(cin)["valid"]:
                    continue
                rows.append({"cin": cin, "din": din, "designation": c.get("designation"), "appointed_on": parse_date(c.get("appointedOn")), "ceased_on": parse_date(c.get("ceasedOn")), "source": "api", "updated_at": now})
                if c.get("name"):  # a stub company row so the name shows; a later company lookup fills the rest
                    _upsert(conn, companies, [{"cin": cin, "name": c["name"], "source": "api", "updated_at": now}], ("cin",))
            _upsert(conn, directorships, rows, ("cin", "din"))
        return True

    def _store_directorships(self, cin: str, people: list[dict[str, Any]]) -> None:
        now = time.time()
        with self.engine.begin() as conn:
            names = {normalise_din(p.get("din")): p.get("name") for p in people if p.get("din")}
            self._ensure_directors(conn, names, "api", now)
            for p in people:
                if p.get("disqualified"):
                    conn.execute(update(directors).where(directors.c.din == normalise_din(p["din"])).values(disqualified=1, disqualified_note="api"))
            _upsert(conn, directorships, [
                {"cin": cin, "din": normalise_din(p["din"]), "designation": p.get("designation"), "appointed_on": parse_date(p.get("appointedOn")),
                 "ceased_on": parse_date(p.get("ceasedOn")), "source": "api", "updated_at": now}
                for p in people if p.get("din")
            ], ("cin", "din"))

    # ------------------------------------------------------------------ reads

    def company(self, cin: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            r = conn.execute(select(companies).where(companies.c.cin == cin)).first()
            return dict(r._mapping) if r else None

    def _board(self, conn, cin: str, as_of: date) -> list[dict[str, Any]]:
        stmt = (
            select(directorships, directors.c.name, directors.c.disqualified, directors.c.disqualified_note)
            .join(directors, directors.c.din == directorships.c.din, isouter=True)
            .where(directorships.c.cin == cin)
        )
        out = []
        for r in conn.execute(stmt):
            d = dict(r._mapping)
            d["current"] = d["ceased_on"] is None or d["ceased_on"] > as_of
            out.append(d)
        return out

    def _companies_of(self, conn, dins: list[str], as_of: date) -> list[dict[str, Any]]:
        if not dins:
            return []
        stmt = (
            select(directorships.c.din, directorships.c.cin, directorships.c.designation, directorships.c.appointed_on, directorships.c.ceased_on,
                   companies.c.name, companies.c.status, companies.c.incorporated_on, companies.c.address_key)
            .join(companies, companies.c.cin == directorships.c.cin, isouter=True)
            .where(directorships.c.din.in_(dins))
        )
        return [dict(r._mapping) | {"current": r.ceased_on is None or r.ceased_on > as_of} for r in conn.execute(stmt)]

    def director(self, din: str, as_of: date | None = None) -> dict[str, Any] | None:
        din = normalise_din(din)
        as_of = as_of or date.today()
        if settings.MCA_PROVIDER == "http":
            self._refresh_director(din)
        with self.engine.connect() as conn:
            r = conn.execute(select(directors).where(directors.c.din == din)).first()
            if not r:
                return None
            roles = self._companies_of(conn, [din], as_of)
        return {**_jsonable(dict(r._mapping)), "companies": [_jsonable(x) for x in roles], "currentDirectorships": sum(1 for x in roles if x["current"])}

    def _refresh_director(self, din: str) -> None:
        with self.engine.connect() as conn:
            fetched = conn.execute(select(directors.c.fetched_at).where(directors.c.din == din)).scalar()
        if not fetched or time.time() - fetched > API_TTL_SECONDS:
            self.fetch_director(din)

    def status(self) -> dict[str, Any]:
        with self.engine.connect() as conn:
            def count(table, *where) -> int:
                return int(conn.execute(select(func.count()).select_from(table).where(*where)).scalar() or 0)

            recent = [dict(r._mapping) for r in conn.execute(select(imports).order_by(imports.c.id.desc()).limit(10))]
            return {
                "companies": count(companies),
                "directors": count(directors),
                "directorships": count(directorships),
                "disqualifiedDirectors": count(directors, directors.c.disqualified == 1),
                "linkedAccounts": count(entity_accounts),
                "provider": {"mode": settings.MCA_PROVIDER, "url": settings.MCA_API_URL or None, "errors": self.api_errors, "lastError": self.last_api_error},
                "imports": recent,
                "thresholds": {"youngDays": YOUNG_DAYS, "lowPaidUp": LOW_PAID_UP, "staleFilingYears": STALE_FILING_YEARS, "directorLimit": DIRECTOR_LIMIT,
                               "busyDirector": BUSY_DIRECTOR, "addressFarm": ADDRESS_FARM, "batchDays": BATCH_DAYS},
            }

    # ------------------------------------------------------------------ linkage report

    def report(self, cin: str, as_of: date | None = None, account_status: Callable[[str], dict[str, Any] | None] | None = None,
               extra_dins: Iterable[str] = ()) -> dict[str, Any]:
        """Everything the registry says about an applicant company, with findings.

        account_status(vpa) -> {"flagged", "frozen", "held", "alerts"} | None comes from the
        rail engine; it is how a linked company's settlement account is checked.
        extra_dins: directors the applicant declared, used even if the registry has no
        board for this CIN yet."""
        cin = normalise_cin(cin)
        as_of = as_of or date.today()
        facts = cin_facts(cin)
        findings: list[dict[str, Any]] = []

        def find(severity: str, code: str, text: str, **evidence: Any) -> None:
            findings.append({"severity": severity, "code": code, "text": text, **({"evidence": _jsonable(evidence)} if evidence else {})})

        if not facts["valid"]:
            find("medium", "invalid_cin", f"{cin} is not a valid CIN or LLPIN.")
            return self._finish(cin, None, facts, [], [], [], [], findings)

        company = self.company(cin)
        if (not company or not company.get("status")) and settings.MCA_PROVIDER == "http":
            self.fetch_company(cin)
            company = self.company(cin)

        declared = [normalise_din(d) for d in extra_dins if str(d).strip()]
        if settings.MCA_PROVIDER == "http":
            with self.engine.connect() as conn:
                board_dins = [r.din for r in conn.execute(select(directorships.c.din).where(directorships.c.cin == cin))]
            for din in set(board_dins) | set(declared):
                self._refresh_director(din)

        with self.engine.connect() as conn:
            board = self._board(conn, cin, as_of)
            known = {b["din"] for b in board}
            for din in declared:
                if din not in known:
                    r = conn.execute(select(directors).where(directors.c.din == din)).first()
                    board.append({"cin": cin, "din": din, "designation": "declared by applicant", "appointed_on": None, "ceased_on": None, "current": True,
                                  "name": r.name if r else None, "disqualified": r.disqualified if r else 0, "disqualified_note": r.disqualified_note if r else None, "declared": True})
            current = [b for b in board if b["current"]]
            roles = self._companies_of(conn, [b["din"] for b in current], as_of)
            same_address = []
            if company and company.get("address_key"):
                same_address = [dict(r._mapping) for r in conn.execute(
                    select(companies.c.cin, companies.c.name, companies.c.status, companies.c.incorporated_on)
                    .where(companies.c.address_key == company["address_key"], companies.c.cin != cin).limit(200)
                )]
            linked_cins = {r["cin"] for r in roles if r["cin"] != cin} | {r["cin"] for r in same_address}
            accounts = [dict(r._mapping) for r in conn.execute(select(entity_accounts).where(entity_accounts.c.cin.in_(list(linked_cins | {cin}))))] if linked_cins or cin else []

        # ---- the company itself
        if not company:
            find("medium", "not_in_registry", "No company master record for this CIN. Load the state's company master file or enable MCA_PROVIDER.")
        else:
            status = (company.get("status") or "").strip().lower()
            if status and status != "active":
                sev = next((s for k, s in INACTIVE.items() if k in status), "medium")
                find(sev, "inactive_status", f"MCA status is '{company['status']}', not Active.")
            inc = company.get("incorporated_on")
            if inc and (as_of - inc).days < YOUNG_DAYS:
                find("medium", "young_company", f"Incorporated {inc.isoformat()}, {(as_of - inc).days} days ago.")
            paid = company.get("paid_up_capital")
            if paid is not None and paid <= LOW_PAID_UP:
                find("low", "low_paid_up", f"Paid-up capital is ₹{paid:,.0f}.")
            filed = company.get("last_annual_return")
            if filed and inc and as_of.year - filed > STALE_FILING_YEARS and (as_of - inc).days > 365 * STALE_FILING_YEARS:
                find("medium", "stale_filings", f"Latest annual return on record is for {filed}.")
        if board and not current:
            find("medium", "no_current_directors", "Every director on record has ceased.")
        if not board:
            find("low", "no_director_data", "No director data for this CIN, so director and common-control checks could not run.")

        # ---- directors
        by_din: dict[str, list[dict[str, Any]]] = {}
        for r in roles:
            by_din.setdefault(r["din"], []).append(r)
        people = []
        for b in current:
            theirs = by_din.get(b["din"], [])
            active_roles = [r for r in theirs if r["current"]]
            people.append({"din": b["din"], "name": b.get("name"), "designation": b.get("designation"), "declared": b.get("declared", False),
                           "disqualified": bool(b.get("disqualified")), "currentDirectorships": len(active_roles),
                           "otherCompanies": [{"cin": r["cin"], "name": r["name"], "status": r["status"], "current": r["current"]} for r in theirs if r["cin"] != cin]})
            label = f"{b.get('name') or 'Director'} (DIN {b['din']})"
            if b.get("disqualified"):
                find("high", "disqualified_director", f"{label} is disqualified ({b.get('disqualified_note') or 's.164(2)'}).", din=b["din"])
            if len(active_roles) > DIRECTOR_LIMIT:
                find("high", "over_director_limit", f"{label} holds {len(active_roles)} current directorships, above the s.165 limit of {DIRECTOR_LIMIT}.", din=b["din"])
            elif len(active_roles) > BUSY_DIRECTOR:
                find("medium", "busy_director", f"{label} holds {len(active_roles)} current directorships.", din=b["din"])
            struck = [r for r in theirs if r["cin"] != cin and any(k in (r["status"] or "").lower() for k in ("strike", "struck"))]
            if len(struck) >= 2:
                find("medium", "director_of_struck_off", f"{label} was a director of {len(struck)} companies that were struck off.", cins=[r["cin"] for r in struck])

        # ---- structure: common control and address farms
        shared: dict[str, dict[str, Any]] = {}
        for r in roles:
            if r["cin"] == cin or not r["current"]:
                continue
            g = shared.setdefault(r["cin"], {"cin": r["cin"], "name": r["name"], "status": r["status"], "incorporatedOn": r["incorporated_on"], "sharedDirectors": set()})
            g["sharedDirectors"].add(r["din"])
        group = [g | {"sharedDirectors": sorted(g["sharedDirectors"])} for g in shared.values() if len(g["sharedDirectors"]) >= 2]
        if group:
            inc = company.get("incorporated_on") if company else None
            batch = [g for g in group if inc and g["incorporatedOn"] and abs((g["incorporatedOn"] - inc).days) <= BATCH_DAYS]
            if len(batch) >= 2:
                find("medium", "batch_incorporation", f"{len(batch)} companies with two or more of the same directors were incorporated within {BATCH_DAYS} days of this one.", cins=[g["cin"] for g in batch])
            else:
                find("low", "common_control", f"{len(group)} other companies share two or more current directors.", cins=[g["cin"] for g in group])
        if len(same_address) + 1 >= ADDRESS_FARM:
            sev = "high" if len(same_address) + 1 >= ADDRESS_FARM_HIGH else "medium"
            find(sev, "address_farm", f"{len(same_address) + 1} companies are registered at this address.", cins=[r["cin"] for r in same_address[:20]])

        # ---- rail crossover
        crossover = []
        if account_status:
            via: dict[str, str] = {}
            for r in roles:
                if r["cin"] != cin:
                    via.setdefault(r["cin"], f"director {r['din']}")
            for r in same_address:
                via.setdefault(r["cin"], "same registered address")
            for a in accounts:
                st = account_status(a["vpa"])
                if not st:
                    continue
                entry = {"cin": a["cin"], "vpa": a["vpa"], "via": "this company" if a["cin"] == cin else via.get(a["cin"], "linked"), **st}
                if st.get("frozen") or st.get("held") or st.get("flagged"):
                    crossover.append(entry)
            for e in crossover:
                what = "frozen" if e.get("frozen") else "on hold" if e.get("held") else "under alert"
                who = "This company's" if e["cin"] == cin else f"Linked company {e['cin']}'s ({e['via']})"
                find("high", "linked_account_flagged", f"{who} settlement VPA {e['vpa']} is {what} in the rail.", cin=e["cin"], vpa=e["vpa"])

        return self._finish(cin, company, facts, people, group, same_address, crossover, findings, accounts)

    def _finish(self, cin, company, facts, people, group, same_address, crossover, findings, accounts=()) -> dict[str, Any]:
        order = {"high": 0, "medium": 1, "low": 2}
        findings.sort(key=lambda f: order[f["severity"]])
        top = findings[0]["severity"] if findings else None
        decision = "hold" if top == "high" else "review" if top == "medium" else "approve"
        return _jsonable({
            "cin": cin, "cinFacts": facts, "company": company, "directors": people, "commonControl": group,
            "sameAddress": same_address[:50], "sameAddressCount": len(same_address), "linkedAccounts": list(accounts), "crossover": crossover,
            "findings": findings, "decision": decision, "provider": settings.MCA_PROVIDER, "checkedAt": time.time(),
        })


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items() if k not in ("address_key", "updated_at", "fetched_at")}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def merge(transactions: dict[str, Any], registry: dict[str, Any] | None) -> dict[str, Any]:
    """Combine the transaction-graph onboarding result with a registry report: the stricter
    recommendation wins, and the reason names where it came from."""
    if not registry:
        return transactions
    rank = {"approve": 0, "review": 1, "hold": 2}
    first = next((f for f in registry["findings"] if f["severity"] != "low"), None)
    out = {**transactions, "registry": registry}
    if rank[registry["decision"]] > rank[transactions["decision"]]:
        out["decision"] = registry["decision"]
        out["reason"] = f"Registry: {first['text']}" if first else transactions["reason"]
    elif registry["decision"] != "approve" and first:
        out["reason"] = f"{transactions['reason']} Registry: {first['text']}"
    return out


_REGISTRY: Registry | None = None
_LOCK = threading.Lock()


def get_registry() -> Registry:
    global _REGISTRY
    with _LOCK:
        if _REGISTRY is None:
            _REGISTRY = Registry()
        return _REGISTRY


def main(argv: list[str] | None = None) -> None:
    import json

    parser = argparse.ArgumentParser(description="MCA company / director registry", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("load")
    p.add_argument("kind", choices=list(ALIASES))
    p.add_argument("file")
    sub.add_parser("status")
    p = sub.add_parser("report")
    p.add_argument("cin")
    p = sub.add_parser("director")
    p.add_argument("din")
    args = parser.parse_args(argv)
    reg = get_registry()
    if args.cmd == "load":
        out = reg.load(args.kind, Path(args.file))
    elif args.cmd == "status":
        out = reg.status()
    elif args.cmd == "report":
        out = reg.report(args.cin)
    else:
        out = reg.director(args.din)
    json.dump(out, sys.stdout, indent=2, default=str)
    print()


if __name__ == "__main__":
    main()
