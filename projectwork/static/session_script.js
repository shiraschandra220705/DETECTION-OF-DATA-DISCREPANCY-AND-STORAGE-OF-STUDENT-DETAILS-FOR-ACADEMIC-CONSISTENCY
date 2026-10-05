const form = document.querySelector("#student-form");
const formCard = document.querySelector(".form-card");
const originalFormMarkup = formCard.innerHTML;

const fields = {
  name: document.querySelector("#name"),
  usn: document.querySelector("#usn"),
  phone: document.querySelector("#phone"),
  dob: document.querySelector("#dob"),
  cgpa: document.querySelector("#cgpa"),
  tenthmarks: document.querySelector("#tenthmarks"),
  pucmarks: document.querySelector("#pucmarks"),
};

const errors = {
  name: document.querySelector("#name-error"),
  usn: document.querySelector("#usn-error"),
  phone: document.querySelector("#phone-error"),
  dob: document.querySelector("#dob-error"),
  cgpa: document.querySelector("#cgpa-error"),
  tenthmarks: document.querySelector("#tenthmarks-error"),
  pucmarks: document.querySelector("#pucmarks-error"),
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
    tenthmarks: fields.tenthmarks.value.trim(),
    pucmarks: fields.pucmarks.value.trim(),
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

  if (!/^\d{1,3}(\.\d{1,2})?$/.test(values.tenthmarks)) {
    setError("tenthmarks", "Enter valid marks (e.g., 95.5).");
    valid = false;
  }

  if (!/^\d{1,3}(\.\d{1,2})?$/.test(values.pucmarks)) {
    setError("pucmarks", "Enter valid marks (e.g., 88.75).");
    valid = false;
  }

  return { valid, values };
}

function showSuccess(values) {
  const payload = {
                tenthmarks: values.tenthmarks,
                pucmarks: values.pucmarks,
                cgpa: values.cgpa,
                dob: values.dob,
                usn: values.usn,
                name: values.name
            };
      fetch('/greetsession', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json' // Tells Flask to expect JSON
                },
                body: JSON.stringify(payload) // Convert JS object to a string
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
        
                  window.location.href = data.redirect; 
                }
            })
            .catch(error => {
                console.error('Error sending data:', error);
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

fields.usn.addEventListener("input", () => {
  fields.usn.value = fields.usn.value.toUpperCase();
});