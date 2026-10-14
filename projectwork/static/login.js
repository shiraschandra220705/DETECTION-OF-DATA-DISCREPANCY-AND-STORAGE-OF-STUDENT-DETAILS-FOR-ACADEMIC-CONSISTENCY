
import { auth } from "./firebase-config.js";
import {
  signInWithEmailAndPassword
} from "https://www.gstatic.com/firebasejs/13.0.0/firebase-auth.js";

const form = document.getElementById("login-form");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const status = document.getElementById("login-status");
const submitButton = form.querySelector('button[type="submit"]');

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const email = emailInput.value.trim();
  const password = passwordInput.value;

  status.textContent = "";
  status.style.color = "";
  submitButton.disabled = true;
  submitButton.firstChild.textContent = "Logging in... ";

  try {
    // Step 1: Authenticate with Firebase
    const userCredential = await signInWithEmailAndPassword(
      auth,
      email,
      password
    );

    // Step 2: Obtain a Firebase ID token
    const idToken = await userCredential.user.getIdToken();

    // Step 3: Send the token to Flask for verification
    const response = await fetch("/greettree", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ idToken })
    });

    const result = await response.json();

    if (!response.ok || result.status !== "success") {
      throw new Error(result.message || "Server authentication failed.");
    }

    // Step 4: Flask has established the session; redirect
    window.location.assign(result.redirect || "/session_page");

  } catch (error) {
    console.error("Login error:", error);

    const messages = {
      "auth/invalid-credential": "Incorrect email or password.",
      "auth/user-not-found": "No account exists with this email.",
      "auth/wrong-password": "Incorrect email or password.",
      "auth/invalid-email": "Please enter a valid email address.",
      "auth/too-many-requests": "Too many attempts. Please try again later.",
      "auth/network-request-failed": "Network error. Check your internet connection."
    };

    status.textContent =
      messages[error.code] ||
      error.message ||
      "Login failed. Please try again.";

    status.style.color = "red";

  } finally {
    submitButton.disabled = false;
    submitButton.firstChild.textContent = "Login ";
  }
});
