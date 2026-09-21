"""Interactively capture the five required human workflow timings."""
from __future__ import annotations

import csv
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "reports/evaluation/manual-timing-input.csv"


def main() -> None:
    with PATH.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    operator = input("Operator name: ").strip()
    if not operator:
        raise SystemExit("Operator name is required.")
    for row in rows:
        print(f"\n{row['case_id']}: {row['scenario']}")
        input("Press Enter when the operator is ready to read the enquiry...")
        started = datetime.now(timezone.utc)
        tick = time.perf_counter()
        input("Complete the manual catalogue/pricing workflow, then press Enter to stop...")
        duration = time.perf_counter() - tick
        finished = datetime.now(timezone.utc)
        check = input("Was the final result independently checked as correct? [y/N] ").strip().lower()
        note = input("Optional note: ").strip()
        row.update(
            operator=operator, started_at=started.isoformat(), finished_at=finished.isoformat(),
            duration_seconds=f"{duration:.3f}", result_check="PASS" if check == "y" else "FAIL", notes=note,
        )
        with PATH.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
        print(f"Recorded {duration:.3f} seconds.")
    print(f"\nSaved 5 observations to {PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
