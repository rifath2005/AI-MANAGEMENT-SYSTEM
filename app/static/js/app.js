const state = {
  token: localStorage.getItem("ams_token") || "",
  user: null,
};

async function api(path, options = {}) {
  const headers = options.headers || {};
  if (state.token) {
    headers["Authorization"] = `Bearer ${state.token}`;
  }
  if (!(options.body instanceof FormData) && options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, { ...options, headers });
  const contentType = res.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

function showEl(el, visible) {
  el.classList.toggle("hidden", !visible);
}

function applyTheme(theme) {
  const mode = theme === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", mode);
  localStorage.setItem("ams_theme", mode);
  document.querySelectorAll(".theme-toggle-btn").forEach((btn) => {
    const iconEl = btn.querySelector(".theme-icon");
    const labelEl = btn.querySelector(".theme-label");
    if (iconEl) iconEl.textContent = mode === "dark" ? "☀" : "☾";
    if (labelEl) labelEl.textContent = mode === "dark" ? "Light Mode" : "Dark Mode";
    btn.setAttribute("aria-pressed", mode === "dark" ? "true" : "false");
  });
}

applyTheme(document.documentElement.getAttribute("data-theme") || "light");
document.querySelectorAll(".theme-toggle-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    applyTheme(current === "dark" ? "light" : "dark");
  });
});

function switchTab(target) {
  document.querySelectorAll(".nav-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === target);
  });
  document.querySelectorAll(".tab-panel").forEach((p) => showEl(p, p.id === `tab-${target}`));
  if (target === "dashboard") loadDashboard();
  if (target === "requests") loadRequests();
  if (target === "admin") loadAdminData();
}

const portalRole = document.getElementById("login-view").dataset.portalRole || "staff";

function setFieldError(inputId, errorId, message) {
  const input = document.getElementById(inputId);
  const errEl = document.getElementById(errorId);
  if (input) {
    input.classList.toggle("is-invalid", !!message);
    input.setAttribute("aria-invalid", message ? "true" : "false");
  }
  if (errEl) {
    errEl.textContent = message || "";
    showEl(errEl, !!message);
  }
}

function clearFieldError(inputId, errorId) {
  setFieldError(inputId, errorId, "");
}

function clearAllFieldErrors(fieldMap) {
  for (const [inputId, errorId] of Object.entries(fieldMap)) {
    clearFieldError(inputId, errorId);
  }
}

const loginFields = {
  "login-email": "login-email-error",
  "login-password": "login-password-error",
};

const signupFields = {
  "signup-fullname": "signup-fullname-error",
  "signup-username": "signup-username-error",
  "signup-dept": "signup-dept-error",
  "signup-email": "signup-email-error",
  "signup-password": "signup-password-error",
};

// Reasonable standard email format regex: local part + @ + domain + top-level domain
const EMAIL_REGEX = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;

function validateEmailFormat(email) {
  return EMAIL_REGEX.test((email || "").trim());
}

function normalizeEmailInput(input) {
  if (!input) return;
  const start = input.selectionStart;
  const end = input.selectionEnd;
  const lowerVal = input.value.toLowerCase();
  if (input.value !== lowerVal) {
    input.value = lowerVal;
    if (start !== null && end !== null) {
      input.setSelectionRange(start, end);
    }
  }
}

// Password Strength Checklist Configuration (Plain language rules)
const passwordRuleConfig = [
  { id: "rule-length", test: (pw) => pw.length >= 8, desc: "At least 8 characters in length" },
  { id: "rule-upper", test: (pw) => /[A-Z]/.test(pw), desc: "At least one uppercase letter (A–Z)" },
  { id: "rule-lower", test: (pw) => /[a-z]/.test(pw), desc: "At least one lowercase letter (a–z)" },
  { id: "rule-digit", test: (pw) => /[0-9]/.test(pw), desc: "At least one numeric digit (0–9)" },
  { id: "rule-special", test: (pw) => /[^A-Za-z0-9]/.test(pw), desc: "At least one special character (!@#$%^&*)" },
];

function evaluatePasswordStrength(password) {
  const pw = password || "";
  const results = {};
  let metCount = 0;

  for (const rule of passwordRuleConfig) {
    const isMet = rule.test(pw);
    results[rule.id] = isMet;
    if (isMet) metCount++;
  }

  let level = "none";
  let label = "None";
  let percent = 0;

  if (pw.length > 0) {
    if (pw.length < 8 || metCount <= 2) {
      level = "weak";
      label = "Weak";
      percent = 33;
    } else if (metCount <= 4) {
      level = "medium";
      label = "Medium";
      percent = 66;
    } else {
      level = "strong";
      label = "Strong";
      percent = 100;
    }
  }

  return {
    results,
    metCount,
    level,
    label,
    percent,
    isFullyValid: metCount === passwordRuleConfig.length,
  };
}

function updatePasswordStrengthUI(evalResult) {
  const labelEl = document.getElementById("signup-strength-label");
  const barEl = document.getElementById("signup-strength-bar");
  const progressEl = document.getElementById("signup-strength-progress");

  if (labelEl) {
    labelEl.textContent = evalResult.label;
    labelEl.className = `strength-badge strength-${evalResult.level}`;
  }

  if (barEl) {
    barEl.className = `strength-meter-bar strength-bar-${evalResult.level}`;
  }

  if (progressEl) {
    progressEl.setAttribute("aria-valuenow", String(evalResult.percent));
  }

  for (const [ruleId, isMet] of Object.entries(evalResult.results)) {
    const itemEl = document.getElementById(ruleId);
    if (itemEl) {
      itemEl.classList.toggle("is-met", isMet);
      itemEl.classList.toggle("is-unmet", !isMet);
      const icon = itemEl.querySelector(".check-icon");
      if (icon) {
        icon.textContent = isMet ? "✓" : "○";
      }
    }
  }
}

function checkSignupFormValidity() {
  const submitBtn = document.getElementById("signup-submit-btn");
  if (!submitBtn) return false;

  const emailInput = document.getElementById("signup-email");
  const passwordInput = document.getElementById("signup-password");
  const fullnameInput = document.getElementById("signup-fullname");
  const usernameInput = document.getElementById("signup-username");
  const deptInput = document.getElementById("signup-dept");

  const emailVal = emailInput ? emailInput.value.trim() : "";
  const isEmailValid = validateEmailFormat(emailVal);
  const pwVal = passwordInput ? passwordInput.value : "";
  const pwEval = evaluatePasswordStrength(pwVal);

  const hasName = fullnameInput ? fullnameInput.value.trim().length > 0 : false;
  const hasUser = usernameInput ? usernameInput.value.trim().length >= 3 : false;
  const hasDept = deptInput ? deptInput.value.trim().length > 0 : false;

  const isFormValid = isEmailValid && pwEval.isFullyValid && hasName && hasUser && hasDept;
  submitBtn.disabled = !isFormValid;
  return isFormValid;
}

// Setup email gate for Login
const loginEmailInput = document.getElementById("login-email") || document.getElementById("login-username");
const loginPasswordInput = document.getElementById("login-password");
const toggleLoginPassBtn = document.getElementById("toggle-login-pass");
const loginSubmitBtn = document.getElementById("login-submit-btn");
const loginPasswordHint = document.getElementById("login-password-hint");

function updateLoginEmailGate(userTriggered = false) {
  if (!loginEmailInput || !loginPasswordInput) return;
  const raw = loginEmailInput.value;
  const trimmed = raw.trim();
  const isValid = portalRole === "admin"
    ? (validateEmailFormat(trimmed) || trimmed.length >= 3)
    : validateEmailFormat(trimmed);

  // Always keep password input and toggle accessible so user and password managers can type freely
  loginPasswordInput.disabled = false;
  if (toggleLoginPassBtn) toggleLoginPassBtn.disabled = false;
  if (loginSubmitBtn) loginSubmitBtn.disabled = false;

  if (isValid) {
    clearFieldError("login-email", "login-email-error");
    clearFieldError("login-username", "login-username-error");
    if (loginPasswordHint) loginPasswordHint.textContent = "";
  } else if (userTriggered && trimmed.length > 0) {
    if (portalRole === "admin") {
      setFieldError("login-email", "login-email-error", "Please enter a valid administrator email or username.");
    } else {
      setFieldError("login-email", "login-email-error", "Please enter a valid email address (e.g. name@company.com).");
    }
  } else if (userTriggered && trimmed.length === 0) {
    setFieldError("login-email", "login-email-error", portalRole === "admin" ? "Administrator email or username is required." : "Corporate email is required.");
  } else {
    clearFieldError("login-email", "login-email-error");
  }
}

if (loginEmailInput) {
  loginEmailInput.addEventListener("input", () => {
    normalizeEmailInput(loginEmailInput);
    updateLoginEmailGate(false);
    showEl(document.getElementById("login-error"), false);
  });
  loginEmailInput.addEventListener("change", () => {
    updateLoginEmailGate(false);
  });
  loginEmailInput.addEventListener("paste", () => {
    setTimeout(() => updateLoginEmailGate(false), 50);
  });
  loginEmailInput.addEventListener("blur", () => {
    loginEmailInput.value = loginEmailInput.value.trim().toLowerCase();
    updateLoginEmailGate(true);
  });
}

if (loginPasswordInput) {
  loginPasswordInput.addEventListener("input", () => {
    clearFieldError("login-password", "login-password-error");
    showEl(document.getElementById("login-error"), false);
  });
}

// Initial state check for login fields
updateLoginEmailGate(false);

// Setup email gate and password strength for Signup
const signupEmailInput = document.getElementById("signup-email");
const signupPasswordInput = document.getElementById("signup-password");
const toggleSignupPassBtn = document.getElementById("toggle-signup-pass");
const signupPasswordHint = document.getElementById("signup-password-hint");
const signupStrengthBox = document.getElementById("signup-password-strength-box");

function updateSignupEmailGate(userTriggered = false) {
  if (!signupEmailInput || !signupPasswordInput) return;
  const raw = signupEmailInput.value;
  const trimmed = raw.trim();
  const isValid = validateEmailFormat(trimmed);

  if (isValid) {
    signupPasswordInput.disabled = false;
    signupPasswordInput.placeholder = "Create a strong password";
    if (toggleSignupPassBtn) toggleSignupPassBtn.disabled = false;
    clearFieldError("signup-email", "signup-email-error");
    if (signupPasswordHint) signupPasswordHint.textContent = "Email verified. Choose a strong password matching all rules.";
    if (signupStrengthBox) showEl(signupStrengthBox, true);
  } else {
    signupPasswordInput.disabled = true;
    signupPasswordInput.placeholder = "Enter valid email first";
    if (toggleSignupPassBtn) toggleSignupPassBtn.disabled = true;
    if (signupPasswordHint) signupPasswordHint.textContent = "Password unlocks after entering a valid corporate email.";
    if (signupStrengthBox) showEl(signupStrengthBox, false);

    if (trimmed.length > 0) {
      setFieldError("signup-email", "signup-email-error", "Please enter a valid corporate email address (e.g. name@company.com).");
    } else {
      if (userTriggered) {
        setFieldError("signup-email", "signup-email-error", "Corporate email is required.");
      } else {
        clearFieldError("signup-email", "signup-email-error");
      }
    }
  }
  checkSignupFormValidity();
}

