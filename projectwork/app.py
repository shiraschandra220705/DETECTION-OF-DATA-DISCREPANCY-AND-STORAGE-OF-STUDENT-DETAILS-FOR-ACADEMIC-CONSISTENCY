from flask import render_template, Flask, request, redirect, jsonify, session
from flask_session import Session
import firebase_admin
from firebase_admin import firestore, auth 
from google.cloud.firestore_v1.field_path import FieldPath
from werkzeug.exceptions import RequestEntityTooLarge
from collections.abc import Mapping
import os

try:
    # Supports launching as `flask --app projectwork.app ...` from repo root.
    from .model import match_student, normalize_usn
    from .comparison import (
        compare_registered_to_reference, compare_external_to_reference,
        compare_registered_to_external, compare_three_sources,
    )
except ImportError:
    # Supports launching from projectwork with `flask --app app ...`.
    from model import match_student, normalize_usn
    from comparison import (
        compare_registered_to_reference, compare_external_to_reference,
        compare_registered_to_external, compare_three_sources,
    )

app = Flask(__name__)

# Load the secret from the environment
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY")

if not app.config["SECRET_KEY"]:
    raise RuntimeError("FLASK_SECRET_KEY environment variable is not set")

# Session configuration
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"

# Session cookie security
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Local development only; enable True when deployed over HTTPS
app.config["SESSION_COOKIE_SECURE"] = False

Session(app)

# Initialize Firebase Admin SDK
if not firebase_admin._apps:
    firebase_admin.initialize_app()

# Initialize Cloud Firestore
db = firestore.client()

REFERENCE_COLLECTION = "reference_students"
REFERENCE_MATCH_FIELDS = (
    "USN",
    "Name",
    "DOB",
    "CGPA",
    "Semester",
    "10th Percentage",
    "12th Percentage",
    "College Name",
    "Branch",
)
REFERENCE_MATCH_FIELD_PATHS = tuple(
    FieldPath(field_name).to_api_repr() for field_name in REFERENCE_MATCH_FIELDS
)
MAX_REFERENCE_CANDIDATES = 100
MAX_EXTENSION_REQUEST_BYTES = 16 * 1024
EXTERNAL_STUDENT_FIELDS = frozenset({
    "usn", "USN",
    "name", "Name",
    "dob", "DOB", "date_of_birth",
    "cgpa", "CGPA",
    "semester", "Semester",
    "tenthmarks", "10th Percentage", "10th_percentage",
    "pucmarks", "12th Percentage", "12th_percentage",
    "college", "College Name", "college_name",
    "branch", "Branch",
})
EXTENSION_FIELD_MAP = {
    "USN": "USN",
    "usn": "USN",
    "Name": "Name",
    "name": "Name",
    "DOB": "DOB",
    "dob": "DOB",
    "date_of_birth": "DOB",
    "CGPA": "CGPA",
    "cgpa": "CGPA",
    "Semester": "Semester",
    "semester": "Semester",
    "10th Grade": "10th Percentage",
    "10th Percentage": "10th Percentage",
    "10th_percentage": "10th Percentage",
    "tenthmarks": "10th Percentage",
    "12th Grade": "12th Percentage",
    "12th Percentage": "12th Percentage",
    "12th_percentage": "12th Percentage",
    "pucmarks": "12th Percentage",
    "College Name": "College Name",
    "college": "College Name",
    "college_name": "College Name",
    "Branch": "Branch",
    "branch": "Branch",
    # Kept in the accepted request format, but there is no comparison rule
    # for academic year in the current comparison engine.
    "Academic Year": None,
}
REQUIRE_HTTPS = os.environ.get("FLASK_REQUIRE_HTTPS", "true").strip().lower() in {"1", "true", "yes"}


