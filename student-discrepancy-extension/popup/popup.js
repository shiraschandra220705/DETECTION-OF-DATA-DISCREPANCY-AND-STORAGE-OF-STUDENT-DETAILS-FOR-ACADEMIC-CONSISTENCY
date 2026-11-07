
import {
    signInWithEmailAndPassword,
    signOut
} from "firebase/auth/web-extension";
import { auth, waitForAuthInitialization } from "../scripts/firebase-auth.js";

const STUDENT_FIELDS = [
    ["usn", "USN"],
    ["name", "Name"],
    ["dob", "Date of birth"],
    ["college", "College"],
    ["branch", "Branch"],
    ["semester", "Semester"],
    ["academic_year", "Academic year"],
    ["cgpa", "CGPA"],
    ["tenth_percentage", "10th percentage"],
    ["twelfth_percentage", "12th percentage"]
];
const COMPARISON_ENDPOINT = "https://127.0.0.1:5000/api/extension/compare";
const BACKEND_FIELD_MAP = [
    ["usn", "USN"],
    ["name", "Name"],
    ["dob", "DOB"],
    ["college", "College Name"],
    ["branch", "Branch"],
    ["semester", "Semester"],
    ["academic_year", "Academic Year"],
    ["cgpa", "CGPA"],
    ["tenth_percentage", "10th Grade"],
    ["twelfth_percentage", "12th Grade"]
];

let extractedStudentFields = null;
let currentAuthenticatedUser = null;
let comparisonInProgress = false;

document.addEventListener("DOMContentLoaded", () => {
    const checkButton = document.getElementById("checkButton");
    checkButton.addEventListener("click", extractStudentDetails);
    document.getElementById("compareButton").addEventListener("click", compareStudentRecords);

    document.getElementById("signInForm").addEventListener("submit", handleSignIn);
    document.getElementById("signOutButton").addEventListener("click", handleSignOut);

    extractStudentDetails();
    restoreAuthenticationState();
});

async function restoreAuthenticationState() {
    const signInForm = document.getElementById("signInForm");
    const signedInView = document.getElementById("signedInView");
    const authStatusMessage = document.getElementById("authStatusMessage");

    setStatus(authStatusMessage, "Checking sign-in status…", "");

    try {
        const user = await waitForAuthInitialization();
        renderAuthenticationState(user);
        setStatus(
            authStatusMessage,
            user ? "You are signed in." : "Sign in to your account.",
            user ? "success" : ""
        );
    } catch {
        currentAuthenticatedUser = null;
        signInForm.hidden = false;
        signedInView.hidden = true;
        updateComparisonAvailability();
        setStatus(
            authStatusMessage,
            "Authentication could not be initialized. Please close and reopen the extension popup.",
            "error"
        );
    }
}

async function handleSignIn(event) {
    event.preventDefault();

    const emailInput = document.getElementById("emailInput");
    const passwordInput = document.getElementById("passwordInput");
    const signInButton = document.getElementById("signInButton");
    const authStatusMessage = document.getElementById("authStatusMessage");

    signInButton.disabled = true;
    setStatus(authStatusMessage, "Signing in…", "");

    try {
        const userCredential = await signInWithEmailAndPassword(
            auth,
            emailInput.value.trim(),
            passwordInput.value
        );
        passwordInput.value = "";
        renderAuthenticationState(userCredential.user);
        setStatus(authStatusMessage, "Signed in successfully.", "success");
    } catch (error) {
        setStatus(authStatusMessage, getAuthenticationErrorMessage(error), "error");
    } finally {
        signInButton.disabled = false;
    }
}

async function handleSignOut() {
    const signOutButton = document.getElementById("signOutButton");
    const authStatusMessage = document.getElementById("authStatusMessage");

    signOutButton.disabled = true;
    setStatus(authStatusMessage, "Signing out…", "");

    try {
        await signOut(auth);
        renderAuthenticationState(null);
        clearComparisonResult("Sign in to compare student records.");
        setStatus(authStatusMessage, "You have been signed out.", "success");
    } catch {
        setStatus(authStatusMessage, "Could not sign out. Please try again.", "error");
    } finally {
        signOutButton.disabled = false;
    }
}

