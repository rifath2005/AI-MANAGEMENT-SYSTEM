"""Project-tuned LLM chat router & fine-tuning dataset builder.

Supports Bring-Your-Own-Key (BYOK) for Gemini, OpenAI, Groq, or any OpenAI-compatible
endpoint using Python stdlib HTTP requests, with live project context grounding and
automatic fallback to the free local NLP parser when no API key is configured.
"""

import json
import os
import re
import urllib.error
import urllib.request

from .ai_engine import parse_chat_command
from .security import ROLE_CAPABILITIES

DEFAULT_MODELS = {
    "gemini": "gemini-2.0-flash",
    "openai": "gpt-4o-mini",
    "groq": "openai/gpt-oss-120b",
    "openai_compatible": "gpt-4o-mini",
}


def detect_provider(api_key: str, explicit_provider: str = "auto") -> str:
    prov = (explicit_provider or "auto").strip().lower()
    if prov != "auto":
        return prov
    if api_key.startswith("AIza"):
        return "gemini"
    if api_key.startswith("gsk_"):
        return "groq"
    return "openai"


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


def get_saved_llm_settings(db) -> dict:
    rows = db.execute("SELECT key, value FROM app_settings WHERE key LIKE 'llm_%'").fetchall()
    return {r["key"]: r["value"] for r in rows}


