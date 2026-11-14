"""Local open-source AI/ML & NLP engine (Scikit-learn + NumPy + local NLP).

Zero paid APIs: runs entirely in-process using scikit-learn models trained on
the SQLite historical dataset plus deterministic policy & NLP extraction.
"""

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

from .currency import to_usd

REQUEST_TYPE_MAP = {
    "expense_report": 0,
    "leave_request": 1,
    "purchase_order": 2,
}

URGENCY_MAP = {"low": 0, "normal": 1, "high": 2}

SUSPICIOUS_TERMS = {
    "casino", "crypto", "offshore", "rush cash", "no invoice",
    "unverified", "personal gift", "wire transfer", "bypass",
}


def extract_nlp_metadata(text: str, fallback_type: str | None = None, fallback_amount: float | None = None) -> dict:
    """Extract structured attributes from free-text descriptions (AI-05)."""
    clean = (text or "").strip()
    lower = clean.lower()

    # Detect request type
    detected_type = fallback_type or "expense_report"
    if any(k in lower for k in ("leave", "vacation", "pto", "sick", "day off", "days off", "medical")):
        detected_type = "leave_request"
    elif any(k in lower for k in ("purchase order", "po ", "procure", "vendor", "laptop", "equipment", "stationery", "chairs", "server")):
        detected_type = "purchase_order"
    elif any(k in lower for k in ("expense", "reimburse", "travel", "flight", "hotel", "dinner", "lunch", "taxi", "conference", "receipt")):
        detected_type = "expense_report"

    # Extract amount / days
    currency = "USD"
    if "eur" in lower or "€" in clean:
        currency = "EUR"
    elif "gbp" in lower or "£" in clean:
        currency = "GBP"
    elif "inr" in lower or "₹" in clean or "rs." in lower:
        currency = "INR"

    extracted_amount = fallback_amount
    if extracted_amount is None:
        if detected_type == "leave_request":
            m_days = re.search(r"(\d+(?:\.\d+)?)\s*(?:day|days)", lower)
            if m_days:
                extracted_amount = float(m_days.group(1))
        if extracted_amount is None:
            m_curr = re.search(r"(?:[$€£₹]|usd|eur|gbp|inr)\s*([0-9][0-9,]*(?:\.\d+)?)", lower)
            if m_curr:
                extracted_amount = float(m_curr.group(1).replace(",", ""))
            else:
                m_num = re.search(r"\b([0-9][0-9,]*(?:\.\d+)?)\b", lower)
                if m_num:
                    extracted_amount = float(m_num.group(1).replace(",", ""))

    urgency = "normal"
    if any(k in lower for k in ("urgent", "asap", "immediately", "emergency", "critical", "rush")):
        urgency = "high"
    elif any(k in lower for k in ("whenever", "low priority", "no rush")):
        urgency = "low"

    matched_risk_terms = sorted([term for term in SUSPICIOUS_TERMS if term in lower])
    tokens = [w for w in re.findall(r"[a-zA-Z]{4,}", lower) if w not in {"this", "that", "with", "from", "have", "for", "request"}]

    return {
        "request_type": detected_type,
        "amount": round(float(extracted_amount), 2) if extracted_amount is not None else 0.0,
        "currency": currency,
        "urgency": urgency,
        "risk_terms": matched_risk_terms,
        "keywords": tokens[:8],
    }


