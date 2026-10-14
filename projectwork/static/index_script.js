
import { auth } from "./firebase-config.js";
import {
  createUserWithEmailAndPassword,
  updateProfile,
  signOut
} from "https://www.gstatic.com/firebasejs/13.0.0/firebase-auth.js";

const form = document.getElementById("profileForm");
const password = document.getElementById("password");
const passwordToggle = document.getElementById("passwordToggle");

passwordToggle.addEventListener("click", () => {
  const isPassword = password.type === "password";
  password.type = isPassword ? "text" : "password";

  passwordToggle.textContent = isPassword ? "Hide" : "Show";
  passwordToggle.setAttribute(
    "aria-label",
    isPassword ? "Hide password" : "Show password"
  );
});

function setError(field, message) {
  const input = document.getElementById(field);
  const error = document.getElementById(field + "Error");

  input?.classList.toggle("invalid", Boolean(message));

  if (error) {
    error.textContent = message || "";
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const name = document.getElementById("name").value.trim();
  const email = document.getElementById("email").value.trim();
  const passwordValue = password.value;
  const agreement = document.getElementById("agreement").checked;

  let valid = true;

  if (name.length < 2) {
    setError("name", "Please enter a name with at least two characters.");
    valid = false;
  } else {
    setError("name", "");
  }

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    setError("email", "Please enter a valid email address.");
    valid = false;
  } else {
    setError("email", "");
  }

  if (
    passwordValue.length < 10 ||
    !/[A-Z]/.test(passwordValue) ||
    !/[0-9]/.test(passwordValue)
  ) {
    setError(
      "password",
      "Use at least 10 characters with one uppercase letter and one number."
    );
    valid = false;
  } else {
    setError("password", "");
  }

  const agreementError = document.getElementById("agreementError");
  agreementError.textContent = agreement
    ? ""
    : "Please accept the terms to continue.";

  if (!agreement) valid = false;
  if (!valid) return;

  const submitButton = form.querySelector('button[type="submit"]');
  const formError = document.getElementById("formError");

  submitButton.disabled = true;
  submitButton.firstChild.textContent = "Creating account... ";

  if (formError) formError.textContent = "";

  try {
    const userCredential = await createUserWithEmailAndPassword(
      auth,
      email,
      passwordValue
    );

    await updateProfile(userCredential.user, {
      displayName: name
    });

    await signOut(auth);

    window.location.href = "/";
  } catch (error) {
    console.error("Signup error:", error.code, error.message);

    const messages = {
      "auth/email-already-in-use": "An account already exists for this email.",
      "auth/invalid-email": "Please enter a valid email address.",
      "auth/weak-password": "Please choose a stronger password.",
      "auth/operation-not-allowed": "Email/password sign-up is not enabled in Firebase.",
      "auth/network-request-failed": "Network error. Please check your connection."
    };

    if (formError) {
      formError.textContent =
        messages[error.code] ||
        "We couldn't create your account. Please try again.";
    }

    submitButton.disabled = false;
    submitButton.firstChild.textContent = "Create profile ";
  }
});
