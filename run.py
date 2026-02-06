import argparse
import json
import os
from dotenv import load_dotenv

from app.agent import ShiftOrchestratorAgent
from app.llm import LLMClient


def load_srs(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "srs" in data:
        return data["srs"], data.get("shift_id")
    if isinstance(data, list):
        return data, None
    raise ValueError("Input JSON must be a list of SRs or an object with 'srs'.")


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run AI Shift Assistant agent.")
    parser.add_argument("--input", required=True, help="Path to SRs JSON file")
    parser.add_argument("--shift-id", help="Shift identifier")
    parser.add_argument("--email-to", help="Email recipient override")
    parser.add_argument("--notify-email", action="store_true", help="Send email")
    args = parser.parse_args()

    srs, shift_from_file = load_srs(args.input)
    shift_id = args.shift_id or shift_from_file

    llm = LLMClient()
    agent = ShiftOrchestratorAgent(
        llm=llm,
        memory_path=os.getenv("MEMORY_PATH", "data/memory.json"),
        followup_hours=float(os.getenv("FOLLOWUP_HOURS", "8")),
        sla_hours=float(os.getenv("SLA_HOURS", "24")),
        max_steps=int(os.getenv("AGENT_MAX_STEPS", "10")),
    )

    report = agent.run(
        srs,
        shift_id=shift_id,
        notify_email=args.notify_email,
        email_to=args.email_to,
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
