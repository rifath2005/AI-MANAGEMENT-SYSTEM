"""Tests for authentication, isolated admin gateway, rate limiting, sign-up, and RBAC."""

from tests.conftest import auth_header


def test_standard_vs_isolated_admin_gateways(client):
    # Admin cannot sign in through the public /api/auth/login gateway
    blocked = client.post("/api/auth/login", json={"username": "sysadmin", "password": "AdminGate#2026"})
    assert blocked.status_code == 403

    # Non-admin cannot sign in through the isolated /api/auth/admin/login gateway
    non_admin = client.post("/api/auth/admin/login", json={"username": "nadia.patel", "password": "ReqPass#2026"})
    assert non_admin.status_code == 403

    # Role-specific portal blocks mismatched roles
    mismatch = client.post(
        "/api/auth/login",
        json={"username": "nadia.patel", "password": "ReqPass#2026", "portal": "manager"},
    )
    assert mismatch.status_code == 403

    # Valid standard and admin gateway logins succeed
    req_ok = client.post("/api/auth/login", json={"username": "nadia.patel", "password": "ReqPass#2026", "portal": "requester"})
    assert req_ok.status_code == 200
    assert req_ok.get_json()["user"]["role"] == "requester"

    adm_ok = client.post("/api/auth/admin/login", json={"username": "sysadmin", "password": "AdminGate#2026"})
    assert adm_ok.status_code == 200
    assert adm_ok.get_json()["user"]["role"] == "admin"


def test_dedicated_login_pages_and_no_quick_signin(client):
    home = client.get("/login")
    assert home.status_code == 200
    html = home.data.decode()
    assert "/login/admin" not in html
    assert "demo123" not in html
    assert "admin123" not in html
    assert "Dedicated Role Sign-In Gateways" not in html
    assert "/login/requester" not in html
    assert 'id="login-username-error"' in html
    assert 'id="login-password-error"' in html
    assert 'class="req-star"' in html
    assert 'aria-required="true"' in html

    # Admin gateway is isolated and accessible directly
    admin_page = client.get("/login/admin")
    assert admin_page.status_code == 200
    assert "Administrator Sign In" in admin_page.data.decode()

    # Legacy dedicated role URLs cleanly redirect to the unified /login gateway
    for role in ("requester", "manager", "approver", "hr"):
        r = client.get(f"/login/{role}")
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/login")

    assert client.get("/login/unknown").status_code == 404


def test_login_required_field_validation(client):
    # Missing both fields
    r_empty = client.post("/api/auth/login", json={})
    assert r_empty.status_code == 400
    assert "Username and password are required" in r_empty.get_json()["error"]

    # Missing username only
    r_no_user = client.post("/api/auth/login", json={"password": "SomePassword123"})
    assert r_no_user.status_code == 400
    assert "Username is required" in r_no_user.get_json()["error"]

    # Missing password only
    r_no_pass = client.post("/api/auth/login", json={"username": "nadia.patel"})
    assert r_no_pass.status_code == 400
    assert "Password is required" in r_no_pass.get_json()["error"]

    # Whitespace-only username
    r_spaces = client.post("/api/auth/login", json={"username": "   ", "password": "SomePassword123"})
    assert r_spaces.status_code == 400
    assert "Username is required" in r_spaces.get_json()["error"]

    # Admin gateway missing fields
    adm_empty = client.post("/api/auth/admin/login", json={})
    assert adm_empty.status_code == 400
    assert "Administrator username and password are required" in adm_empty.get_json()["error"]


def test_login_rate_limiter_and_self_signup(client):
    for _ in range(5):
        res = client.post("/api/auth/login", json={"username": "nadia.patel", "password": "WrongPassword1"})
        assert res.status_code == 401

    locked = client.post("/api/auth/login", json={"username": "nadia.patel", "password": "ReqPass#2026"})
    assert locked.status_code == 429

    # Self sign-up requires strong password and strictly assigns 'requester' role
    weak = client.post(
        "/api/auth/register",
        json={"username": "priya", "password": "weak", "full_name": "Priya", "email": "p@company.com"},
    )
    assert weak.status_code == 400

    ok = client.post(
        "/api/auth/register",
        json={
            "username": "priya.sharma",
            "password": "StrongUser#2026",
            "full_name": "Priya Sharma",
            "email": "priya.sharma@company.com",
            "department": "Product",
            "role": "admin",  # attempted privilege escalation must be ignored
        },
    )
    assert ok.status_code == 201
    assert ok.get_json()["user"]["role"] == "requester"