if (signupEmailInput) {
  signupEmailInput.addEventListener("input", () => {
    normalizeEmailInput(signupEmailInput);
    updateSignupEmailGate(false);
    showEl(document.getElementById("signup-error"), false);
  });
  signupEmailInput.addEventListener("blur", () => {
    signupEmailInput.value = signupEmailInput.value.trim().toLowerCase();
    updateSignupEmailGate(true);
  });
}

if (signupPasswordInput) {
  signupPasswordInput.addEventListener("input", () => {
    clearFieldError("signup-password", "signup-password-error");
    showEl(document.getElementById("signup-error"), false);
    const evalResult = evaluatePasswordStrength(signupPasswordInput.value);
    updatePasswordStrengthUI(evalResult);
    checkSignupFormValidity();
  });
}

// Input clearing listeners for other signup fields
["signup-fullname", "signup-username", "signup-dept"].forEach((inputId) => {
  const el = document.getElementById(inputId);
  if (el) {
    el.addEventListener("input", () => {
      clearFieldError(inputId, `${inputId}-error`);
      showEl(document.getElementById("signup-error"), false);
      checkSignupFormValidity();
    });
  }
});

// Toggle Password Buttons
if (toggleLoginPassBtn) {
  toggleLoginPassBtn.addEventListener("click", () => {
    if (loginPasswordInput.disabled) return;
    const isHidden = loginPasswordInput.type === "password";
    loginPasswordInput.type = isHidden ? "text" : "password";
    toggleLoginPassBtn.textContent = isHidden ? "Hide" : "Show";
  });
}

if (toggleSignupPassBtn) {
  toggleSignupPassBtn.addEventListener("click", () => {
    if (signupPasswordInput.disabled) return;
    const isHidden = signupPasswordInput.type === "password";
    signupPasswordInput.type = isHidden ? "text" : "password";
    toggleSignupPassBtn.textContent = isHidden ? "Hide" : "Show";
  });
}

document.querySelectorAll(".auth-mode-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".auth-mode-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const isSignup = btn.dataset.mode === "signup";
    showEl(document.getElementById("login-form"), !isSignup);
    const signupForm = document.getElementById("signup-form");
    if (signupForm) showEl(signupForm, isSignup);
    clearAllFieldErrors(loginFields);
    showEl(document.getElementById("login-error"), false);
    if (signupForm) {
      clearAllFieldErrors(signupFields);
      showEl(document.getElementById("signup-error"), false);
    }
    if (isSignup) {
      updateSignupEmailGate(false);
    } else {
      updateLoginEmailGate(false);
    }
  });
});

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errEl = document.getElementById("login-error");
  showEl(errEl, false);
  clearAllFieldErrors(loginFields);

  const emailInput = document.getElementById("login-email") || document.getElementById("login-username");
  const passwordInput = document.getElementById("login-password");
  const email = (emailInput.value || "").trim().toLowerCase();
  const password = passwordInput.value || "";

  let hasError = false;
  let firstInvalidEl = null;

  if (!email) {
    setFieldError("login-email", "login-email-error", portalRole === "admin" ? "Administrator email or username is required." : "Corporate email is required.");
    hasError = true;
    firstInvalidEl = firstInvalidEl || emailInput;
  } else if (portalRole !== "admin" && !validateEmailFormat(email)) {
    setFieldError("login-email", "login-email-error", "Please enter a valid email address (e.g. name@company.com).");
    hasError = true;
    firstInvalidEl = firstInvalidEl || emailInput;
  } else if (portalRole === "admin" && !validateEmailFormat(email) && email.length < 3) {
    setFieldError("login-email", "login-email-error", "Please enter a valid administrator email or username.");
    hasError = true;
    firstInvalidEl = firstInvalidEl || emailInput;
  }

  // Login page accepts any non-empty password without enforcing signup password-strength rules
  if (!password) {
    setFieldError("login-password", "login-password-error", "Password is required.");
    hasError = true;
    firstInvalidEl = firstInvalidEl || passwordInput;
  }

  if (hasError) {
    if (firstInvalidEl) firstInvalidEl.focus();
    return;
  }

  const submitBtn = document.getElementById("login-submit-btn");
  const originalBtnText = submitBtn ? submitBtn.textContent : "";
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = portalRole === "admin" ? "Authenticating Admin Gateway..." : "Signing In...";
  }

  const endpoint = portalRole === "admin" ? "/api/auth/admin/login" : "/api/auth/login";
  const payload = {
    username: email,
    email: email,
    password: password,
  };
  if (portalRole !== "admin") {
    payload.portal = portalRole;
  }
  try {
    const res = await api(endpoint, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.token = res.token;
    state.user = res.user;
    localStorage.setItem("ams_token", res.token);
    enterApp();
  } catch (err) {
    errEl.textContent = err.message;
    showEl(errEl, true);
    if (err.message && err.message.toLowerCase().includes("credentials")) {
      emailInput.classList.add("is-invalid");
      passwordInput.classList.add("is-invalid");
    }
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = originalBtnText;
    }
  }
});

const signupForm = document.getElementById("signup-form");
if (signupForm) {
  signupForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errEl = document.getElementById("signup-error");
    showEl(errEl, false);
    clearAllFieldErrors(signupFields);

    const fullnameInput = document.getElementById("signup-fullname");
    const usernameInput = document.getElementById("signup-username");
    const deptInput = document.getElementById("signup-dept");
    const emailInput = document.getElementById("signup-email");
    const passwordInput = document.getElementById("signup-password");

    const fullName = (fullnameInput.value || "").trim();
    const username = (usernameInput.value || "").trim();
    const department = (deptInput.value || "").trim();
    const email = (emailInput.value || "").trim().toLowerCase();
    const password = passwordInput.value || "";

    let hasError = false;
    let firstInvalidEl = null;

    if (!fullName) {
      setFieldError("signup-fullname", "signup-fullname-error", "Full name is required.");
      hasError = true;
      firstInvalidEl = firstInvalidEl || fullnameInput;
    }

    if (!username) {
      setFieldError("signup-username", "signup-username-error", "Username is required.");
      hasError = true;
      firstInvalidEl = firstInvalidEl || usernameInput;
    } else if (username.length < 3) {
      setFieldError("signup-username", "signup-username-error", "Username must be at least 3 characters.");
      hasError = true;
      firstInvalidEl = firstInvalidEl || usernameInput;
    } else if (!/^[a-zA-Z0-9._]+$/.test(username)) {
      setFieldError("signup-username", "signup-username-error", "Username may only contain letters, numbers, dots, and underscores.");
      hasError = true;
      firstInvalidEl = firstInvalidEl || usernameInput;
    }

    if (!department) {
      setFieldError("signup-dept", "signup-dept-error", "Department is required.");
      hasError = true;
      firstInvalidEl = firstInvalidEl || deptInput;
    }

    if (!email) {
      setFieldError("signup-email", "signup-email-error", "Corporate email is required.");
      hasError = true;
      firstInvalidEl = firstInvalidEl || emailInput;
    } else if (!validateEmailFormat(email)) {
      setFieldError("signup-email", "signup-email-error", "Please enter a valid corporate email address.");
      hasError = true;
      firstInvalidEl = firstInvalidEl || emailInput;
    }

    const pwEval = evaluatePasswordStrength(password);
    if (!password) {
      setFieldError("signup-password", "signup-password-error", "Password is required.");
      hasError = true;
      firstInvalidEl = firstInvalidEl || passwordInput;
    } else if (!pwEval.isFullyValid) {
      setFieldError(
        "signup-password",
        "signup-password-error",
        "Password does not meet the minimum security requirements. Please satisfy all rules below."
      );
      hasError = true;
      firstInvalidEl = firstInvalidEl || passwordInput;
    }

    if (hasError) {
      if (firstInvalidEl) firstInvalidEl.focus();
      return;
    }

    const submitBtn = document.getElementById("signup-submit-btn");
    const originalBtnText = submitBtn ? submitBtn.textContent : "";
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Creating Account...";
    }

    try {
      const res = await api("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({
          full_name: fullName,
          username: username,
          department: department,
          email: email,
          password: password,
        }),
      });
      state.token = res.token;
      state.user = res.user;
      localStorage.setItem("ams_token", res.token);
      enterApp();
    } catch (err) {
      errEl.textContent = err.message;
      showEl(errEl, true);
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = originalBtnText;
      }
    }
  });
}

document.getElementById("logout-btn").addEventListener("click", () => {
  state.token = "";
  state.user = null;
  localStorage.removeItem("ams_token");
  document.getElementById("login-form").reset();
  clearAllFieldErrors(loginFields);
  updateLoginEmailGate(false);
  showEl(document.getElementById("login-error"), false);
  const signupForm = document.getElementById("signup-form");
  if (signupForm) {
    signupForm.reset();
    clearAllFieldErrors(signupFields);
    updateSignupEmailGate(false);
    showEl(document.getElementById("signup-error"), false);
  }
  showEl(document.getElementById("app-shell"), false);
  showEl(document.getElementById("login-view"), true);
});

async function bootstrap() {
  if (!state.token) return;
  try {
    const res = await api("/api/auth/me");
    state.user = res.user;
    enterApp();
  } catch {
    localStorage.removeItem("ams_token");
    state.token = "";
  }
}

const ROLE_PORTAL_META = {
  requester: {
    title: "Requester Portal — My Submissions & Tracking",
    subtitle: "Submit expenses, leave, or purchase orders and monitor real-time approval stages.",
    tabLabel: "My Dashboard",
  },
  manager: {
    title: "Manager Review Desk — Team Approvals & SLAs",
    subtitle: "Review Stage-1 team requests, track turnaround bottlenecks, and act on pending items.",
    tabLabel: "Manager Desk",
  },
  approver: {
    title: "Finance Approver Desk — Risk & Anomaly Control",
    subtitle: "Verify budgets, review AI risk/compliance scores, and inspect flagged anomalies.",
    tabLabel: "Approver Desk",
  },
  hr: {
    title: "HR People Portal — Leave & Staff Administration",
    subtitle: "Process employee leave requests, review leave volume, and manage staff profiles.",
    tabLabel: "HR Desk",
  },
  admin: {
    title: "System Admin Console — Governance, Workflows & AI",
    subtitle: "System governance, workflow definitions, policy thresholds, and audit integrity.",
    tabLabel: "Admin Console",
  },
};

function enterApp() {
  showEl(document.getElementById("login-view"), false);
  showEl(document.getElementById("app-shell"), true);
  document.getElementById("user-display-name").textContent = state.user.full_name;
  document.getElementById("user-role-badge").textContent = state.user.role;

  const meta = ROLE_PORTAL_META[state.user.role] || ROLE_PORTAL_META.requester;
  document.getElementById("portal-subtitle").textContent = meta.title;
  document.getElementById("nav-dashboard-btn").textContent = meta.tabLabel;

  const isAdmin = state.user.role === "admin";
  const isApprover = ["manager", "approver", "hr", "admin"].includes(state.user.role);
  document.querySelectorAll(".admin-only").forEach((el) => showEl(el, isAdmin));
  document.querySelectorAll(".approver-only").forEach((el) => showEl(el, isApprover));

  switchTab("dashboard");
  loadNotifications();
  loadRequests();
  loadChatConfig();
}

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

// Notifications
document.getElementById("notif-toggle-btn").addEventListener("click", () => {
  const drawer = document.getElementById("notif-drawer");
  showEl(drawer, drawer.classList.contains("hidden"));
});
document.getElementById("close-notif-btn").addEventListener("click", () => {
  showEl(document.getElementById("notif-drawer"), false);
});
document.getElementById("sweep-reminders-btn").addEventListener("click", async () => {
  const res = await api("/api/notifications/sweep", { method: "POST" });
  alert(`Checked ${res.checked_tasks} task(s); sent ${res.reminders_sent} reminder(s).`);
  loadNotifications();
});