def find_exact_reference_by_normalized_usn(usn):
    """Return a unique projected reference record for an exact normalized USN.

    The scan is deliberately bounded and uses only comparison fields. A full
    scan beyond the bound cannot establish uniqueness, so it fails closed.
    """
    normalized_usn = normalize_usn(usn)
    if not normalized_usn:
        return {"status": "not_found"}

    query = db.collection(REFERENCE_COLLECTION).select(
        list(REFERENCE_MATCH_FIELD_PATHS)
    ).limit(MAX_REFERENCE_CANDIDATES + 1)
    scanned_records = [snapshot.to_dict() or {} for snapshot in query.stream()]
    if len(scanned_records) > MAX_REFERENCE_CANDIDATES:
        return {"status": "lookup_incomplete"}

    matches = [
        record for record in scanned_records
        if normalize_usn(record.get("USN")) == normalized_usn
    ]
    if len(matches) > 1:
        return {"status": "ambiguous"}
    if not matches:
        return {"status": "not_found"}
    return {"status": "found", "record": matches[0]}


def match_current_student_reference(authenticated_uid=None):
    """Match the logged-in student's registered record to reference records.

    The UID comes only from the verified Flask session established at login.
    The raw model result is returned for internal server-side use; this helper
    is not itself exposed as an HTTP endpoint.
    """
    # Explicit identity is supplied only by the extension API after Firebase
    # token verification. Existing website calls continue using the session.
    uid = authenticated_uid if authenticated_uid is not None else session.get("uid")
    if not uid:
        return {"status": "unauthenticated", "model_result": None}

    student_snapshot = db.collection("student_records").document(uid).get()
    if not student_snapshot.exists:
        return {"status": "student_record_missing", "model_result": None}

    stored_student = student_snapshot.to_dict() or {}
    profile_snapshot = db.collection("users").document(uid).get(field_paths=["name"])
    profile = profile_snapshot.to_dict() if profile_snapshot.exists else {}
    profile = profile or {}

    # Send the matcher only fields it uses for identity or the planned
    # academic comparisons. In particular, phone and other profile data stay
    # outside the reference-matching flow.
    registered_student = {
        "usn": stored_student.get("usn"),
        "dob": stored_student.get("dob"),
        "cgpa": stored_student.get("cgpa"),
        "semester": stored_student.get("semester"),
        "tenthmarks": stored_student.get("tenthmarks"),
        "pucmarks": stored_student.get("pucmarks"),
        "college": stored_student.get("college"),
        "branch": stored_student.get("branch"),
        "name": profile.get("name") or (session.get("name") if authenticated_uid is None else None),
    }
    normalized_usn = normalize_usn(registered_student["usn"])
    if not normalized_usn:
        raw_usn = registered_student["usn"]
        status = "registered_usn_missing" if raw_usn is None or (isinstance(raw_usn, str) and not raw_usn.strip()) else "registered_usn_invalid"
        return {"status": status, "registered_record": registered_student, "model_result": None}

    reference_collection = db.collection(REFERENCE_COLLECTION)
    direct_snapshot = reference_collection.document(normalized_usn).get(
        field_paths=list(REFERENCE_MATCH_FIELD_PATHS)
    )

    direct_record = direct_snapshot.to_dict() or {} if direct_snapshot.exists else {}
    direct_hit = (
        direct_snapshot.exists
        and normalize_usn(direct_record.get("USN")) == normalized_usn
    )
    retrieval_method = "direct_usn_document" if direct_hit else "bounded_scan"

    # Even a direct document hit must be checked against a bounded projected
    # scan: different document IDs may contain USNs that normalize identically.
    query = reference_collection.select(list(REFERENCE_MATCH_FIELD_PATHS)).limit(
        MAX_REFERENCE_CANDIDATES + 1
    )
    scanned_records = [snapshot.to_dict() or {} for snapshot in query.stream()]
    candidate_set_truncated = len(scanned_records) > MAX_REFERENCE_CANDIDATES
    bounded_records = scanned_records[:MAX_REFERENCE_CANDIDATES]

    if candidate_set_truncated:
        return {
            "status": "uncertain",
            "retrieval_method": retrieval_method,
            "candidate_set_truncated": True,
            "registered_record": registered_student,
            "model_result": None,
        }

    exact_usn_records = [
        record for record in bounded_records
        if normalize_usn(record.get("USN")) == normalized_usn
    ]
    if len(exact_usn_records) > 1:
        return {
            "status": "ambiguous_match",
            "retrieval_method": retrieval_method,
            "candidate_set_truncated": False,
            "registered_record": registered_student,
            "model_result": {
                "matching_method": "exact_usn",
                "similarity_score": None,
                "matched_candidate": None,
                "ambiguity_status": {"status": "ambiguous", "is_ambiguous": True},
            },
        }

    if direct_hit:
        # The complete bounded scan must confirm the direct record as the sole
        # normalized match before it is eligible for comparison.
        if not exact_usn_records:
            return {
                "status": "uncertain",
                "retrieval_method": retrieval_method,
                "candidate_set_truncated": False,
                "registered_record": registered_student,
                "model_result": None,
            }
        reference_records = [direct_record]
    else:
        reference_records = bounded_records

    if not reference_records:
        return {
            "status": "reference_record_missing",
            "retrieval_method": retrieval_method,
            "registered_record": registered_student,
            "model_result": None,
        }

    model_result = match_student(registered_student, reference_records)
    model_status = model_result.get("ambiguity_status", {}).get("status")

    if candidate_set_truncated and model_status != "ambiguous":
        # A bounded, partial scan cannot establish uniqueness or safely
        # eliminate other candidates, even if the visible subset looks strong.
        status = "uncertain"
    elif model_status == "resolved":
        status = "exact_match" if model_result.get("matching_method") == "exact_usn" else "fuzzy_match"
    elif model_status == "ambiguous":
        status = "ambiguous_match"
    elif model_status == "unmatched":
        status = "unmatched"
    else:
        status = "uncertain"

    return {
        "status": status,
        "retrieval_method": retrieval_method,
        "candidate_set_truncated": candidate_set_truncated,
        "registered_record": registered_student,
        "model_result": model_result,
    }