def parse_chat_command(message: str) -> dict:
    """Parse chat or voice transcript into an actionable intent (AI-06)."""
    text = (message or "").strip()
    lower = text.lower()

    # Check approval/rejection command
    m_action = re.search(r"\b(approve|reject|deny)\s+(?:request\s*#?|#)?(\d+)\b", lower)
    if m_action:
        verb = m_action.group(1)
        req_id = int(m_action.group(2))
        comment = ""
        m_reason = re.search(r"(?:because|reason|note|comment)\s+(.+)$", text, flags=re.IGNORECASE)
        if m_reason:
            comment = m_reason.group(1).strip()
        return {
            "intent": "approve_request" if verb == "approve" else "reject_request",
            "request_id": req_id,
            "comment": comment or f"Processed via conversational interface ({verb})",
        }

    # Check status lookup
    m_status = re.search(r"\bstatus\s+(?:of\s+)?(?:request\s*#?|#)?(\d+)\b", lower)
    if m_status:
        return {"intent": "check_status", "request_id": int(m_status.group(1))}

    if any(k in lower for k in ("pending", "my approvals", "queue", "to approve", "what needs")):
        return {"intent": "list_pending"}

    if any(k in lower for k in ("my requests", "track my", "list requests")):
        return {"intent": "list_my_requests"}

    # Default to submission if descriptive request keywords or submit verb are present
    if any(k in lower for k in ("submit", "create", "new", "request", "expense", "leave", "purchase", "reimburse", "vacation", "buy")):
        extracted = extract_nlp_metadata(text)
        title = text[:65].strip()
        if len(text) > 65:
            title += "..."
        return {
            "intent": "submit_request",
            "title": title,
            "description": text,
            **extracted,
        }

    return {
        "intent": "help",
        "message": "Try: 'Submit an expense report for $180 for team dinner', 'Check status of request 5', 'Pending approvals', or 'Approve request 31'.",
    }