def resolve_llm_config(db, header_key: str = "", header_provider: str = "", header_model: str = "", header_base_url: str = "") -> dict:
    """Resolve effective LLM configuration from request headers, DB settings, or env vars."""
    saved = get_saved_llm_settings(db)

    api_key = (
        header_key.strip()
        or saved.get("llm_api_key", "").strip()
        or os.environ.get("AMS_LLM_API_KEY", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
        or os.environ.get("GROQ_API_KEY", "").strip()
    )

    explicit_provider = (
        header_provider.strip()
        or saved.get("llm_provider", "").strip()
        or os.environ.get("AMS_LLM_PROVIDER", "auto").strip()
    )
    if not api_key:
        return {"configured": False, "provider": "local_nlp", "model": "local-rule-parser", "api_key": "", "base_url": ""}

    if explicit_provider == "auto":
        if os.environ.get("GEMINI_API_KEY") and api_key == os.environ.get("GEMINI_API_KEY"):
            provider = "gemini"
        elif os.environ.get("GROQ_API_KEY") and api_key == os.environ.get("GROQ_API_KEY"):
            provider = "groq"
        else:
            provider = detect_provider(api_key, "auto")
    else:
        provider = explicit_provider

    model = (
        header_model.strip()
        or saved.get("llm_model", "").strip()
        or os.environ.get("AMS_LLM_MODEL", "").strip()
        or DEFAULT_MODELS.get(provider, "gpt-4o-mini")
    )
    base_url = (
        header_base_url.strip()
        or saved.get("llm_base_url", "").strip()
        or os.environ.get("AMS_LLM_BASE_URL", "").strip()
    )
    return {
        "configured": True,
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
    }


def build_project_system_prompt(db, user: dict) -> str:
    """Build a domain-grounded system prompt reflecting live policies, workflows, and user RBAC."""
    policies = [
        {
            "name": p["name"],
            "request_type": p["request_type"],
            "auto_approve_max_amount": p["auto_approve_max_amount"],
            "require_attachment_above": p["require_attachment_above"],
            "max_allowed_amount": p["max_allowed_amount"],
            "blocked_keywords": json.loads(p["blocked_keywords_json"] or "[]"),
        }
        for p in db.execute("SELECT * FROM policies WHERE is_active = 1").fetchall()
    ]
    workflows = [
        {
            "name": w["name"],
            "request_type": w["request_type"],
            "execution_mode": w["execution_mode"],
            "stages": json.loads(w["stages_json"]),
            "sla_hours": w["sla_hours"],
        }
        for w in db.execute("SELECT * FROM workflows WHERE is_active = 1").fetchall()
    ]
    my_recent = [
        dict(r)
        for r in db.execute(
            "SELECT id, title, request_type, amount, status FROM requests WHERE requester_id = ? ORDER BY id DESC LIMIT 5",
            (user["id"],),
        ).fetchall()
    ]
    pending_queue = []
    if user["role"] in ("manager", "approver", "hr", "admin"):
        pending_queue = [
            dict(r)
            for r in db.execute(
                """
                SELECT r.id, r.title, r.request_type, r.amount, r.status, t.stage_name
                FROM approval_tasks t JOIN requests r ON r.id = t.request_id
                WHERE t.status = 'pending' AND (t.assigned_role = ? OR ? = 'admin')
                ORDER BY r.id DESC LIMIT 8
                """,
                (user["role"], user["role"]),
            ).fetchall()
        ]

    context_blob = {
        "current_user": {
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "department": user["department"],
            "capabilities": ROLE_CAPABILITIES.get(user["role"], []),
        },
        "active_policies": policies,
        "active_workflows": workflows,
        "user_recent_requests": my_recent,
        "pending_approval_queue": pending_queue,
    }

    return (
        "You are the AI Assistant for the Approval Management System using AI.\n"
        "Respond ONLY with a valid JSON object (no markdown fences) matching one of these intents:\n"
        "1. submit_request: {\"intent\":\"submit_request\",\"request_type\":\"expense_report|leave_request|purchase_order\",\"title\":\"...\",\"description\":\"...\",\"amount\":number,\"currency\":\"USD\",\"urgency\":\"low|normal|high\",\"reply\":\"...\"}\n"
        "2. check_status: {\"intent\":\"check_status\",\"request_id\":number,\"reply\":\"...\"}\n"
        "3. list_my_requests: {\"intent\":\"list_my_requests\",\"reply\":\"...\"}\n"
        "4. list_pending: {\"intent\":\"list_pending\",\"reply\":\"...\"}\n"
        "5. approve_request: {\"intent\":\"approve_request\",\"request_id\":number,\"comment\":\"...\",\"reply\":\"...\"}\n"
        "6. reject_request: {\"intent\":\"reject_request\",\"request_id\":number,\"comment\":\"...\",\"reply\":\"...\"}\n"
        "7. policy_qa: {\"intent\":\"policy_qa\",\"reply\":\"concise answer grounded in active_policies and active_workflows\"}\n"
        "8. help: {\"intent\":\"help\",\"reply\":\"...\"}\n\n"
        "Rules:\n"
        "- Never approve/reject if user's role is 'requester'; explain RBAC restriction via intent 'policy_qa'.\n"
        "- Ground policy answers strictly in active_policies and active_workflows.\n"
        "- For leave requests, amount represents number of days.\n"
        f"Live Project Context:\n{json.dumps(context_blob)}"
    )


def _extract_json_object(text: str) -> dict | None:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except Exception:
        m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
                return obj if isinstance(obj, dict) else None
            except Exception:
                return None
    return None


def _call_gemini(api_key: str, model: str, system_prompt: str, user_message: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "AMS-Approval-System/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["candidates"][0]["content"]["parts"][0]["text"]


def _call_openai_compatible(api_key: str, model: str, provider: str, base_url: str, system_prompt: str, user_message: str) -> str:
    if not base_url:
        if provider == "groq":
            base_url = "https://api.groq.com/openai/v1"
        else:
            base_url = "https://api.openai.com/v1"
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "AMS-Approval-System/1.0",
    }
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        # Fallback for Groq if requested model is unavailable
        if provider == "groq" and e.code == 404 and model != "openai/gpt-oss-120b":
            payload["model"] = "openai/gpt-oss-120b"
            req_fb = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req_fb, timeout=20) as resp_fb:
                body_fb = json.loads(resp_fb.read().decode("utf-8"))
            return body_fb["choices"][0]["message"]["content"]
        raise


