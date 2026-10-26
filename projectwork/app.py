from flask import render_template, Flask, request, redirect, jsonify, session
from flask_session import Session
import firebase_admin
from firebase_admin import firestore, auth 
import os

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