document.getElementById("mark-all-read-btn")?.addEventListener("click", async () => {
  try {
    await api("/api/notifications/read-all", { method: "POST" });
    loadNotifications();
  } catch (err) {
    alert("Failed to mark notifications read: " + err.message);
  }
});

document.getElementById("view-emails-btn")?.addEventListener("click", async () => {
  showEl(document.getElementById("emails-modal"), true);
  const listEl = document.getElementById("emails-list");
  if (listEl) listEl.innerHTML = '<p class="muted small">Loading outbound email log...</p>';
  try {
    const res = await api("/api/notifications/emails");
    if (!listEl) return;
    listEl.innerHTML = (res.emails || []).length
      ? res.emails
          .map(
            (em) => `
        <div style="padding:10px 12px;background:var(--bg-subtle);border:1px solid var(--border);border-radius:10px;font-size:0.85rem;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;flex-wrap:wrap;gap:4px;">
            <strong style="color:var(--primary);">${escapeHtml(em.subject)}</strong>
            <span class="muted small">${formatDate(em.sent_at)}</span>
          </div>
          <div class="muted small" style="margin-bottom:6px;">
            Recipient: <code>${escapeHtml(em.recipient_email)}</code> &bull; Template: <code>${escapeHtml(em.template)}</code>
          </div>
          <pre style="margin:0;padding:8px;background:var(--card-bg);border:1px solid var(--border);border-radius:6px;font-size:0.8rem;white-space:pre-wrap;font-family:inherit;">${escapeHtml(em.body)}</pre>
        </div>`
          )
          .join("")
      : '<p class="muted small">No dispatched email logs found.</p>';
  } catch (err) {
    if (listEl) listEl.innerHTML = `<p class="error-text">Failed to load emails: ${escapeHtml(err.message)}</p>`;
  }
});

document.getElementById("emails-close-btn")?.addEventListener("click", () => {
  showEl(document.getElementById("emails-modal"), false);
});

async function loadNotifications() {
  const res = await api("/api/notifications");
  const unread = res.notifications.filter((n) => !n.is_read).length;
  document.getElementById("notif-badge").textContent = unread;
  const list = document.getElementById("notif-list");
  list.innerHTML = res.notifications.length
    ? res.notifications
        .map(
          (n) => `
      <div class="notif-item ${n.is_read ? "" : "unread"}">
        <strong>${n.title}</strong>
        <div class="muted small">${n.category} • ${n.created_at.slice(0, 16)}</div>
        <p style="margin:4px 0;">${n.message}</p>
        ${!n.is_read ? `<button class="btn btn-sm btn-secondary" onclick="markRead(${n.id})">Mark Read</button>` : ""}
      </div>`
        )
        .join("")
    : '<p class="muted small">No notifications.</p>';
}

window.markRead = async (id) => {
  await api(`/api/notifications/${id}/read`, { method: "POST" });
  loadNotifications();
};

// Role-Dedicated Dashboard Loader
async function loadDashboard() {
  const role = state.user.role;
  const meta = ROLE_PORTAL_META[role] || ROLE_PORTAL_META.requester;

  const isApprover = ["manager", "approver", "hr", "admin"].includes(role);
  document.getElementById("role-banner").innerHTML = `
    <div>
      <h2>${meta.title}</h2>
      <p>${meta.subtitle}</p>
    </div>
    <div class="form-actions" style="margin-top:0;">
      <button class="btn btn-special btn-sm" onclick="window._goTab('submit')">+ New Request / Chat</button>
      ${isApprover ? `<button class="btn btn-primary btn-sm" onclick="window._exportCsv()">Export CSV Report</button>` : ""}
    </div>
  `;

  const [dash, roleData] = await Promise.all([
    api("/api/analytics/dashboard"),
    api("/api/analytics/role-dashboard"),
  ]);
  const s = dash.summary;

  if (role === "requester") {
    const st = roleData.stats;
    document.getElementById("kpi-grid").innerHTML = `
      <div class="kpi-card"><div class="kpi-label">My Total Requests</div><div class="kpi-val">${st.my_total || 0}</div></div>
      <div class="kpi-card"><div class="kpi-label">My Active / Pending</div><div class="kpi-val">${st.my_active || 0}</div></div>
      <div class="kpi-card"><div class="kpi-label">My Approved</div><div class="kpi-val">${st.my_approved || 0}</div></div>
      <div class="kpi-card"><div class="kpi-label">Auto-Approved</div><div class="kpi-val">${st.my_auto_approved || 0}</div></div>
    `;
    document.getElementById("role-dashboard-body").innerHTML = `
      <div class="card">
        <h3>My Recent Submissions</h3>
        ${
          roleData.items.length
            ? roleData.items
                .map(
                  (r) => `
              <div class="list-row" style="display:flex;justify-content:space-between;align-items:center;gap:10px;">
                <div><strong>#${r.id} ${r.title}</strong> (${r.request_type} • ${r.amount} ${r.currency})</div>
                <div>
                  <span class="status-pill status-${r.status}">${r.status}</span>
                  <button class="btn btn-sm btn-secondary" onclick="openRequestDetail(${r.id})">Track</button>
                </div>
              </div>`
                )
                .join("")
            : '<p class="muted">You have not submitted any requests yet.</p>'
        }
      </div>
    `;
  } else if (role === "manager" || role === "approver" || role === "hr") {
    document.getElementById("kpi-grid").innerHTML = `
      <div class="kpi-card"><div class="kpi-label">Pending My Queue</div><div class="kpi-val">${roleData.queue.length}</div></div>
      <div class="kpi-card"><div class="kpi-label">Flagged Anomalies</div><div class="kpi-val">${roleData.flagged.length}</div></div>
      <div class="kpi-card"><div class="kpi-label">Org Approval Rate</div><div class="kpi-val">${s.approval_rate_pct}%</div></div>
      <div class="kpi-card"><div class="kpi-label">Avg Cycle Time</div><div class="kpi-val">${s.avg_cycle_time_hours}h</div></div>
      ${role === "hr" ? `<div class="kpi-card"><div class="kpi-label">Total Leave Requests</div><div class="kpi-val">${roleData.extra.leave_count || 0}</div></div>` : ""}
    `;
    document.getElementById("role-dashboard-body").innerHTML = `
      <div class="two-col">
        <div class="card">
          <h3>Pending My Action (${role.toUpperCase()})</h3>
          ${
            roleData.queue.length
              ? roleData.queue
                  .map(
                    (q) => `
                <div class="list-row ${q.is_anomaly ? "anomaly-row" : ""}">
                  <strong>#${q.id} ${q.title}</strong> — ${q.amount} ${q.currency} (${q.requester_name})<br/>
                  <span class="muted">Stage: ${q.stage_name} • AI: ${q.ai_recommendation} (${Math.round((q.ai_risk_score || 0) * 100)}% risk)</span>
                  <div class="form-actions">
                    <button class="btn btn-sm btn-primary" onclick="openRequestDetail(${q.id})">Review</button>
                    <button class="btn btn-sm btn-success" onclick="quickDecision(${q.id}, 'approved')">Approve</button>
                    <button class="btn btn-sm btn-special" onclick="quickDecision(${q.id}, 'rejected')">Reject</button>
                  </div>
                </div>`
                  )
                  .join("")
              : '<p class="muted">Your approval queue is clear.</p>'
          }
        </div>
        <div class="card">
          <h3>Flagged Anomalies &amp; High-Risk Items</h3>
          ${
            roleData.flagged.length
              ? roleData.flagged
                  .map(
                    (f) => `
                <div class="list-row anomaly-row">
                  <strong>#${f.id} ${f.title}</strong> (${f.amount} ${f.currency})<br/>
                  <span class="muted">Risk Score: ${Math.round((f.ai_risk_score || 0) * 100)}%</span>
                  <button class="btn btn-sm btn-special" style="margin-left:8px;" onclick="openRequestDetail(${f.id})">Inspect</button>
                </div>`
                  )
                  .join("")
              : '<p class="muted">No active anomalies flagged.</p>'
          }
        </div>
      </div>
    `;
  } else {
    // admin
    const sys = roleData.system;
    document.getElementById("kpi-grid").innerHTML = `
      <div class="kpi-card"><div class="kpi-label">Total Requests</div><div class="kpi-val">${s.total_requests}</div></div>
      <div class="kpi-card"><div class="kpi-label">Active / Pending</div><div class="kpi-val">${s.active_requests}</div></div>
      <div class="kpi-card"><div class="kpi-label">Auto-Approval Rate</div><div class="kpi-val">${s.auto_approval_rate_pct}%</div></div>
      <div class="kpi-card"><div class="kpi-label">Anomalies Flagged</div><div class="kpi-val">${s.anomaly_requests}</div></div>
      <div class="kpi-card"><div class="kpi-label">Storage Space</div><div class="kpi-val" style="font-size:1.15rem;">${sys.storage_backend.toUpperCase()}</div></div>
      <div class="kpi-card"><div class="kpi-label">DB Engine</div><div class="kpi-val" style="font-size:1.05rem;">${sys.database}</div></div>
    `;
    document.getElementById("role-dashboard-body").innerHTML = "";
  }

  const maxType = Math.max(...dash.by_type.map((t) => t.count), 1);
  document.getElementById("type-breakdown").innerHTML = dash.by_type.length
    ? dash.by_type
        .map(
          (t) => `
    <div class="bar-row">
      <div class="bar-meta"><span>${t.request_type}</span><span>${t.count} requests ($${Number(t.total_amount).toLocaleString()})</span></div>
      <div class="bar-track"><div class="bar-fill" style="width:${(t.count / maxType) * 100}%"></div></div>
    </div>`
        )
        .join("")
    : '<p class="muted small" style="margin:8px 0;">No request submissions recorded yet.</p>';

  if (isApprover) {
    const pred = await api("/api/analytics/predictions");
    const vf = pred.volume_forecast;

    const histData = vf.daily_series || [];
    const predData = vf.forecast_series || [];
    const allCounts = [...histData.map((d) => d.count), ...predData.map((d) => d.count), 5];
    const maxVal = Math.max(...allCounts);
    const trendIcon = vf.trend === "increasing" ? "↗ Trending Up" : vf.trend === "decreasing" ? "↘ Trending Down" : "→ Stable Demand";
    const trendColor = vf.trend === "increasing" ? "#059669" : vf.trend === "decreasing" ? "#2563EB" : "var(--muted)";

    const chartW = 340;
    const chartH = 75;
    const totalPoints = Math.max(histData.length + predData.length, 2);
    const step = chartW / Math.max(totalPoints - 1, 1);

    let histPath = "";
    histData.forEach((d, i) => {
      const x = i * step;
      const y = chartH - (d.count / maxVal) * (chartH - 16) - 8;
      histPath += `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)} `;
    });

    let predPath = "";
    if (histData.length && predData.length) {
      const lastHistX = (histData.length - 1) * step;
      const lastHistY = chartH - (histData[histData.length - 1].count / maxVal) * (chartH - 16) - 8;
      predPath = `M ${lastHistX.toFixed(1)} ${lastHistY.toFixed(1)} `;
    }
    predData.forEach((d, i) => {
      const x = (histData.length + i) * step;
      const y = chartH - (d.count / maxVal) * (chartH - 16) - 8;
      predPath += `${predPath ? "L" : "M"} ${x.toFixed(1)} ${y.toFixed(1)} `;
    });

    const svgChart = `
      <div style="background:var(--bg-subtle);border:1px solid var(--border);border-radius:10px;padding:12px;margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-wrap:wrap;gap:4px;">
          <div>
            <span style="font-weight:700;font-size:0.88rem;">AI Volume &amp; Workflow Trend Forecast</span>
            <div class="muted small">~${vf.predicted_next_7_days_requests} requests next 7 days &bull; ~${vf.predicted_next_30_days_requests} next 30 days</div>
          </div>
          <span style="font-size:0.75rem;padding:3px 8px;border-radius:9999px;background:var(--card-bg);border:1px solid var(--border);font-weight:700;color:${trendColor};">
            ${trendIcon}
          </span>
        </div>
        <div style="overflow-x:auto;">
          <svg viewBox="0 0 ${chartW} ${chartH}" style="width:100%;height:75px;display:block;overflow:visible;">
            <line x1="0" y1="${chartH - 2}" x2="${chartW}" y2="${chartH - 2}" stroke="var(--border)" stroke-width="1" />
            ${histPath ? `<path d="${histPath}" fill="none" stroke="var(--primary)" stroke-width="2.5" stroke-linecap="round" />` : ""}
            ${predPath ? `<path d="${predPath}" fill="none" stroke="#059669" stroke-width="2.5" stroke-dasharray="4 3" stroke-linecap="round" />` : ""}
            ${histData
              .map((d, i) => {
                const x = i * step;
                const y = chartH - (d.count / maxVal) * (chartH - 16) - 8;
                return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3" fill="var(--primary)" title="${escapeHtml(d.date)}: ${d.count} requests" />`;
              })
              .join("")}
            ${predData
              .map((d, i) => {
                const x = (histData.length + i) * step;
                const y = chartH - (d.count / maxVal) * (chartH - 16) - 8;
                return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.5" fill="#059669" stroke="var(--card-bg)" stroke-width="1.5" title="${escapeHtml(d.date)} (predicted): ${d.count} requests" />`;
              })
              .join("")}
          </svg>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;font-size:0.72rem;color:var(--muted);flex-wrap:wrap;gap:4px;">
          <span>● Historical observed volume</span>
          <span>--○-- AI Linear Forecast (next 7 days)</span>
        </div>
      </div>
    `;

    document.getElementById("predictions-panel").innerHTML = `
      ${svgChart}
      ${
        pred.bottlenecks.length
          ? pred.bottlenecks
              .map(
                (b) => `
        <div class="list-row">
          <strong>Role: ${b.role.toUpperCase()}</strong> • Delay Risk: <strong>${Math.round(b.delay_risk_score * 100)}%</strong> (${b.status})<br/>
          <span class="muted">Pending: ${b.pending_tasks} • Overdue: ${b.overdue_tasks} • Avg Cycle: ${b.avg_cycle_hours}h</span>
        </div>`
              )
              .join("")
          : '<p class="muted small">No operational bottlenecks detected across queues.</p>'
      }
    `;

    const opt = await api("/api/analytics/optimizations");
    const optHtml = [
      ...opt.workflow_optimizations.map(
        (o) => `<div class="list-row"><strong>Workflow Optimization (${o.workflow_name}):</strong> ${o.finding} -> ${o.recommendation} (~${o.estimated_time_savings_pct}% faster)</div>`
      ),
      ...opt.dynamic_rule_proposals.map(
        (p) => `
        <div class="list-row">
          <strong>Dynamic Rule Proposal (${p.policy_name}):</strong> Auto-approve limit <code>${p.current_auto_approve_max}</code> -> <code>${p.suggested_auto_approve_max}</code><br/>
          <span class="muted">${p.rationale}</span>
          ${role === "admin" ? `<br/><button class="btn btn-sm btn-special" style="margin-top:6px;" onclick="applyDynamicRule(${p.policy_id})">Apply Dynamic Rule</button>` : ""}
        </div>`
      ),
    ].join("");
    document.getElementById("optimizations-panel").innerHTML = optHtml || '<p class="muted">No optimization changes needed right now.</p>';
  } else {
    document.getElementById("predictions-panel").innerHTML = '<p class="muted">Department bottleneck predictions are restricted to Managers, Approvers, HR, and Admins.</p>';
  }
}

window._goTab = switchTab;
window._exportCsv = async (extraParams = {}) => {
  const params = new URLSearchParams(extraParams);
  const qs = params.toString() ? `?${params.toString()}` : "";
  try {
    const res = await fetch(`/api/analytics/export.csv${qs}`, {
      headers: { Authorization: `Bearer ${state.token}` },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Export failed with status ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `accounting_reconciliation_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert("Export CSV failed: " + err.message);
  }
};