def compare_current_student_records(external_record=None, authenticated_uid=None):
    """Compare the current student's registered data to a resolved reference.

    Optional external data is accepted only as a mapping containing supported
    student fields. This is an internal service function, not an HTTP route.
    Its return value deliberately excludes source records and raw matcher data.
    """
    if external_record is not None:
        if not isinstance(external_record, Mapping):
            return {
                "match_status": "invalid_external_record",
                "matching_method": None,
                "similarity_score": None,
                "comparisons": {},
                "registered_record_exists": False,
                "reference_record_exists": False,
                "reference_identity_verified": False,
                "identity_verification_status": "incomplete",
                "external_comparisons_blocked": False,
                "discrepancies_detected": False,
                "message": "Invalid external student record; no comparison could be performed.",
                "overall_result": "No comparison could be performed",
            }
        if any(key not in EXTERNAL_STUDENT_FIELDS for key in external_record):
            return {
                "match_status": "invalid_external_record",
                "matching_method": None,
                "similarity_score": None,
                "comparisons": {},
                "registered_record_exists": False,
                "reference_record_exists": False,
                "reference_identity_verified": False,
                "identity_verification_status": "incomplete",
                "external_comparisons_blocked": False,
                "discrepancies_detected": False,
                "message": "Invalid external student record; no comparison could be performed.",
                "overall_result": "No comparison could be performed",
            }
        # Pass a new, allowlisted mapping rather than the caller's mapping.
        external_record = {key: external_record[key] for key in external_record}

    match_result = match_current_student_reference(authenticated_uid)
    model_result = match_result.get("model_result") or {}
    status = match_result.get("status", "unmatched")
    response = {
        "match_status": status,
        "matching_method": model_result.get("matching_method"),
        "similarity_score": model_result.get("similarity_score"),
        "registered_record_exists": status != "student_record_missing" and status != "unauthenticated",
        "reference_record_exists": False,
        "reference_identity_verified": False,
        "identity_verification_status": "incomplete",
        "external_comparisons_blocked": False,
        "comparisons": {},
        "discrepancies_detected": False,
        "message": None,
    }

    registered_record = match_result.get("registered_record")
    matched_reference = model_result.get("matched_candidate")
    registered_exists = status != "student_record_missing" and isinstance(registered_record, Mapping)
    response["registered_record_exists"] = registered_exists

    if status in {"exact_match", "fuzzy_match"} and not isinstance(matched_reference, Mapping):
        response["match_status"] = "uncertain"
        response["message"] = "Reference identity could not be safely resolved."

    if registered_exists and status in {"exact_match", "fuzzy_match"} and isinstance(matched_reference, Mapping):
        response["reference_record_exists"] = True
        response["reference_identity_verified"] = True
        response["identity_verification_status"] = "verified"
    elif status in {"student_record_missing", "registered_usn_missing", "registered_usn_invalid"} and external_record is not None:
        # With no registered identity, use only the external normalized USN for
        # an exact document lookup. Never use fuzzy matching to select a student.
        external_usn = normalize_usn(next(
            (external_record[key] for key in ("usn", "USN") if key in external_record), None
        ))
        if external_usn:
            snapshot = db.collection(REFERENCE_COLLECTION).document(external_usn).get(
                field_paths=list(REFERENCE_MATCH_FIELD_PATHS)
            )
            candidate = snapshot.to_dict() or {} if snapshot.exists else {}
            if snapshot.exists and normalize_usn(candidate.get("USN")) == external_usn:
                matched_reference = candidate
                response["reference_record_exists"] = True

    safe_to_compare_reference = isinstance(matched_reference, Mapping)
    if registered_exists and external_record is not None:
        registered_usn = normalize_usn(registered_record.get("usn"))
        external_usn = normalize_usn(next(
            (external_record[key] for key in ("usn", "USN") if key in external_record), None
        ))
        if not registered_usn or not external_usn or registered_usn != external_usn:
            response["message"] = "External identity could not be safely matched to the registered student."
            response["external_comparisons_blocked"] = True
            safe_external = False
        else:
            safe_external = True
    else:
        safe_external = external_record is not None

    if registered_exists and safe_to_compare_reference and status not in {"registered_usn_missing", "registered_usn_invalid"}:
        if external_record is not None and safe_external:
            response["comparisons"] = compare_three_sources(registered_record, matched_reference, external_record)
        else:
            response["comparisons"]["registered_vs_reference"] = compare_registered_to_reference(registered_record, matched_reference)
    elif not registered_exists and safe_to_compare_reference and external_record is not None and safe_external:
        response["comparisons"]["external_vs_reference"] = compare_external_to_reference(external_record, matched_reference)
    elif registered_exists and status in {"registered_usn_missing", "registered_usn_invalid"} and safe_to_compare_reference and external_record is not None:
        response["comparisons"]["external_vs_reference"] = compare_external_to_reference(external_record, matched_reference)
    elif registered_exists and external_record is not None and safe_external:
        # Reference is unavailable, but registered and external can still be compared.
        response["comparisons"]["registered_vs_external"] = compare_registered_to_external(registered_record, external_record)

    identity_unverified = (
        status in {"registered_usn_missing", "registered_usn_invalid"}
        or response["external_comparisons_blocked"]
        or (status == "student_record_missing" and external_record is not None)
        or status in {"ambiguous_match", "uncertain", "unmatched"}
    )
    if status in {"registered_usn_missing", "registered_usn_invalid"}:
        response["message"] = "Registered record exists, but its USN is missing or invalid; authenticated identity could not be safely verified."
    elif response["external_comparisons_blocked"]:
        response["message"] = "External identity could not be safely matched to the registered student; external comparisons were blocked."
    elif not registered_exists and status != "student_record_missing":
        response["message"] = response["message"] or "Student identity is unavailable."
    elif not registered_exists:
        response["message"] = "Student is not registered."
    elif not response["reference_record_exists"]:
        response["message"] = "Reference record is unavailable."
    response["discrepancies_detected"] = any(
        pair["summary"]["mismatches"] > 0 for pair in response["comparisons"].values()
    )
    if response["comparisons"] and identity_unverified and response["discrepancies_detected"]:
        response["overall_result"] = "Discrepancies detected in available comparisons; identity could not be fully verified."
    elif response["comparisons"] and identity_unverified:
        response["overall_result"] = "Identity could not be safely verified; only partial comparisons were possible."
    elif response["discrepancies_detected"]:
        response["overall_result"] = "Discrepancies detected"
    elif response["comparisons"]:
        response["overall_result"] = "No discrepancies detected in the available comparisons"
    else:
        response["overall_result"] = "No comparison could be performed"
        if not identity_unverified and not (response.get("message") and "identity" in response["message"].casefold()):
            response["message"] = "No comparison could be performed because the required records were unavailable."
    return response