function renderAuthenticationState(user) {
    const signInForm = document.getElementById("signInForm");
    const signedInView = document.getElementById("signedInView");
    const signedInEmail = document.getElementById("signedInEmail");

    currentAuthenticatedUser = user || null;
    signInForm.hidden = Boolean(user);
    signedInView.hidden = !user;
    signedInEmail.textContent = user?.email || "Signed-in account";
    updateComparisonAvailability();
}

function getAuthenticationErrorMessage(error) {
    const messages = {
        "auth/invalid-credential": "Email or password is incorrect.",
        "auth/invalid-login-credentials": "Email or password is incorrect.",
        "auth/user-not-found": "Email or password is incorrect.",
        "auth/wrong-password": "Email or password is incorrect.",
        "auth/invalid-email": "Enter a valid email address.",
        "auth/missing-password": "Enter your password.",
        "auth/user-disabled": "This account is disabled. Contact your administrator.",
        "auth/too-many-requests": "Too many sign-in attempts. Please wait and try again.",
        "auth/network-request-failed": "Network error. Check your connection and try again.",
        "auth/operation-not-allowed": "Email and password sign-in is not enabled for this account."
    };

    return messages[error?.code] || "Sign-in failed. Check your details and try again.";
}

function updateComparisonAvailability(showHint = true) {
    const compareButton = document.getElementById("compareButton");
    if (!compareButton) return;

    const hasUsn = Boolean(extractedStudentFields?.usn?.trim());
    const isReady = Boolean(
        extractedStudentFields && currentAuthenticatedUser && hasUsn && !comparisonInProgress
    );
    compareButton.disabled = !isReady;

    if (!showHint || comparisonInProgress) return;

    const comparisonStatus = document.getElementById("comparisonStatus");
    if (!extractedStudentFields) {
        setStatus(comparisonStatus, "Extract student details to enable comparison.", "");
    } else if (!currentAuthenticatedUser) {
        setStatus(comparisonStatus, "Sign in to compare student records.", "");
    } else if (!hasUsn) {
        setStatus(comparisonStatus, "A student USN is required before records can be compared.", "error");
    } else {
        setStatus(comparisonStatus, "Ready to compare student records.", "");
    }
}

function clearComparisonResult(message) {
    const comparisonResult = document.getElementById("comparisonResult");
    const comparisonSummary = document.getElementById("comparisonSummary");
    const comparisonPairs = document.getElementById("comparisonPairs");

    comparisonResult.hidden = true;
    comparisonSummary.replaceChildren();
    comparisonPairs.replaceChildren();
    setStatus(document.getElementById("comparisonStatus"), message, "");
}

function buildExternalRecord(fields) {
    const externalRecord = {};
    for (const [sourceField, backendField] of BACKEND_FIELD_MAP) {
        const value = fields[sourceField];
        if (typeof value === "string" && value.trim()) {
            externalRecord[backendField] = value.trim();
        }
    }
    return externalRecord;
}