class LocalAIEngine:
    """Encapsulates Scikit-learn models trained on historical DB records."""

    def __init__(self):
        self.vectorizer = TfidfVectorizer(max_features=80, stop_words="english")
        self.scaler = StandardScaler()
        self.classifier = RandomForestClassifier(n_estimators=25, random_state=42, n_jobs=1)
        self.anomaly_detector = IsolationForest(contamination=0.12, random_state=42, n_jobs=1)
        self.is_trained = False
        self._last_trained_count = 0
        self._last_db_file = None
        self.type_amount_stats: dict[str, tuple[float, float]] = {}

    def _numeric_features(self, rows: list[dict]) -> np.ndarray:
        numeric = []
        for r in rows:
            rtype = REQUEST_TYPE_MAP.get(r.get("request_type", "expense_report"), 0)
            amt = float(r.get("amount") or 0.0)
            urg = URGENCY_MAP.get(r.get("urgency", "normal"), 1)
            desc = f"{r.get('title', '')} {r.get('description', '')}".lower()
            has_risk_term = 1.0 if any(t in desc for t in SUSPICIOUS_TERMS) else 0.0
            numeric.append([rtype, np.log1p(max(amt, 0.0)), urg, has_risk_term])
        return np.array(numeric, dtype=float)

    def _featurize(self, rows: list[dict], fit_vectorizer: bool = False) -> np.ndarray:
        texts = [f"{r.get('title', '')} {r.get('description', '')}" for r in rows]
        if fit_vectorizer:
            tfidf = self.vectorizer.fit_transform(texts).toarray()
        else:
            tfidf = self.vectorizer.transform(texts).toarray()
        return np.hstack([self._numeric_features(rows), tfidf])

    def train_from_db(self, db, force: bool = False, retrain_threshold: int = 10) -> dict:
        db_file = db.execute("PRAGMA database_list").fetchone()[2]
        completed_count = db.execute(
            "SELECT COUNT(*) AS c FROM requests WHERE status IN ('approved', 'rejected')"
        ).fetchone()["c"]

        if (
            not force
            and self.is_trained
            and self._last_db_file == db_file
            and abs(completed_count - self._last_trained_count) < retrain_threshold
        ):
            return {"trained": True, "cached": True, "sample_count": self._last_trained_count}

        rows = [
            dict(r)
            for r in db.execute(
                """
                SELECT request_type, title, description, amount, urgency, status
                FROM requests
                WHERE status IN ('approved', 'rejected')
                ORDER BY id DESC LIMIT 500
                """
            ).fetchall()
        ]
        if len(rows) < 6:
            self.is_trained = False
            return {"trained": False, "sample_count": len(rows)}

        # Compute per-type mean/std for interpretable z-score anomaly explanations
        grouped: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            if r["status"] == "approved":
                grouped[r["request_type"]].append(float(r["amount"] or 0.0))
        self.type_amount_stats = {}
        for rtype, vals in grouped.items():
            arr = np.array(vals, dtype=float)
            self.type_amount_stats[rtype] = (float(np.mean(arr)), max(float(np.std(arr)), 1.0))

        X = self._featurize(rows, fit_vectorizer=True)
        X_num = self.scaler.fit_transform(self._numeric_features(rows))
        y = np.array([1 if r["status"] == "approved" else 0 for r in rows])

        if len(set(y)) >= 2:
            self.classifier.fit(X, y)
            self.anomaly_detector.fit(X_num)
            self.is_trained = True
        else:
            self.anomaly_detector.fit(X_num)
            self.is_trained = False

        self._last_trained_count = completed_count
        self._last_db_file = db_file
        return {"trained": self.is_trained, "cached": False, "sample_count": len(rows)}

    def evaluate_request(self, db, req_data: dict, has_attachment: bool = False) -> dict:
        """Run policy rules, ML decision support, and anomaly detection (AI-01..AI-04, AI-11)."""
        self.train_from_db(db, force=False)

        rtype = req_data.get("request_type", "expense_report")
        amount = float(req_data.get("amount") or 0.0)
        currency = (req_data.get("currency") or "USD").upper()
        amount_usd = to_usd(amount, currency)
        desc = f"{req_data.get('title', '')} {req_data.get('description', '')}".lower()
        nlp_meta = extract_nlp_metadata(desc, fallback_type=rtype, fallback_amount=amount)

        policy_row = db.execute(
            "SELECT * FROM policies WHERE request_type = ? AND is_active = 1 ORDER BY id DESC LIMIT 1",
            (rtype,),
        ).fetchone()
        policy = dict(policy_row) if policy_row else None

        compliance_issues = []
        anomaly_reasons = []
        blocked_hits = []

        if policy:
            blocked_keywords = json.loads(policy.get("blocked_keywords_json") or "[]")
            blocked_hits = [kw for kw in blocked_keywords if kw.lower() in desc]
            if blocked_hits:
                compliance_issues.append(f"Blocked policy keyword(s): {', '.join(blocked_hits)}")
                anomaly_reasons.append(f"Blocked keyword match: {', '.join(blocked_hits)}")

            if amount_usd > float(policy["max_allowed_amount"]):
                compliance_issues.append(
                    f"Amount {amount} {currency} (~${amount_usd:.2f} USD) exceeds policy max ${policy['max_allowed_amount']}"
                )
                anomaly_reasons.append("Exceeds policy maximum limit")

            if amount_usd > float(policy["require_attachment_above"]) and not has_attachment:
                compliance_issues.append(
                    f"Supporting attachment required above ${policy['require_attachment_above']} USD"
                )

        # Statistical outlier check against historical approved baseline
        if rtype in self.type_amount_stats:
            mean_amt, std_amt = self.type_amount_stats[rtype]
            z_score = (amount_usd - mean_amt) / std_amt
            if z_score > 2.5 and amount_usd > mean_amt * 2.5:
                anomaly_reasons.append(
                    f"Amount ({amount:.2f} {currency}) is {z_score:.1f}x std-dev above approved {rtype} average ({mean_amt:.2f} USD)"
                )

        # ML inference
        if self.is_trained:
            X_one = self._featurize([req_data], fit_vectorizer=False)
            X_num_one = self.scaler.transform(self._numeric_features([req_data]))
            proba = self.classifier.predict_proba(X_one)[0]
            approve_prob = float(proba[1]) if len(proba) > 1 else 0.5
            iso_pred = int(self.anomaly_detector.predict(X_num_one)[0])
            iso_raw = float(-self.anomaly_detector.decision_function(X_num_one)[0])
            ml_anomaly_score = float(np.clip(0.5 + iso_raw, 0.0, 1.0))
            if iso_pred == -1:
                anomaly_reasons.append("IsolationForest detected multivariate deviation from historical pattern")
        else:
            approve_prob = 0.75 if not compliance_issues else 0.25
            ml_anomaly_score = 0.8 if anomaly_reasons else 0.15

        if nlp_meta["risk_terms"]:
            for term in nlp_meta["risk_terms"]:
                reason = f"Risk keyword in description: '{term}'"
                if reason not in anomaly_reasons:
                    anomaly_reasons.append(reason)

        is_anomaly = len(anomaly_reasons) > 0 or ml_anomaly_score >= 0.72
        anomaly_score = round(max(ml_anomaly_score, 0.85 if anomaly_reasons else ml_anomaly_score), 3)

        # Combine ML probability + policy/anomaly into risk_score & recommendation
        risk_score = 1.0 - approve_prob
        if blocked_hits or (policy and amount_usd > float(policy["max_allowed_amount"])):
            risk_score = max(risk_score, 0.85)
        elif compliance_issues:
            risk_score = max(risk_score, 0.55)
        if is_anomaly:
            risk_score = max(risk_score, 0.72)
        risk_score = round(float(np.clip(risk_score, 0.01, 0.99)), 3)

        if risk_score >= 0.75 or blocked_hits:
            recommendation = "reject" if blocked_hits else "review"
        elif risk_score >= 0.4 or compliance_issues:
            recommendation = "review"
        else:
            recommendation = "approve"

        confidence = round(float(np.clip(abs(approve_prob - 0.5) * 2 * 0.5 + 0.5, 0.5, 0.98)), 3)

        auto_approve_eligible = bool(
            policy
            and not is_anomaly
            and not compliance_issues
            and amount_usd <= float(policy["auto_approve_max_amount"])
            and recommendation == "approve"
            and risk_score <= 0.35
        )

        explanation_parts = []
        if auto_approve_eligible:
            curr_str = f" ({amount} {currency} [~${amount_usd:.2f} USD])" if currency != "USD" else f" (${amount})"
            explanation_parts.append(
                f"Eligible for auto-approval (amount{curr_str} <= policy threshold ${policy['auto_approve_max_amount']}, low risk {risk_score})."
            )
        else:
            explanation_parts.append(
                f"AI recommends '{recommendation}' (approval likelihood {approve_prob:.0%}, risk score {risk_score})."
            )
        if compliance_issues:
            explanation_parts.append("Policy checks: " + "; ".join(compliance_issues) + ".")
        else:
            explanation_parts.append("Passes organizational policy rules.")
        if anomaly_reasons:
            explanation_parts.append("Anomaly alerts: " + "; ".join(anomaly_reasons) + ".")

        return {
            "recommendation": recommendation,
            "confidence": confidence,
            "risk_score": risk_score,
            "compliance_status": "violation" if blocked_hits else ("warning" if compliance_issues else "compliant"),
            "compliance_issues": compliance_issues,
            "is_anomaly": is_anomaly,
            "anomaly_score": anomaly_score,
            "anomaly_reasons": anomaly_reasons,
            "auto_approve_eligible": auto_approve_eligible,
            "nlp_extracted": nlp_meta,
            "explanation": " ".join(explanation_parts),
        }