print("Firebase Admin SDK initialized successfully")
print("Cloud Firestore client initialized successfully")

@app.route("/")
def login_page():
    return render_template("login.html")

@app.route("/signup")
def index():
    return render_template("index.html")


@app.route("/greettree", methods=["POST"])
def greettree():
    data = request.get_json(silent=True) or {}
    id_token = data.get("idToken")

    if not id_token:
        return jsonify({
            "status": "error",
            "message": "Firebase ID token is required."
        }), 401

    try:
        # Verify the token with Firebase Admin SDK
        decoded_token = firebase_admin.auth.verify_id_token(id_token)

        # Use the verified identity, not user-supplied form values
        uid = decoded_token["uid"]
        email = decoded_token.get("email", "")
        name = decoded_token.get("name", "")
        
        # Save the authenticated user's basic profile to Firestore
        db.collection("users").document(uid).set({
            "uid": uid,
            "name": name,
            "email": email,
            "updatedAt": firestore.SERVER_TIMESTAMP
        }, merge=True)


        # Clear any previous session before establishing authentication
        session.clear()
        session["uid"] = uid
        session["email"] = email
        session["name"] = name

        return jsonify({
            "status": "success",
            "redirect": "/session_page"
        })

    except Exception:
        app.logger.exception("Firebase token verification failed")
        return jsonify({
            "status": "error",
            "message": "Authentication failed. Please log in again."
        }), 401



