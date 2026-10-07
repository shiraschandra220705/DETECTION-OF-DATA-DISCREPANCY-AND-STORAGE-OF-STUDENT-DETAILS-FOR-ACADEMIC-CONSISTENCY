from flask import render_template, Flask, request, redirect, jsonify, session
from flask_session import Session

app = Flask(__name__)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

@app.route("/")
def login_page():
    return render_template("login.html")

@app.route("/signup")
def index():
    return render_template("index.html")

@app.route("/greettree", methods = ["POST"])
def greettree():
    data = request.get_json()
    name = data.get('name')
    password = data.get('password')
    username = data.get('username')
    session["name"] = name
    session["password"] = password
    session["username"] = username
    return jsonify({"status": "success", "redirect": "/session_page"})

@app.route("/session_page")
def session_page():
    user_name = session.get('name')
    user_password = session.get('password')
    user_username = session.get('username')
    return render_template("session.html", name = user_name, password= user_password, username = user_username)

@app.route("/greetsession", methods=["POST"])
def greetsession():
    data = request.get_json()
    usn = data.get('usn')
    cgpa = data.get('cgpa')
    tenthmarks = data.get('tenthmarks')
    pucmarks = data.get('pucmarks')
    dob = data.get('dob')
    session["usn"] = usn
    session["cgpa"] = cgpa
    session["tenthmarks"] = tenthmarks
    session["pucmarks"] = pucmarks
    session["dob"] = dob
    return jsonify({"status": "success", "redirect": "/greet"})

@app.route("/greet")
def greet():
    name = session.get("name")
    usn = session.get("usn")
    cgpa = session.get("cgpa")
    tenthmarks = session.get("tenthmarks")
    pucmarks = session.get("pucmarks")
    dob = session.get("dob")
    return render_template("greet.html", name=name, usn=usn, cgpa=cgpa, tenthmarks=tenthmarks, pucmarks=pucmarks, dob=dob)

    