document.getElementById("export-accounting-csv-btn")?.addEventListener("click", () => {
  const status = document.getElementById("filter-status")?.value;
  const extra = {};
  if (status && status !== "draft" && status !== "withdrawn") {
    extra.status = status;
  }
  window._exportCsv(extra);
});

window.quickDecision = async (reqId, decision) => {
  try {
    await api(`/api/requests/${reqId}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, comment: `Quick ${decision} from ${state.user.role} dashboard` }),
    });
    loadDashboard();
    loadRequests();
    loadNotifications();
  } catch (err) {
    alert(err.message);
  }
};

window.applyDynamicRule = async (policyId) => {
  await api(`/api/policies/${policyId}/apply-dynamic-rule`, { method: "POST" });
  loadDashboard();
  if (state.user.role === "admin") loadAdminData();
};

// Requests Table & Detail Modal
let cachedRequests = [];

function updateBulkBar() {
  const checked = [...document.querySelectorAll(".bulk-row-check:checked")];
  const bar = document.getElementById("bulk-actions-bar");
  const countEl = document.getElementById("bulk-selected-count");
  if (!bar) return;
  if (checked.length > 0) {
    showEl(bar, true);
    if (countEl) countEl.textContent = `${checked.length} request(s) selected`;
  } else {
    showEl(bar, false);
    const selectAll = document.getElementById("bulk-select-all");
    if (selectAll) selectAll.checked = false;
  }
}

document.getElementById("bulk-select-all")?.addEventListener("change", (e) => {
  const isChecked = e.target.checked;
  document.querySelectorAll(".bulk-row-check:not(:disabled)").forEach((cb) => {
    cb.checked = isChecked;
  });
  updateBulkBar();
});

document.getElementById("bulk-clear-btn")?.addEventListener("click", () => {
  document.querySelectorAll(".bulk-row-check").forEach((cb) => (cb.checked = false));
  updateBulkBar();
});

document.getElementById("bulk-approve-btn")?.addEventListener("click", async () => {
  const ids = [...document.querySelectorAll(".bulk-row-check:checked")].map((cb) => parseInt(cb.dataset.id, 10));
  if (!ids.length) return alert("No requests selected.");
  if (!confirm(`Batch approve ${ids.length} selected request(s)?`)) return;
  try {
    const res = await api("/api/requests/bulk-decision", {
      method: "POST",
      body: JSON.stringify({ request_ids: ids, decision: "approved" }),
    });
    alert(`Bulk approval complete: ${res.processed_count} approved successfully.`);
    document.querySelectorAll(".bulk-row-check").forEach((cb) => (cb.checked = false));
    updateBulkBar();
    loadRequests();
    loadDashboard();
    loadNotifications();
  } catch (err) {
    alert("Bulk approval failed: " + err.message);
  }
});

document.getElementById("bulk-reject-btn")?.addEventListener("click", async () => {
  const ids = [...document.querySelectorAll(".bulk-row-check:checked")].map((cb) => parseInt(cb.dataset.id, 10));
  if (!ids.length) return alert("No requests selected.");
  const reason = prompt("Enter standardized rejection reason (e.g. POLICY_VIOLATION, MISSING_DOCS, BUDGET_EXCEEDED):", "POLICY_VIOLATION");
  if (!reason) return;
  try {
    const res = await api("/api/requests/bulk-decision", {
      method: "POST",
      body: JSON.stringify({ request_ids: ids, decision: "rejected", rejection_reason: reason.trim() }),
    });
    alert(`Bulk rejection complete: ${res.processed_count} rejected.`);
    document.querySelectorAll(".bulk-row-check").forEach((cb) => (cb.checked = false));
    updateBulkBar();
    loadRequests();
    loadDashboard();
    loadNotifications();
  } catch (err) {
    alert("Bulk rejection failed: " + err.message);
  }
});

function renderRequestsTable() {
  const tbody = document.getElementById("requests-tbody");
  if (!tbody) return;
  const isApprover = state.user && ["manager", "approver", "hr", "admin"].includes(state.user.role);
  const searchVal = (document.getElementById("filter-search")?.value || "").toLowerCase().trim();
  let list = cachedRequests;
  if (searchVal) {
    list = list.filter((r) =>
      String(r.id).includes(searchVal) ||
      (r.title && r.title.toLowerCase().includes(searchVal)) ||
      (r.requester_name && r.requester_name.toLowerCase().includes(searchVal)) ||
      (r.request_type && r.request_type.toLowerCase().includes(searchVal))
    );
  }
  tbody.innerHTML = list.length
    ? list
        .map(
          (r) => {
            let amtStr = `${Number(r.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })} ${escapeHtml(r.currency || "USD")}`;
            if (r.currency && r.currency !== "USD" && r.amount_usd) {
              amtStr += `<br/><span class="muted small">(~$${Number(r.amount_usd).toFixed(2)} USD)</span>`;
            }
            let statusBadge = `<span class="status-pill status-${r.status}">${r.status}</span>`;
            if (r.is_draft) {
              statusBadge = `<span class="status-pill" style="background:#6B7280;color:#fff;">Draft</span>`;
            } else if (r.is_withdrawn) {
              statusBadge = `<span class="status-pill" style="background:#EF4444;color:#fff;">Withdrawn</span>`;
            } else if (r.auto_approved) {
              statusBadge += ' <span class="small muted">(Auto)</span>';
            }
            const canBatch = isApprover && r.status === "in_review";
            const checkCol = isApprover
              ? `<td style="width:36px;"><input type="checkbox" class="bulk-row-check" data-id="${r.id}" ${canBatch ? "" : "disabled style='opacity:0.25;'"} /></td>`
              : "";
            return `
    <tr>
      ${checkCol}
      <td>#${r.id}</td>
      <td><strong>${escapeHtml(r.title)}</strong><div class="muted small">${humanizeType(r.request_type)}</div></td>
      <td>${escapeHtml(r.requester_name)}</td>
      <td>${amtStr}</td>
      <td>${statusBadge}</td>
      <td>${r.ai_recommendation || "-"} (${Math.round((r.ai_risk_score || 0) * 100)}% risk)${r.is_anomaly ? ' <strong>[Anomaly]</strong>' : ""}</td>
      <td><button class="btn btn-sm btn-primary" onclick="openRequestDetail(${r.id})">View</button></td>
    </tr>`;
          }
        )
        .join("")
    : `<tr><td colspan="${isApprover ? 8 : 7}" class="muted small" style="text-align:center;padding:26px;">No requests found matching current filter.</td></tr>`;

  document.querySelectorAll(".bulk-row-check").forEach((cb) => {
    cb.addEventListener("change", updateBulkBar);
  });
  updateBulkBar();
}

document.getElementById("refresh-requests-btn").addEventListener("click", loadRequests);
document.getElementById("filter-scope").addEventListener("change", loadRequests);
document.getElementById("filter-status").addEventListener("change", loadRequests);
document.getElementById("filter-search")?.addEventListener("input", renderRequestsTable);

async function loadRequests() {
  const scope = document.getElementById("filter-scope").value;
  const status = document.getElementById("filter-status").value;
  const params = new URLSearchParams();
  if (scope) params.set("scope", scope);
  if (status) params.set("status", status);
  const res = await api(`/api/requests?${params.toString()}`);
  cachedRequests = res.requests || [];
  renderRequestsTable();
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function humanizeType(type) {
  if (!type) return "General Request";
  const map = {
    expense_report: "Expense Report",
    hardware_request: "Hardware Request",
    software_license: "Software License",
    travel_booking: "Travel Booking",
    leave_request: "Leave Request",
    vendor_payment: "Vendor Payment",
    access_grant: "Access Grant",
    general: "General Request",
  };
  return map[type] || type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatDate(isoStr) {
  if (!isoStr) return "-";
  try {
    const d = new Date(isoStr);
    return isNaN(d.getTime())
      ? isoStr
      : d.toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        });
  } catch (e) {
    return isoStr;
  }
}

window.openRequestDetail = async (id) => {
  const data = await api(`/api/requests/${id}`);
  const r = data.request;

  const humanType = humanizeType(r.request_type);
  const urgencyLabel = (r.urgency || "normal").toUpperCase();
  const urgencyClass = (r.urgency === "critical" || r.urgency === "high") ? "badge-urgent" : "badge-normal";

  // Header Title & Status Badges
  const titleContainer = document.getElementById("modal-title");
  if (titleContainer) {
    titleContainer.innerHTML = `
      <div class="modal-header-info">
        <div class="modal-header-badges">
          <span class="status-pill status-${r.status}">${r.status}</span>
          ${r.auto_approved ? '<span class="status-pill status-approved" style="background:rgba(15,118,110,0.12);color:#0D9488;border-color:rgba(15,118,110,0.3);">⚡ Auto-Approved</span>' : ""}
          ${r.is_anomaly ? '<span class="status-pill status-rejected" style="background:rgba(239,68,68,0.12);color:#DC2626;border-color:rgba(239,68,68,0.3);">⚠️ Anomaly</span>' : ""}
          <span class="detail-badge-type">${humanType}</span>
        </div>
        <h3 class="modal-title-text">Request #${r.id}: ${escapeHtml(r.title)}</h3>
      </div>
    `;
  }

  const canDecide =
    ["manager", "approver", "hr", "admin"].includes(state.user.role) &&
    !["approved", "rejected"].includes(r.status) &&
    data.tasks.some((t) => t.status === "pending" && (t.assigned_role === state.user.role || state.user.role === "admin"));

  const isRequester = state.user && r.requester_id === state.user.id;
  const canWithdraw = isRequester && !r.is_draft && !r.is_withdrawn && r.status !== "approved" && r.status !== "rejected";

  let formattedAmount = `${Number(r.amount).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} ${escapeHtml(r.currency || "USD")}`;
  if (r.currency && r.currency !== "USD" && r.amount_usd) {
    formattedAmount += ` (~$${Number(r.amount_usd).toFixed(2)} USD)`;
  }

  const riskPct = Math.round((r.ai_risk_score || 0) * 100);
  const confPct = Math.round((r.ai_confidence || 0) * 100);
  const rec = (r.ai_recommendation || "review").toLowerCase();
  const recClass =
    rec === "approve"
      ? "ai-chip-rec-approve"
      : rec === "reject"
      ? "ai-chip-rec-reject"
      : "ai-chip-rec-review";

  let headerActions = "";
  if (canWithdraw) {
    headerActions += `<button class="btn btn-secondary btn-sm" style="color:var(--accent-red);border-color:var(--accent-red);" onclick="withdrawCurrentRequest(${r.id})">🛑 Withdraw Request</button>`;
  }

  document.getElementById("modal-title").innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;width:100%;padding-right:12px;">
      <div>
        <div class="modal-header-badges">
          <span class="detail-badge-type">${humanType}</span>
          <span class="status-pill status-${r.status}">${r.is_draft ? "Draft" : r.is_withdrawn ? "Withdrawn" : r.status}</span>
        </div>
        <h3 class="modal-title-text" style="margin-top:4px;">Request #${r.id} — ${escapeHtml(r.title)}</h3>
      </div>
      <div>${headerActions}</div>
    </div>
  `;

  document.getElementById("modal-body").innerHTML = `
    <!-- Structured Key-Value Metadata Grid -->
    <div class="detail-grid">
      <div class="detail-grid-cell">
        <div class="detail-label">Requester</div>
        <div class="detail-value">${escapeHtml(r.requester_name)}</div>
        <div class="detail-subvalue">${escapeHtml(r.department || "Company Staff")}</div>
      </div>
      <div class="detail-grid-cell">
        <div class="detail-label">Total Amount</div>
        <div class="detail-value" style="color:var(--primary);">${formattedAmount}</div>
        <div class="detail-subvalue">Currency: ${escapeHtml(r.currency || "USD")}</div>
      </div>
      <div class="detail-grid-cell">
        <div class="detail-label">Category / Type</div>
        <div class="detail-value">${humanType}</div>
        <div class="detail-subvalue">Policy Evaluated</div>
      </div>
      <div class="detail-grid-cell">
        <div class="detail-label">Priority / Urgency</div>
        <div class="detail-value">
          <span class="detail-urgency ${urgencyClass}">${urgencyLabel}</span>
        </div>
        <div class="detail-subvalue">${r.created_at ? formatDate(r.created_at) : "Standard SLA"}</div>
      </div>
    </div>

    <!-- Rejection Classification Banner (if rejected) -->
    ${
      r.rejection_reason
        ? `
      <div class="card" style="margin-top:14px;background:rgba(239, 68, 68, 0.08);border:1px solid rgba(239, 68, 68, 0.25);border-radius:10px;padding:12px 14px;">
        <strong style="color:var(--accent-red);">Rejection / Return Classification:</strong>
        <span style="font-weight:600;margin-left:6px;">${escapeHtml(r.rejection_reason.replace(/_/g, ' '))}</span>
      </div>`
        : ""
    }

    <!-- Purpose & Description Box -->
    <div class="detail-desc-box">
      <div class="detail-desc-label">Business Purpose &amp; Description</div>
      <p class="detail-desc-text">${escapeHtml(r.description || "No description provided.")}</p>
    </div>

    <!-- AI Decision Support Executive Card -->
    <div class="ai-support-card">
      <div class="ai-support-header">
        <div class="ai-support-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--primary);"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>
          AI Decision Support &amp; Policy Analysis
        </div>
        <div class="ai-support-chips">
          <span class="ai-chip ${recClass}">Recommended: <strong>${rec.toUpperCase()}</strong></span>
          <span class="ai-chip ai-chip-metric">Confidence: <strong>${confPct}%</strong></span>
          <span class="ai-chip ai-chip-metric" style="${riskPct > 50 ? "color:#DC2626;" : ""}">Risk: <strong>${riskPct}%</strong></span>
        </div>
      </div>
      <div class="ai-support-body">
        ${escapeHtml(r.ai_explanation || "Automated organizational policy evaluation complete.")}
      </div>
      ${
        r.is_anomaly
          ? `<div class="ai-anomaly-box">
               <strong>⚠️ Anomaly Flagged (${r.anomaly_score}):</strong> ${escapeHtml((r.anomaly_reasons || []).join("; "))}
             </div>`
          : ""
      }
    </div>

    <!-- Draft Action Box -->
    ${
      r.is_draft && isRequester
        ? `
      <div class="card" style="margin-top:20px;background:var(--bg-subtle);border:1px dashed var(--border);border-radius:10px;padding:16px;">
        <h4 style="margin:0 0 6px 0;">Draft Status — Ready to Submit?</h4>
        <p class="small muted" style="margin:0 0 12px 0;">This request is currently saved as a private draft. Submitting will run compliance evaluation and route it to reviewers.</p>
        <button class="btn btn-special btn-sm" onclick="submitDraftRequest(${r.id})">🚀 Submit Draft for Review</button>
      </div>`
        : ""
    }

    <!-- Workflow Stages & Approval Trail -->
    <div class="detail-section-header">
      <h4>Workflow Stages &amp; Approval Trail</h4>
    </div>
    ${
      data.tasks && data.tasks.length
        ? `<div class="workflow-timeline">` +
          data.tasks
            .map(
              (t) => `
            <div class="workflow-step">
              <div class="workflow-step-num">${t.stage_index + 1}</div>
              <div class="workflow-step-content">
                <div class="workflow-step-header">
                  <div class="workflow-step-title">
                    ${escapeHtml(t.stage_name)} <span class="muted small">(${escapeHtml(t.assigned_role)})</span>
                    ${t.is_escalated ? `<span class="badge" style="background:var(--accent-red);color:#fff;font-size:0.7rem;margin-left:6px;">⚠️ Escalated (SLA Breached)</span>` : ""}
                  </div>
                  <span class="status-pill status-${t.status === "waiting" ? "pending" : t.status}">${t.status}</span>
                </div>
                ${
                  t.decision_by_name
                    ? `<div class="workflow-step-sub">Reviewed by: <strong>${escapeHtml(t.decision_by_name)}</strong></div>`
                    : `<div class="workflow-step-sub">Assigned to: ${escapeHtml(t.assigned_role)}</div>`
                }
                ${t.comment ? `<div class="workflow-step-comment">"${escapeHtml(t.comment)}"</div>` : ""}
              </div>
            </div>`
            )
            .join("") +
          `</div>`
        : `
        <div class="auto-approved-card">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
          <div>
            <strong>Automated Instant Approval:</strong> Request amount (${formattedAmount}) meets company policy threshold rules with low risk rating (${riskPct}%). No manual escalation required.
          </div>
        </div>
      `
    }

    <!-- Attachments Section -->
    ${
      data.attachments && data.attachments.length
        ? `
        <div class="detail-section-header" style="margin-top:20px;">
          <h4>Attached Documents (${data.attachments.length})</h4>
        </div>
        <div class="attachment-grid">
          ${data.attachments
            .map(
              (a) => `
            <div class="attachment-card">
              <div class="attachment-meta">
                <div class="attachment-filename" title="${escapeHtml(a.original_filename)}">📄 ${escapeHtml(a.original_filename)}</div>
                <div class="attachment-size">${(a.size_bytes / 1024).toFixed(1)} KB • Storage: ${escapeHtml(a.storage_backend || "local")}</div>
              </div>
              <a href="/api/requests/${r.id}/attachments/${a.id}" target="_blank" class="btn btn-secondary btn-sm" style="flex-shrink:0;text-decoration:none;">Download</a>
            </div>`
            )
            .join("")}
        </div>`
        : ""
    }

    <!-- Approver Decision Card -->
    ${
      canDecide
        ? `
      <div class="card" style="margin-top:20px;border:1px solid var(--primary);box-shadow:var(--shadow-md);">
        <h4 style="margin-top:0;display:flex;align-items:center;gap:8px;">
          <span>Submit Approval Decision</span>
          <span class="muted small">(Action required for your role)</span>
        </h4>
        <textarea id="decision-comment" rows="2" placeholder="Provide audit reason or notes for this decision..."></textarea>
        <div class="form-actions" style="margin-top:12px;display:flex;gap:10px;">
          <button class="btn btn-success" style="flex:1;" onclick="submitDecision(${r.id}, 'approved')">✓ Approve Request</button>
          <button class="btn btn-special" style="flex:1;background:var(--accent-red);border-color:var(--accent-red);" onclick="openRejectionModal(${r.id})">✕ Reject Request</button>
        </div>
      </div>`
        : ""
    }
  `;
  showEl(document.getElementById("detail-modal"), true);
};

document.getElementById("modal-close-btn").addEventListener("click", () => {
  showEl(document.getElementById("detail-modal"), false);
});

window.submitDecision = async (reqId, decision, rejectionReason = null) => {
  const comment = document.getElementById("decision-comment")?.value || "";
  try {
    await api(`/api/requests/${reqId}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, comment, rejection_reason: rejectionReason }),
    });
    showEl(document.getElementById("detail-modal"), false);
    loadRequests();
    loadDashboard();
    loadNotifications();
  } catch (err) {
    alert(err.message);
  }
};

window.openRejectionModal = (reqId) => {
  document.getElementById("rej-request-id").value = reqId;
  document.getElementById("rej-reason-select").value = "";
  document.getElementById("rej-comment").value = "";
  showEl(document.getElementById("rejection-modal"), true);
};

document.getElementById("rejection-modal-close-btn")?.addEventListener("click", () => {
  showEl(document.getElementById("rejection-modal"), false);
});
document.getElementById("rejection-cancel-btn")?.addEventListener("click", () => {
  showEl(document.getElementById("rejection-modal"), false);
});

document.getElementById("rejection-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const reqId = document.getElementById("rej-request-id").value;
  const reason = document.getElementById("rej-reason-select").value;
  const comment = document.getElementById("rej-comment").value;
  if (!reason) return alert("Please select a standardized rejection reason.");
  try {
    await api(`/api/requests/${reqId}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision: "rejected", rejection_reason: reason, comment }),
    });
    showEl(document.getElementById("rejection-modal"), false);
    showEl(document.getElementById("detail-modal"), false);
    loadRequests();
    loadDashboard();
    loadNotifications();
    alert("Request returned/rejected with compliance classification.");
  } catch (err) {
    alert("Rejection failed: " + err.message);
  }
});

