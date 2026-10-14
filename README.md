# Detection of Data Discrepancy and Storage of Student Details for Academic Consistency

A web-based student record management system designed to securely store student academic details and provide a foundation for detecting discrepancies in academic records.

## Project Overview

The system allows students to create accounts, authenticate securely, submit their academic information, and retrieve their saved details. Firebase Authentication handles user authentication, while Cloud Firestore stores student profiles and academic records.

The project is being developed as part of a Bachelor of Engineering major project.

## Technology Stack

- **Frontend:** HTML, CSS, JavaScript
- **Backend:** Python, Flask
- **Authentication:** Firebase Authentication (Email/Password)
- **Database:** Cloud Firestore
- **Firebase Backend SDK:** Firebase Admin SDK
- **Development Tools:** Visual Studio Code, Git, GitHub

## Features Implemented

- User registration using email and password
- User login using Firebase Authentication
- Firebase ID-token verification on the Flask backend
- Authenticated Flask sessions
- Protection of the student-details page against unauthenticated access
- Storage of basic user profiles in Firestore
- Submission and storage of academic details in Firestore
- Retrieval and display of saved academic details
- Server-side validation of submitted student information

## Project Structure

```text
project/
├── app.py
├── requirements.txt
├── README.md
├── templates/
│   ├── login.html
│   ├── index.html
│   ├── session.html
│   └── greet.html
└── static/
    ├── firebase-config.js
    ├── login.js
    ├── index_script.js
    ├── session_script.js
    ├── greet.js
    └── *.css
```

*Note: The exact filenames may vary slightly depending on the latest project version.*

## Prerequisites

Install the following before running the project:

- Python 3.13 or another compatible Python version
- Git
- Visual Studio Code (recommended)
- An internet connection

You must also have access to the Firebase project and its configured Authentication and Firestore services.

## Setup Instructions

### 1. Clone the repository

Clone the project from GitHub:

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
```

Navigate to the cloned project directory:

```bash
cd <YOUR_PROJECT_FOLDER>
```

Replace the placeholders with the actual repository URL and folder name.

### 2. Create a Python virtual environment

On Windows, run:

```powershell
python -m venv .venv
```

Activate the environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, use Command Prompt instead:

```cmd
.venv\Scripts\activate.bat
```

### 3. Install dependencies

Install the required packages:

```powershell
python -m pip install -r requirements.txt
```

If `requirements.txt` is not yet present, create it with these minimum dependencies:

```text
Flask
Flask-Session
firebase-admin
```

Then run the installation command again.

### 4. Configure Firebase

The project uses Firebase Authentication and Cloud Firestore.

#### Firebase web configuration

Check `static/firebase-config.js` and ensure that it contains the web configuration for the intended Firebase project.

The Firebase web configuration is distinct from the Firebase Admin service-account private key. Never place Admin SDK credentials in frontend files.

#### Firebase Admin SDK credentials

Obtain authorized credentials for the backend through the project administrator.

Store the service-account JSON file outside the cloned repository. For example:

```text
C:\Users\<YOUR_USERNAME>\firebase-credentials\serviceAccountKey.json
```

Do not commit this file to GitHub or share it publicly.

### 5. Configure environment variables

Open a PowerShell terminal in the project directory.

Set the Firebase credentials path:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = "$HOME\firebase-credentials\serviceAccountKey.json"
```

Generate a unique Flask session secret:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the generated value locally and configure it:

```powershell
$env:FLASK_SECRET_KEY = "YOUR_GENERATED_SECRET"
```

Use your own secret and keep it private. Do not commit it to GitHub.

These PowerShell environment variables apply to the current terminal session. Configure them again in a new terminal, or use an appropriately secured persistent configuration.

### 6. Run the Flask application

From the project directory, execute:

```powershell
python -m flask run
```

Open the application in your browser:

http://127.0.0.1:5000/

The application should display the login page.

## Firebase Database Structure

The application currently uses the following Firestore collections.

### `users`

Stores basic information about authenticated users.

Example document structure:

```json
{
  "uid": "FIREBASE_AUTH_UID",
  "name": "Student Name",
  "email": "student@example.com",
  "updatedAt": "Firestore server timestamp"
}
```

Each document is identified by the authenticated user's Firebase UID.

### `student_records`

Stores the academic details submitted by each student.

Example document structure:

```json
{
  "uid": "FIREBASE_AUTH_UID",
  "usn": "1DA23IS000",
  "phone": "9999999999",
  "dob": "2005-01-01",
  "cgpa": 8.5,
  "tenthmarks": 92.5,
  "pucmarks": 94.0,
  "college": "College Name",
  "branch": "ISE",
  "semester": 5,
  "updatedAt": "Firestore server timestamp"
}
```

The document ID is the authenticated user's UID. The values above are illustrative examples, not actual student records.

## Application Workflow

1. A new user registers using email and password.
2. The user logs in through Firebase Authentication.
3. The frontend obtains a Firebase ID token.
4. Flask verifies the ID token and establishes an authenticated session.
5. The authenticated user enters their academic details.
6. Flask validates the submitted data and saves the record to Firestore.
7. The user sees a submission confirmation.
8. The user can retrieve and view their saved academic details.

## Security Considerations

- Never commit Firebase service-account JSON files, private keys, or Flask session secrets.
- Do not store user passwords in Flask sessions or Firestore.
- Verify Firebase ID tokens on the backend.
- Require an authenticated session for student-record operations.
- Use the authenticated UID to identify which student's record to retrieve or update.
- Configure Firebase permissions and credentials with the minimum required access.
- Use HTTPS and secure cookie settings when deploying outside local development.
- Keep `.venv/`, `.env` files containing secrets, and credential files out of version control.

## Current Development Status

The following functionality has been implemented and tested locally:

- Firebase email/password authentication
- Backend Firebase ID-token verification
- Flask authenticated sessions
- Basic user-profile storage in Firestore
- Academic record submission and storage
- Retrieval and display of saved student details

Further development will focus on completing the academic discrepancy-detection workflow, strengthening authorization, and improving the overall application.

## Contributors

- Shriyans — Project Lead
- Shiras — Team Member
- Vishnu — Team Member

## Academic Project

**Project Title:** Detection of Data Discrepancy and Storage of Student Details for Academic Consistency

**Department:** Information Science and Engineering

**Institution:** Dr. Ambedkar Institute of Technology
