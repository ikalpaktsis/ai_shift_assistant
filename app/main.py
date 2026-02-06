import os

from fastapi import FastAPI
from dotenv import load_dotenv

from .agent import ShiftOrchestratorAgent
from .llm import LLMClient
from .models import ReportResponse, ShiftRequest

load_dotenv()

app = FastAPI(title="AI Shift Assistant", version="1.0.0")


def build_agent() -> ShiftOrchestratorAgent:
    memory_path = os.getenv("MEMORY_PATH", "data/memory.json")
    followup_hours = float(os.getenv("FOLLOWUP_HOURS", "8"))
    sla_hours = float(os.getenv("SLA_HOURS", "24"))
    max_steps = int(os.getenv("AGENT_MAX_STEPS", "10"))
    llm = LLMClient()
    return ShiftOrchestratorAgent(
        llm=llm,
        memory_path=memory_path,
        followup_hours=followup_hours,
        sla_hours=sla_hours,
        max_steps=max_steps,
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/run-agent", response_model=ReportResponse)
def run_agent(req: ShiftRequest):
    agent = build_agent()
    srs = [sr.model_dump() for sr in req.srs]
    report = agent.run(
        srs,
        shift_id=req.shift_id,
        notify_email=req.notify_email,
        email_to=req.email_to,
    )
    return report