@app.route("/session_page")
def session_page():
    # Only authenticated users can access this page.
    uid = session.get("uid")
    if not uid:
        return redirect("/")

    try:
        record_doc = db.collection("student_records").document(uid).get()
        is_editing = request.args.get("edit") == "1"

        # Returning users go straight to their saved record unless they
        # explicitly choose Edit Details.
        if record_doc.exists and not is_editing:
            return redirect("/greet")

        details = record_doc.to_dict() if record_doc.exists else {}
        return render_template(
            "session.html",
            name=session.get("name", ""),
            email=session.get("email", ""),
            details=details,
            is_editing=is_editing and record_doc.exists
        )
    except Exception:
        app.logger.exception("Failed to load student record for the form")
        return "Could not load your student details. Please try again.", 500



@app.route("/greetsession", methods=["POST"])
def greetsession():
    # Require an authenticated Flask session
    uid = session.get("uid")
    if not uid:
        return jsonify({
            "status": "error",
            "message": "Please log in again."
        }), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "status": "error",
            "message": "Invalid request data."
        }), 400

    try:
        # Read and validate the submitted fields
        usn = str(data.get("usn", "")).strip().upper()
        phone = str(data.get("phone", "")).strip()
        dob = str(data.get("dob", "")).strip()
        college = str(data.get("college", "")).strip()
        branch = str(data.get("branch", "")).strip()
        cgpa = float(data.get("cgpa"))
        tenthmarks = float(data.get("tenthmarks"))
        pucmarks = float(data.get("pucmarks"))
        semester = int(data.get("semester"))

        # Validate values on the server, not just in JavaScript
        if len(usn) < 3:
            raise ValueError("Please enter a valid USN.")

        phone_digits = "".join(c for c in phone if c.isdigit())
        if not 10 <= len(phone_digits) <= 15:
            raise ValueError("Please enter a valid phone number.")

        from datetime import date
        dob_date = date.fromisoformat(dob)
        if dob_date > date.today():
            raise ValueError("Date of birth cannot be in the future.")

        if not 4 <= cgpa <= 10:
            raise ValueError("CGPA must be between 4.0 and 10.0.")

        if not 0 <= tenthmarks <= 100:
            raise ValueError("10th marks must be between 0 and 100.")

        if not 0 <= pucmarks <= 100:
            raise ValueError("PUC marks must be between 0 and 100.")

        if not 1 <= semester <= 8:
            raise ValueError("Semester must be between 1 and 8.")

        if len(college) < 2 or len(branch) < 2:
            raise ValueError("Please enter a valid college and branch.")

        # Save the record under the authenticated user's UID
        db.collection("student_records").document(uid).set({
            "uid": uid,
            "usn": usn,
            "phone": phone,
            "dob": dob,
            "cgpa": cgpa,
            "tenthmarks": tenthmarks,
            "pucmarks": pucmarks,
            "college": college,
            "branch": branch,
            "semester": semester,
            "updatedAt": firestore.SERVER_TIMESTAMP
        }, merge=True)

        return jsonify({
            "status": "success",
            "redirect": "/greet"
        })

    except (ValueError, TypeError):
        return jsonify({
            "status": "error",
            "message": "Please check your academic details and try again."
        }), 400

    except Exception:
        app.logger.exception("Failed to save student record")
        return jsonify({
            "status": "error",
            "message": "Could not save your details. Please try again."
        }), 500