def interpret_chat_with_project_llm(db, user: dict, message: str, config: dict) -> dict:
    """Route chat through configured project-tuned LLM, falling back cleanly to local NLP."""
    if not config.get("configured"):
        parsed = parse_chat_command(message)
        parsed["_engine"] = "local_nlp"
        return parsed

    system_prompt = build_project_system_prompt(db, user)
    try:
        provider = config["provider"]
        if provider == "gemini":
            raw = _call_gemini(config["api_key"], config["model"], system_prompt, message)
        else:
            raw = _call_openai_compatible(
                config["api_key"], config["model"], provider, config.get("base_url", ""), system_prompt, message
            )
        parsed = _extract_json_object(raw)
        if parsed and parsed.get("intent"):
            parsed["_engine"] = f"{provider}:{config['model']}"
            return parsed
        return {
            "intent": "policy_qa",
            "reply": raw.strip() or "I could not parse a structured action from that response.",
            "_engine": f"{provider}:{config['model']}",
        }
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, IndexError, TimeoutError, Exception) as exc:
        fallback = parse_chat_command(message)
        fallback["_engine"] = "local_nlp_fallback"
        fallback["_llm_error"] = str(exc)
        return fallback


def generate_finetune_dataset(db, fmt: str = "openai") -> list[dict]:
    """Generate project-specific fine-tuning examples from live policies, workflows, and requests."""
    system_msg = (
        "You are the AI assistant for the Approval Management System. "
        "Output structured JSON intents grounded in company approval policies, RBAC roles, and multi-level workflows."
    )
    examples = [
        (
            "Submit an expense report for $160 for team sprint lunch",
            {"intent": "submit_request", "request_type": "expense_report", "title": "Team sprint lunch", "description": "Team sprint lunch", "amount": 160, "currency": "USD", "urgency": "normal", "reply": "Submitting expense report for $160."},
        ),
        (
            "I need 2 days of annual leave for a family event",
            {"intent": "submit_request", "request_type": "leave_request", "title": "Annual leave 2 days", "description": "2 days annual leave for a family event", "amount": 2, "currency": "USD", "urgency": "normal", "reply": "Submitting 2-day leave request."},
        ),
        (
            "Create an urgent purchase order for $1400 for developer monitors",
            {"intent": "submit_request", "request_type": "purchase_order", "title": "Developer monitors PO", "description": "Urgent purchase order for developer monitors", "amount": 1400, "currency": "USD", "urgency": "high", "reply": "Submitting urgent purchase order for $1400."},
        ),
        (
            "Check status of request #31",
            {"intent": "check_status", "request_id": 31, "reply": "Looking up status for request #31."},
        ),
        (
            "What is in my pending approval queue?",
            {"intent": "list_pending", "reply": "Checking your pending approval tasks."},
        ),
        (
            "Approve request 31 because the travel receipt matches policy",
            {"intent": "approve_request", "request_id": 31, "comment": "Travel receipt matches policy", "reply": "Approving request #31."},
        ),
        (
            "Reject request 32 because invoice is missing",
            {"intent": "reject_request", "request_id": 32, "comment": "Invoice is missing", "reply": "Rejecting request #32."},
        ),
    ]

    for pol in db.execute("SELECT * FROM policies WHERE is_active = 1").fetchall():
        examples.append((
            f"What is the auto-approval limit and max limit for {pol['request_type']}?",
            {
                "intent": "policy_qa",
                "reply": (
                    f"{pol['name']} ({pol['request_type']}) auto-approves low-risk requests up to {pol['auto_approve_max_amount']}, "
                    f"requires supporting attachments above {pol['require_attachment_above']}, and caps requests at {pol['max_allowed_amount']}."
                ),
            },
        ))

    for wf in db.execute("SELECT * FROM workflows WHERE is_active = 1").fetchall():
        stages = json.loads(wf["stages_json"])
        stage_names = " -> ".join(f"{s['name']} ({s['role']})" for s in stages)
        examples.append((
            f"How does the approval workflow work for {wf['request_type']}?",
            {
                "intent": "policy_qa",
                "reply": f"{wf['name']} runs in {wf['execution_mode']} mode with SLA {wf['sla_hours']}h across stages: {stage_names}.",
            },
        ))

    records = []
    for user_text, assistant_obj in examples:
        assistant_json = json.dumps(assistant_obj)
        if fmt == "gemini":
            records.append({"text_input": f"{system_msg}\nUser: {user_text}", "output": assistant_json})
        else:
            records.append({
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": assistant_json},
                ]
            })
    return records
