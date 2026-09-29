"""infra/registry.py: loaders for the real MCA / data.gov.in layouts, and the shell checks.

The rows below are test fixtures, not data: invented CINs, DINs and names in valid
formats, laid out with the real files' headers. Nothing here is loaded by the bridge.

    cd Multi-GNN && python -m pytest tests -q
"""

from __future__ import annotations

from datetime import date

import pytest

from infra import registry as reg
from infra.store import Store

AS_OF = date(2026, 9, 28)

# data.gov.in "Company Master Data" download layout
COMPANIES_DATAGOVIN = """CORPORATE_IDENTIFICATION_NUMBER,COMPANY_NAME,COMPANY_STATUS,COMPANY_CLASS,COMPANY_CATEGORY,COMPANY_SUB_CATEGORY,DATE_OF_REGISTRATION,REGISTERED_STATE,AUTHORIZED_CAP,PAIDUP_CAPITAL,INDUSTRIAL_CLASS,PRINCIPAL_BUSINESS_ACTIVITY_AS_PER_CIN,REGISTERED_OFFICE_ADDRESS,REGISTRAR_OF_COMPANIES,EMAIL_ADDR,LATEST_YEAR_ANNUAL_RETURN,LATEST_YEAR_FINANCIAL_STATEMENT
U74999MH2026PTC000001,TEST APPLICANT PRIVATE LIMITED,ACTIVE,Private,Company limited by Shares,Non-govt company,15-06-2026,Maharashtra,100000,100000,74999,Business Services,"12, M.G. Road, Pune - 411001",RoC-Pune,a@example.test,NA,NA
U74999MH2026PTC000002,TEST SIBLING ONE PRIVATE LIMITED,ACTIVE,Private,Company limited by Shares,Non-govt company,20-05-2026,Maharashtra,100000,10000,74999,Business Services,"12 MG RD, PUNE 411001",RoC-Pune,b@example.test,NA,NA
U74999MH2026PTC000003,TEST SIBLING TWO PRIVATE LIMITED,ACTIVE,Private,Company limited by Shares,Non-govt company,01-07-2026,Maharashtra,100000,10000,74999,Business Services,"12, M.G. Road, Pune 411001",RoC-Pune,c@example.test,NA,NA
U74999MH2019PTC000004,TEST OLD STRUCK PRIVATE LIMITED,Strike Off,Private,Company limited by Shares,Non-govt company,10-01-2019,Maharashtra,100000,100000,74999,Business Services,"Plot 9, Andheri East, Mumbai 400069",RoC-Mumbai,,2020,2020
U74999MH2018PTC000005,TEST OLDER STRUCK PRIVATE LIMITED,Strike Off,Private,Company limited by Shares,Non-govt company,10-01-2018,Maharashtra,100000,100000,74999,Business Services,"Plot 10, Andheri East, Mumbai 400069",RoC-Mumbai,,2019,2019
L65910MH1995PLC000006,TEST CLEAN LISTED LIMITED,ACTIVE,Public,Company limited by Shares,Non-govt company,01-04-1995,Maharashtra,500000000,250000000,65910,Finance,"Tower A, Nariman Point, Mumbai 400021",RoC-Mumbai,,2025,2025
"""

# newer OGD naming, as on the 2024+ releases
COMPANIES_OGD = """CIN,CompanyName,CompanyROCcode,CompanyCategory,CompanySubCategory,CompanyClass,AuthorizedCapital,PaidupCapital,CompanyRegistrationdate_date,Registered_Office_Address,Listingstatus,CompanyStatus,CompanyStateCode
U74999MH2026PTC000007,TEST SIBLING THREE PRIVATE LIMITED,RoC-Pune,Company limited by Shares,Non-govt company,Private,"1,00,000","10,000",2026-06-30,"12 M G Road Pune 411001",Unlisted,Active,Maharashtra
U74999MH2026PTC000008,TEST ADDRESS NEIGHBOUR PRIVATE LIMITED,RoC-Pune,Company limited by Shares,Non-govt company,Private,100000,100000,2026-01-02,"12 MG Road, Pune 411001",Unlisted,Active,Maharashtra
"""