@app.route("/greet")
def greet():
    uid = session.get("uid")

    if not uid:
        return redirect("/")

    try:
        record = db.collection("student_records").document(uid).get()

        if not record.exists:
            return redirect("/session_page")

        details = record.to_dict()

        return render_template(
            "greet.html",
            name=session.get("name", ""),
            usn=details.get("usn", ""),
            phone=details.get("phone", ""),
            cgpa=details.get("cgpa", ""),
            tenthmarks=details.get("tenthmarks", ""),
            pucmarks=details.get("pucmarks", ""),
            dob=details.get("dob", ""),
            college = "Dr. Ambedkar Institute of Technology",
            branch=details.get("branch", ""),
            semester=details.get("semester", "")
        )

    except Exception:
        app.logger.exception("Failed to retrieve student record")
        return "Could not retrieve your details. Please try again.", 500


@app.route("/api/my-details", methods=["GET"])
def get_my_details():
    # Require an authenticated user
    uid = session.get("uid")
    if not uid:
        return jsonify({
            "status": "error",
            "message": "Please log in again."
        }), 401

    try:
        # Retrieve only the current user's record
        doc = db.collection("student_records").document(uid).get()

        if not doc.exists:
            return jsonify({
                "status": "error",
                "message": "No student record found."
            }), 404

        details = doc.to_dict()

        # Return only the fields needed by the frontend
        return jsonify({
            "status": "success",
            "details": {
                "usn": details.get("usn", ""),
                "phone": details.get("phone", ""),
                "dob": details.get("dob", ""),
                "cgpa": details.get("cgpa", ""),
                "tenthmarks": details.get("tenthmarks", ""),
                "pucmarks": details.get("pucmarks", ""),
                "college": details.get("college", ""),
                "branch": details.get("branch", ""),
                "semester": details.get("semester", "")
            }
        })

    except Exception:
        app.logger.exception("Failed to retrieve student details")
        return jsonify({
            "status": "error",
            "message": "Unable to retrieve your details."
        }), 500


