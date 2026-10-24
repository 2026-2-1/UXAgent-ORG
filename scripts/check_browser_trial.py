"""Run one real participant with the saved Decathlon persona, without changing UI defaults."""

import argparse
import asyncio
import json
import logging
import traceback
from pathlib import Path

from litellm.litellm_core_utils.logging_worker import GLOBAL_LOGGING_WORKER

from src.simulated_web_agent.agent import gpt
from src.simulated_web_agent.main.experiment import _load_cfg, _run_for_persona_and_intent


async def check(max_steps=3, deadline=600):
    cfg = _load_cfg()
    cfg.environment.browser.user_data_dir = None
    cfg.environment.browser.cache_dir = "runs/local-ui/trial-browser-cache"
    cfg.environment.browser.launch_options.headless = True
    gpt.configure(cfg)
    if gpt.provider != "local" or gpt.embedding_provider != "local":
        raise RuntimeError("This trial requires local chat and local embeddings")
    preset = json.loads(Path("experiment-ui/src/presets/decathlon-hiking.json").read_text(encoding="utf-8"))["form"]
    report = {
        "participants": 1, "max_steps": max_steps, "status": "started",
        "start_url": preset["experiment"]["startUrl"],
        "scope": "real browser, real Qwen chat, real Qwen embeddings",
    }
    print("Starting trial: " + json.dumps(report), flush=True)
    try:
        trace = await asyncio.wait_for(_run_for_persona_and_intent(
            cfg=cfg,
            persona_info={"persona": preset["persona"]["examplePersona"], "intent": preset["persona"]["generalIntent"]},
            start_url=report["start_url"], max_steps=max_steps,
        ), timeout=deadline)
        report["trace_dir"] = str(trace)
        if (trace / "error.txt").exists():
            report["status"] = "failed"
            report["error"] = (trace / "error.txt").read_text(encoding="utf-8")
        else:
            actions = json.loads((trace / "action_trace.json").read_text(encoding="utf-8"))
            memories = json.loads((trace / "memory_trace.json").read_text(encoding="utf-8"))
            report["action_count"] = len(actions)
            report["memory_count"] = len(memories)
            report["status"] = "passed" if 0 < len(actions) <= max_steps and memories else "failed"
    except Exception:
        report["status"] = "failed"
        report["error"] = traceback.format_exc()
    finally:
        path = Path("runs/local-ui/one-participant-trial.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("TRIAL RESULT: " + json.dumps(report, ensure_ascii=True), flush=True)
        await asyncio.sleep(1)
        await GLOBAL_LOGGING_WORKER.stop()
    if report["status"] != "passed":
        raise RuntimeError("Trial failed; see runs/local-ui/one-participant-trial.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-steps", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--deadline", type=int, default=600)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    logging.getLogger("LiteLLM Router").setLevel(logging.WARNING)
    asyncio.run(check(args.max_steps, args.deadline))
