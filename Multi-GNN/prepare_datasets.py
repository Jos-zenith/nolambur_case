#!/usr/bin/env python3
"""
Low-memory dataset preparation for the two-stage fraud pipeline.

This script:
1. Converts IBM AML flat transaction CSVs into formatted_transactions.csv using a streaming CSV writer.
2. Builds Nolambur formatted_transactions.csv from nolambur_transactions.csv + nolambur_labels.csv
   by aligning rows in file order (the Nolambur files do not expose a tx_id join key).

It avoids pandas for the heavy formatting step so large files do not trigger memory spikes.
"""

from __future__ import annotations

import csv
import logging
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def resolve_workspace_root() -> Path:
    return Path(__file__).resolve().parent


def csv_rows(path: Path) -> Iterator[dict]:
    with path.open("r", newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row


def write_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def parse_timestamp(value: str) -> datetime:
    value = (value or "").strip()
    for fmt in (
        "%Y/%m/%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported timestamp format: {value!r}")


def first_nonempty(row: dict, keys: Sequence[str], default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def convert_ibm_variant(base_dir: Path, variant: str) -> Optional[Path]:
    """Convert a flat IBM AML transaction file into formatted_transactions.csv."""
    source = base_dir / f"{variant}_Trans.csv"
    if not source.exists():
        logging.warning("IBM variant missing flat file: %s", source)
        return None

    out_dir = base_dir / variant
    out_path = out_dir / "formatted_transactions.csv"
    if out_path.exists():
        logging.info("IBM %s already formatted: %s", variant, out_path)
        return out_path

    logging.info("Formatting IBM %s from %s", variant, source.name)
    out_dir.mkdir(parents=True, exist_ok=True)

    currency_ids: Dict[str, int] = OrderedDict()
    payment_ids: Dict[str, int] = OrderedDict()
    account_ids: Dict[str, int] = OrderedDict()

    def encode(mapping: Dict[str, int], value: str) -> int:
        key = str(value)
        if key not in mapping:
            mapping[key] = len(mapping)
        return mapping[key]

    first_ts: Optional[datetime] = None

    with source.open("r", newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        with out_path.open("w", newline="", encoding="utf-8") as out_f:
            writer = csv.writer(out_f)
            writer.writerow([
                "EdgeID",
                "from_id",
                "to_id",
                "Timestamp",
                "Amount Sent",
                "Sent Currency",
                "Amount Received",
                "Received Currency",
                "Payment Format",
                "Is Laundering",
            ])

            row_count = 0
            for idx, row in enumerate(reader):
                ts = parse_timestamp(first_nonempty(row, ["Timestamp", "timestamp"]))
                if first_ts is None:
                    first_ts = datetime(ts.year, ts.month, ts.day)
                ts_value = int((ts - first_ts).total_seconds())

                from_key = f"{first_nonempty(row, ['From Bank', 'from_bank', 'sender_bank'])}:{first_nonempty(row, ['Payer', 'From Account', 'sender_id', 'sender_vpa', 'from_id'])}"
                to_key = f"{first_nonempty(row, ['To Bank', 'to_bank', 'recv_bank'])}:{first_nonempty(row, ['Payee', 'To Account', 'recv_id', 'recv_vpa', 'to_id'])}"

                writer.writerow([
                    idx,
                    encode(account_ids, from_key),
                    encode(account_ids, to_key),
                    ts_value,
                    float(first_nonempty(row, ["Amount Paid", "Amount Sent", "amount_inr"], "0") or 0),
                    encode(currency_ids, first_nonempty(row, ["Payment Currency", "Sent Currency", "Currency"], "0")),
                    float(first_nonempty(row, ["Amount Received", "Amount Paid", "amount_inr"], "0") or 0),
                    encode(currency_ids, first_nonempty(row, ["Receiving Currency", "Received Currency", "Currency"], "0")),
                    encode(payment_ids, first_nonempty(row, ["Payment Format"], "0")),
                    int(float(first_nonempty(row, ["Is Laundering", "is_fraud"], "0") or 0)),
                ])
                row_count += 1

    logging.info("Wrote %s (%d rows)", out_path, row_count)
    return out_path


def convert_nolambur(base_dir: Path) -> Optional[Path]:
    """Build Nolambur formatted_transactions.csv from the flat transaction and label files."""
    tx_path = base_dir / "nolambur_transactions.csv"
    labels_path = base_dir / "nolambur_labels.csv"
    out_dir = base_dir / "nolambur"
    out_path = out_dir / "formatted_transactions.csv"

    if not tx_path.exists():
        logging.warning("Nolambur transactions missing: %s", tx_path)
        return None
    if not labels_path.exists():
        logging.warning("Nolambur labels missing: %s", labels_path)
        return None
    if out_path.exists():
        logging.info("Nolambur already formatted: %s", out_path)
        return out_path

    logging.info("Formatting Nolambur from %s + %s", tx_path.name, labels_path.name)
    out_dir.mkdir(parents=True, exist_ok=True)

    tx_count = sum(1 for _ in csv_rows(tx_path))
    label_count = sum(1 for _ in csv_rows(labels_path))
    if tx_count != label_count:
        logging.warning(
            "Row count mismatch for Nolambur: %d transactions vs %d labels. Using minimum length.",
            tx_count,
            label_count,
        )

    first_ts: Optional[datetime] = None
    id_map: Dict[str, int] = OrderedDict()

    def encode(value: str) -> int:
        key = str(value)
        if key not in id_map:
            id_map[key] = len(id_map)
        return id_map[key]

    with out_path.open("w", newline="", encoding="utf-8") as out_f:
        writer = csv.writer(out_f)
        writer.writerow([
            "EdgeID",
            "from_id",
            "to_id",
            "Timestamp",
            "Amount Sent",
            "Sent Currency",
            "Amount Received",
            "Received Currency",
            "Payment Format",
            "Is Laundering",
        ])

        row_count = 0
        for idx, (tx, label) in enumerate(zip(csv_rows(tx_path), csv_rows(labels_path))):
            ts = parse_timestamp(first_nonempty(tx, ["timestamp", "Timestamp"]))
            if first_ts is None:
                first_ts = datetime(ts.year, ts.month, ts.day)
            ts_value = int((ts - first_ts).total_seconds()) + 10

            amount = float(first_nonempty(tx, ["amount_inr", "Amount", "amount"], "0") or 0)
            writer.writerow([
                idx,
                encode(first_nonempty(tx, ["sender_id", "from_id", "sender_vpa"])),
                encode(first_nonempty(tx, ["recv_id", "to_id", "recv_vpa"])),
                ts_value,
                amount,
                0,
                amount,
                0,
                0,
                int(float(first_nonempty(label, ["is_fraud", "Is Laundering"], "0") or 0)),
            ])
            row_count += 1

    logging.info("Wrote %s (%d rows)", out_path, row_count)
    return out_path


def main() -> int:
    setup_logging()
    root = resolve_workspace_root()
    ibm_base = (root / ".." / "ibm-transactions-for-anti-money-laundering-aml").resolve()

    variants = ["HI-Large", "HI-Medium", "HI-Small", "LI-Large", "LI-Medium", "LI-Small"]
    created: List[Path] = []

    logging.info("Preparing IBM AML data under %s", ibm_base)
    for variant in variants:
        out = convert_ibm_variant(ibm_base, variant)
        if out is not None:
            created.append(out)

    logging.info("Preparing Nolambur data under %s", root)
    nol = convert_nolambur(root)
    if nol is not None:
        created.append(nol)

    logging.info("Created or confirmed %d formatted files", len(created))
    for path in created:
        logging.info("- %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())