window.withdrawCurrentRequest = async (reqId) => {
  if (!confirm("Are you sure you want to withdraw and cancel this request?")) return;
  try {
    await api(`/api/requests/${reqId}/withdraw`, { method: "POST" });
    showEl(document.getElementById("detail-modal"), false);
    loadRequests();
    loadDashboard();
    loadNotifications();
    alert("Request withdrawn successfully.");
  } catch (err) {
    alert("Failed to withdraw request: " + err.message);
  }
};

window.submitDraftRequest = async (reqId) => {
  try {
    const res = await api(`/api/requests/${reqId}/submit-draft`, { method: "POST" });
    showEl(document.getElementById("detail-modal"), false);
    loadRequests();
    loadDashboard();
    loadNotifications();
    alert(`Draft submitted successfully • Resulting Status: ${res.status}`);
  } catch (err) {
    alert("Failed to submit draft: " + err.message);
  }
};

// Request Submission & NLP Preview
document.getElementById("nlp-preview-btn").addEventListener("click", async () => {
  const text = document.getElementById("req-description").value.trim();
  if (!text) return alert("Enter a description first.");
  const res = await api("/api/nlp/analyze", { method: "POST", body: JSON.stringify({ text }) });
  const box = document.getElementById("nlp-preview-box");
  const e = res.extracted;
  box.innerHTML = `<strong>NLP Extracted:</strong> Type=<code>${e.request_type}</code>, Amount=<code>${e.amount} ${e.currency}</code>, Urgency=<code>${e.urgency}</code>${e.risk_terms.length ? `, Risk Terms=<code>${e.risk_terms.join(", ")}</code>` : ""}`;
  showEl(box, true);
});