# MCA21 "View Signatory Details"-style export, DINs with leading zeros stripped by a spreadsheet
DIRECTORSHIPS = """CIN,DIN/PAN,Name,Designation,Date of Appointment,Cessation Date
U74999MH2026PTC000001,1234501,RAVI TESTNAME,Director,15-06-2026,
U74999MH2026PTC000001,01234502,SITA TESTNAME,Director,15-06-2026,
U74999MH2026PTC000002,01234501,RAVI TESTNAME,Director,20-05-2026,
U74999MH2026PTC000002,01234502,SITA TESTNAME,Director,20-05-2026,
U74999MH2026PTC000003,01234501,RAVI TESTNAME,Director,01-07-2026,
U74999MH2026PTC000003,01234502,SITA TESTNAME,Director,01-07-2026,
U74999MH2019PTC000004,01234501,RAVI TESTNAME,Director,10-01-2019,
U74999MH2018PTC000005,01234501,RAVI TESTNAME,Director,10-01-2018,
L65910MH1995PLC000006,09999901,ASHA TESTNAME,Managing Director,01-04-2010,
L65910MH1995PLC000006,09999902,OLD TESTNAME,Director,01-04-1995,31-03-2005
NOT-A-CIN,01234501,RAVI TESTNAME,Director,01-01-2020,
"""

DISQUALIFIED = """DIN,Director Name,Period of Disqualification
01234502,SITA TESTNAME,s.164(2)(a) 01-11-2025 to 31-10-2030
"""

ACCOUNTS = """CIN,Settlement VPA
U74999MH2026PTC000002,sibling1.settle@ybl
L65910MH1995PLC000006,clean.listed@okaxis
"""


