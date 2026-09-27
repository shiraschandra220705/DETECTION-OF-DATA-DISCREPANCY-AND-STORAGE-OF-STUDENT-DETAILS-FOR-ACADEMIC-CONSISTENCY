# SecuroServ Student Details Form

This is a standalone version of the SecuroServ website. It uses only HTML,
CSS, and JavaScript, so it is easy to run in VS Code.

## Run in VS Code

1. Open the `securoserv-vscode` folder in VS Code.
2. Open `index.html`.
3. Right-click the file and choose **Open with Live Server**.

If Live Server is not installed, install the **Live Server** extension by Ritwick
Dey. You can also double-click `index.html` to open it directly in a browser.

## Files

- `index.html` — page structure and form fields
- `styles.css` — layout, colours, responsive design, and form states
- `script.js` — validation and submission success state

The form validates:

- Name
- USN
- Phone number
- Date of birth
- CGPA from 4.0 to 10.0
- Grade from A to F

This standalone version displays a success message in the browser. It does not
save details to a database.