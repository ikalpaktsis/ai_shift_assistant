import json
import os
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from .memory import load_memory as _load_memory
from .memory import save_memory as _save_memory
from .prompts import SUMMARY_SYSTEM_PROMPT


CLOSED_STATUSES = {"closed", "resolved", "done", "completed", "cancelled"}
HIGH_PRIORITIES = {"p1", "p2", "critical", "high", "urgent"}


def _norm(text: Optional[str]) -> str:
    return (text or "").strip().lower()


def _is_closed(status: Optional[str]) -> bool:
    return _norm(status) in CLOSED_STATUSES


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _ticket_reason(sr: Dict[str, Any]) -> str:
    status = _norm(sr.get("status"))
    text = " ".join([
        _norm(sr.get("title")),
        _norm(sr.get("description")),
        _norm(sr.get("notes")),
    ])
    if "pending" in status or "waiting" in status:
        return "Pending response"
    if "vendor" in text:
        return "Pending vendor"
    if "customer" in text:
        return "Pending customer"
    if "waiting" in text or "await" in text:
        return "Waiting action"
    return "Needs follow-up"


def analyze_tickets(srs: List[Dict[str, Any]]) -> Dict[str, Any]:
    status_counts: Dict[str, int] = {}
    priority_counts: Dict[str, int] = {}
    open_count = 0
    age_values = []

    for sr in srs:
        status = _norm(sr.get("status")) or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        if not _is_closed(status):
            open_count += 1

        priority = _norm(sr.get("priority")) or "unknown"
        priority_counts[priority] = priority_counts.get(priority, 0) + 1

        age = sr.get("age_hours")
        if isinstance(age, (int, float)):
            age_values.append(float(age))

    avg_age = round(sum(age_values) / len(age_values), 2) if age_values else 0.0

    return {
        "total": len(srs),
        "open": open_count,
        "status_counts": status_counts,
        "priority_counts": priority_counts,
        "avg_age_hours": avg_age,
    }


def classify_tickets(
    srs: List[Dict[str, Any]],
    followup_hours: float = 8.0,
    sla_hours: float = 24.0,
) -> Dict[str, Any]:
    open_issues = []
    follow_up = []
    escalations = []
    recurrent = []

    now = datetime.now(timezone.utc)

    for sr in srs:
        sr_id = sr.get("id") or sr.get("sr_id")
        status = sr.get("status")
        priority = _norm(sr.get("priority"))
        last_update = _parse_datetime(sr.get("last_update"))
        escalation_flag = bool(sr.get("escalation_flag"))

        if not _is_closed(status):
            open_issues.append({
                "id": sr_id,
                "title": sr.get("title"),
                "status": status,
            })

        stale = False
        if last_update:
            hours_since = (now - last_update).total_seconds() / 3600.0
            if hours_since >= followup_hours:
                stale = True
        else:
            hours_since = None

        needs_followup = (
            (not _is_closed(status))
            and (stale or "pending" in _norm(status) or "waiting" in _norm(status))
        )

        if needs_followup:
            follow_up.append({
                "id": sr_id,
                "title": sr.get("title"),
                "status": status,
                "hours_since_update": hours_since,
                "reason": _ticket_reason(sr),
            })

        escalation_text = " ".join([
            _norm(sr.get("title")),
            _norm(sr.get("description")),
            _norm(sr.get("notes")),
        ])
        sla_risk = False
        if last_update:
            hours_since = (now - last_update).total_seconds() / 3600.0
            if hours_since >= sla_hours:
                sla_risk = True

        if (
            escalation_flag
            or priority in HIGH_PRIORITIES
            or "sla" in escalation_text
            or "breach" in escalation_text
            or "escalat" in escalation_text
            or sla_risk
        ):
            escalations.append({
                "id": sr_id,
                "title": sr.get("title"),
                "priority": sr.get("priority"),
                "reason": "SLA risk or high priority",
            })

        if sr.get("reopen_count"):
            recurrent.append({
                "id": sr_id,
                "title": sr.get("title"),
                "reason": "Repeated reopen",
            })

    return {
        "open_issues": open_issues,
        "follow_up_required": follow_up,
        "escalations": escalations,
        "recurrent": recurrent,
    }


def detect_persistent_sites(
    srs: List[Dict[str, Any]],
    memory: Dict[str, Any],
    min_recurrence: int = 2,
) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for sr in srs:
        site = sr.get("site") or sr.get("node")
        if not site:
            continue
        site_key = str(site).strip()
        if not site_key:
            continue
        counts[site_key] = counts.get(site_key, 0) + 1

    persistent = []
    memory_counts = memory.get("recurring_sites", {}) if memory else {}
    for site, count in counts.items():
        historical = int(memory_counts.get(site, 0))
        if count >= min_recurrence or historical >= min_recurrence:
            persistent.append(site)

    return {"persistent_sites": sorted(set(persistent)), "current_counts": counts}


