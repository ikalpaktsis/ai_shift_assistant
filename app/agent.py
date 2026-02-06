import json
from typing import Any, Dict, List, Optional

from .llm import LLMClient
from .memory import load_memory as load_memory_store
from .memory import save_memory as save_memory_store
from .memory import update_memory
from .prompts import ORCHESTRATOR_SYSTEM_PROMPT
from .tools import (
    TOOL_SCHEMAS,
    analyze_tickets,
    classify_tickets,
    create_action_list,
    detect_persistent_sites,
    generate_summary,
    load_memory,
    save_memory,
    send_email,
)


class ShiftOrchestratorAgent:
    def __init__(
        self,
        llm: LLMClient,
        memory_path: str,
        followup_hours: float = 8.0,
        sla_hours: float = 24.0,
        max_steps: int = 10,
    ):
        self.llm = llm
        self.memory_path = memory_path
        self.followup_hours = followup_hours
        self.sla_hours = sla_hours
        self.max_steps = max_steps
        self.tool_schemas = TOOL_SCHEMAS

    def _parse_args(self, raw_args: Any) -> Dict[str, Any]:
        if raw_args is None:
            return {}
        if isinstance(raw_args, dict):
            return raw_args
        if isinstance(raw_args, str):
            try:
                return json.loads(raw_args)
            except Exception:
                return {}
        return {}

    def _normalize_srs(self, srs: Any) -> List[Dict[str, Any]]:
        if not srs:
            return []
        if isinstance(srs, list):
            normalized = []
            for sr in srs:
                if hasattr(sr, "model_dump"):
                    normalized.append(sr.model_dump())
                elif isinstance(sr, dict):
                    normalized.append(sr)
            return normalized
        raise ValueError("srs must be a list of dicts")

    def _execute_tool(self, name: str, args: Dict[str, Any], state: Dict[str, Any]):
        if name == "analyze_tickets":
            srs = args.get("srs") or state["srs"]
            result = analyze_tickets(srs)
            state["stats"] = result
            return result

        if name == "classify_tickets":
            srs = args.get("srs") or state["srs"]
            followup_hours = args.get("followup_hours", self.followup_hours)
            sla_hours = args.get("sla_hours", self.sla_hours)
            result = classify_tickets(srs, followup_hours=followup_hours, sla_hours=sla_hours)
            state["classifications"] = result
            return result

        if name == "detect_persistent_sites":
            srs = args.get("srs") or state["srs"]
            memory = args.get("memory") or state.get("memory", {})
            min_recurrence = args.get("min_recurrence", 2)
            result = detect_persistent_sites(srs, memory, min_recurrence=min_recurrence)
            state["persistent_sites"] = result
            return result

        if name == "create_action_list":
            classifications = args.get("classifications") or state.get("classifications", {})
            srs = args.get("srs") or state["srs"]
            result = create_action_list(classifications, srs)
            state["action_list"] = result
            return result

        if name == "generate_summary":
            stats = args.get("stats") or state.get("stats", {})
            classifications = args.get("classifications") or state.get("classifications", {})
            persistent_sites = args.get("persistent_sites") or state.get("persistent_sites", {})
            action_list = args.get("action_list") or state.get("action_list", {})
            shift_id = args.get("shift_id") or state.get("shift_id")
            result = generate_summary(
                stats,
                classifications,
                persistent_sites,
                action_list,
                shift_id,
                self.llm,
            )
            state["summary"] = result.get("summary")
            return result

        if name == "send_email":
            report = args.get("report") or state.get("report", {})
            to = args.get("to")
            subject = args.get("subject")
            smtp_settings = args.get("smtp_settings") or {}
            result = send_email(report, to, subject, smtp_settings)
            state["email"] = result
            return result

        if name == "save_memory":
            memory = args.get("memory") or state.get("memory")
            memory_path = args.get("memory_path") or self.memory_path
            result = save_memory(memory_path, memory)
            return result

        if name == "load_memory":
            memory_path = args.get("memory_path") or self.memory_path
            result = load_memory(memory_path)
            state["memory"] = result.get("memory", {})
            return result

        return {"error": f"Unknown tool: {name}"}

    def run(
        self,
        srs: List[Dict[str, Any]],
        shift_id: Optional[str] = None,
        notify_email: bool = False,
        email_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        srs = self._normalize_srs(srs)
        memory = load_memory_store(self.memory_path)
        state: Dict[str, Any] = {
            "srs": srs,
            "shift_id": shift_id,
            "memory": memory,
            "stats": None,
            "classifications": None,
            "persistent_sites": None,
            "action_list": None,
            "summary": None,
            "email": None,
        }

        if not srs:
            report = {
                "shift_id": shift_id,
                "summary": "No SRs provided for this shift.",
                "stats": {"total": 0, "open": 0},
                "classifications": {
                    "open_issues": [],
                    "follow_up_required": [],
                    "escalations": [],
                    "recurrent": [],
                },
                "actions": [{"action": "No actions required.", "priority": "low"}],
                "persistent_sites": [],
            }
            updated_memory = update_memory(
                memory,
                report,
                report["classifications"],
                report["persistent_sites"],
                report["stats"],
            )
            memory_saved = save_memory_store(self.memory_path, updated_memory)
            return {**report, "email": None, "memory_updated": bool(memory_saved)}

        messages = [
            {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "shift_id": shift_id,
                        "srs_count": len(srs),
                        "memory_stats": memory.get("stats", {}),
                        "available_state": [
                            "stats",
                            "classifications",
                            "persistent_sites",
                            "action_list",
                            "summary",
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ]

        for _ in range(self.max_steps):
            if (
                state.get("stats")
                and state.get("classifications")
                and state.get("persistent_sites")
                and state.get("action_list")
                and state.get("summary")
            ):
                break

            response = self.llm.chat(messages, tools=self.tool_schemas, tool_choice="auto")
            tool_calls = response.get("tool_calls") or []
            if not tool_calls:
                content = (response.get("content") or "").strip()
                if content and not state.get("summary"):
                    state["summary"] = content
                break

            assistant_message = {
                "role": "assistant",
                "content": response.get("content"),
                "tool_calls": [],
            }
            for call in tool_calls:
                assistant_message["tool_calls"].append(
                    {
                        "id": call.get("id"),
                        "type": "function",
                        "function": {
                            "name": call.get("name"),
                            "arguments": call.get("arguments"),
                        },
                    }
                )
            messages.append(assistant_message)

            for call in tool_calls:
                args = self._parse_args(call.get("arguments"))
                name = call.get("name")
                tool_call_id = call.get("id")
                result = self._execute_tool(name, args, state)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        if not state.get("stats"):
            state["stats"] = analyze_tickets(srs)
        if not state.get("classifications"):
            state["classifications"] = classify_tickets(
                srs, followup_hours=self.followup_hours, sla_hours=self.sla_hours
            )
        if not state.get("persistent_sites"):
            state["persistent_sites"] = detect_persistent_sites(srs, memory)
        if not state.get("action_list"):
            state["action_list"] = create_action_list(state["classifications"], srs)
        if not state.get("summary"):
            state["summary"] = generate_summary(
                state["stats"],
                state["classifications"],
                state["persistent_sites"],
                state["action_list"],
                shift_id,
                self.llm,
            ).get("summary")

        report = {
            "shift_id": shift_id,
            "summary": state.get("summary", ""),
            "stats": state.get("stats", {}),
            "classifications": state.get("classifications", {}),
            "actions": state.get("action_list", {}).get("actions", []),
            "persistent_sites": state.get("persistent_sites", {}).get("persistent_sites", []),
        }
        state["report"] = report

        updated_memory = update_memory(
            memory,
            report,
            state.get("classifications", {}),
            state.get("persistent_sites", {}).get("persistent_sites", []),
            state.get("stats", {}),
        )
        memory_saved = save_memory_store(self.memory_path, updated_memory)

        email_result = None
        if notify_email or email_to:
            email_result = send_email(report, email_to, None, {})

        return {
            **report,
            "email": email_result,
            "memory_updated": bool(memory_saved),
        }
