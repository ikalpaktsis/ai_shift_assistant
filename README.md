# AI Shift Assistant (Agentic)

An autonomous shift orchestration agent for NMC environments. It ingests SRs, reasons with an LLM, selects tools dynamically, produces a structured handover report, and stores memory across shifts.

## Features
- Agentic reasoning with tool calling
- Ticket analysis and classification
- Persistent site detection using memory
- Action list generation
- LLM-generated shift summary
- Optional email notification via SMTP
- FastAPI endpoint for automation

## Setup
1. Create a virtual environment and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in values.

## Configuration
- `OPENAI_API_KEY`: required
- `OPENAI_MODEL`: model name (default `gpt-4.1-mini`)
- `OPENAI_TEMPERATURE`: sampling temperature
- `MEMORY_PATH`: path to JSON memory
- `FOLLOWUP_HOURS`: threshold for follow-up classification
- `SLA_HOURS`: threshold for SLA risk classification
- `AGENT_MAX_STEPS`: max agent reasoning steps

## Run API
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### POST `/run-agent`
Request body:
```json
{
  "shift_id": "2026-02-06-23:00",
  "notify_email": false,
  "srs": [
    {
      "id": "SR-10234",
      "title": "Fiber cut",
      "status": "Open",
      "priority": "High",
      "last_update": "2026-02-06T20:10:00Z",
      "site": "Athens POP",
      "escalation_flag": true
    }
  ]
}
```

Response (example):
```json
{
  "shift_id": "2026-02-06-23:00",
  "summary": "...",
  "stats": {"total": 1, "open": 1},
  "classifications": {"open_issues": [], "follow_up_required": [], "escalations": []},
  "actions": [],
  "persistent_sites": [],
  "email": null,
  "memory_updated": true
}
```

## Run CLI
```bash
python run.py --input data/srs.json --shift-id 2026-02-06-23:00
```

Input file can be either a list of SRs or:
```json
{
  "shift_id": "2026-02-06-23:00",
  "srs": [ ... ]
}
```

## Notes
- The agent requires `OPENAI_API_KEY` and a valid model.
- Memory is stored in `data/memory.json` by default.
- Email sending requires SMTP settings in `.env`.