@app.route("/api/extension/compare", methods=["POST"])
def extension_compare():
    """Compare AcademicPortal values for the Firebase-authenticated user."""
    if REQUIRE_HTTPS and not request.is_secure and not app.testing:
        return jsonify({
            "status": "error",
            "message": "HTTPS is required for this endpoint.",
        }), 400

    # Keep this endpoint's payload bounded without changing limits for other
    # website routes. Extension requests include only a small student record.
    request.max_content_length = MAX_EXTENSION_REQUEST_BYTES
    if request.content_length is not None and request.content_length > MAX_EXTENSION_REQUEST_BYTES:
        return jsonify({
            "status": "error",
            "message": "Request body is too large.",
        }), 413

    authorization = request.headers.get("Authorization", "")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].casefold() != "bearer" or not parts[1]:
        return jsonify({
            "status": "error",
            "message": "A valid Firebase Bearer token is required.",
        }), 401

    try:
        decoded_token = auth.verify_id_token(parts[1], check_revoked=True)
        uid = decoded_token.get("uid") if isinstance(decoded_token, Mapping) else None
        if not isinstance(uid, str) or not uid.strip():
            return jsonify({
                "status": "error",
                "message": "Authentication failed. Please log in again.",
            }), 401
    except Exception:
        # Verification failures include invalid, expired, revoked, and
        # malformed Firebase ID tokens. Do not return verifier details.
        return jsonify({
            "status": "error",
            "message": "Authentication failed. Please log in again.",
        }), 401

    try:
        data = request.get_json(silent=True)
    except RequestEntityTooLarge:
        return jsonify({
            "status": "error",
            "message": "Request body is too large.",
        }), 413
    if not isinstance(data, dict) or set(data) != {"external_record"}:
        return jsonify({
            "status": "error",
            "message": "Request must contain only an external_record object.",
        }), 400

    supplied_record = data.get("external_record")
    if not isinstance(supplied_record, dict) or not supplied_record:
        return jsonify({
            "status": "error",
            "message": "external_record must be a non-empty object.",
        }), 400

    if any(key not in EXTENSION_FIELD_MAP for key in supplied_record):
        return jsonify({
            "status": "error",
            "message": "external_record contains unsupported fields.",
        }), 400
    canonical_fields = [
        EXTENSION_FIELD_MAP[key]
        for key in supplied_record
        if EXTENSION_FIELD_MAP[key] is not None
    ]
    if len(canonical_fields) != len(set(canonical_fields)):
        return jsonify({
            "status": "error",
            "message": "external_record contains conflicting field aliases.",
        }), 400
    if any(isinstance(value, (dict, list, bool)) for value in supplied_record.values()):
        return jsonify({
            "status": "error",
            "message": "Student field values must be strings, numbers, or null.",
        }), 400

    # Convert extension labels to the aliases understood by the existing
    # comparison layer. Academic Year is accepted but intentionally omitted.
    external_record = {
        EXTENSION_FIELD_MAP[key]: value
        for key, value in supplied_record.items()
        if EXTENSION_FIELD_MAP[key] is not None
    }
    if not external_record:
        return jsonify({
            "status": "error",
            "message": "external_record must include at least one comparable student field.",
        }), 400

    extracted_usn = normalize_usn(external_record.get("USN"))
    if not extracted_usn:
        return jsonify({
            "status": "error",
            "message": "external_record must contain a valid USN.",
        }), 400

    try:
        # Read only the authenticated user's own USN to choose the mode. Never
        # query a private record using the submitted/extracted USN.
        own_record = db.collection("student_records").document(uid).get(
            field_paths=["usn"]
        )
        own_data = own_record.to_dict() or {} if own_record.exists else {}
        registered_usn = normalize_usn(own_data.get("usn"))

        if registered_usn and registered_usn == extracted_usn:
            result = compare_current_student_records(
                external_record,
                authenticated_uid=uid,
            )
            if result.get("match_status") == "student_record_missing":
                return jsonify({
                    "status": "error",
                    "message": "No registered student record found for this account.",
                }), 404
            result["mode"] = "personal"
            result["relationship_verification_status"] = "verified"
            return jsonify({"status": "success", "comparison": result}), 200

        lookup = find_exact_reference_by_normalized_usn(extracted_usn)
        reference_status = lookup["status"]
        if reference_status == "found":
            external_comparison = compare_external_to_reference(
                external_record, lookup["record"]
            )
            comparisons = {"external_vs_reference": external_comparison}
            discrepancy = external_comparison["summary"]["mismatches"] > 0
            message = "Comparison with the exact reference record completed."
            overall_result = (
                "Discrepancies detected" if discrepancy
                else "No discrepancies detected in the available comparison"
            )
        else:
            comparisons = {}
            discrepancy = False
            if reference_status == "ambiguous":
                message = "Multiple reference records match this normalized USN; no comparison was performed."
                overall_result = "Reference record is ambiguous"
            elif reference_status == "lookup_incomplete":
                message = "A unique reference record could not be established; no comparison was performed."
                overall_result = "Reference lookup could not be completed safely"
            else:
                reference_status = "unavailable"
                message = "No exact reference record is available for this USN."
                overall_result = "Reference record is unavailable"

        is_other_student = bool(own_record.exists and registered_usn)
        mode = "other_student" if is_other_student else "reference_only"
        relationship_status = "different_student" if is_other_student else "unverified"
        result = {
            "mode": mode,
            "relationship_verification_status": relationship_status,
            "reference_status": reference_status,
            "reference_available": reference_status == "found",
            "comparisons": comparisons,
            "discrepancies_detected": discrepancy,
            "message": message,
            "overall_result": overall_result,
        }
        return jsonify({"status": "success", "comparison": result}), 200
    except Exception:
        app.logger.exception("Extension discrepancy comparison failed")
        return jsonify({
            "status": "error",
            "message": "Unable to complete the comparison. Please try again.",
        }), 500
