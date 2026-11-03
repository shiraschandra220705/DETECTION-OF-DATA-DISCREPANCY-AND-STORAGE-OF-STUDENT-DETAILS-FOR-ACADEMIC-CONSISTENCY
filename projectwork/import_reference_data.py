"""Import the CSV reference records into the Firestore reference_students collection.

Run from any working directory with the project's Python dependencies installed
and Firebase Admin Application Default Credentials configured.
"""

import csv
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import firebase_admin
from firebase_admin import firestore


CSV_PATH = Path(__file__).resolve().parent / "data" / "Student_Details.csv"
COLLECTION_NAME = "reference_students"
USN_COLUMN = "USN"


def read_records(csv_path: Path) -> Tuple[List[Tuple[str, Dict[str, str]]], int, int]:
    """Read rows and return (USN, all-column record) pairs and skip counts.

    A blank USN cannot be used as a document ID. Repeated USNs in the CSV are
    skipped after the first occurrence so one source row cannot silently
    replace another during the same import.
    """
    records: List[Tuple[str, Dict[str, str]]] = []
    skipped_blank_usn = 0
    skipped_duplicate_usn = 0
    seen_usns = set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames or USN_COLUMN not in reader.fieldnames:
            raise ValueError(f"CSV must contain a {USN_COLUMN!r} column.")

        for row in reader:
            # DictReader uses a None key for extra values in malformed rows.
            if None in row:
                raise ValueError(f"CSV row {reader.line_num} has more values than its header.")

            usn_value = (row.get(USN_COLUMN) or "").strip()
            if not usn_value:
                skipped_blank_usn += 1
                continue

            # Normalize the document ID to match the app's uppercase USN
            # convention while preserving the original CSV value in the record.
            document_id = usn_value.upper()
            if document_id in seen_usns:
                skipped_duplicate_usn += 1
                continue

            seen_usns.add(document_id)
            records.append((document_id, dict(row)))

    return records, skipped_blank_usn, skipped_duplicate_usn


def main() -> int:
    if not CSV_PATH.is_file():
        print(f"Import failed: CSV file not found at {CSV_PATH}", file=sys.stderr)
        return 1

    try:
        records, skipped_blank_usn, skipped_duplicate_usn = read_records(CSV_PATH)
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        print(f"Import failed while reading CSV: {error}", file=sys.stderr)
        return 1

    if not records:
        print("Import finished: no valid records found.")
        print(f"Successfully imported: 0; skipped: {skipped_blank_usn + skipped_duplicate_usn}")
        return 0

    try:
        # Match the Flask app's Firebase Admin setup. Credentials come from
        # Application Default Credentials, never from this source file.
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        db = firestore.client()

        # A document ID derived from USN makes reruns idempotent. Writes are
        # limited to reference_students; users and student_records are untouched.
        batch = db.batch()
        collection = db.collection(COLLECTION_NAME)
        for document_id, record in records:
            batch.set(collection.document(document_id), record)
        batch.commit()
    except Exception as error:
        # Avoid printing exception details that could contain configuration or
        # other sensitive information.
        print(f"Import failed during Firestore write ({type(error).__name__}).", file=sys.stderr)
        return 1

    skipped = skipped_blank_usn + skipped_duplicate_usn
    print(f"CSV data rows: {len(records) + skipped}")
    print(f"Successfully imported: {len(records)}")
    print(f"Skipped: {skipped} (blank USN: {skipped_blank_usn}, duplicate USN: {skipped_duplicate_usn})")
    print(f"Target collection: {COLLECTION_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
