"""FastAPI backend. The agent runs in a background thread; the UI follows it over SSE and decides on drafts."""
from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

from .. import tracing
from ..env import load_env
from ..agent.graph import build_agent
from ..agent.session import Session
from ..agent.tools import _case_view, build_tools
from ..llm import CacheMiss, make_model
from ..schemas import AgentEventType, CaseStatus
from ..triage.memory import Memory

ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Settings:
    fixtures: Path = ROOT / "fixtures"
    data: Path = ROOT / "data"           # persistent: sqlite memory, AGENTS.md lessons, checkpoints, uploads
    cases: Path = ROOT / "cases"
    today: date = date(2026, 11, 14)     # fixed so the offline demo is reproducible
    model_factory: Callable | None = None


@dataclass
class Run:
    id: str
    session: Session
    agent: object
    config: dict
    status: str = "running"              # running | waiting_approval | done | error
    pending_case: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class StartRun(BaseModel):
    fixture: str | None = None           # a file name inside fixtures/
    upload_id: str | None = None


class Decision(BaseModel):
    decision: Literal["approve", "edit", "skip"]
    body: str | None = None              # required for edit


class OutcomeIn(BaseModel):
    result: Literal["won", "lost", "pending"]
    recovered_cents: int = 0
    lesson: str = ""


