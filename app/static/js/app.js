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
  const isValid = validateEmailFormat(trimmed);

  if (isValid) {
    loginPasswordInput.disabled = false;
    loginPasswordInput.placeholder = "Enter your password";
    if (toggleLoginPassBtn) toggleLoginPassBtn.disabled = false;
    clearFieldError("login-email", "login-email-error");
    clearFieldError("login-username", "login-username-error");
    if (loginPasswordHint) loginPasswordHint.textContent = "Email verified. Enter your password to continue.";
    if (loginSubmitBtn) {
      loginSubmitBtn.disabled = loginPasswordInput.value.length === 0;
    }
  } else {
    loginPasswordInput.disabled = true;
    loginPasswordInput.placeholder = "Enter valid email first";
    if (toggleLoginPassBtn) toggleLoginPassBtn.disabled = true;
    if (loginSubmitBtn) loginSubmitBtn.disabled = true;
    if (loginPasswordHint) loginPasswordHint.textContent = "Password unlocks after entering a valid corporate email.";

    if (trimmed.length > 0) {
      setFieldError("login-email", "login-email-error", "Please enter a valid email address (e.g. name@company.com).");
    } else {
      if (userTriggered) {
        setFieldError("login-email", "login-email-error", "Corporate email is required.");
      } else {
        clearFieldError("login-email", "login-email-error");
      }
    }
  }
}

if (loginEmailInput) {
  loginEmailInput.addEventListener("input", () => {
    normalizeEmailInput(loginEmailInput);
    updateLoginEmailGate(false);
    showEl(document.getElementById("login-error"), false);
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
    const emailVal = loginEmailInput ? loginEmailInput.value.trim() : "";
    if (loginSubmitBtn) {
      loginSubmitBtn.disabled = !(validateEmailFormat(emailVal) && loginPasswordInput.value.length > 0);
    }
  });
}

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
    setFieldError("login-email", "login-email-error", "Corporate email is required.");
    hasError = true;
    firstInvalidEl = firstInvalidEl || emailInput;
  } else if (!validateEmailFormat(email)) {
    setFieldError("login-email", "login-email-error", "Please enter a valid email address (e.g. name@company.com).");
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
    title: "System Admin Console — Governance, Storage & AI",
    subtitle: "Configure workflows, policies, Supabase storage, LLM keys, and audit integrity.",
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
    document.getElementById("predictions-panel").innerHTML = `
      <p><strong>Forecast:</strong> ~${vf.predicted_next_7_days_requests} requests in 7 days (~${vf.predicted_next_30_days_requests} in 30 days) • Trend: <strong>${vf.trend}</strong></p>
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
window._exportCsv = async () => {
  const res = await fetch("/api/analytics/export.csv", {
    headers: { Authorization: `Bearer ${state.token}` },
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "approval_report.csv";
  a.click();
  URL.revokeObjectURL(url);
};

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
document.getElementById("refresh-requests-btn").addEventListener("click", loadRequests);
document.getElementById("filter-scope").addEventListener("change", loadRequests);
document.getElementById("filter-status").addEventListener("change", loadRequests);

async function loadRequests() {
  const scope = document.getElementById("filter-scope").value;
  const status = document.getElementById("filter-status").value;
  const params = new URLSearchParams();
  if (scope) params.set("scope", scope);
  if (status) params.set("status", status);
  const res = await api(`/api/requests?${params.toString()}`);
  tbody.innerHTML = res.requests.length
    ? res.requests
        .map(
          (r) => `
    <tr>
      <td>#${r.id}</td>
      <td><strong>${r.title}</strong><div class="muted small">${r.request_type}</div></td>
      <td>${r.requester_name}</td>
      <td>${r.amount} ${r.currency}</td>
      <td><span class="status-pill status-${r.status}">${r.status}</span>${r.auto_approved ? ' <span class="small muted">(Auto)</span>' : ""}</td>
      <td>${r.ai_recommendation || "-"} (${Math.round((r.ai_risk_score || 0) * 100)}% risk)${r.is_anomaly ? ' <strong>[Anomaly]</strong>' : ""}</td>
      <td><button class="btn btn-sm btn-primary" onclick="openRequestDetail(${r.id})">View</button></td>
    </tr>`
        )
        .join("")
    : '<tr><td colspan="7" class="muted small" style="text-align:center;padding:26px;">No requests found matching current filter.</td></tr>';
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

  const formattedAmount = `${Number(r.amount).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} ${r.currency}`;

  const riskPct = Math.round((r.ai_risk_score || 0) * 100);
  const confPct = Math.round((r.ai_confidence || 0) * 100);
  const rec = (r.ai_recommendation || "review").toLowerCase();
  const recClass =
    rec === "approve"
      ? "ai-chip-rec-approve"
      : rec === "reject"
      ? "ai-chip-rec-reject"
      : "ai-chip-rec-review";

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
        <div class="detail-subvalue">Currency: ${escapeHtml(r.currency)}</div>
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
                  <div class="workflow-step-title">${escapeHtml(t.stage_name)} <span class="muted small">(${escapeHtml(t.assigned_role)})</span></div>
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
            <strong>Automated Instant Approval:</strong> Request amount ($${Number(r.amount).toFixed(2)}) meets company policy threshold rules with low risk rating (${riskPct}%). No manual escalation required.
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
          <button class="btn btn-special" style="flex:1;" onclick="submitDecision(${r.id}, 'rejected')">✕ Reject Request</button>
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

window.submitDecision = async (reqId, decision) => {
  const comment = document.getElementById("decision-comment")?.value || "";
  try {
    await api(`/api/requests/${reqId}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, comment }),
    });
    showEl(document.getElementById("detail-modal"), false);
    loadRequests();
    loadDashboard();
    loadNotifications();
  } catch (err) {
    alert(err.message);
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
  fd.append("urgency", document.getElementById("req-urgency").value);
  fd.append("description", document.getElementById("req-description").value);
  const fileInput = document.getElementById("req-attachment");
  if (fileInput.files.length > 0) {
    fd.append("attachment", fileInput.files[0]);
  }
  const res = await api("/api/requests", { method: "POST", body: fd });
  const box = document.getElementById("submit-result-box");
  box.innerHTML = `Created <strong>Request #${res.request_id}</strong> • Status: <strong>${res.status}</strong><br/>${res.ai_evaluation.explanation}`;
  showEl(box, true);
  e.target.reset();
  loadRequests();
  loadDashboard();
  loadNotifications();
});

