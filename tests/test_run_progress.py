import asyncio
import importlib
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

api = importlib.import_module("src.simulated_web_agent.main.app")
survey = importlib.import_module("src.simulated_web_agent.main.survey")

PAYLOAD = dict(total_personas=2, demographics=[], general_intent="Test", start_url="https://example.com", max_steps=5, questionnaire={})


class RunProgressTests(unittest.TestCase):
    def setUp(self):
        api.runs.clear()
        api.latest_run_id = None
        self.client = api.app.test_client()

    def create_run(self):
        with patch.object(api.threading, "Thread"):
            response = self.client.post("/run", json=PAYLOAD)
        self.assertEqual(response.status_code, 202)
        return response.json["run_id"]

    def test_progress_is_scoped_and_duplicate_run_is_rejected(self):
        self.assertEqual(self.client.get("/progress").json["status"], "idle")
        run_id = self.create_run()
        api.log_progress(run_id, dict(participant_id=1, status="running", steps=3, url="https://example.com/item"))
        snapshot = self.client.get("/progress", query_string=dict(run_id=run_id))
        self.assertEqual(snapshot.json["participants"][1]["steps"], 3)
        self.assertEqual(snapshot.json["participants"][0]["status"], "generating")
        self.assertEqual(snapshot.headers["Cache-Control"], "no-store")
        self.assertEqual(self.client.post("/run", json=PAYLOAD).status_code, 409)
        self.assertEqual(self.client.get("/progress?run_id=missing").status_code, 404)

    def test_success_failure_and_state_reset(self):
        first = self.create_run()
        with patch.object(api, "run", side_effect=RuntimeError("Model offline")):
            api.execute_run(first, PAYLOAD)
        self.assertEqual(api.runs[first]["status"], "error")
        self.assertTrue(all(p["status"] == "error" for p in api.runs[first]["participants"]))
        second = self.create_run()
        self.assertNotEqual(first, second)
        self.assertEqual(api.runs[second]["participants"][0]["steps"], 0)
        with patch.object(api, "run"):
            api.execute_run(second, PAYLOAD)
        self.assertEqual(api.runs[second]["status"], "completed")
        self.assertEqual(self.client.get(f"/progress?run_id={first}").json["status"], "error")

    def test_partial_errors_are_not_reported_as_success(self):
        run_id = self.create_run()
        api.log_progress(run_id, dict(participant_id=0, status="error", error="Browser failed"))
        with patch.object(api, "run"):
            api.execute_run(run_id, PAYLOAD)
        self.assertEqual(api.runs[run_id]["status"], "completed_with_errors")

    def test_request_returns_while_worker_is_running(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()

        def fake_run(**kwargs):
            started.set()
            release.wait(5)
            finished.set()

        threads = []
        thread_class = threading.Thread

        def make_thread(**kwargs):
            thread = thread_class(**kwargs)
            threads.append(thread)
            return thread

        with patch.object(api, "run", side_effect=fake_run), patch.object(api.threading, "Thread", side_effect=make_thread):
            try:
                response = self.client.post("/run", json=PAYLOAD)
                self.assertEqual(response.status_code, 202)
                self.assertTrue(started.wait(2))
                self.assertFalse(finished.is_set())
                self.assertEqual(self.client.get("/progress").json["status"], "running")
            finally:
                release.set()
                self.assertTrue(finished.wait(2))
                for thread in threads:
                    thread.join(2)

    def test_invalid_request(self):
        for payload in ([], {}, {**PAYLOAD, "max_steps": 0}, {**PAYLOAD, "concurrency": 0}):
            self.assertEqual(self.client.post("/run", json=payload).status_code, 400)


class SurveyProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_participant_identity_is_preserved_when_browser_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memory_trace.json").write_text("[]", encoding="utf-8")
            events, counts = [], []
            with patch.object(survey, "async_chat", new_callable=AsyncMock, return_value='{"ok":true}'):
                await survey.run_survey(
                    [RuntimeError("Browser failed"), root], {},
                    on_participant=events.append, on_progress=lambda k, n: counts.append((k, n)),
                )
            self.assertIn(dict(participant_id=0, status="error", message="Browser task failed; survey skipped"), events)
            self.assertIn(dict(participant_id=1, status="completed", message="Survey completed"), events)
            self.assertEqual(counts[-1], (2, 2))

    async def test_survey_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memory_trace.json").write_text("[]", encoding="utf-8")
            events = []
            with patch.object(survey, "async_chat", new_callable=AsyncMock, side_effect=RuntimeError("Offline")):
                await survey.run_survey([root], {}, on_participant=events.append)
            self.assertEqual(events[-1]["status"], "error")
            self.assertEqual(events[-1]["error"], "Offline")


if __name__ == "__main__":
    unittest.main()
