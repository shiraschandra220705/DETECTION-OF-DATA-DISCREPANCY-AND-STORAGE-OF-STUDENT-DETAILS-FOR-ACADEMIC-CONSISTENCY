
const viewButton = document.querySelector("#view-details-btn");
const detailsContainer = document.querySelector("#details-container");
const detailsList = document.querySelector("#details-list");
const statusMessage = document.querySelector("#details-status");

const labels = {
  usn: "USN",
  phone: "Phone number",
  dob: "Date of birth",
  cgpa: "CGPA",
  tenthmarks: "10th percentage",
  pucmarks: "PUC percentage",
  college: "College",
  branch: "Branch",
  semester: "Semester"
};

viewButton.addEventListener("click", async () => {
  viewButton.disabled = true;
  statusMessage.textContent = "Retrieving your saved details...";
  statusMessage.classList.add("visible");

  try {
    const response = await fetch("/api/my-details", {
      method: "GET",
      headers: {
        "Accept": "application/json"
      },
      credentials: "same-origin"
    });

    const result = await response.json();

    if (!response.ok || result.status !== "success") {
      throw new Error(result.message || "Unable to retrieve your details.");
    }

    detailsList.replaceChildren();

    Object.entries(labels).forEach(([key, label]) => {
      const term = document.createElement("dt");
      term.textContent = label;

      const description = document.createElement("dd");
      const value = result.details[key];

      description.textContent =
        value === undefined || value === null || value === ""
          ? "Not provided"
          : String(value);

      detailsList.append(term, description);
    });

    detailsContainer.hidden = false;
    statusMessage.textContent = "Your saved details have been retrieved.";
    viewButton.textContent = "Details Retrieved";

  } catch (error) {
    statusMessage.textContent =
      error.message || "Something went wrong. Please try again.";

    viewButton.disabled = false;
  }
});