// Voice & Chat Assistant + BYOK Project-Tuned LLM Config
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
  try {
    const cfg = await api("/api/chat/config", { headers: getSessionLlmHeaders() });
    document.getElementById("chat-engine-badge").textContent = cfg.configured
      ? `${cfg.provider}:${cfg.model}`
      : "local_nlp";
    document.getElementById("llm-config-status").textContent = cfg.configured
      ? `Active: ${cfg.provider} (${cfg.model}) • Key ${cfg.masked_key}`
      : "Active: Free Local NLP Parser (no external API key required)";
  } catch {
    // ignore before login
  }
}

document.getElementById("llm-provider").addEventListener("change", (e) => {
  showEl(document.getElementById("llm-base-url"), e.target.value === "openai_compatible");
});

document.getElementById("chat-key-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const apiKey = document.getElementById("llm-api-key").value.trim();
  const provider = document.getElementById("llm-provider").value;
  const model = document.getElementById("llm-model").value.trim();
  const baseUrl = document.getElementById("llm-base-url").value.trim();

  if (state.user && state.user.role === "admin") {
    await api("/api/chat/config", {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey, provider, model, base_url: baseUrl }),
    });
    sessionStorage.removeItem("ams_llm_key");
  } else if (apiKey) {
    sessionStorage.setItem("ams_llm_key", apiKey);
    sessionStorage.setItem("ams_llm_provider", provider);
    sessionStorage.setItem("ams_llm_model", model);
    sessionStorage.setItem("ams_llm_base_url", baseUrl);
  }
  document.getElementById("llm-api-key").value = "";
  loadChatConfig();
});