document.getElementById("request-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData();
  fd.append("request_type", document.getElementById("req-type").value);
  fd.append("title", document.getElementById("req-title").value);
  fd.append("amount", document.getElementById("req-amount").value);
  fd.append("currency", document.getElementById("req-currency")?.value || "USD");
  fd.append("urgency", document.getElementById("req-urgency").value);
  fd.append("description", document.getElementById("req-description").value);
  const fileInput = document.getElementById("req-attachment");
  if (fileInput && fileInput.files.length > 0) {
    for (let i = 0; i < fileInput.files.length; i++) {
      fd.append("attachment", fileInput.files[i]);
    }
  }
  try {
    const res = await api("/api/requests", { method: "POST", body: fd });
    const box = document.getElementById("submit-result-box");
    box.innerHTML = `Created <strong>Request #${res.request_id}</strong> • Status: <strong>${res.status}</strong><br/>${res.ai_evaluation ? res.ai_evaluation.explanation : ""}`;
    showEl(box, true);
    e.target.reset();
    loadRequests();
    loadDashboard();
    loadNotifications();
  } catch (err) {
    alert("Submission failed: " + err.message);
  }
});

document.getElementById("save-draft-btn")?.addEventListener("click", async () => {
  const title = document.getElementById("req-title").value.trim();
  if (!title) return alert("Please enter at least a title to save a draft.");
  const fd = new FormData();
  fd.append("request_type", document.getElementById("req-type").value);
  fd.append("title", title);
  fd.append("amount", document.getElementById("req-amount").value || "0");
  fd.append("currency", document.getElementById("req-currency")?.value || "USD");
  fd.append("urgency", document.getElementById("req-urgency").value);
  fd.append("description", document.getElementById("req-description").value || "");
  fd.append("is_draft", "true");
  const fileInput = document.getElementById("req-attachment");
  if (fileInput && fileInput.files.length > 0) {
    for (let i = 0; i < fileInput.files.length; i++) {
      fd.append("attachment", fileInput.files[i]);
    }
  }
  try {
    const res = await api("/api/requests", { method: "POST", body: fd });
    const box = document.getElementById("submit-result-box");
    box.innerHTML = `Saved <strong>Draft #${res.request_id}</strong>. You can view or submit it under <em>Requests &amp; Queue</em>.`;
    showEl(box, true);
    document.getElementById("request-form").reset();
    loadRequests();
    loadDashboard();
    loadNotifications();
  } catch (err) {
    alert("Failed to save draft: " + err.message);
  }
});

// Voice & Chat Assistant
function getSessionLlmHeaders() {
  const key = sessionStorage.getItem("ams_llm_key") || "";
  if (!key) return {};
  return {
    "X-LLM-API-Key": key,
    "X-LLM-Provider": sessionStorage.getItem("ams_llm_provider") || "auto",
    "X-LLM-Model": sessionStorage.getItem("ams_llm_model") || "",
    "X-LLM-Base-Url": sessionStorage.getItem("ams_llm_base_url") || "",
  };
}

async function loadChatConfig() {
  // Handled transparently by backend environment
}