async function compareStudentRecords() {
    if (!extractedStudentFields || !currentAuthenticatedUser || comparisonInProgress) return;

    comparisonInProgress = true;
    const compareButton = document.getElementById("compareButton");
    const extractButton = document.getElementById("checkButton");
    const comparisonStatus = document.getElementById("comparisonStatus");
    const originalButtonLabel = "Compare Student Records";
    compareButton.textContent = "Comparing…";
    extractButton.disabled = true;
    updateComparisonAvailability(false);
    clearComparisonResult("");
    setStatus(comparisonStatus, "Comparing student records…", "");

    try {
        const initializedUser = await waitForAuthInitialization();
        const requestUser = auth.currentUser;
        if (!initializedUser || !requestUser) {
            throw new Error("Sign in to your Firebase account before comparing records.");
        }

        const externalRecord = buildExternalRecord(extractedStudentFields);
        if (!externalRecord.USN) {
            throw new Error("A student USN is required before records can be compared.");
        }

        // Firebase manages token refresh; this token is used only for this request.
        if (!auth.currentUser || auth.currentUser.uid !== requestUser.uid) {
            throw new Error("Your signed-in account changed during comparison. Please retry.");
        }
        const idToken = await auth.currentUser.getIdToken();
        if (!auth.currentUser || auth.currentUser.uid !== requestUser.uid) {
            throw new Error("Your signed-in account changed during comparison. Please retry.");
        }
        const response = await fetch(COMPARISON_ENDPOINT, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${idToken}`,
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ external_record: externalRecord })
        });

        let responseBody = null;
        try {
            responseBody = await response.json();
        } catch {
            // Handle non-JSON server or proxy errors below without exposing internals.
        }

        if (!response.ok) {
            if (response.status === 401) {
                throw new Error("Your Firebase sign-in could not be verified. Sign out, sign in again, and retry.");
            }
            const backendMessage = typeof responseBody?.message === "string"
                ? responseBody.message
                : "The comparison service could not complete the request.";
            throw new Error(`${backendMessage} (HTTP ${response.status})`);
        }

        const comparison = responseBody?.comparison;
        if (responseBody?.status !== "success" || !comparison || typeof comparison !== "object") {
            const backendMessage = typeof responseBody?.message === "string"
                ? responseBody.message
                : "The comparison service returned an unexpected response.";
            throw new Error(backendMessage);
        }
        if (!auth.currentUser || auth.currentUser.uid !== requestUser.uid) {
            throw new Error("Your signed-in account changed during comparison. The result was not displayed.");
        }

        renderComparisonResult(comparison);
        setStatus(comparisonStatus, comparison.message || comparison.overall_result || "Comparison completed.", "success");
    } catch (error) {
        setStatus(comparisonStatus, getComparisonErrorMessage(error), "error");
    } finally {
        comparisonInProgress = false;
        compareButton.textContent = originalButtonLabel;
        extractButton.disabled = false;
        updateComparisonAvailability(false);
    }
}

function renderComparisonResult(comparison) {
    const comparisonResult = document.getElementById("comparisonResult");
    const comparisonSummary = document.getElementById("comparisonSummary");
    const comparisonPairs = document.getElementById("comparisonPairs");
    const summary = document.createElement("div");

    appendSummaryLine(summary, "Mode", comparison.mode);
    appendSummaryLine(
        summary,
        "Identity verification",
        comparison.relationship_verification_status || comparison.identity_verification_status
    );
    if (comparison.reference_status) {
        appendSummaryLine(summary, "Reference status", comparison.reference_status);
    }
    if (typeof comparison.discrepancies_detected === "boolean") {
        appendSummaryLine(
            summary,
            "Discrepancies detected",
            comparison.discrepancies_detected ? "Yes" : "No",
            "discrepancy-flag"
        );
    }
    appendSummaryLine(summary, "Result", comparison.overall_result);
    appendSummaryLine(summary, "Message", comparison.message);

    const comparisons = comparison.comparisons;
    if (!comparisons || typeof comparisons !== "object" || Array.isArray(comparisons)) {
        throw new Error("The comparison service returned an invalid comparison result.");
    }

    for (const [comparisonName, pair] of Object.entries(comparisons)) {
        if (!pair || typeof pair !== "object") continue;

        const pairContainer = document.createElement("section");
        pairContainer.className = "comparison-pair";
        const pairHeading = document.createElement("h4");
        pairHeading.textContent = comparisonName.replaceAll("_", " ");
        pairContainer.append(pairHeading);

        if (pair.summary && typeof pair.summary === "object") {
            const pairSummary = document.createElement("p");
            pairSummary.className = "comparison-pair-summary";
            pairSummary.textContent = `Matches: ${displayValue(pair.summary.matches)} · Mismatches: ${displayValue(pair.summary.mismatches)} · Missing: ${displayValue(pair.summary.missing)}`;
            pairContainer.append(pairSummary);
        }

        if (Array.isArray(pair.fields)) {
            for (const field of pair.fields) {
                if (!field || typeof field !== "object") continue;
                const fieldContainer = document.createElement("div");
                fieldContainer.className = "comparison-field";
                appendTextElement(fieldContainer, "strong", displayValue(field.field));
                appendTextElement(
                    fieldContainer,
                    "span",
                    `${displayValue(pair.left_source)}: ${displayValue(field.left_value)}`
                );
                appendTextElement(
                    fieldContainer,
                    "span",
                    `${displayValue(pair.right_source)}: ${displayValue(field.right_value)}`
                );
                const fieldStatus = document.createElement("span");
                fieldStatus.className = "field-status";
                fieldStatus.textContent = `Status: ${displayValue(field.status)}`;
                fieldContainer.append(fieldStatus);
                pairContainer.append(fieldContainer);
            }
        }

        comparisonPairs.append(pairContainer);
    }

    comparisonSummary.replaceChildren(summary);
    comparisonResult.hidden = false;
}

function appendSummaryLine(container, label, value, className = "") {
    if (value === undefined || value === null || value === "") return;
    const line = document.createElement("p");
    if (className) line.className = className;
    line.textContent = `${label}: ${displayValue(value)}`;
    container.append(line);
}

function appendTextElement(container, tagName, text) {
    const element = document.createElement(tagName);
    element.textContent = text;
    container.append(element);
}

function displayValue(value) {
    if (value === undefined || value === null || value === "") return "Not available";
    if (["string", "number", "boolean"].includes(typeof value)) return String(value);
    return "Not available";
}

function getComparisonErrorMessage(error) {
    if (typeof error?.code === "string" && error.code.startsWith("auth/")) {
        if (["auth/user-token-expired", "auth/invalid-user-token", "auth/user-disabled"].includes(error.code)) {
            return "Your Firebase sign-in needs to be renewed. Sign out, sign in again, and retry.";
        }
        if (error.code === "auth/network-request-failed") {
            return "Firebase could not refresh your sign-in because the network is unavailable. Check your connection and retry.";
        }
        return "Firebase could not confirm your sign-in. Sign out, sign in again, and retry.";
    }
    if (error instanceof TypeError) {
        return "Could not reach the local HTTPS comparison service. Check that Flask is running and its certificate is trusted.";
    }
    return error?.message || "The comparison could not be completed. Please try again.";
}

async function extractStudentDetails() {
    const checkButton = document.getElementById("checkButton");
    const statusMessage = document.getElementById("statusMessage");
    const details = document.getElementById("studentDetails");

    checkButton.disabled = true;
    extractedStudentFields = null;
    clearComparisonResult("Extract student details and sign in to compare records.");
    updateComparisonAvailability(true);
    details.hidden = true;
    details.replaceChildren();
    setStatus(statusMessage, "Checking the active tab…", "");

    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab || !tab.url) {
            throw new Error("Could not determine the active tab.");
        }

        let profileUrl;
        try {
            profileUrl = new URL(tab.url);
        } catch {
            throw new Error("Open an AcademicPortal student profile to extract details.");
        }

        if (profileUrl.hostname !== "vishnu05.pythonanywhere.com" || profileUrl.protocol !== "https:") {
            throw new Error("You are not on AcademicPortal. Open a student profile on vishnu05.pythonanywhere.com.");
        }

        if (!/^\/students\/[^/]+\/?$/.test(profileUrl.pathname)) {
            throw new Error("Open an AcademicPortal student profile (not the homepage) to extract details.");
        }

        const results = await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            func: extractFieldsFromPage,
            args: [STUDENT_FIELDS.map(([key]) => key)]
        });
        const student = results?.[0]?.result;

        if (!student || !student.found) {
            throw new Error("No student details were found on this profile.");
        }

        extractedStudentFields = student.fields;
        renderDetails(details, student.fields);
        updateComparisonAvailability(true);
        setStatus(statusMessage, "Student details extracted.", "success");
    } catch (error) {
        extractedStudentFields = null;
        updateComparisonAvailability(true);
        const message = error?.message || "Student details could not be extracted. Reload the profile and try again.";
        setStatus(statusMessage, message, "error");
    } finally {
        checkButton.disabled = false;
    }
}

function extractFieldsFromPage(fieldNames) {
    const fields = {};
    let found = false;

    for (const field of fieldNames) {
        const element = document.querySelector(`[data-field="${field}"]`);
        const value = element?.textContent?.trim() || "";
        fields[field] = value;
        if (value) found = true;
    }

    return { fields, found };
}

function renderDetails(container, fields) {
    for (const [key, label] of STUDENT_FIELDS) {
        const item = document.createElement("div");
        item.className = "detail-item";

        const term = document.createElement("dt");
        term.textContent = label;
        const value = document.createElement("dd");
        value.textContent = fields[key] || "Not available";

        item.append(term, value);
        container.append(item);
    }
    container.hidden = false;
}

function setStatus(element, message, state) {
    element.textContent = message;
    element.className = state;
}