document.getElementById("llm-clear-btn").addEventListener("click", async () => {
  sessionStorage.removeItem("ams_llm_key");
  sessionStorage.removeItem("ams_llm_provider");
  sessionStorage.removeItem("ams_llm_model");
  sessionStorage.removeItem("ams_llm_base_url");
  if (state.user && state.user.role === "admin") {
    await api("/api/chat/config", {
      method: "POST",
      body: JSON.stringify({ api_key: "", provider: "auto", model: "", base_url: "" }),
    });
  }
  loadChatConfig();
});

document.getElementById("download-finetune-btn").addEventListener("click", async (e) => {
  e.preventDefault();
  const prov = document.getElementById("llm-provider").value;
  const fmt = prov === "gemini" ? "gemini" : "openai";
  const res = await fetch(`/api/chat/finetune-dataset?format=${fmt}`, {
    headers: { Authorization: `Bearer ${state.token}` },
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `ams_chat_finetune_${fmt}.jsonl`;
  a.click();
  URL.revokeObjectURL(url);
});

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
    if (res.engine) {
      document.getElementById("chat-engine-badge").textContent = res.engine;
    }
    appendChat(res.reply, "chat-bot");
    loadRequests();
    loadNotifications();
  } catch (err) {
    appendChat(`Error: ${err.message}`, "chat-bot");
  }
});

document.getElementById("voice-btn").addEventListener("click", () => {
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRec) {
    appendChat("Voice recognition is not supported in this browser; please type your command.", "chat-bot");
    return;
  }
  const rec = new SpeechRec();
  rec.lang = "en-US";
  rec.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    document.getElementById("chat-input").value = transcript;
  };
  rec.start();
});

// Admin Tools + Supabase Storage
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
    ? `Active Storage: Supabase (${stoRes.bucket}, Key ${stoRes.masked_key})`
    : "Active Storage: Local Disk (free fallback; enter Supabase URL & key above to switch)";

  document.getElementById("workflows-list").innerHTML = wfRes.workflows.length
    ? wfRes.workflows
        .map(
          (w) => `
    <div class="list-row">
      <strong>${w.name}</strong> (${w.request_type} • <code>${w.execution_mode}</code> • SLA ${w.sla_hours}h)<br/>
      <span class="muted">Stages: ${w.stages.map((s) => `${s.name} [${s.role}]`).join(" -> ")}</span>
    </div>`
        )
        .join("")
    : '<p class="muted small">No workflows configured.</p>';

  document.getElementById("policies-list").innerHTML = polRes.policies.length
    ? polRes.policies
        .map(
          (p) => `
    <div class="list-row">
      <strong>${p.name}</strong> (${p.request_type})<br/>
      Auto-approve <= <strong>${p.auto_approve_max_amount}</strong> • Attachment > ${p.require_attachment_above} • Max ${p.max_allowed_amount}<br/>
      <span class="muted">Blocked keywords: ${p.blocked_keywords.join(", ") || "None"}</span>
    </div>`
        )
        .join("")
    : '<p class="muted small">No policies configured.</p>';

  document.getElementById("users-list").innerHTML = usrRes.users.length
    ? usrRes.users
        .map((u) => `<div class="list-row"><strong>${u.full_name}</strong> (@${u.username}) — <code>${u.role}</code> • ${u.department}</div>`)
        .join("")
    : '<p class="muted small">No users found.</p>';

  document.getElementById("audit-list").innerHTML = audRes.audit_logs.length
    ? audRes.audit_logs
        .map(
          (a) => `<div class="audit-item"><strong>#${a.id} ${a.action}</strong> by ${a.actor_username} (${a.entity_type} ${a.entity_id || "-"}) <span class="muted">${a.created_at}</span></div>`
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
    ? `Active Storage: Supabase (${res.bucket}, Key ${res.masked_key})`
    : "Active Storage: Local Disk";
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

bootstrap();