def test_rbac_user_management_and_audit_access(client):
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")
    hr_hdr = auth_header(client, "david.okafor", "HrPass#2026")
    admin_hdr = auth_header(client, "sysadmin", "AdminGate#2026", is_admin=True)

    assert client.get("/api/users", headers=req_hdr).status_code == 403
    assert client.get("/api/audit", headers=req_hdr).status_code == 403

    assert client.get("/api/users", headers=hr_hdr).status_code == 200
    res_bad = client.post(
        "/api/users",
        headers=hr_hdr,
        json={"username": "badadmin", "password": "StrongUser#1", "full_name": "Bad", "email": "b@c.com", "role": "admin"},
    )
    assert res_bad.status_code == 403

    res_ok = client.post(
        "/api/users",
        headers=admin_hdr,
        json={"username": "eva.lin", "password": "StrongUser#2", "full_name": "Eva Lin", "email": "eva@c.com", "role": "approver"},
    )
    assert res_ok.status_code == 201
    assert client.get("/api/audit/verify", headers=admin_hdr).get_json()["valid"] is True


def test_email_login_and_lowercase_normalization(client):
    """Verify email-based authentication with case-insensitive normalization and whitespace trimming."""
    # Standard login with exact email
    r_exact = client.post(
        "/api/auth/login",
        json={"email": "nadia.patel@company.com", "password": "ReqPass#2026", "portal": "requester"},
    )
    assert r_exact.status_code == 200
    assert r_exact.get_json()["user"]["email"] == "nadia.patel@company.com"

    # Standard login with uppercase email (User@Example.COM normalization)
    r_upper = client.post(
        "/api/auth/login",
        json={"email": "NADIA.PATEL@COMPANY.COM", "password": "ReqPass#2026", "portal": "requester"},
    )
    assert r_upper.status_code == 200
    assert r_upper.get_json()["user"]["username"] == "nadia.patel"

    # Whitespace-padded email
    r_padded = client.post(
        "/api/auth/login",
        json={"email": "   nadia.patel@company.com   ", "password": "ReqPass#2026", "portal": "requester"},
    )
    assert r_padded.status_code == 200

    # Isolated admin login with uppercase email
    r_adm_upper = client.post(
        "/api/auth/admin/login",
        json={"email": "SYSADMIN@COMPANY.COM", "password": "AdminGate#2026"},
    )
    assert r_adm_upper.status_code == 200
    assert r_adm_upper.get_json()["user"]["role"] == "admin"


def test_password_strength_enforcement(client):
    """Verify character mix enforcement (length, upper, lower, digit, special character)."""
    base_user = {
        "full_name": "Test Candidate",
        "username": "candidate.user",
        "email": "candidate@company.com",
        "department": "Security",
    }

    # Too short (< 8 chars)
    r_short = client.post("/api/auth/register", json={**base_user, "password": "Sh1!"})
    assert r_short.status_code == 400
    assert "8 characters" in r_short.get_json()["error"]

    # Missing uppercase
    r_no_upper = client.post("/api/auth/register", json={**base_user, "password": "weakpass1!"})
    assert r_no_upper.status_code == 400
    assert "uppercase" in r_no_upper.get_json()["error"]

    # Missing lowercase
    r_no_lower = client.post("/api/auth/register", json={**base_user, "password": "WEAKPASS1!"})
    assert r_no_lower.status_code == 400
    assert "lowercase" in r_no_lower.get_json()["error"]

    # Missing numeric digit
    r_no_digit = client.post("/api/auth/register", json={**base_user, "password": "WeakPassword!"})
    assert r_no_digit.status_code == 400
    assert "digit" in r_no_digit.get_json()["error"]

    # Missing special character
    r_no_special = client.post("/api/auth/register", json={**base_user, "password": "WeakPassword1"})
    assert r_no_special.status_code == 400
    assert "special character" in r_no_special.get_json()["error"]

    # Strong password satisfying all 5 criteria is accepted
    r_strong = client.post(
        "/api/auth/register",
        json={**base_user, "password": "StrongSecurity#2026"},
    )
    assert r_strong.status_code == 201
    assert r_strong.get_json()["user"]["username"] == "candidate.user"


def test_client_validation_markup_and_gates(client):
    """Verify that password fields start disabled and checklist rules are rendered in plain language."""
    resp = client.get("/login")
    assert resp.status_code == 200
    html = resp.data.decode()

    # Login form: email field present and password locked
    assert 'id="login-email"' in html
    assert 'id="login-password"' in html
    assert 'id="login-password" name="password" autocomplete="current-password" placeholder="Enter valid email first" required aria-required="true" aria-describedby="login-password-error" disabled' in html

    # Signup form: password locked and strength checklist present
    assert 'id="signup-email"' in html
    assert 'id="signup-password"' in html
    assert 'id="signup-password" autocomplete="new-password" placeholder="Enter valid email first" required aria-required="true" aria-describedby="signup-password-error" disabled' in html
    assert 'id="signup-password-strength-box"' in html
    assert 'id="signup-strength-label"' in html
    assert 'id="signup-strength-bar"' in html

    # Plain language rules checklist
    assert "At least 8 characters in length" in html
    assert "At least one uppercase letter (A–Z)" in html
    assert "At least one lowercase letter (a–z)" in html
    assert "At least one numeric digit (0–9)" in html
    assert "At least one special character (!@#$%^&amp;*)" in html