def predict_bottlenecks_and_forecast(db) -> dict:
    """Predict approval bottlenecks and forecast request volume (AI-07, AI-08)."""
    # 1. Stage/role latency and pending queue bottlenecks
    stage_rows = db.execute(
        """
        SELECT stage_name, assigned_role, status, created_at, decided_at, due_at
        FROM approval_tasks
        """
    ).fetchall()

    role_stats: dict[str, dict] = defaultdict(lambda: {"pending": 0, "overdue": 0, "latencies": []})
    now = datetime.now(timezone.utc)
    for row in stage_rows:
        role = row["assigned_role"]
        if row["status"] in ("pending", "waiting"):
            role_stats[role]["pending"] += 1
            if row["due_at"]:
                due = datetime.fromisoformat(row["due_at"])
                if due < now:
                    role_stats[role]["overdue"] += 1
        elif row["decided_at"] and row["created_at"]:
            delta_h = (
                datetime.fromisoformat(row["decided_at"]) - datetime.fromisoformat(row["created_at"])
            ).total_seconds() / 3600.0
            role_stats[role]["latencies"].append(max(delta_h, 0.0))

    # Also inspect historical approvals cycle times by approver role
    hist_rows = db.execute(
        """
        SELECT u.role, a.cycle_time_hours
        FROM approvals a
        JOIN users u ON u.id = a.approver_id
        WHERE a.decision != 'auto_approved'
        """
    ).fetchall()
    for hr in hist_rows:
        role_stats[hr["role"]]["latencies"].append(float(hr["cycle_time_hours"] or 0.0))

    bottlenecks = []
    for role, st in role_stats.items():
        avg_h = round(float(np.mean(st["latencies"])) if st["latencies"] else 12.0, 2)
        delay_risk = min(0.95, round(0.15 + (avg_h / 48.0) * 0.45 + st["overdue"] * 0.2 + st["pending"] * 0.05, 2))
        bottlenecks.append({
            "role": role,
            "pending_tasks": st["pending"],
            "overdue_tasks": st["overdue"],
            "avg_cycle_hours": avg_h,
            "delay_risk_score": delay_risk,
            "status": "high_risk" if delay_risk >= 0.6 else ("moderate" if delay_risk >= 0.35 else "healthy"),
        })
    bottlenecks.sort(key=lambda x: x["delay_risk_score"], reverse=True)

    # 2. Request volume forecasting using LinearRegression over daily buckets
    req_rows = db.execute("SELECT created_at FROM requests ORDER BY created_at ASC").fetchall()
    daily_counts: dict[str, int] = defaultdict(int)
    for r in req_rows:
        day_key = r["created_at"][:10]
        daily_counts[day_key] += 1

    sorted_days = sorted(daily_counts.keys())
    forecast_series = []
    from datetime import date, timedelta
    last_date_str = sorted_days[-1] if sorted_days else date.today().isoformat()
    try:
        last_d = date.fromisoformat(last_date_str)
    except Exception:
        last_d = date.today()

    if len(sorted_days) >= 3:
        y_vals = np.array([daily_counts[d] for d in sorted_days], dtype=float)
        x_vals = np.arange(len(y_vals)).reshape(-1, 1)
        reg = LinearRegression().fit(x_vals, y_vals)
        slope = float(reg.coef_[0])
        future_x = np.arange(len(y_vals), len(y_vals) + 7).reshape(-1, 1)
        next_7_preds = np.clip(reg.predict(future_x), 0.5, None)
        next_7_total = int(round(float(np.sum(next_7_preds))))
        trend = "increasing" if slope > 0.03 else ("decreasing" if slope < -0.03 else "stable")
        for i, pred_val in enumerate(next_7_preds):
            d_next = (last_d + timedelta(days=i + 1)).isoformat()
            forecast_series.append({"date": d_next, "count": max(1, int(round(float(pred_val))))})
    else:
        next_7_total = max(len(req_rows), 7)
        trend = "stable"
        avg_daily = max(1, int(round(next_7_total / 7.0)))
        for i in range(7):
            d_next = (last_d + timedelta(days=i + 1)).isoformat()
            forecast_series.append({"date": d_next, "count": avg_daily})

    return {
        "bottlenecks": bottlenecks,
        "volume_forecast": {
            "historical_days_observed": len(sorted_days),
            "predicted_next_7_days_requests": next_7_total,
            "predicted_next_30_days_requests": int(round(next_7_total * (30.0 / 7.0))),
            "trend": trend,
            "daily_series": [{"date": d, "count": daily_counts[d]} for d in sorted_days[-14:]],
            "forecast_series": forecast_series,
        },
    }


