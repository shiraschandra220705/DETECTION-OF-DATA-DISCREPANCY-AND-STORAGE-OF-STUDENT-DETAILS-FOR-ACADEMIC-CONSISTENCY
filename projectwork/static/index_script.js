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

    document.getElementById("username").addEventListener("input", (event) => {
      event.target.value = event.target.value
        .toLowerCase()
        .replace(/\s/g, "");
    });

    function setError(field, message) {
      const input = document.getElementById(field);
      const error = document.getElementById(field + "Error");

      input?.classList.toggle("invalid", Boolean(message));
      if (error) error.textContent = message || "";
    }

    form.addEventListener("submit", (event) => {
      event.preventDefault();

      const name = document.getElementById("name").value.trim();
      const username = document.getElementById("username").value.trim();
      const email = document.getElementById("email").value.trim();
      const passwordValue = password.value;
      const agreement = document.getElementById("agreement").checked;

      let valid = true;

      if (!name) {
        setError("name", "Your name is required.");
        valid = false;
      } else if (name.length < 2) {
        setError("name", "Use at least two characters.");
        valid = false;
      } else {
        setError("name", "");
      }

      if (!/^[a-z0-9_]{3,20}$/.test(username)) {
        setError(
          "username",
          "Use 3–20 lowercase letters, numbers, or underscores."
        );
        valid = false;
      } else {
        setError("username", "");
      }

      
      setError("email", "");
      

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
      const payload = {
                name: name,
                password: passwordValue,
                username: username
            };
      fetch('/greettree', {
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
    });