function appendChat(text, cls) {
  const log = document.getElementById("chat-log");
  const div = document.createElement("div");
  div.className = `chat-msg ${cls}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

document.getElementById("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const msg = input.value.trim();
  if (!msg) return;
  appendChat(msg, "chat-user");
  input.value = "";
  try {
    const res = await api("/api/chat", {
      method: "POST",
      headers: getSessionLlmHeaders(),
      body: JSON.stringify({ message: msg }),
    });
    const badge = document.getElementById("chat-engine-badge");
    if (badge && res.engine) {
      badge.textContent = res.engine;
    }
    appendChat(res.reply, "chat-bot");
    loadRequests();
    loadNotifications();
  } catch (err) {
    appendChat(`Error: ${err.message}`, "chat-bot");
  }
});

// Production-Grade Web Voice Recognition Engine
let recognition = null;
let isVoiceRecording = false;

function initVoiceRecognition() {
  const voiceBtn = document.getElementById("voice-btn");
  const statusBar = document.getElementById("voice-status-bar");
  const statusText = document.getElementById("voice-status-text");
  const cancelBtn = document.getElementById("voice-cancel-btn");
  const chatInput = document.getElementById("chat-input");

  if (!voiceBtn) return;

  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;

  function updateVoiceUI(recording, message, isListening = true) {
    isVoiceRecording = recording;
    if (recording) {
      voiceBtn.classList.add("is-recording");
      voiceBtn.innerHTML = `<span>🔴</span> <span>Stop</span>`;
      voiceBtn.title = "Click to finish voice recording";
      if (statusBar) {
        statusBar.classList.remove("hidden");
        statusBar.classList.toggle("is-listening", isListening);
        if (statusText) statusText.textContent = message || "Listening... Speak your request clearly.";
      }
    } else {
      voiceBtn.classList.remove("is-recording");
      voiceBtn.innerHTML = `<span>🎙️</span> <span>Mic</span>`;
      voiceBtn.title = "Click to speak with voice assistant";
      if (statusBar) {
        if (message) {
          statusBar.classList.remove("hidden");
          statusBar.classList.toggle("is-listening", isListening);
          if (statusText) statusText.textContent = message;
          setTimeout(() => {
            if (!isVoiceRecording && statusBar) statusBar.classList.add("hidden");
          }, 3500);
        } else {
          statusBar.classList.add("hidden");
        }
      }
    }
  }

  if (!SpeechRec) {
    voiceBtn.addEventListener("click", () => {
      updateVoiceUI(false, "Speech recognition is supported in Google Chrome, Microsoft Edge, and Safari. Please type your request.", false);
    });
    return;
  }

  try {
    recognition = new SpeechRec();
    recognition.lang = "en-US";
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      updateVoiceUI(true, "Listening... Speak now (e.g. 'Submit expense for team lunch $40')");
      chatInput.placeholder = "Listening to your voice...";
    };

    recognition.onresult = (event) => {
      let interim = "";
      let final = "";
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          final += event.results[i][0].transcript;
        } else {
          interim += event.results[i][0].transcript;
        }
      }
      const current = final || interim;
      if (current) {
        chatInput.value = current;
      }
      if (final) {
        updateVoiceUI(false, "Voice captured successfully! Click Send or press Enter to submit.", true);
        chatInput.placeholder = "e.g. Submit expense report for $140 for team lunch";
        chatInput.focus();
      }
    };

    recognition.onerror = (event) => {
      let msg = "Voice capture failed: " + event.error;
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        msg = "Microphone access blocked. Click the microphone icon in your browser URL bar to allow access.";
      } else if (event.error === "no-speech") {
        msg = "No voice detected. Please click the mic and speak clearly.";
      } else if (event.error === "network") {
        msg = "Speech recognition network service error. Please check your internet connection.";
      } else if (event.error === "audio-capture") {
        msg = "No microphone hardware detected on this device.";
      }
      updateVoiceUI(false, msg, false);
      chatInput.placeholder = "e.g. Submit expense report for $140 for team lunch";
    };

    recognition.onend = () => {
      if (isVoiceRecording) {
        updateVoiceUI(false);
        chatInput.placeholder = "e.g. Submit expense report for $140 for team lunch";
      }
    };

    voiceBtn.addEventListener("click", () => {
      if (isVoiceRecording) {
        try { recognition.stop(); } catch (e) {}
        updateVoiceUI(false);
      } else {
        chatInput.value = "";
        try {
          recognition.start();
        } catch (err) {
          try {
            recognition.stop();
            setTimeout(() => recognition.start(), 200);
          } catch (e) {
            updateVoiceUI(false, "Microphone start error: " + err.message, false);
          }
        }
      }
    });

    if (cancelBtn) {
      cancelBtn.addEventListener("click", () => {
        if (isVoiceRecording) {
          try { recognition.abort(); } catch (e) {}
        }
        updateVoiceUI(false);
      });
    }
  } catch (err) {
    console.warn("Failed to instantiate SpeechRecognition:", err);
  }
}

initVoiceRecognition();

// Executive Admin Component Helpers
const roleAvatarGradients = {
  admin: "linear-gradient(135deg, #7C3AED 0%, #6D28D9 100%)",
  manager: "linear-gradient(135deg, #0284C7 0%, #0369A1 100%)",
  approver: "linear-gradient(135deg, #0F766E 0%, #0D9488 100%)",
  hr: "linear-gradient(135deg, #D97706 0%, #B45309 100%)",
  requester: "linear-gradient(135deg, #475569 0%, #334155 100%)",
};

function getInitials(name) {
  if (!name) return "U";
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].substring(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

window.setWfTemplate = (type) => {
  const textarea = document.getElementById("wf-stages");
  if (!textarea) return;
  if (type === "standard") {
    textarea.value = JSON.stringify([
      { name: "Direct Manager Review", role: "manager", sla_hours: 24 },
      { name: "Finance Approval", role: "approver", sla_hours: 48 },
    ]);
  } else if (type === "executive") {
    textarea.value = JSON.stringify([
      { name: "Manager Sign-Off", role: "manager", sla_hours: 24 },
      { name: "Finance Verification", role: "approver", sla_hours: 48 },
      { name: "Executive HR Review", role: "hr", sla_hours: 72 },
    ]);
  }
};

// Admin Tools + Storage & Workflows
async function loadAdminData() {
  const [wfRes, polRes, usrRes, audRes, stoRes] = await Promise.all([
    api("/api/workflows"),
    api("/api/policies"),
    api("/api/users"),
    api("/api/audit"),
    api("/api/storage/config"),
  ]);

  document.getElementById("sb-url").value = stoRes.supabase_url || "";
  document.getElementById("sb-bucket").value = stoRes.bucket || "approval-attachments";
  document.getElementById("storage-status-box").textContent = stoRes.supabase_configured
    ? `Active Storage: Cloud Storage Connected (${stoRes.bucket})`
    : "Active Storage: Standard Secure Storage";

  window._cachedPolicies = polRes.policies || [];

  // Workflows Grid
  document.getElementById("workflows-list").innerHTML = wfRes.workflows.length
    ? `<div class="workflows-grid">` +
      wfRes.workflows
        .map((w) => {
          const humanType = humanizeType(w.request_type);
          const stages = w.stages || [];
          return `
            <div class="workflow-card">
              <div class="workflow-card-head">
                <div class="workflow-title-group">
                  <span class="workflow-type-badge">${humanType}</span>
                  <h4 class="workflow-title">${escapeHtml(w.name)}</h4>
                </div>
                <div class="workflow-meta-chips">
                  <button class="btn btn-secondary btn-sm" onclick="toggleWorkflowActive(${w.id}, ${!w.is_active})" style="font-size:0.7rem;padding:2px 8px;">${w.is_active ? "Pause" : "Activate"}</button>
                  <span class="workflow-mode-chip mode-${w.execution_mode}">${w.execution_mode === "parallel" ? "🔀 Parallel" : "⚡ Sequential"}</span>
                  <span class="workflow-sla-chip">⏱️ ${w.sla_hours}h SLA</span>
                </div>
              </div>
              <div class="workflow-stages-track">
                ${stages
                  .map(
                    (s, idx) => `
                  <div class="workflow-stage-pill">
                    <span class="stage-step-num">${idx + 1}</span>
                    <span class="stage-step-name">${escapeHtml(s.name)}</span>
                    <span class="user-role-badge role-badge-${s.role}">${escapeHtml(s.role)}</span>
                  </div>
                  ${idx < stages.length - 1 ? '<span class="stage-arrow">→</span>' : ""}`
                  )
                  .join("")}
              </div>
            </div>`;
        })
        .join("") +
      `</div>`
    : '<p class="muted small">No workflows configured.</p>';

  // Policies Grid
  document.getElementById("policies-list").innerHTML = polRes.policies.length
    ? `<div class="policies-grid">` +
      polRes.policies
        .map((p) => {
          const humanType = humanizeType(p.request_type);
          const blocked = p.blocked_keywords || [];
          return `
            <div class="policy-card">
              <div class="policy-card-head">
                <div class="policy-title-group">
                  <span class="policy-type-badge">${humanType}</span>
                  <h4 class="policy-title">${escapeHtml(p.name)}</h4>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                  <span class="policy-status-pill">${p.is_active ? "Active Policy" : "Inactive"}</span>
                  <button class="btn btn-secondary btn-sm" onclick="openPolicyModal(${p.id})" style="font-size:0.75rem;padding:3px 10px;">⚙️ Adjust Thresholds</button>
                </div>
              </div>
              <div class="policy-thresholds-grid">
                <div class="policy-thresh-cell">
                  <span class="thresh-label">Auto-Approval Threshold</span>
                  <span class="thresh-val" style="color:var(--primary);">≤ $${Number(p.auto_approve_max_amount).toLocaleString()}</span>
                </div>
                <div class="policy-thresh-cell">
                  <span class="thresh-label">Requires Receipt / Doc</span>
                  <span class="thresh-val">> $${Number(p.require_attachment_above).toLocaleString()}</span>
                </div>
                <div class="policy-thresh-cell">
                  <span class="thresh-label">Max Allowed Amount</span>
                  <span class="thresh-val">≤ $${Number(p.max_allowed_amount).toLocaleString()}</span>
                </div>
              </div>
              ${
                blocked.length
                  ? `
                <div class="policy-blocked-bar">
                  <span class="blocked-title">Blocked Keywords:</span>
                  <div class="blocked-tag-list">
                    ${blocked.map((kw) => `<span class="blocked-tag">${escapeHtml(kw)}</span>`).join("")}
                  </div>
                </div>`
                  : ""
              }
            </div>`;
        })
        .join("") +
      `</div>`
    : '<p class="muted small">No policies configured.</p>';

  // User Profiles & RBAC Grid
  document.getElementById("users-list").innerHTML = usrRes.users.length
    ? `<div class="user-profiles-grid">` +
      usrRes.users
        .map((u) => {
          const initials = getInitials(u.full_name);
          const bg = roleAvatarGradients[u.role] || roleAvatarGradients.requester;
          const isActive = u.is_active !== 0 && u.is_active !== false;
          const statusBadge = isActive
            ? `<span style="font-size:0.68rem;padding:2px 7px;border-radius:9999px;background:rgba(16,185,129,0.15);color:#059669;font-weight:700;">Active</span>`
            : `<span style="font-size:0.68rem;padding:2px 7px;border-radius:9999px;background:rgba(239,68,68,0.15);color:#DC2626;font-weight:700;">Deactivated</span>`;

          let adminControls = "";
          if (state.user && state.user.role === "admin") {
            const isSelf = u.id === state.user.id;
            adminControls = `
              <div style="display:flex;align-items:center;gap:6px;margin-top:6px;flex-wrap:wrap;">
                ${!isSelf ? `
                  <button class="btn btn-secondary btn-sm" style="font-size:0.72rem;padding:2px 8px;${isActive ? 'color:var(--accent-red);' : 'color:#059669;'}" onclick="toggleUserActive(${u.id}, ${!isActive})">
                    ${isActive ? "Deactivate" : "Activate"}
                  </button>
                ` : ""}
                <button class="btn btn-secondary btn-sm" style="font-size:0.72rem;padding:2px 8px;" onclick="openUserPwdModal(${u.id}, '${escapeHtml(u.username)}')">
                  🔑 Reset Pwd
                </button>
              </div>
            `;
          }

          return `
            <div class="user-profile-card" style="${!isActive ? 'opacity:0.75;' : ''}">
              <div class="user-avatar-circle" style="background:${bg};">${initials}</div>
              <div class="user-profile-info">
                <div class="user-profile-top">
                  <span class="user-profile-name">${escapeHtml(u.full_name)}</span>
                  <div style="display:flex;align-items:center;gap:6px;">
                    ${statusBadge}
                    <span class="user-role-badge role-badge-${u.role}">${escapeHtml(u.role)}</span>
                  </div>
                </div>
                <div class="user-profile-meta">
                  <span class="user-profile-handle">@${escapeHtml(u.username)}</span>
                  <span class="meta-dot">&bull;</span>
                  <span class="user-profile-dept">${escapeHtml(u.department || "Organization")}</span>
                  ${u.email ? `<span class="meta-dot">&bull;</span><span class="user-profile-email">${escapeHtml(u.email)}</span>` : ""}
                </div>
                ${adminControls}
              </div>
            </div>`;
        })
        .join("") +
      `</div>`
    : '<p class="muted small">No users found.</p>';

  // Tamper-Evident Audit Trail List
  document.getElementById("audit-list").innerHTML = audRes.audit_logs.length
    ? audRes.audit_logs
        .map(
          (a) => `
        <div class="audit-card-item">
          <div class="audit-card-left">
            <span class="audit-action-badge">${escapeHtml(a.action)}</span>
            <span class="audit-actor">${escapeHtml(a.actor_username)}</span>
            <span class="audit-target">${escapeHtml(a.entity_type)} ${a.entity_id ? "#" + a.entity_id : ""}</span>
          </div>
          <div class="audit-card-right">
            <span class="audit-time">${formatDate(a.created_at)}</span>
            <span class="audit-hash-pill">✓ Hash Intact</span>
          </div>
        </div>`
        )
        .join("")
    : '<p class="muted small">No audit log entries recorded.</p>';
}

document.getElementById("storage-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const res = await api("/api/storage/config", {
    method: "POST",
    body: JSON.stringify({
      supabase_url: document.getElementById("sb-url").value.trim(),
      supabase_key: document.getElementById("sb-key").value.trim(),
      bucket: document.getElementById("sb-bucket").value.trim(),
    }),
  });
  document.getElementById("sb-key").value = "";
  document.getElementById("storage-status-box").textContent = res.supabase_configured
    ? `Active Storage: Cloud Storage Connected (${res.bucket})`
    : "Active Storage: Standard Secure Storage";
});

document.getElementById("retrain-ai-btn").addEventListener("click", async () => {
  const res = await api("/api/ai/retrain", { method: "POST" });
  alert(`AI model retrained on ${res.sample_count} completed historical requests.`);
});

document.getElementById("workflow-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const stages = JSON.parse(document.getElementById("wf-stages").value);
    await api("/api/workflows", {
      method: "POST",
      body: JSON.stringify({
        name: document.getElementById("wf-name").value,
        request_type: document.getElementById("wf-type").value,
        execution_mode: document.getElementById("wf-mode").value,
        stages,
      }),
    });
    e.target.reset();
    loadAdminData();
  } catch (err) {
    alert(err.message);
  }
});

document.getElementById("user-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/users", {
      method: "POST",
      body: JSON.stringify({
        username: document.getElementById("u-username").value,
        password: document.getElementById("u-password").value,
        full_name: document.getElementById("u-fullname").value,
        email: document.getElementById("u-email").value,
        role: document.getElementById("u-role").value,
        department: document.getElementById("u-dept").value,
      }),
    });
    e.target.reset();
    loadAdminData();
  } catch (err) {
    alert(err.message);
  }
});

document.getElementById("verify-audit-btn").addEventListener("click", async () => {
  const res = await api("/api/audit/verify");
  document.getElementById("audit-verify-status").textContent = res.valid
    ? `Hash chain valid across ${res.entries_verified} audit entries.`
    : `Integrity broken at audit ID #${res.broken_at_id}`;
});