def create_app(settings: Settings | None = None) -> FastAPI:
    load_env()
    trace_note = tracing.ensure_consistent()
    cfg = settings or Settings()
    cfg.data.mkdir(parents=True, exist_ok=True)
    (cfg.data / "uploads").mkdir(exist_ok=True)
    memory = Memory(cfg.data / "reclaim.db")   # shared across runs: this is the persistent memory
    runs: dict[str, Run] = {}
    app = FastAPI(title="Reclaim")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                       allow_methods=["*"], allow_headers=["*"])

    def get_run(run_id: str) -> Run:
        if run_id not in runs:
            raise HTTPException(404, "unknown run")
        return runs[run_id]

    def drive(run: Run, payload) -> None:
        """Run or resume the agent until it finishes or pauses for the owner. Never raises.
        Streams graph updates so the UI sees the plan, todo changes and subagent hand-offs live."""
        s = run.session
        interrupt, last_text = None, ""
        try:
            for chunk in run.agent.stream(payload, run.config, stream_mode="updates"):
                for node, upd in chunk.items():
                    if node == "__interrupt__":
                        interrupt = upd[0].value
                        continue
                    msgs = upd.get("messages") if isinstance(upd, dict) else None
                    for m in (msgs if isinstance(msgs, list) else []):
                        last_text = _emit_agent_events(s, m) or last_text
            if interrupt:
                req = interrupt["action_requests"][0]
                run.pending_case = req["args"]["case_id"]
                s.emit(AgentEventType.INTERRUPT, {"case_id": run.pending_case, "tool": req["name"],
                                                  "message": "Waiting for the owner to approve, edit or skip."})
                run.status = "waiting_approval"   # status flips after its event is visible
            else:
                run.pending_case = None
                s.emit(AgentEventType.DONE, {"summary": last_text})
                run.status = "done"
        except CacheMiss as e:
            s.emit(AgentEventType.ERROR, {"kind": "cache_miss", "message": str(e)})
            run.status = "error"
        except Exception as e:  # surfaced to the UI's designed error state, never swallowed
            s.emit(AgentEventType.ERROR, {"kind": type(e).__name__, "message": str(e)[:500]})
            run.status = "error"

    def start_thread(run: Run, payload) -> None:
        run.status = "running"
        threading.Thread(target=drive, args=(run, payload), daemon=True).start()

    @app.get("/api/health")
    def health():
        mode = "scripted" if cfg.model_factory is not None else (
            os.getenv("RECLAIM_LLM_MODE") or ("auto" if os.getenv("ANTHROPIC_API_KEY") else "replay"))
        return {"ok": True, "llm_mode": mode, "tracing": tracing.status(trace_note)}

    @app.get("/api/fixtures")
    def fixtures():
        """Synthetic sample payouts, labelled. samples.json supplies names; any other *_payout.csv is listed plainly."""
        idx = cfg.fixtures / "samples.json"
        listed = json.loads(idx.read_text()) if idx.exists() else []
        known = {x["file"] for x in listed}
        extra = [{"file": p.name, "label": p.stem, "platform": "", "note": "synthetic"}
                 for p in sorted(cfg.fixtures.glob("*_payout.csv")) if p.name not in known]
        return [x for x in listed + extra if (cfg.fixtures / x["file"]).exists()]

    @app.post("/api/uploads")
    async def upload(file: UploadFile = File(...)):
        uid = uuid.uuid4().hex[:12]
        (cfg.data / "uploads" / f"{uid}.csv").write_bytes(await file.read())
        return {"upload_id": uid}

    @app.post("/api/runs", status_code=202)
    def start(req: StartRun):
        if req.upload_id:
            path = cfg.data / "uploads" / f"{Path(req.upload_id).name}.csv"
        elif req.fixture:
            path = cfg.fixtures / Path(req.fixture).name   # name only: no path traversal
        else:
            raise HTTPException(422, "give a fixture name or an upload_id")
        if not path.exists():
            raise HTTPException(404, "payout file not found")
        run_id = uuid.uuid4().hex[:10]
        session = Session(cfg.cases / run_id, cfg.fixtures / "tickets.json", cfg.today, memory=memory,
                          memory_dir=cfg.data / "memory")
        model = cfg.model_factory() if cfg.model_factory else make_model(cfg.fixtures / "llm_cache")
        agent = build_agent(session, model, cfg.data / "checkpoints.db")
        mode = "scripted" if cfg.model_factory is not None else getattr(model, "mode", "live")
        run = Run(run_id, session, agent, {"configurable": {"thread_id": run_id}, "recursion_limit": 100,
                                           **tracing.run_config(run_id, mode, "upload" if req.upload_id else "synthetic-sample")})
        runs[run_id] = run
        start_thread(run, {"messages": [("user", f"Process the payout file at {path}.")]})
        return {"run_id": run_id}

    @app.get("/api/runs/{run_id}")
    def run_state(run_id: str):
        r = get_run(run_id)
        return {"run_id": r.id, "status": r.status, "pending_case": r.pending_case,
                "hero": r.session.hero().model_dump(mode="json")}

    @app.get("/api/runs/{run_id}/events.json")
    def events_json(run_id: str, after: int = 0):
        evs = get_run(run_id).session.events_since(after)
        return [{"id": after + i + 1, **e.model_dump(mode="json")} for i, e in enumerate(evs)]

    @app.get("/api/runs/{run_id}/events")
    async def events_sse(run_id: str, after: int = 0):
        r = get_run(run_id)

        async def gen():
            i = after
            while True:
                for e in r.session.events_since(i):
                    i += 1
                    yield f"id: {i}\ndata: {json.dumps(e.model_dump(mode='json'))}\n\n"
                if r.status in ("done", "error") and not r.session.events_since(i):
                    yield "event: end\ndata: {}\n\n"
                    return
                await asyncio.sleep(0.15)
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @app.get("/api/runs/{run_id}/cases")
    def cases(run_id: str):
        s = get_run(run_id).session
        return {"hero": s.hero().model_dump(mode="json"),
                "cases": [{**_case_view(c), "rank": i + 1} for i, c in enumerate(s.ranked())]}

    @app.get("/api/runs/{run_id}/cases/{case_id}")
    def case_detail(run_id: str, case_id: str):
        s = get_run(run_id).session
        if case_id not in s.cases:
            raise HTTPException(404, "unknown case")
        d = s.disputes.get(case_id)
        t = s.tickets.get(s.cases[case_id].deduction.order_id)
        return {**_case_view(s.cases[case_id]), "draft": d.body if d else None,
                "cited_evidence_ids": d.cited_evidence_ids if d else [],
                "ticket": {"order_id": t.order_id, "items": t.items,
                           "image_url": f"/api/tickets/{t.order_id}.png"} if t and t.image_path else None}

    @app.get("/api/tickets/{name}")
    def ticket_image(name: str):
        p = cfg.fixtures / "tickets" / Path(name).name
        if not p.exists():
            raise HTTPException(404, "no ticket image")
        return FileResponse(p)

    @app.post("/api/runs/{run_id}/cases/{case_id}/decision", status_code=202)
    def decide(run_id: str, case_id: str, dec: Decision):
        r = get_run(run_id)
        s = r.session
        with r.lock:
            if r.status != "waiting_approval" or r.pending_case != case_id:
                raise HTTPException(409, "this case is not waiting for a decision")
            if dec.decision == "skip":
                s.skip(case_id)
                payload = Command(resume={"decisions": [{"type": "reject", "message": "The owner chose to skip this case."}]})
            else:
                if dec.decision == "edit":
                    if not dec.body:
                        raise HTTPException(422, "edit needs the new text")
                    errors = s.save_draft(case_id, dec.body, s.disputes[case_id].cited_evidence_ids)
                    if errors:
                        raise HTTPException(422, {"errors": errors})   # edits face the same checks as the agent's drafts
                s.approve(case_id)
                payload = Command(resume={"decisions": [{"type": "approve"}]})
            start_thread(r, payload)
        return {"ok": True}

    @app.post("/api/runs/{run_id}/cases/{case_id}/outcome")
    def outcome(run_id: str, case_id: str, o: OutcomeIn):
        s = get_run(run_id).session
        if case_id not in s.cases:
            raise HTTPException(404, "unknown case")
        res = json.loads(build_tools(s)["record_outcome"].invoke(
            {"case_id": case_id, "result": o.result, "recovered_cents": o.recovered_cents, "lesson": o.lesson}))
        return res

    @app.get("/api/memory")
    def memory_view():
        lessons = cfg.data / "memory" / "AGENTS.md"
        return {"outcomes": memory.count(), "lessons": lessons.read_text() if lessons.exists() else ""}

    return app


def _emit_agent_events(s: Session, m) -> str:
    """Turn the deep agent's own tool calls (planning and delegation) into UI events. Returns final prose, if any."""
    calls = getattr(m, "tool_calls", None) or []
    for c in calls:
        if c["name"] == "write_todos":
            s.emit(AgentEventType.PLAN, {"todos": [{"content": t.get("content", ""), "status": t.get("status", "pending")}
                                                   for t in c["args"].get("todos", [])]})
        elif c["name"] == "task":
            s.emit(AgentEventType.SUBAGENT, {"agent": c["args"].get("subagent_type"), "state": "started",
                                             "task": str(c["args"].get("description", ""))[:200]})
    if getattr(m, "type", "") == "tool" and getattr(m, "name", "") == "task":
        s.emit(AgentEventType.SUBAGENT, {"state": "finished", "result": str(m.content)[:300]})
    if getattr(m, "type", "") == "ai" and not calls and isinstance(m.content, str):
        return m.content
    return ""

