"""Browser smoke test against the built UI, with deterministic API responses.

Run experiment-ui's npm run build first, then execute this script with Python.
No LLM calls or real studies are started.
"""
import copy
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    root = Path(__file__).resolve().parents[1]
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root / "experiment-ui" / "dist")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    state = {
        "run_id": "browser-check", "status": "running", "phase": "agents", "current": 0, "total": 2,
        "message": "Running agents", "start_url": "https://example.com",
        "participants": [
            dict(id=0, name="Persona 1", status="running", steps=2, max_steps=5, persona="Test persona", message="Choosing next action"),
            dict(id=1, name="Persona 2", status="queued", steps=0, max_steps=5, persona="Second persona"),
        ],
    }
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            errors = []
            context.on("weberror", lambda error: errors.append(str(error.error)))
            context.route("**/progress?*", lambda route: route.fulfill(json=copy.deepcopy(state)))
            context.route("**/progress", lambda route: route.fulfill(json=copy.deepcopy(state)))
            context.route("**/run", lambda route: route.fulfill(status=202, json={"run_id": "browser-check", "status": "running"}))
            page = context.new_page()
            page.goto(base + "/?step=3")
            with page.expect_popup() as popup_info:
                page.get_by_role("button", name="Confirm and Run").click()
            popup = popup_info.value
            popup.wait_for_url("**/*run_id=browser-check")
            popup.get_by_text("2 / 5", exact=True).wait_for()
            popup.get_by_text("Persona 2", exact=True).wait_for()
            state["participants"][0]["steps"] = 4
            popup.get_by_text("4 / 5", exact=True).wait_for(timeout=5000)
            popup.reload()
            popup.get_by_text("4 / 5", exact=True).wait_for()
            popup.set_viewport_size({"width": 390, "height": 844})
            assert popup.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            state["status"] = "completed_with_errors"
            state["participants"][0]["status"] = "completed"
            state["participants"][1].update(status="error", error="Browser failed")
            popup.get_by_text("실행 종료 · 일부 오류", exact=True).wait_for(timeout=5000)
            popup.get_by_text("Browser failed", exact=True).wait_for()
            output = root / "output"
            output.mkdir(exist_ok=True)
            popup.screenshot(path=str(output / "progress-mobile.png"), full_page=True)
            popup.set_viewport_size({"width": 1200, "height": 850})
            popup.screenshot(path=str(output / "progress-desktop.png"), full_page=True)
            # A blocked popup must leave a usable link in the original window.
            page.reload()
            page.evaluate("window.open = () => null")
            page.get_by_role("button", name="Confirm and Run").click()
            page.get_by_role("link", name="페르소나별 진행 상황 열기 ↗").wait_for()
            page.get_by_text("새 창이 차단되었습니다.", exact=False).wait_for()
            # Failed submissions must not announce a successfully created study.
            page.reload()
            context.unroute("**/run")
            context.route("**/run", lambda route: route.fulfill(status=500, json={"error": "Test failure"}))
            page.evaluate("window.open = () => null")
            page.get_by_role("button", name="Confirm and Run").click()
            page.get_by_text("실행 실패", exact=True).wait_for()
            assert page.get_by_text("Study Successfully Created!", exact=True).count() == 0
            assert not errors, errors
            browser.close()
        print("PASS: popup, live updates, reload, mobile layout, terminal errors, blocked popup, failed submission")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