// Admin Policy Threshold Adjustment Modal Handlers
window.openPolicyModal = (policyId) => {
  const p = (window._cachedPolicies || []).find((x) => x.id === policyId);
  if (!p) return;
  document.getElementById("edit-policy-id").value = p.id;
  document.getElementById("policy-modal-title").textContent = `Adjust Thresholds — ${p.name}`;
  document.getElementById("policy-modal-badge").textContent = humanizeType(p.request_type);
  document.getElementById("edit-auto-max").value = p.auto_approve_max_amount;
  document.getElementById("edit-attach-above").value = p.require_attachment_above;
  document.getElementById("edit-max-allowed").value = p.max_allowed_amount;
  document.getElementById("edit-blocked-keywords").value = (p.blocked_keywords || []).join(", ");
  document.getElementById("edit-dynamic-adj").checked = Boolean(p.dynamic_adjustment_enabled);
  showEl(document.getElementById("policy-modal"), true);
};

document.getElementById("policy-modal-close-btn")?.addEventListener("click", () => {
  showEl(document.getElementById("policy-modal"), false);
});

document.getElementById("policy-cancel-btn")?.addEventListener("click", () => {
  showEl(document.getElementById("policy-modal"), false);
});

document.getElementById("policy-edit-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const policyId = document.getElementById("edit-policy-id").value;
  const autoMax = parseFloat(document.getElementById("edit-auto-max").value);
  const attachAbove = parseFloat(document.getElementById("edit-attach-above").value);
  const maxAllowed = parseFloat(document.getElementById("edit-max-allowed").value);
  const blockedRaw = document.getElementById("edit-blocked-keywords").value;
  const blockedKeywords = blockedRaw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const dynamicEnabled = document.getElementById("edit-dynamic-adj").checked;

  try {
    await api(`/api/policies/${policyId}`, {
      method: "PATCH",
      body: JSON.stringify({
        auto_approve_max_amount: autoMax,
        require_attachment_above: attachAbove,
        max_allowed_amount: maxAllowed,
        blocked_keywords: blockedKeywords,
        dynamic_adjustment_enabled: dynamicEnabled,
      }),
    });
    showEl(document.getElementById("policy-modal"), false);
    loadAdminData();
    alert("Policy thresholds updated successfully and committed to the audit trail.");
  } catch (err) {
    alert("Failed to update policy: " + err.message);
  }
});

// Admin Workflow Active Toggle Handler
window.toggleWorkflowActive = async (workflowId, makeActive) => {
  try {
    await api(`/api/workflows/${workflowId}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active: makeActive }),
    });
    loadAdminData();
  } catch (err) {
    alert("Failed to update workflow: " + err.message);
  }
};

// Out of Office & Approval Delegation Handlers
async function loadDelegationsData() {
  try {
    const [delRes, colRes] = await Promise.all([
      api("/api/delegations"),
      api("/api/delegations/colleagues"),
    ]);

    // Populate colleague selector
    const colSelect = document.getElementById("del-colleague-select");
    if (colSelect) {
      colSelect.innerHTML = (colRes.colleagues || []).length
        ? `<option value="">Select an active colleague...</option>` +
          colRes.colleagues
            .map(
              (c) =>
                `<option value="${c.id}">${escapeHtml(c.full_name)} (@${escapeHtml(c.username)}) — ${c.role.toUpperCase()} (${escapeHtml(c.department || "General")})</option>`
            )
            .join("")
        : `<option value="">No eligible colleagues available</option>`;
    }

    // Populate active delegations list
    const listEl = document.getElementById("active-delegations-list");
    if (listEl) {
      const activeList = (delRes.delegations || []).filter((d) => d.is_active);
      listEl.innerHTML = activeList.length
        ? activeList
            .map((d) => {
              const isMine = d.user_id === state.user.id;
              const title = isMine
                ? `You ➔ <strong>${escapeHtml(d.delegate_name)}</strong>`
                : `<strong>${escapeHtml(d.delegator_name)}</strong> ➔ You (Acting Delegate)`;
              return `
              <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 10px;background:var(--card-bg);border:1px solid var(--border);border-radius:8px;margin-bottom:6px;gap:8px;flex-wrap:wrap;">
                <div style="font-size:0.85rem;">
                  <div>${title}</div>
                  <div class="muted small">${escapeHtml(d.start_date)} to ${escapeHtml(d.end_date)}${d.notes ? ` • <em>${escapeHtml(d.notes)}</em>` : ""}</div>
                </div>
                ${
                  isMine || state.user.role === "admin"
                    ? `<button type="button" class="btn btn-secondary btn-sm" style="color:var(--accent-red);font-size:0.75rem;padding:2px 8px;" onclick="revokeDelegation(${d.id})">Revoke</button>`
                    : '<span class="status-pill status-approved" style="font-size:0.7rem;">Active</span>'
                }
              </div>`;
            })
            .join("")
        : '<p class="muted small" style="margin:0;">No active delegations configured.</p>';
    }
  } catch (err) {
    console.warn("Failed to load delegations:", err);
  }
}

window.revokeDelegation = async (id) => {
  if (!confirm("Revoke this approval delegation coverage?")) return;
  try {
    await api(`/api/delegations/${id}`, { method: "DELETE" });
    loadDelegationsData();
    loadRequests();
    alert("Delegation coverage revoked successfully.");
  } catch (err) {
    alert("Failed to revoke delegation: " + err.message);
  }
};

document.getElementById("ooo-btn")?.addEventListener("click", () => {
  const today = new Date().toISOString().slice(0, 10);
  const startInput = document.getElementById("del-start-date");
  if (startInput && !startInput.value) startInput.value = today;
  showEl(document.getElementById("delegation-modal"), true);
  loadDelegationsData();
});

document.getElementById("delegation-close-btn")?.addEventListener("click", () => {
  showEl(document.getElementById("delegation-modal"), false);
});

document.getElementById("delegation-cancel-btn")?.addEventListener("click", () => {
  showEl(document.getElementById("delegation-modal"), false);
});

document.getElementById("delegation-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const delegate_user_id = document.getElementById("del-colleague-select").value;
  const start_date = document.getElementById("del-start-date").value;
  const end_date = document.getElementById("del-end-date").value;
  const notes = document.getElementById("del-notes").value;
  if (!delegate_user_id) return alert("Please select an active colleague delegate.");
  if (start_date > end_date) return alert("End date must be on or after start date.");

  try {
    await api("/api/delegations", {
      method: "POST",
      body: JSON.stringify({ delegate_user_id: parseInt(delegate_user_id, 10), start_date, end_date, notes }),
    });
    document.getElementById("del-notes").value = "";
    loadDelegationsData();
    loadRequests();
    alert("Out-of-Office approval delegation activated successfully!");
  } catch (err) {
    alert("Failed to activate delegation: " + err.message);
  }
});

// Admin User Lifecycle Management Handlers
window.toggleUserActive = async (userId, makeActive) => {
  const actionName = makeActive ? "activate" : "deactivate";
  if (!confirm(`Are you sure you want to ${actionName} this user account?`)) return;
  try {
    await api(`/api/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active: makeActive }),
    });
    loadAdminData();
    alert(`User account ${makeActive ? "activated" : "deactivated"} successfully.`);
  } catch (err) {
    alert("Failed to update user account: " + err.message);
  }
};

window.openUserPwdModal = (userId, username) => {
  document.getElementById("pwd-user-id").value = userId;
  document.getElementById("pwd-modal-user-title").textContent = `Reset Password — @${username}`;
  document.getElementById("admin-new-password").value = "";
  showEl(document.getElementById("user-pwd-modal"), true);
};

document.getElementById("pwd-modal-close-btn")?.addEventListener("click", () => {
  showEl(document.getElementById("user-pwd-modal"), false);
});

document.getElementById("pwd-cancel-btn")?.addEventListener("click", () => {
  showEl(document.getElementById("user-pwd-modal"), false);
});

document.getElementById("user-pwd-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const userId = document.getElementById("pwd-user-id").value;
  const password = document.getElementById("admin-new-password").value;
  try {
    await api(`/api/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({ password }),
    });
    showEl(document.getElementById("user-pwd-modal"), false);
    document.getElementById("user-pwd-form").reset();
    alert("User password successfully reset and logged to audit trail.");
  } catch (err) {
    alert("Password reset failed: " + err.message);
  }
});

// User Self-Service Profile Modal Handlers
async function openProfileModal() {
  try {
    const res = await api("/api/auth/me");
    const u = res.user;
    state.user = u;
    const initials = getInitials(u.full_name);
    const bg = roleAvatarGradients[u.role] || roleAvatarGradients.requester;

    const av = document.getElementById("profile-avatar");
    if (av) {
      av.textContent = initials;
      av.style.background = bg;
    }
    const fn = document.getElementById("profile-fullname");
    if (fn) fn.textContent = u.full_name;
    const un = document.getElementById("profile-username");
    if (un) un.textContent = `@${u.username}`;
    const dp = document.getElementById("profile-dept");
    if (dp) dp.textContent = u.department || "Organization";
    const rb = document.getElementById("profile-role-badge");
    if (rb) {
      rb.textContent = u.role;
      rb.className = `user-role-badge role-badge-${u.role}`;
    }

    const st = u.stats || {};
    const stTot = document.getElementById("profile-stat-total");
    if (stTot) stTot.textContent = st.total_submitted || 0;
    const stApp = document.getElementById("profile-stat-approved");
    if (stApp) stApp.textContent = st.approved_count || 0;
    const stPen = document.getElementById("profile-stat-pending");
    if (stPen) stPen.textContent = st.pending_count || 0;

    const ifn = document.getElementById("profile-input-fullname");
    if (ifn) ifn.value = u.full_name || "";
    const iem = document.getElementById("profile-input-email");
    if (iem) iem.value = u.email || "";
    const cpwd = document.getElementById("profile-current-pwd");
    if (cpwd) cpwd.value = "";
    const npwd = document.getElementById("profile-new-pwd");
    if (npwd) npwd.value = "";

    showEl(document.getElementById("profile-modal"), true);
  } catch (err) {
    alert("Failed to load profile: " + err.message);
  }
}

document.getElementById("user-profile-pill")?.addEventListener("click", openProfileModal);

document.getElementById("profile-modal-close-btn")?.addEventListener("click", () => {
  showEl(document.getElementById("profile-modal"), false);
});

document.getElementById("profile-cancel-btn")?.addEventListener("click", () => {
  showEl(document.getElementById("profile-modal"), false);
});

document.getElementById("profile-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const full_name = document.getElementById("profile-input-fullname").value.trim();
  const email = document.getElementById("profile-input-email").value.trim();
  const current_password = document.getElementById("profile-current-pwd").value;
  const new_password = document.getElementById("profile-new-pwd").value;

  const payload = { full_name, email };
  if (new_password) {
    if (!current_password) return alert("Please enter your current password to set a new password.");
    payload.current_password = current_password;
    payload.new_password = new_password;
  }

  try {
    const res = await api("/api/auth/profile", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    state.user.full_name = res.user.full_name;
    state.user.email = res.user.email;
    document.getElementById("user-display-name").textContent = res.user.full_name;
    showEl(document.getElementById("profile-modal"), false);
    alert("Profile updated successfully!");
  } catch (err) {
    alert("Failed to update profile: " + err.message);
  }
});

bootstrap();

