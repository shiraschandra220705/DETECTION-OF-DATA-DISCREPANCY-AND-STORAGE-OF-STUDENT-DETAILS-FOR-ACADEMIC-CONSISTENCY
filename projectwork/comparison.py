"""Import-safe pairwise comparison of registered, reference, and external data.

The module has no Flask, Firebase, Firestore, CSV, or database dependencies.
Inputs are mappings supplied by the caller; outputs contain JSON-compatible
field values, statuses, and independent pairwise summaries.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any, Dict, Mapping, Optional, Tuple


# Canonical display name, accepted record keys, and normalization type.
_FIELDS = (
    ("USN", ("usn", "USN"), "usn"),
    ("Name", ("name", "Name"), "text"),
    ("DOB", ("dob", "DOB", "date_of_birth"), "date"),
    ("CGPA", ("cgpa", "CGPA"), "number"),
    ("Semester", ("semester", "Semester"), "number"),
    ("10th Percentage", ("tenthmarks", "10th Percentage", "10th_percentage"), "number"),
    ("12th Percentage", ("pucmarks", "12th Percentage", "12th_percentage"), "number"),
    ("College Name", ("college", "College Name", "college_name"), "text"),
    ("Branch", ("branch", "Branch"), "branch"),
)

_NULL_MARKERS = {"nan", "none", "null", "n/a", "na", "<na>"}
_BRANCH_ALIASES = {
    "cse": "computer science and engineering",
    "computer science engineering": "computer science and engineering",
    "ise": "information science and engineering",
    "information science engineering": "information science and engineering",
    "ece": "electronics and communication engineering",
    "eee": "electrical and electronics engineering",
    "me": "mechanical engineering",
    "mech": "mechanical engineering",
    "civil": "civil engineering",
}


def _missing(value: Any) -> bool:
    """Recognize None, blank/null markers, and common NaN-like scalar values."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip().casefold() in _NULL_MARKERS
    try:
        if str(value).strip().casefold() in _NULL_MARKERS:
            return True
    except (TypeError, ValueError):
        pass
    try:
        result = value != value
        return bool(result)
    except (TypeError, ValueError):
        return False


def _raw_display(value: Any) -> Any:
    """Convert unusual input values to JSON-safe representations."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        # Decimal is not JSON-native; a string preserves its exact precision
        # and trailing-zero formatting for the displayed original value.
        return str(value)
    return str(value)


def _normalize_usn(value: Any) -> Optional[str]:
    if _missing(value):
        return None
    normalized = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    return normalized or None


def _normalize_date(value: Any) -> Optional[str]:
    if _missing(value):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        pass
    for format_string in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, format_string).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_number(value: Any) -> Optional[Decimal]:
    if _missing(value) or isinstance(value, bool):
        return None
    text = str(value).strip().replace(" ", "")
    if "," in text and "." not in text:
        # Treat one/two trailing comma digits as a decimal separator; otherwise
        # regard commas as thousands separators.
        if text.count(",") == 1 and len(text.rsplit(",", 1)[1]) <= 2:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", "")
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def _normalize_text(value: Any) -> Optional[str]:
    if _missing(value):
        return None
    return re.sub(r"\s+", " ", str(value).strip().casefold())


def _normalize_branch(value: Any) -> Optional[str]:
    text = _normalize_text(value)
    if text is None:
        return None
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    text = re.sub(r"\s+", " ", text)
    return _BRANCH_ALIASES.get(text, text) or None


def _normalize(value: Any, kind: str) -> Any:
    if kind == "usn":
        return _normalize_usn(value)
    if kind == "date":
        return _normalize_date(value)
    if kind == "number":
        return _normalize_number(value)
    if kind == "branch":
        return _normalize_branch(value)
    return _normalize_text(value)


def _is_invalid_present(value: Any, normalized: Any, kind: str) -> bool:
    """True when a present USN, date, or number cannot be normalized safely."""
    return kind in {"usn", "date", "number"} and not _missing(value) and normalized is None


def _json_value(value: Any) -> Any:
    """Convert normalized internal values to JSON-compatible scalar values."""
    if isinstance(value, Decimal):
        converted = float(value)
        return converted if math.isfinite(converted) else None
    return _raw_display(value)


def _record_value(record: Mapping[str, Any], aliases: Tuple[str, ...]) -> Any:
    for key in aliases:
        if key in record and not _missing(record[key]):
            return record[key]
    return None


def _compare_pair(
    left_record: Mapping[str, Any],
    right_record: Mapping[str, Any],
    left_source: str,
    right_source: str,
) -> Dict[str, Any]:
    if not isinstance(left_record, Mapping) or not isinstance(right_record, Mapping):
        raise TypeError("Both records must be mappings")

    fields = []
    counts = {"match": 0, "mismatch": 0, "missing": 0}
    for display_name, aliases, kind in _FIELDS:
        left_raw = _record_value(left_record, aliases)
        right_raw = _record_value(right_record, aliases)
        left_normalized = _normalize(left_raw, kind)
        right_normalized = _normalize(right_raw, kind)
        left_missing = _missing(left_raw)
        right_missing = _missing(right_raw)
        left_invalid = _is_invalid_present(left_raw, left_normalized, kind)
        right_invalid = _is_invalid_present(right_raw, right_normalized, kind)

        if left_missing or right_missing:
            status = "missing"
        elif left_invalid or right_invalid:
            status = "mismatch"
        else:
            status = "match" if left_normalized == right_normalized else "mismatch"

        counts[status] += 1
        fields.append({
            "field": display_name,
            "left_value": _raw_display(left_raw),
            "right_value": _raw_display(right_raw),
            "left_normalized": _json_value(left_normalized),
            "right_normalized": _json_value(right_normalized),
            "status": status,
            "validation": {
                "left_invalid": left_invalid,
                "right_invalid": right_invalid,
            },
        })

    return {
        "left_source": left_source,
        "right_source": right_source,
        "fields": fields,
        "summary": {
            "matches": counts["match"],
            "mismatches": counts["mismatch"],
            "missing": counts["missing"],
        },
    }


def compare_records(
    left_record: Mapping[str, Any],
    right_record: Mapping[str, Any],
    *,
    left_source: str = "left",
    right_source: str = "right",
) -> Dict[str, Any]:
    """Compare two records field by field and return a JSON-compatible result."""
    return _compare_pair(left_record, right_record, left_source, right_source)


def compare_registered_to_reference(
    registered_record: Mapping[str, Any], reference_record: Mapping[str, Any]
) -> Dict[str, Any]:
    """Compare registered student details against the reference record."""
    return _compare_pair(registered_record, reference_record, "registered", "reference")


def compare_external_to_reference(
    external_record: Mapping[str, Any], reference_record: Mapping[str, Any]
) -> Dict[str, Any]:
    """Compare externally captured details against the reference record."""
    return _compare_pair(external_record, reference_record, "external", "reference")


def compare_registered_to_external(
    registered_record: Mapping[str, Any], external_record: Mapping[str, Any]
) -> Dict[str, Any]:
    """Compare registered student details against externally captured details."""
    return _compare_pair(registered_record, external_record, "registered", "external")


def compare_three_sources(
    registered_record: Mapping[str, Any],
    reference_record: Mapping[str, Any],
    external_record: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return the three independent pairwise comparisons without merging status."""
    return {
        "registered_vs_reference": compare_registered_to_reference(
            registered_record, reference_record
        ),
        "external_vs_reference": compare_external_to_reference(
            external_record, reference_record
        ),
        "registered_vs_external": compare_registered_to_external(
            registered_record, external_record
        ),
    }