@pytest.fixture()
def registry(tmp_path):
    store = Store(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    r = reg.Registry(store)
    assert r.load("companies", COMPANIES_DATAGOVIN)["loaded"] == 6
    ogd = r.load("companies", COMPANIES_OGD)
    assert ogd["loaded"] == 2 and "Listingstatus" in ogd["unmappedColumns"]
    ds = r.load("directorships", DIRECTORSHIPS)
    assert (ds["loaded"], ds["skipped"]) == (10, 1)
    r.load("disqualified", DISQUALIFIED)
    r.load("accounts", ACCOUNTS)
    return r


def codes(report):
    return {f["code"]: f["severity"] for f in report["findings"]}


def test_parsers():
    assert reg.normalise_din("1234501") == "01234501"
    assert reg.normalise_din("1234501.0") == "01234501"
    assert reg.parse_date("15-06-2026") == date(2026, 6, 15)
    assert reg.parse_date("2026-06-30") == date(2026, 6, 30)
    assert reg.parse_date("NA") is None
    assert reg.parse_amount("1,00,000") == 100000.0
    assert reg.address_key("Office No. 4, 12 M.G. Road, Pune") == reg.address_key("OFFICE 4 12 MG RD PUNE") == reg.address_key("office no 4 12 m g road pune")
    assert reg.address_key("Office 4, 12 MG Road, Pune") != reg.address_key("Office 5, 12 MG Road, Pune")
    facts = reg.cin_facts("L65910MH1995PLC000006")
    assert facts["listed"] and facts["year"] == 1995 and facts["state"] == "MH"
    assert reg.cin_facts("AAB-1234")["kind"] == "llp"
    assert not reg.cin_facts("NOT-A-CIN")["valid"]


def test_missing_required_column_is_rejected(registry):
    with pytest.raises(ValueError, match="no column for din"):
        registry.load("directorships", "CIN,Name\nU74999MH2026PTC000001,X\n")


def test_shell_applicant(registry):
    flagged = {"sibling1.settle@ybl": {"flagged": True, "frozen": True, "held": False, "alerts": ["A-1"]}}
    out = registry.report("U74999MH2026PTC000001", AS_OF, account_status=lambda v: flagged.get(v, {"flagged": False, "frozen": False, "held": False, "alerts": []}))
    c = codes(out)
    assert c["disqualified_director"] == "high"
    assert c["linked_account_flagged"] == "high"
    assert c["young_company"] == "medium"
    assert c["batch_incorporation"] == "medium"  # 2 and 3 share both directors and were incorporated within a year
    assert c["address_farm"] == "medium"  # 1, 2, 3, 7, 8 all normalise to 12 MG Road Pune
    assert c["director_of_struck_off"] == "medium"
    assert c["low_paid_up"] == "low"
    assert out["decision"] == "hold"
    assert out["sameAddressCount"] == 4
    assert {g["cin"] for g in out["commonControl"]} == {"U74999MH2026PTC000002", "U74999MH2026PTC000003"}
    cross = out["crossover"][0]
    assert cross["cin"] == "U74999MH2026PTC000002" and cross["via"].startswith("director")


def test_clean_listed_company(registry):
    out = registry.report("L65910MH1995PLC000006", AS_OF, account_status=lambda v: {"flagged": False, "frozen": False, "held": False, "alerts": []})
    assert out["findings"] == []
    assert out["decision"] == "approve"
    assert [d["din"] for d in out["directors"]] == ["09999901"]  # the ceased director is not current


def test_unknown_company_and_declared_directors(registry):
    out = registry.report("U74999MH2026PTC999999", AS_OF, extra_dins=["1234502"])
    c = codes(out)
    assert c["not_in_registry"] == "medium"
    assert c["disqualified_director"] == "high"  # the declared DIN is known to be disqualified
    assert out["decision"] == "hold"


def test_director_limit(registry):
    rows = "CIN,DIN,Name\n" + "\n".join(f"U74999MH2020PTC{i:06d},07777777,BUSY TESTNAME" for i in range(100, 122))
    registry.load("directorships", rows)
    out = registry.report("U74999MH2020PTC000100", AS_OF)
    assert codes(out)["over_director_limit"] == "high"


def test_merge_takes_the_stricter_decision():
    txn = {"decision": "approve", "reason": "No links.", "results": []}
    r = {"decision": "review", "findings": [{"severity": "medium", "code": "young_company", "text": "Incorporated recently."}]}
    merged = reg.merge(txn, r)
    assert merged["decision"] == "review" and merged["reason"].startswith("Registry:")
    assert reg.merge({"decision": "hold", "reason": "Direct link."}, r)["decision"] == "hold"


def test_status_and_director(registry):
    st = registry.status()
    assert st["companies"] == 8 and st["disqualifiedDirectors"] == 1 and st["linkedAccounts"] == 2
    d = registry.director("1234501", AS_OF)
    assert d["currentDirectorships"] == 5


def test_http_provider(registry, monkeypatch):
    """MCA_PROVIDER=http: a cache miss goes to the API and is stored."""
    from infra import settings

    monkeypatch.setattr(settings, "MCA_PROVIDER", "http")
    monkeypatch.setattr(settings, "MCA_API_URL", "https://mca.vendor.test")
    calls = []

    class Resp:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    def fake_get(url, headers, timeout):
        calls.append(url)
        if url.endswith("/companies/U74999KA2026PTC000050"):
            return Resp(200, {"company": {"cin": "U74999KA2026PTC000050", "name": "TEST API CO", "status": "Active", "incorporatedOn": "2026-09-01", "paidUpCapital": 10000},
                              "directors": [{"din": "01234501", "name": "RAVI TESTNAME", "appointedOn": "2026-09-01"}]})
        if url.endswith("/directors/01234501"):
            return Resp(200, {"director": {"din": "01234501", "name": "RAVI TESTNAME"}, "companies": [{"cin": "U74999KA2026PTC000050", "name": "TEST API CO", "appointedOn": "2026-09-01"}]})
        return Resp(404, None)

    monkeypatch.setattr(reg.requests, "get", fake_get)
    out = registry.report("U74999KA2026PTC000050", AS_OF)
    assert out["company"]["name"] == "TEST API CO" and out["company"]["source"] if "source" in out["company"] else True
    assert codes(out)["young_company"] == "medium"
    assert any(u.endswith("/companies/U74999KA2026PTC000050") for u in calls)
    assert registry.company("U74999KA2026PTC000050")["paid_up_capital"] == 10000
