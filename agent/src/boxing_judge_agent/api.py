from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from .agent import BoxingJudgeAgent
from .errors import AgentError
from .rag.ingest import rebuild_index
from .schemas import ConfirmRequest, MessageRequest, SessionStatus


app = FastAPI(title="拳击评判员 Agent", version="0.1.0")
PACKAGE_DIR = Path(__file__).resolve().parent


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(PACKAGE_DIR / "frontend.html", media_type="text/html")


@app.get("/assets/app.css", include_in_schema=False)
def frontend_styles() -> FileResponse:
    return FileResponse(PACKAGE_DIR / "frontend.css", media_type="text/css")


@app.get("/assets/app.js", include_in_schema=False)
def frontend_script() -> FileResponse:
    return FileResponse(PACKAGE_DIR / "frontend.js", media_type="text/javascript")


def service() -> BoxingJudgeAgent:
    return BoxingJudgeAgent()


@app.exception_handler(AgentError)
async def agent_error_handler(_: Request, exc: AgentError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sessions")
def create_session(csv: UploadFile = File(...), question: str | None = Form(default=None)) -> dict:
    agent = service()
    suffix = ".csv" if not csv.filename else (".csv" if csv.filename.lower().endswith(".csv") else ".upload")
    destination = agent.store.uploads / f"{uuid.uuid4()}{suffix}"
    with destination.open("wb") as output:
        shutil.copyfileobj(csv.file, output)
    session = agent.create_session(destination, question)
    return {
        "session": session.model_dump(mode="json", exclude={"batch_analysis", "report"}),
        "choices": ["add_supplement", "skip_supplement"],
        "missing_context": session.missing_context,
    }


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    session = service().get_session(session_id)
    return {"session": session.model_dump(mode="json", exclude={"batch_analysis"})}


@app.get("/sessions/{session_id}/progress")
def get_session_progress(session_id: str) -> dict:
    session = service().get_session(session_id)
    return {
        "session_id": session.session_id,
        "status": session.status,
        "progress": [event.model_dump(mode="json") for event in session.progress_events],
        "updated_at": session.updated_at,
        "finished": session.status in {SessionStatus.COMPLETE, SessionStatus.LLM_UNAVAILABLE},
    }


@app.post("/sessions/{session_id}/messages")
def post_message(session_id: str, request: MessageRequest) -> dict:
    return service().add_message(session_id, request.message)


@app.post("/sessions/{session_id}/confirm")
def confirm(session_id: str, request: ConfirmRequest) -> dict:
    return service().confirm(session_id, request.action)


@app.get("/sessions/{session_id}/report")
def get_report(session_id: str, format: str = "json"):
    report = service().get_report(session_id)
    if format == "markdown":
        return PlainTextResponse(report["report_markdown"], media_type="text/markdown; charset=utf-8")
    return report


@app.get("/sessions/{session_id}/events/{event_id}")
def get_event(session_id: str, event_id: str) -> dict:
    return service().get_event(session_id, event_id)


@app.post("/rag/rebuild")
def rebuild_rag() -> dict:
    agent = service()
    return rebuild_index(agent.settings.knowledge_base, agent.store.indexes / "rules.json", settings=agent.settings)