def create_action_list(
    classifications: Dict[str, Any], srs: List[Dict[str, Any]]
) -> Dict[str, Any]:
    actions = []

    for esc in classifications.get("escalations", []):
        actions.append(
            {
                "action": f"Escalate SR {esc.get('id')} to L2/management",
                "sr_id": esc.get("id"),
                "priority": esc.get("priority") or "high",
            }
        )

    for fu in classifications.get("follow_up_required", []):
        actions.append(
            {
                "action": f"Follow up on SR {fu.get('id')}: {fu.get('reason')}",
                "sr_id": fu.get("id"),
                "priority": "medium",
            }
        )

    if not actions:
        actions.append({"action": "No critical actions detected.", "priority": "low"})

    return {"actions": actions}


def generate_summary(
    stats: Dict[str, Any],
    classifications: Dict[str, Any],
    persistent_sites: Any,
    action_list: Dict[str, Any],
    shift_id: Optional[str],
    llm,
) -> Dict[str, Any]:
    if isinstance(persistent_sites, list):
        persistent_sites = {"persistent_sites": persistent_sites}
    elif not isinstance(persistent_sites, dict):
        persistent_sites = {}

    payload = {
        "shift_id": shift_id,
        "stats": stats,
        "open": len(classifications.get("open_issues", [])),
        "follow_up": len(classifications.get("follow_up_required", [])),
        "escalations": len(classifications.get("escalations", [])),
        "persistent_sites": persistent_sites.get("persistent_sites", []),
        "actions": action_list.get("actions", []),
    }

    try:
        summary = llm.generate_text(
            SUMMARY_SYSTEM_PROMPT,
            "Summarize shift data:\n" + json.dumps(payload, ensure_ascii=False, indent=2),
        )
        summary = summary.strip()
        if summary:
            return {"summary": summary}
    except Exception:
        pass

    fallback = (
        f"Shift {shift_id or ''} summary: {stats.get('total', 0)} SRs handled, "
        f"{stats.get('open', 0)} open, {len(classifications.get('escalations', []))} escalations."
    ).strip()
    return {"summary": fallback}


def send_email(report: Dict[str, Any], to: Optional[str], subject: Optional[str], smtp_settings: Dict[str, Any]) -> Dict[str, Any]:
    host = smtp_settings.get("SMTP_HOST") or os.getenv("SMTP_HOST")
    port = int(smtp_settings.get("SMTP_PORT") or os.getenv("SMTP_PORT", "587"))
    user = smtp_settings.get("SMTP_USER") or os.getenv("SMTP_USER")
    password = smtp_settings.get("SMTP_PASSWORD") or os.getenv("SMTP_PASSWORD")
    sender = smtp_settings.get("SMTP_FROM") or os.getenv("SMTP_FROM")
    recipient = to or smtp_settings.get("SMTP_TO") or os.getenv("SMTP_TO")

    if not host or not sender or not recipient:
        return {
            "sent": False,
            "message": "SMTP settings missing; email not sent.",
            "to": recipient,
        }

    subject = subject or f"Shift Summary - {report.get('shift_id') or datetime.utcnow().date()}"
    body_lines = [
        report.get("summary", ""),
        "",
        "Actions:",
    ]
    for action in report.get("actions", []):
        body_lines.append(f"- {action.get('action')}")

    msg = MIMEText("\n".join(body_lines), _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.sendmail(sender, [recipient], msg.as_string())
        return {"sent": True, "message": "Email sent.", "to": recipient}
    except Exception as exc:
        return {"sent": False, "message": f"Email failed: {exc}", "to": recipient}


def save_memory(memory_path: str, memory: Dict[str, Any]) -> Dict[str, Any]:
    saved = _save_memory(memory_path, memory)
    return {"saved": saved, "path": memory_path}


def load_memory(memory_path: str) -> Dict[str, Any]:
    memory = _load_memory(memory_path)
    return {"memory": memory}


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "analyze_tickets",
            "description": "Analyze SRs and return stats (total, open, status counts, priority counts).",
            "parameters": {
                "type": "object",
                "properties": {"srs": {"type": "array", "items": {"type": "object"}}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_tickets",
            "description": "Classify SRs into open, follow-up, escalations, recurrent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "srs": {"type": "array", "items": {"type": "object"}},
                    "followup_hours": {"type": "number"},
                    "sla_hours": {"type": "number"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_persistent_sites",
            "description": "Detect persistent sites/nodes based on current SRs and past memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "srs": {"type": "array", "items": {"type": "object"}},
                    "memory": {"type": "object"},
                    "min_recurrence": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_action_list",
            "description": "Create an actionable task list from classifications.",
            "parameters": {
                "type": "object",
                "properties": {
                    "classifications": {"type": "object"},
                    "srs": {"type": "array", "items": {"type": "object"}},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_summary",
            "description": "Generate a human-readable shift summary using the LLM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "stats": {"type": "object"},
                    "classifications": {"type": "object"},
                    "persistent_sites": {
                        "anyOf": [
                            {"type": "object"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                    "action_list": {"type": "object"},
                    "shift_id": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send shift report by email if SMTP settings are configured.",
            "parameters": {
                "type": "object",
                "properties": {
                    "report": {"type": "object"},
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "smtp_settings": {"type": "object"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Persist agent memory to disk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_path": {"type": "string"},
                    "memory": {"type": "object"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_memory",
            "description": "Load agent memory from disk.",
            "parameters": {
                "type": "object",
                "properties": {"memory_path": {"type": "string"}},
                "required": [],
            },
        },
    },
]


