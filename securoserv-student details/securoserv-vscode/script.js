const form = document.querySelector("#student-form");
const formCard = document.querySelector(".form-card");
const originalFormMarkup = formCard.innerHTML;

const fields = {
  name: document.querySelector("#name"),
  usn: document.querySelector("#usn"),
  phone: document.querySelector("#phone"),
  dob: document.querySelector("#dob"),
  cgpa: document.querySelector("#cgpa"),
  grade: document.querySelector("#grade"),
};

const errors = {
  name: document.querySelector("#name-error"),
  usn: document.querySelector("#usn-error"),
  phone: document.querySelector("#phone-error"),
  dob: document.querySelector("#dob-error"),
  cgpa: document.querySelector("#cgpa-error"),
  grade: document.querySelector("#grade-error"),
};

fields.dob.max = new Date().toISOString().split("T")[0];

function setError(fieldName, message) {
  const field = fields[fieldName];
  const error = errors[fieldName];

  field.setAttribute("aria-invalid", message ? "true" : "false");
  error.textContent = message;
}

function validate() {
  const values = {
    name: fields.name.value.trim(),
    usn: fields.usn.value.trim(),
    phone: fields.phone.value.trim(),
    dob: fields.dob.value,
    cgpa: Number(fields.cgpa.value),
    grade: fields.grade.value.trim().toUpperCase(),
  };

  Object.keys(errors).forEach((fieldName) => setError(fieldName, ""));

  let valid = true;

  if (values.name.length < 2) {
    setError("name", "Please enter your name.");
    valid = false;
  }

  if (values.usn.length < 3) {
    setError("usn", "Please enter your USN.");
    valid = false;
  }

  const phoneDigits = values.phone.replace(/\D/g, "");
  if (phoneDigits.length < 10 || phoneDigits.length > 15) {
    setError("phone", "Please enter a valid phone number.");
    valid = false;
  }

  if (!values.dob) {
    setError("dob", "Please select your date of birth.");
    valid = false;
  } else if (values.dob > fields.dob.max) {
    setError("dob", "Date of birth cannot be in the future.");
    valid = false;
  }

  if (!values.cgpa || values.cgpa < 4 || values.cgpa > 10) {
    setError("cgpa", "CGPA must be between 4.0 and 10.0.");
    valid = false;
  }

  if (!/^[A-F]$/.test(values.grade)) {
    setError("grade", "Enter one grade from A to F.");
    valid = false;
  }

  return { valid, values };
}

function showSuccess(values) {
  formCard.innerHTML = `
    <div class="success-card">
      <div class="success-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none">
          <path d="m5 12.5 4.2 4.2L19 7" />
        </svg>
      </div>
      <span class="mono-label">ENTRY SAVED</span>
      <h2>Details submitted.</h2>
      <p>Thank you, ${escapeHtml(values.name)}. Your student details have been recorded for the academic office.</p>
      <button type="button" id="new-entry">Start another entry <span aria-hidden="true">→</span></button>
    </div>
  `;

  document.querySelector("#new-entry").addEventListener("click", () => {
    formCard.innerHTML = originalFormMarkup;
    window.location.reload();
  });
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[character]));
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const { valid, values } = validate();

  if (!valid) {
    const firstInvalid = Object.keys(fields).find(
      (fieldName) => fields[fieldName].getAttribute("aria-invalid") === "true",
    );
    fields[firstInvalid]?.focus();
    return;
  }

  showSuccess(values);
});

fields.grade.addEventListener("input", () => {
  fields.grade.value = fields.grade.value.toUpperCase();
});