def analyze_workflows_and_rules(db) -> dict:
    """Identify workflow inefficiencies & propose dynamic rule adjustments (AI-09, AI-10, AI-12)."""
    recommendations = []
    rule_proposals = []

    workflows = [dict(w) for w in db.execute("SELECT * FROM workflows WHERE is_active = 1").fetchall()]
    for wf in workflows:
        stages = json.loads(wf["stages_json"])
        if wf["execution_mode"] == "sequential" and len(stages) >= 2:
            avg_row = db.execute(
                """
                SELECT AVG(a.cycle_time_hours) AS avg_h, COUNT(*) AS cnt
                FROM approvals a
                JOIN requests r ON r.id = a.request_id
                WHERE r.workflow_id = ? AND a.decision != 'auto_approved'
                """,
                (wf["id"],),
            ).fetchone()
            avg_h = float(avg_row["avg_h"] or 0.0)
            if avg_h > 18.0:
                recommendations.append({
                    "workflow_id": wf["id"],
                    "workflow_name": wf["name"],
                    "finding": f"Sequential workflow averages {avg_h:.1f}h per manual approval.",
                    "recommendation": "Switch non-dependent stages to parallel execution to cut cycle time.",
                    "estimated_time_savings_pct": 35,
                })

    policies = [dict(p) for p in db.execute("SELECT * FROM policies WHERE is_active = 1").fetchall()]
    for pol in policies:
        rtype = pol["request_type"]
        current_auto = float(pol["auto_approve_max_amount"])
        # Look at approved vs rejected requests just above current auto-approve limit (up to 1.8x)
        upper_band = max(current_auto * 1.8, current_auto + 100.0)
        band_rows = db.execute(
            """
            SELECT status, amount FROM requests
            WHERE request_type = ? AND amount > ? AND amount <= ? AND status IN ('approved', 'rejected')
            """,
            (rtype, current_auto, upper_band),
        ).fetchall()

        if len(band_rows) >= 2:
            approved_cnt = sum(1 for r in band_rows if r["status"] == "approved")
            approval_rate = approved_cnt / len(band_rows)
            if approval_rate >= 0.90 and pol["dynamic_adjustment_enabled"]:
                suggested = round(min(upper_band, current_auto * 1.35), 2)
                rule_proposals.append({
                    "policy_id": pol["id"],
                    "policy_name": pol["name"],
                    "request_type": rtype,
                    "current_auto_approve_max": current_auto,
                    "suggested_auto_approve_max": suggested,
                    "rationale": f"{approved_cnt}/{len(band_rows)} historical requests in ({current_auto}, {upper_band:.0f}] were approved with 0 rejections.",
                })
        elif current_auto > 0:
            # Check if there were rejections below current threshold
            bad_rows = db.execute(
                """
                SELECT COUNT(*) AS c FROM requests
                WHERE request_type = ? AND amount <= ? AND status = 'rejected'
                """,
                (rtype, current_auto),
            ).fetchone()
            if bad_rows["c"] > 0 and pol["dynamic_adjustment_enabled"]:
                suggested = round(current_auto * 0.75, 2)
                rule_proposals.append({
                    "policy_id": pol["id"],
                    "policy_name": pol["name"],
                    "request_type": rtype,
                    "current_auto_approve_max": current_auto,
                    "suggested_auto_approve_max": suggested,
                    "rationale": f"Detected {bad_rows['c']} rejected request(s) below current threshold; tightening ceiling recommended.",
                })

    return {
        "workflow_optimizations": recommendations,
        "dynamic_rule_proposals": rule_proposals,
    }


ai_engine = LocalAIEngine()
