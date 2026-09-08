"""Operator web UI for the PLVA agent demo. Loopback only.

Serves a single-file page (``ui.html``) plus a small JSON API over the shared ``RunState``.
Everything the page receives comes from ``RunState.public_view`` and is value-free unless the
local operator explicitly asks for ``reveal=1``. Request bodies are never logged.

Run:  uv run python -m plva_agent_demo.ui --port 18600   then open http://127.0.0.1:18600
"""

from __future__ import annotations

import argparse
import importlib
import ipaddress
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .state import RunConfig, RunState
from .types import DEFAULT_POLICY

ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = Path(__file__).with_name("ui.html")
TEST_PAGE_PATH = ROOT / "test-pages" / "account.html"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18600
ALLOWED_SCHEMES = frozenset({"http", "https", "file"})
LEVELS = frozenset({"hide_use", "approval", "blocked"})
MAX_TASK_CHARS = 4000
MAX_STEPS_LIMIT = 100
NO_STORE = {"Cache-Control": "no-store"}


class RequestError(ValueError):
    """Client-side validation failure. The message never echoes submitted values."""


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status, headers=NO_STORE)


def _load_runner() -> Any | None:
    """Import the lead's runner lazily so the UI still serves when it is missing."""
    try:
        return importlib.import_module(".runner", __package__)
    except ImportError:
        return None


def is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def build_run_config(body: Any) -> RunConfig:
    """Validate a POST /api/run body and turn it into a RunConfig. Raises RequestError."""
    if not isinstance(body, dict):
        raise RequestError("body must be a JSON object")

    url = body.get("url")
    if not isinstance(url, str) or not url.strip():
        raise RequestError("url is required")
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise RequestError("url must use http, https or file")
    if parts.scheme != "file" and not parts.netloc:
        raise RequestError("url must include a host")

    task = body.get("task")
    if not isinstance(task, str) or not task.strip():
        raise RequestError("task must be a non-empty string")
    task = task.strip()
    if len(task) > MAX_TASK_CHARS:
        raise RequestError(f"task must be at most {MAX_TASK_CHARS} characters")

    policy: dict[str, Any] = dict(DEFAULT_POLICY)
    raw_policy = body.get("policy")
    if raw_policy is not None:
        if not isinstance(raw_policy, dict):
            raise RequestError("policy must be an object of class -> level")
        for key, level in raw_policy.items():
            if key not in DEFAULT_POLICY:
                raise RequestError(f"unknown policy class: {key}")
            if level not in LEVELS:
                raise RequestError(f"invalid level for {key}; expected one of {sorted(LEVELS)}")
            policy[key] = level

    model = body.get("model", "")
    if model is None:
        model = ""
    if not isinstance(model, str):
        raise RequestError("model must be a string")

    max_steps = body.get("max_steps", RunConfig().max_steps)
    if isinstance(max_steps, bool) or not isinstance(max_steps, int):
        raise RequestError("max_steps must be an integer")
    if not 1 <= max_steps <= MAX_STEPS_LIMIT:
        raise RequestError(f"max_steps must be between 1 and {MAX_STEPS_LIMIT}")

    plva_enabled = body.get("plva_enabled", True)
    if not isinstance(plva_enabled, bool):
        raise RequestError("plva_enabled must be a boolean")

    return RunConfig(
        url=url,
        task=task,
        policy=policy,
        model=model.strip(),
        max_steps=max_steps,
        plva_enabled=plva_enabled,
    )


def create_ui_app(state: RunState) -> FastAPI:
    app = FastAPI(title="PLVA agent demo UI", docs_url=None, redoc_url=None, openapi_url=None)
    start_lock = threading.Lock()

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"), headers=NO_STORE)

    @app.get("/api/frame/{step}")
    def api_frame(step: int) -> JSONResponse:
        """Both frames for one step. Fetched by the page only when the step changes."""
        view = state.public_view(reveal_values=False, include_images=True)
        for record in view["steps"]:
            if record["step"] == step:
                body = {
                    "step": step,
                    "frame_sha256": record["frame_sha256"],
                    "redacted_png": record["redacted_png"],
                    "raw_png": record["raw_png"],
                }
                return JSONResponse(body, headers={"Cache-Control": "no-store"})
        return JSONResponse(
            {"error": "no such step"}, status_code=404, headers={"Cache-Control": "no-store"}
        )

    @app.get("/api/state")
    def api_state(since: int = -1, reveal: int = 0, images: int = 1) -> JSONResponse:
        if since == state.version:
            return JSONResponse({"version": state.version, "unchanged": True}, headers=NO_STORE)
        view = state.public_view(reveal_values=reveal == 1, include_images=images != 0)
        return JSONResponse(view, headers=NO_STORE)

    @app.post("/api/run")
    async def api_run(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except ValueError:
            return _error(400, "body must be valid JSON")
        try:
            config = build_run_config(body)
        except RequestError as exc:
            return _error(400, str(exc))

        runner = _load_runner()
        if runner is None:
            return _error(503, "runner not available")

        with start_lock:
            if state.status == "running":
                return _error(409, "a run is already in progress")
            state.reset(config)
            state.set_status("running")
            try:
                runner.start_run(state, config)
            except Exception as exc:  # surface any runner start failure as a failed run
                state.set_status("failed", f"runner failed to start: {type(exc).__name__}")
                return _error(500, "runner failed to start")
        return JSONResponse({"ok": True, "version": state.version}, headers=NO_STORE)

    @app.post("/api/stop")
    def api_stop() -> JSONResponse:
        runner = _load_runner()
        if runner is None:
            return _error(503, "runner not available")
        runner.stop_run(state)
        return JSONResponse({"ok": True, "status": state.status}, headers=NO_STORE)

    @app.get("/api/policy")
    def api_policy() -> JSONResponse:
        return JSONResponse(dict(DEFAULT_POLICY), headers=NO_STORE)

    @app.get("/api/test-page", response_class=HTMLResponse)
    def api_test_page() -> Response:
        if not TEST_PAGE_PATH.is_file():
            return _error(404, "test page not found")
        return HTMLResponse(TEST_PAGE_PATH.read_text(encoding="utf-8"), headers=NO_STORE)

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="plva-agent-demo-ui", description="Operator UI for the PLVA agent demo (loopback)."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="loopback address to bind")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    if not is_loopback_host(args.host):
        parser.error("--host must be a loopback address (127.0.0.1, ::1 or localhost)")

    import uvicorn

    state = RunState()
    app = create_ui_app(state)
    print(f"[ui] http://{args.host}:{args.port}  (loopback only; synthetic values only)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
