"""Student identity matching helpers.

This module performs record identification only. It has no CSV, Firestore,
Flask, global-dataframe, or generated-model-file side effects. Callers supply
student details and candidate reference records.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from rapidfuzz import fuzz


# Canonical project fields map to either the student_records schema or the
# original CSV/Firestore reference field names.
_FIELD_ALIASES = {
    "usn": ("usn", "USN"),
    "name": ("name", "Name"),
    "dob": ("dob", "DOB", "date_of_birth"),
    "cgpa": ("cgpa", "CGPA"),
    "semester": ("semester", "Semester"),
    "tenthmarks": ("tenthmarks", "10th Percentage", "10th_percentage"),
    "pucmarks": ("pucmarks", "12th Percentage", "12th_percentage"),
    "college": ("college", "College Name", "college_name"),
    "branch": ("branch", "Branch"),
}

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

# The primary ID dominates. Other fields only help rank possible candidates;
# academic values are deliberately low-weight evidence and are not compared as
# discrepancies here. Calculated CGPA and semester SGPA fields are not read.
_WEIGHTS = {
    "usn": 0.45,
    "name": 0.25,
    "dob": 0.15,
    "branch": 0.05,
    "semester": 0.03,
    "cgpa": 0.03,
    "tenthmarks": 0.02,
    "pucmarks": 0.02,
}
_FUZZY_MATCH_THRESHOLD = 72.0
_AMBIGUITY_MARGIN = 8.0
# Independent identity evidence needed in addition to the aggregate score.
# When USN is supplied, a fuzzy USN must score at least 85 and must be
# corroborated by either a strong name (>= 85) or DOB (>= 90). If USN is
# missing, the documented fallback requires both a strong name (>= 92) and
# exact/near-exact DOB (>= 90). Academic values and branch never satisfy this
# identity-evidence gate.
_MIN_FUZZY_USN_SCORE = 85.0
_MIN_CORROBORATING_NAME_SCORE = 85.0
_MIN_FALLBACK_NAME_SCORE = 92.0
_MIN_DOB_SCORE = 90.0


def normalize_missing(value: Any) -> Any:
    """Convert common empty/null markers to None, preserving other values."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.casefold() in {"nan", "none", "null", "n/a", "na", "<na>"}:
            return None
        return stripped
    try:
        if value != value:  # NaN without requiring pandas/numpy.
            return None
    except (TypeError, ValueError):
        pass
    return value


def normalize_usn(value: Any) -> Optional[str]:
    """Normalize USN casing and formatting for exact and fuzzy matching."""
    value = normalize_missing(value)
    if value is None:
        return None
    normalized = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    return normalized or None


def normalize_date(value: Any) -> Optional[str]:
    """Normalize supported date values to ISO YYYY-MM-DD."""
    value = normalize_missing(value)
    if value is None:
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
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return re.sub(r"\s+", "", text).casefold()


def normalize_number(value: Any) -> Optional[float]:
    """Parse finite numeric values consistently; return None when missing/invalid."""
    value = normalize_missing(value)
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(" ", "")
    if "," in text and "." not in text:
        # Accept decimal-comma values while also allowing grouped thousands.
        if text.count(",") == 1 and len(text.rsplit(",", 1)[1]) <= 2:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", "")
    try:
        number = float(Decimal(text))
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def normalize_branch(value: Any) -> Optional[str]:
    """Normalize branch spelling, punctuation, spacing, and common abbreviations."""
    value = normalize_missing(value)
    if value is None:
        return None
    text = re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()
    text = re.sub(r"\s+", " ", text)
    return _BRANCH_ALIASES.get(text, text) or None


def _field(record: Mapping[str, Any], canonical_name: str) -> Any:
    for key in _FIELD_ALIASES[canonical_name]:
        if key in record:
            return normalize_missing(record[key])
    return None


