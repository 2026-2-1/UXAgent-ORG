import copy
import os
import threading
import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from werkzeug.exceptions import BadRequest
from .run import run

app = Flask(__name__)
PHASE_LABELS = {"personas": "Generating personas", "agents": "Running agents", "surveys": "Filling surveys"}
runs = {}
state_lock = threading.RLock()
latest_run_id = None


def now():
    return datetime.now(timezone.utc).isoformat()


def log_progress(run_id, event):
    with state_lock:
        state = runs[run_id]
        state["updated_at"] = now()
        if "participant_id" in event:
            participant = state["participants"][event["participant_id"]]
            participant.update({k: v for k, v in event.items() if k != "participant_id"})
            participant["updated_at"] = state["updated_at"]
        else:
            phase = event.get("phase")
            if phase in PHASE_LABELS:
                state.update(phase=phase, label=PHASE_LABELS[phase])
                state["current"] = event.get("current", 0)
                state["total"] = event.get("total", state["total"])
                state["message"] = f'{state["label"]}: {state["current"]}/{state["total"]}'


def execute_run(run_id, payload):
    try:
        run(**payload, on_progress=lambda event: log_progress(run_id, event))
        with state_lock:
            state = runs[run_id]
            failed = any(p["status"] == "error" for p in state["participants"])
            state.update(status="completed_with_errors" if failed else "completed", message="Run finished", finished_at=now())
    except Exception as exc:
        app.logger.exception("Run %s failed", run_id)
        with state_lock:
            runs[run_id].update(status="error", error=str(exc), message=str(exc), finished_at=now())
            for participant in runs[run_id]["participants"]:
                if participant["status"] not in ("completed", "error"):
                    participant.update(status="error", error="Run stopped: " + str(exc))


@app.post("/run")
def run_endpoint():
    global latest_run_id
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise BadRequest("Expected application/json object")
    required = ["total_personas", "demographics", "general_intent", "start_url", "max_steps", "questionnaire"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise BadRequest(f"Missing required fields: {', '.join(missing)}")
    try:
        arguments = {key: payload[key] for key in required}
        for key, default in (("total_personas", 1), ("max_steps", 50), ("concurrency", 4)):
            arguments[key] = int(payload.get(key, default))
            if arguments[key] < 1:
                raise ValueError(f"{key} must be positive")
        arguments.update(headless=bool(payload.get("headless", True)), example_persona=payload.get("example_persona"))
    except (ValueError, TypeError) as exc:
        raise BadRequest(str(exc)) from exc
    with state_lock:
        if latest_run_id and runs[latest_run_id]["status"] == "running":
            return jsonify(error="A study is already running", run_id=latest_run_id), 409
        run_id = uuid.uuid4().hex
        runs[run_id] = {
            "run_id": run_id, "status": "running", "phase": "personas",
            "label": PHASE_LABELS["personas"], "current": 0, "total": arguments["total_personas"],
            "message": "Starting study", "start_url": arguments["start_url"], "started_at": now(),
            "participants": [
                {"id": i, "name": f"Persona {i + 1}", "status": "generating", "steps": 0,
                 "max_steps": arguments["max_steps"], "persona": "", "error": None}
                for i in range(arguments["total_personas"])
            ],
        }
        latest_run_id = run_id
        threading.Thread(target=execute_run, args=(run_id, arguments), daemon=True).start()
    return jsonify(run_id=run_id, status="running"), 202


@app.get("/progress")
def progress_endpoint():
    with state_lock:
        run_id = request.args.get("run_id") or latest_run_id
        if not run_id:
            result, code = {"status": "idle", "message": "No run started yet.", "participants": []}, 200
        elif run_id not in runs:
            result, code = {"error": "Run not found. The backend may have restarted."}, 404
        else:
            result, code = copy.deepcopy(runs[run_id]), 200
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response, code


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("UXAGENT_API_PORT", "8081")), debug=True, use_reloader=False, threaded=True)
