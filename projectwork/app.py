from flask import render_template, Flask, request, redirect, jsonify, session
from flask_session import Session
import firebase_admin
from firebase_admin import firestore, auth 
from google.cloud.firestore_v1.field_path import FieldPath
from collections.abc import Mapping
import os

try:
    # Supports launching as `flask --app projectwork.app ...` from repo root.
    from .model import match_student, normalize_usn
    from .comparison import compare_registered_to_reference, compare_three_sources
except ImportError:
    # Supports launching from projectwork with `flask --app app ...`.
    from model import match_student, normalize_usn
    from comparison import compare_registered_to_reference, compare_three_sources

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


def match_current_student_reference():
    """Match the logged-in student's registered record to reference records.

    The UID comes only from the verified Flask session established at login.
    The raw model result is returned for internal server-side use; this helper
    is not itself exposed as an HTTP endpoint.
    """
    uid = session.get("uid")
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
        "name": profile.get("name") or session.get("name"),
    }
    normalized_usn = normalize_usn(registered_student["usn"])
    if not normalized_usn:
        return {"status": "registered_usn_missing", "model_result": None}

    reference_collection = db.collection(REFERENCE_COLLECTION)
    direct_snapshot = reference_collection.document(normalized_usn).get(
        field_paths=list(REFERENCE_MATCH_FIELD_PATHS)
    )

    reference_records = []
    retrieval_method = "bounded_scan"
    if direct_snapshot.exists:
        direct_record = direct_snapshot.to_dict() or {}
        if normalize_usn(direct_record.get("USN")) == normalized_usn:
            reference_records = [direct_record]
            retrieval_method = "direct_usn_document"

    candidate_set_truncated = False
    if not reference_records:
        query = reference_collection.select(list(REFERENCE_MATCH_FIELD_PATHS)).limit(
            MAX_REFERENCE_CANDIDATES + 1
        )
        scanned_records = [snapshot.to_dict() or {} for snapshot in query.stream()]
        candidate_set_truncated = len(scanned_records) > MAX_REFERENCE_CANDIDATES
        reference_records = scanned_records[:MAX_REFERENCE_CANDIDATES]

    if not reference_records:
        return {
            "status": "reference_record_missing",
            "retrieval_method": retrieval_method,
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


def compare_current_student_records(external_record=None):
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
            }
        if any(key not in EXTERNAL_STUDENT_FIELDS for key in external_record):
            return {
                "match_status": "invalid_external_record",
                "matching_method": None,
                "similarity_score": None,
                "comparisons": {},
            }
        # Pass a new, allowlisted mapping rather than the caller's mapping.
        external_record = {key: external_record[key] for key in external_record}

    match_result = match_current_student_reference()
    model_result = match_result.get("model_result") or {}
    response = {
        "match_status": match_result.get("status", "unmatched"),
        "matching_method": model_result.get("matching_method"),
        "similarity_score": model_result.get("similarity_score"),
        "comparisons": {},
    }

    if response["match_status"] not in {"exact_match", "fuzzy_match"}:
        return response

    registered_record = match_result.get("registered_record")
    matched_reference = model_result.get("matched_candidate")
    if not isinstance(registered_record, Mapping) or not isinstance(matched_reference, Mapping):
        response["match_status"] = "uncertain"
        return response

    if external_record is None:
        response["comparisons"] = {
            "registered_vs_reference": compare_registered_to_reference(
                registered_record, matched_reference
            )
        }
    else:
        response["comparisons"] = compare_three_sources(
            registered_record, matched_reference, external_record
        )
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