def _text_score(left: Any, right: Any, *, branch: bool = False) -> Optional[float]:
    if branch:
        left = normalize_branch(left)
        right = normalize_branch(right)
    else:
        left = normalize_missing(left)
        right = normalize_missing(right)
        left = str(left).casefold() if left is not None else None
        right = str(right).casefold() if right is not None else None
    if left is None or right is None:
        return None
    return float(fuzz.WRatio(left, right))


def _numeric_score(left: Any, right: Any, tolerance: float) -> Optional[float]:
    left_number = normalize_number(left)
    right_number = normalize_number(right)
    if left_number is None or right_number is None:
        return None
    return max(0.0, 100.0 * (1.0 - abs(left_number - right_number) / tolerance))


def _score_candidate(student: Mapping[str, Any], candidate: Mapping[str, Any]) -> Optional[float]:
    scores = {
        "usn": _text_score(normalize_usn(_field(student, "usn")), normalize_usn(_field(candidate, "usn"))),
        "name": _text_score(_field(student, "name"), _field(candidate, "name")),
        "dob": _text_score(normalize_date(_field(student, "dob")), normalize_date(_field(candidate, "dob"))),
        "branch": _text_score(_field(student, "branch"), _field(candidate, "branch"), branch=True),
        "semester": _numeric_score(_field(student, "semester"), _field(candidate, "semester"), 8.0),
        "cgpa": _numeric_score(_field(student, "cgpa"), _field(candidate, "cgpa"), 4.0),
        "tenthmarks": _numeric_score(_field(student, "tenthmarks"), _field(candidate, "tenthmarks"), 100.0),
        "pucmarks": _numeric_score(_field(student, "pucmarks"), _field(candidate, "pucmarks"), 100.0),
    }
    available = [(score, _WEIGHTS[field]) for field, score in scores.items() if score is not None]
    if not available:
        return None
    return sum(score * weight for score, weight in available) / sum(weight for _, weight in available)


def _identity_evidence(student: Mapping[str, Any], candidate: Mapping[str, Any]) -> Dict[str, Optional[float]]:
    """Return only the independent identity-field scores used for acceptance."""
    return {
        "usn": _text_score(
            normalize_usn(_field(student, "usn")),
            normalize_usn(_field(candidate, "usn")),
        ),
        "name": _text_score(_field(student, "name"), _field(candidate, "name")),
        "dob": _text_score(
            normalize_date(_field(student, "dob")),
            normalize_date(_field(candidate, "dob")),
        ),
    }


def _has_sufficient_identity_evidence(
    student: Mapping[str, Any], candidate: Mapping[str, Any]
) -> Tuple[bool, str]:
    """Require at least two independent identity signals for fuzzy resolution."""
    evidence = _identity_evidence(student, candidate)
    usn_supplied = normalize_usn(_field(student, "usn")) is not None

    if usn_supplied:
        usn_score = evidence["usn"]
        if usn_score is None or usn_score < _MIN_FUZZY_USN_SCORE:
            return False, "Fuzzy USN similarity is below the required 85."
        corroborated = (
            evidence["name"] is not None
            and evidence["name"] >= _MIN_CORROBORATING_NAME_SCORE
        ) or (evidence["dob"] is not None and evidence["dob"] >= _MIN_DOB_SCORE)
        if not corroborated:
            return False, "A sufficiently similar USN requires corroboration by name or DOB."
        return True, "Fuzzy USN is corroborated by an independent identity field."

    # Fallback when the primary identifier is absent: require both name and
    # DOB, since either alone can identify multiple students or be mistyped.
    if (
        evidence["name"] is not None
        and evidence["name"] >= _MIN_FALLBACK_NAME_SCORE
        and evidence["dob"] is not None
        and evidence["dob"] >= _MIN_DOB_SCORE
    ):
        return True, "USN is missing; strong name and DOB jointly satisfy the fallback."
    return False, "USN is missing; fuzzy resolution requires strong name and DOB evidence."


def _json_value(value: Any) -> Any:
    """Convert Firestore-like and standard Python values to JSON-safe values."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        converted = float(value)
        return converted if math.isfinite(converted) else None
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    # Firestore Timestamp and other SDK scalar types commonly provide this.
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)


def match_student(
    student_details: Mapping[str, Any],
    reference_records: Iterable[Mapping[str, Any]],
    *,
    threshold: float = _FUZZY_MATCH_THRESHOLD,
    ambiguity_margin: float = _AMBIGUITY_MARGIN,
    max_candidates: int = 5,
) -> Dict[str, Any]:
    """Identify a supplied student against reference records.

    Exact normalized USN is authoritative. Without an exact match, candidates
    are ranked using a weighted multi-field fuzzy score. Low-confidence or
    close-scoring results are reported as uncertain/ambiguous and are not
    asserted as a match. This function does not detect field discrepancies.
    """
    if not isinstance(student_details, Mapping):
        raise TypeError("student_details must be a mapping")

    records = [record for record in reference_records if isinstance(record, Mapping)]
    input_usn = normalize_usn(_field(student_details, "usn"))
    if input_usn:
        exact = [record for record in records if normalize_usn(_field(record, "usn")) == input_usn]
        if len(exact) == 1:
            candidate = _json_value(exact[0])
            return {
                "matched_candidate": candidate,
                "candidate": candidate,
                "matching_method": "exact_usn",
                "similarity_score": 100.0,
                "ambiguity_status": {"status": "resolved", "is_ambiguous": False, "reason": None},
                "identity_evidence": {
                    "scores": {"usn": 100.0, "name": None, "dob": None},
                    "sufficient": True,
                    "reason": "Unique exact normalized USN match.",
                },
                "possible_candidates": [],
            }
        if len(exact) > 1:
            possible = [_json_value(record) for record in exact[:max_candidates]]
            return {
                "matched_candidate": None,
                "candidate": None,
                "matching_method": "exact_usn",
                "similarity_score": 100.0,
                "ambiguity_status": {"status": "ambiguous", "is_ambiguous": True, "reason": "Multiple reference records have the same normalized USN."},
                "identity_evidence": {
                    "scores": {"usn": 100.0, "name": None, "dob": None},
                    "sufficient": False,
                    "reason": "Duplicate normalized USN records prevent a unique exact match.",
                },
                "possible_candidates": possible,
            }

    scored: List[Tuple[float, Mapping[str, Any]]] = []
    for record in records:
        score = _score_candidate(student_details, record)
        if score is not None:
            scored.append((score, record))
    scored.sort(key=lambda item: item[0], reverse=True)

    if not scored:
        return {
            "matched_candidate": None,
            "candidate": None,
            "matching_method": "none",
            "similarity_score": None,
            "ambiguity_status": {"status": "unmatched", "is_ambiguous": False, "reason": "No comparable identity fields were supplied."},
            "possible_candidates": [],
        }

    top_score, top_record = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else None
    ambiguous = second_score is not None and (top_score - second_score) < ambiguity_margin
    possible = [
        {"candidate": _json_value(record), "similarity_score": round(score, 2)}
        for score, record in scored[:max_candidates]
    ]
    top_candidate = _json_value(top_record)
    sufficient_evidence, evidence_reason = _has_sufficient_identity_evidence(
        student_details, top_record
    )

    if ambiguous:
        status = "ambiguous"
        reason = "Top candidates have scores within the configured ambiguity margin."
        matched = None
    elif top_score < threshold:
        status = "uncertain"
        reason = "Best candidate score is below the configured match threshold."
        matched = None
    elif not sufficient_evidence:
        status = "uncertain"
        reason = evidence_reason
        matched = None
    else:
        status = "resolved"
        reason = None
        matched = top_candidate

    return {
        "matched_candidate": matched,
        "candidate": top_candidate,
        "matching_method": "fuzzy_multifield",
        "similarity_score": round(top_score, 2),
        "ambiguity_status": {"status": status, "is_ambiguous": ambiguous, "reason": reason},
        "identity_evidence": {
            "scores": _identity_evidence(student_details, top_record),
            "sufficient": sufficient_evidence,
            "reason": evidence_reason,
        },
        "possible_candidates": possible,
    }
