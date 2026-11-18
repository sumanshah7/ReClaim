"""FastAPI backend. The agent runs in a background thread; the UI follows it over SSE and decides on drafts."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Literal

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

from .. import tracing
from ..env import load_env
from ..agent.graph import build_agent
from ..agent.session import Session
from ..agent.tools import _case_view, build_tools
from ..ingest.normalize import load_payout as parse_payout
from ..codewatch import PACKAGE_DIR, CodeWatch
from .. import runlog
from ..llm import USAGE, CacheMiss, MissingApiKey, make_model, require_api_key, resolved_mode
from ..photon.bridge import DEMO_OWNER, Bridge, DecisionRejected, WebhookTransport
from ..schemas import AgentEventType, CaseStatus
from ..triage.memory import Memory, signature_of
from ..triage.scoring import BASE_BP, blended_base

MAX_UPLOAD = 2 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Settings:
    fixtures: Path = ROOT / "fixtures"
    data: Path = Path(os.getenv("RECLAIM_DATA_DIR") or ROOT / "data")   # sqlite memory, lessons, checkpoints, uploads
    cases: Path = Path(os.getenv("RECLAIM_CASES_DIR") or ROOT / "cases")
    today: date = date(2026, 11, 14)     # fixed so the offline demo is reproducible
    model_factory: Callable | None = None
    # Code-change guard. None = off unless RECLAIM_RESTART_ON_CODE_CHANGE=1 (set by `make api`).
    watch_dirs: list[Path] | None = None
    restart_hook: Callable[[], None] | None = None     # default: re-exec this process so it loads the new code
    watch_interval: float = 1.0
    run_log: Path | None = None        # JSONL run record; default <data>/runs.jsonl (env RECLAIM_RUN_LOG overrides)


CODE_CHANGED_MSG = ("The backend code changed while this run was in progress, so the run was stopped instead of "
                    "continuing on old code. A fresh run is starting on the new code.")


def _reexec() -> None:
    """Replace this process with a fresh one running the same command (same effect as uvicorn --reload)."""
    time.sleep(0.4)                                    # let in-flight responses reach the browser first
    sys.stdout.flush(); sys.stderr.flush()
    os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])


_SECRET = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")


def explain_model_error(e: BaseException) -> tuple[str, str]:
    """A plain-English reason for a failed model call, with any API key redacted. Walks the exception chain because
    LangChain wraps the provider's error."""
    chain, cur = [], e
    while cur is not None and len(chain) < 6:
        chain.append(type(cur).__name__)
        cur = cur.__cause__ or cur.__context__
    names = " ".join(chain)
    if "Authentication" in names or "PermissionDenied" in names:
        kind, msg = "auth", "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in .env. Nothing was sent."
    elif "Timeout" in names:
        kind, msg = "timeout", "The model did not respond in time. Nothing was sent. Start the run again."
    elif "Connection" in names:
        kind, msg = "network", "Could not reach the Anthropic API. Check the network connection. Nothing was sent."
    elif "RateLimit" in names:
        kind, msg = "rate_limit", "The model is rate-limited right now. Wait a moment and start the run again."
    elif "Overloaded" in names or "InternalServer" in names or "ServiceUnavailable" in names:
        kind, msg = "provider", "The model service had a problem. Start the run again in a minute."
    else:
        kind, msg = type(e).__name__, str(e)
    msg = _SECRET.sub("[redacted key]", msg)
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if key:
        msg = msg.replace(key, "[redacted key]")
    return kind, msg[:500]


def _memory_view(s, c) -> dict | None:
    """Why past outcomes moved this case's win probability, from the same inputs scoring uses (no model involved).
    None when there is no resolved history for this claim type."""
    d = c.deduction
    pattern = f"{d.platform.value}:{d.reason.value}"
    sig = signature_of(c.evidence)
    (won, total), scope = s.history(pattern, sig)
    if total == 0:
        return None
    base = BASE_BP[d.reason]
    lessons = []
    if s.lessons_path.exists():
        lessons = [ln[2:].strip() for ln in s.lessons_path.read_text().splitlines() if ln.startswith(f"- {pattern}")]
    return {"claim": d.reason.value.replace("_", " "), "won": won, "total": total, "scope": scope,
            "base_pct": base // 100, "adjusted_pct": blended_base(base, won, total) // 100,
            "similar": s.memory.similar(pattern, sig, d.claimed_item, limit=4), "lessons": lessons[-3:]}


@dataclass
class Run:
    id: str
    session: Session
    agent: object
    config: dict
    status: str = "running"              # running | waiting_approval | done | error | stopped
    pending_case: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    source: dict = field(default_factory=dict)   # what started it (fixture or upload id), to re-launch after a restart
    cancelled: bool = False
    mode: str = ""                       # replay | live | auto | scripted, for the run log
    queue: list = field(default_factory=list)       # cases the paused graph is waiting on (a model may ask to send several at once)
    collected: list = field(default_factory=list)   # the owner's decisions so far for that batch, in queue order


class StartRun(BaseModel):
    fixture: str | None = None           # a file name inside fixtures/
    upload_id: str | None = None


class Decision(BaseModel):
    decision: Literal["approve", "edit", "skip"]
    body: str | None = None              # required for edit


class Inbound(BaseModel):
    sender: str
    text: str


class OutcomeIn(BaseModel):
    result: Literal["won", "lost", "pending"]
    recovered_cents: int = 0
    lesson: str = ""


def create_app(settings: Settings | None = None) -> FastAPI:
    load_env()
    trace_note = tracing.ensure_consistent()
    cfg = settings or Settings()
    if cfg.model_factory is None:
        require_api_key(resolved_mode())   # explicit live/record mode without a key stops here with a clear message
    boot_id = uuid.uuid4().hex[:8]
    cfg.data.mkdir(parents=True, exist_ok=True)
    (cfg.data / "uploads").mkdir(exist_ok=True)
    memory = Memory(cfg.data / "reclaim.db")   # shared across runs: this is the persistent memory
    run_log = cfg.run_log or Path(os.getenv("RECLAIM_RUN_LOG") or cfg.data / "runs.jsonl")
    runs: dict[str, Run] = {}
    replaced: dict[str, str | None] = {}   # runs stopped by a code change in the previous process -> their fresh run
    dirs = cfg.watch_dirs
    if dirs is None and os.getenv("RECLAIM_RESTART_ON_CODE_CHANGE", "").lower() in ("1", "true", "yes"):
        dirs = [Path(p) for p in os.getenv("RECLAIM_WATCH_DIRS", "").split(os.pathsep) if p] or [PACKAGE_DIR]
    watch = CodeWatch(dirs) if dirs else None
    restart_hook = cfg.restart_hook or _reexec
    watch_state = {"handled": False, "last": 0.0}
    watch_lock = threading.Lock()
    hook = os.getenv("PHOTON_BRIDGE_URL")
    bridge = Bridge(transport=WebhookTransport(hook) if hook else Bridge().transport,
                    owner=(os.getenv("OWNER_PHONE") or DEMO_OWNER) if hook else DEMO_OWNER)
    app = FastAPI(title="Reclaim")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                       allow_methods=["*"], allow_headers=["*"])

    def get_run(run_id: str) -> Run:
        if run_id not in runs:
            raise HTTPException(404, "unknown run")
        return runs[run_id]

    def _drive(run: Run, payload) -> None:
        """Run or resume the agent until it finishes or pauses for the owner. Never raises.
        Streams graph updates so the UI sees the plan, todo changes and subagent hand-offs live."""
        s = run.session
        interrupt, last_text = None, ""
        try:
            for chunk in run.agent.stream(payload, run.config, stream_mode="updates"):
                if run.cancelled:      # the code changed: stop here, touch nothing further
                    return
                for node, upd in chunk.items():
                    if node == "__interrupt__":
                        interrupt = upd[0].value
                        continue
                    msgs = upd.get("messages") if isinstance(upd, dict) else None
                    for m in (msgs if isinstance(msgs, list) else []):
                        last_text = _emit_agent_events(s, m) or last_text
            if run.cancelled:
                return
            if interrupt:
                reqs = interrupt["action_requests"]    # normally one; a model can ask to send several in one turn
                run.queue = [r["args"]["case_id"] for r in reqs]
                run.collected = []
                run.pending_case = run.queue[0]
                s.emit(AgentEventType.INTERRUPT, {"case_id": run.pending_case, "tool": reqs[0]["name"],
                                                  "message": "Waiting for the owner to approve, edit or skip."})
                if _set_status(run, "waiting_approval"):   # status flips after its event is visible
                    _notify(run)
            else:
                run.pending_case = None
                s.emit(AgentEventType.DONE, {"summary": last_text})
                if _set_status(run, "done"):
                    _notify_done(run)
        except CacheMiss as e:
            if not run.cancelled:
                s.emit(AgentEventType.ERROR, {"kind": "cache_miss", "message": str(e)})
                _set_status(run, "error")
        except Exception as e:  # surfaced to the UI's designed error state, never swallowed
            if not run.cancelled:
                kind, message = explain_model_error(e)
                s.emit(AgentEventType.ERROR, {"kind": kind, "message": message})
                _set_status(run, "error")

    def drive(run: Run, payload) -> None:
        """_drive plus one structured log record per segment (success, pause, error or stop)."""
        t0, u0, n0 = time.monotonic(), dict(USAGE), len(run.session.events)
        _drive(run, payload)
        resume = getattr(payload, "resume", None)
        err = next((e.payload for e in reversed(run.session.events[n0:]) if e.type == AgentEventType.ERROR), None)
        runlog.log_event(
            run_log, event="segment", run_id=run.id, llm_mode=run.mode,
            input={"kind": "resume" if resume is not None else "start",
                   **({"decisions": [d.get("type") for d in resume.get("decisions", [])]} if resume is not None
                      else {"source": run.source})},
            output={"status": run.status, "pending_case": run.pending_case,
                    "cases_triaged": len(run.session.cases), "drafts": len(run.session.disputes)},
            duration_s=round(time.monotonic() - t0, 3), usage=runlog.usage_delta(u0, dict(USAGE)),
            error=({"kind": err.get("kind"), "message": err.get("message")} if err else None))

    def _set_status(run: Run, status: str) -> bool:
        """Change status unless the run was cancelled meanwhile (a stopped run must stay stopped)."""
        with run.lock:
            if run.cancelled:
                return False
            run.status = status
            return True

    def stop_run(run: Run, reason: str) -> bool:
        with run.lock:
            if run.status not in ("running", "waiting_approval"):
                return False
            run.cancelled = True
            run.status = "stopped"
            stale = run.pending_case
            run.pending_case = None
        run.session.emit(AgentEventType.ERROR, {"kind": "code_changed", "message": reason})
        if stale:
            bridge.decided_elsewhere(run.id, stale)
        return True

    def check_code() -> None:
        """If the source changed since start: stop every active run, remember what to re-launch, and restart."""
        if watch is None:
            return
        with watch_lock:
            now = time.monotonic()
            if watch_state["handled"] or now - watch_state["last"] < 0.3:
                return
            watch_state["last"] = now
            if not watch.changed():
                return
            watch_state["handled"] = True
        active = [r for r in list(runs.values()) if stop_run(r, CODE_CHANGED_MSG)]
        if active:
            (cfg.data / "restart_pending.json").write_text(json.dumps({
                "at": datetime.now().isoformat(timespec="seconds"),
                "runs": [{"old_id": r.id, "source": r.source} for r in active]}))
        threading.Thread(target=restart_hook, daemon=True).start()

    if watch is not None:
        def _watch_loop() -> None:
            while not watch_state["handled"]:
                time.sleep(cfg.watch_interval)
                check_code()
        threading.Thread(target=_watch_loop, daemon=True).start()

    def start_thread(run: Run, payload) -> None:
        run.status = "running"
        threading.Thread(target=drive, args=(run, payload), daemon=True).start()


    def _notify(run: Run) -> None:
        try:
            s = run.session
            bridge.notify(run.id, s.get(run.pending_case), s.disputes[run.pending_case].body)
        except Exception:  # the text channel is optional; the web UI still has the decision
            pass

    def _notify_done(run: Run) -> None:
        try:
            st = [c.status for c in run.session.cases.values()]
            bridge.notify_done(sum(x == CaseStatus.SENT for x in st), sum(x == CaseStatus.SKIPPED for x in st))
        except Exception:
            pass

    def apply_decision(run_id: str, case_id: str, decision: str, body: str | None) -> None:
        """The single approval gate. The web UI and the text bridge both call this; nothing else resumes the graph."""
        if run_id not in runs:
            raise DecisionRejected(404, ["unknown run"])
        r = runs[run_id]
        s = r.session
        with r.lock:
            if r.status == "stopped":
                raise DecisionRejected(409, ["this run was stopped because the code changed; a fresh run is starting"])
            if r.status != "waiting_approval" or r.pending_case != case_id:
                raise DecisionRejected(409, ["this case is not waiting for a decision"])
            if decision == "skip":
                s.skip(case_id)
                entry = {"type": "reject", "message": "The owner chose to skip this case."}
            else:
                if decision == "edit":
                    if not body:
                        raise DecisionRejected(422, ["edit needs the new text"])
                    errors = s.save_draft(case_id, body, s.disputes[case_id].cited_evidence_ids)
                    if errors:
                        raise DecisionRejected(422, errors)   # edits face the same checks as the agent's drafts
                s.approve(case_id)
                entry = {"type": "approve"}
            r.collected.append(entry)
            r.queue = r.queue[1:]
            more = bool(r.queue)
            if more:       # the model asked to send several at once: decide each in turn, send nothing until all are decided
                r.pending_case = r.queue[0]
                s.emit(AgentEventType.INTERRUPT, {"case_id": r.pending_case, "tool": "send_dispute",
                                                  "message": "Waiting for the owner to approve, edit or skip."})
            else:
                decisions, r.collected = r.collected, []
                start_thread(r, Command(resume={"decisions": decisions}))
        bridge.decided_elsewhere(run_id, case_id)
        if more:
            _notify(r)

    def record_outcome_for(run_id: str, case_id: str, result: str, cents: int) -> None:
        s = get_run(run_id).session
        build_tools(s)["record_outcome"].invoke({"case_id": case_id, "result": result, "recovered_cents": cents, "lesson": ""})

    bridge.decide, bridge.outcome = apply_decision, record_outcome_for

    @app.get("/api/health")
    def health():
        mode = "scripted" if cfg.model_factory is not None else (
            os.getenv("RECLAIM_LLM_MODE") or ("auto" if os.getenv("ANTHROPIC_API_KEY") else "replay"))
        return {"ok": True, "llm_mode": mode, "tracing": tracing.status(trace_note), "boot_id": boot_id,
                "code_watch": watch is not None, "api_key": "present" if (os.getenv("ANTHROPIC_API_KEY") or "").strip() else "missing"}

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
        raw = await file.read(MAX_UPLOAD + 1)
        if len(raw) > MAX_UPLOAD:
            runlog.log_event(run_log, event="rejected", input={"upload_bytes": f">{MAX_UPLOAD}"}, status=413,
                             error={"kind": "http_413", "message": "file too large"})
            raise HTTPException(413, "file is too large for a payout report (2 MB limit)")
        uid = uuid.uuid4().hex[:12]
        (cfg.data / "uploads" / f"{uid}.csv").write_bytes(raw)
        return {"upload_id": uid}

    @app.post("/api/runs", status_code=202)
    def start(req: StartRun):
        return {"run_id": launch(req)}

    def launch(req: StartRun) -> str:
        try:
            return _launch(req)
        except HTTPException as e:   # a rejected input leaves a record too
            runlog.log_event(run_log, event="rejected", input=req.model_dump(exclude_none=True), status=e.status_code,
                             error={"kind": "http_%d" % e.status_code, "message": str(e.detail)[:300]})
            raise

    def _launch(req: StartRun) -> str:
        if req.upload_id:
            path = cfg.data / "uploads" / f"{Path(req.upload_id).name}.csv"
            path = _matching_sample(path, cfg.fixtures) or path
        elif req.fixture:
            path = cfg.fixtures / Path(req.fixture).name   # name only: no path traversal
        else:
            raise HTTPException(422, "give a fixture name or an upload_id")
        if not path.exists():
            raise HTTPException(404, "payout file not found")
        try:   # fail fast and free: no model call is spent on a file we cannot read
            parsed = parse_payout(path)
        except Exception as e:
            raise HTTPException(422, f"could not read this payout report: {str(e)[:200]}")
        if not parsed.deductions:
            detail = parsed.errors[0] if parsed.errors else "no refund deductions found"
            raise HTTPException(422, f"no refund deductions found in this report ({detail})")
        run_id = uuid.uuid4().hex[:10]
        try:
            session = Session(cfg.cases / run_id, cfg.fixtures / "tickets.json", cfg.today, memory=memory,
                              memory_dir=cfg.data / "memory")
        except ValueError as e:          # unreadable ticket data: say so instead of a bare 500
            raise HTTPException(503, f"Order ticket data is unavailable: {e}")
        try:
            model = cfg.model_factory() if cfg.model_factory else make_model(Path(os.getenv("RECLAIM_CACHE_DIR") or cfg.fixtures / "llm_cache"))
        except MissingApiKey as e:
            raise HTTPException(503, str(e))
        agent = build_agent(session, model, cfg.data / "checkpoints.db")
        mode = "scripted" if cfg.model_factory is not None else getattr(model, "mode", "live")
        run = Run(run_id, session, agent, {"configurable": {"thread_id": run_id}, "recursion_limit": 100,
                                           **tracing.run_config(run_id, mode, "upload" if req.upload_id else "synthetic-sample")})
        run.source = req.model_dump(exclude_none=True)
        run.mode = mode
        runs[run_id] = run
        start_thread(run, {"messages": [("user", f"Process the payout file at {path}.")]})
        return run_id

    @app.get("/api/runs/{run_id}")
    def run_state(run_id: str):
        check_code()
        if run_id in replaced and run_id not in runs:    # stopped by a code change; the new process knows its successor
            return {"run_id": run_id, "status": "stopped", "pending_case": None, "replaced_by": replaced[run_id],
                    "hero": {"recoverable_cents": 0, "gross_cents": 0, "workable_cases": 0, "next_deadline": None,
                             "next_deadline_days": None}}
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
                if r.status in ("done", "error", "stopped") and not r.session.events_since(i):
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
        return {**_case_view(s.cases[case_id]), "memory": _memory_view(s, s.cases[case_id]), "draft": d.body if d else None,
                "cited_evidence_ids": d.cited_evidence_ids if d else [],
                "ticket": {"order_id": t.order_id, "items": t.items,
                           "image_url": f"/api/tickets/{t.order_id}.png"} if t and t.image_path else None}

    TEXT_EXT = {".md", ".json", ".jsonl", ".txt"}

    def run_dir(run_id: str) -> Path:
        get_run(run_id)
        return (cfg.cases / Path(run_id).name).resolve()

    @app.get("/api/runs/{run_id}/files")
    def run_files(run_id: str):
        """What the agent actually wrote: its plan, per-case evidence notes, drafts, decisions and packets."""
        base = run_dir(run_id)
        files = sorted(p for p in base.rglob("*") if p.is_file() and p.suffix in TEXT_EXT) if base.exists() else []
        return [{"path": str(p.relative_to(base)), "bytes": p.stat().st_size} for p in files[:300]]

    @app.get("/api/runs/{run_id}/files/{path:path}")
    def run_file(run_id: str, path: str):
        base = run_dir(run_id)
        p = (base / path).resolve()
        if base not in p.parents or p.suffix not in TEXT_EXT or not p.is_file():
            raise HTTPException(404, "no such file")
        return {"path": path, "text": p.read_text(errors="replace")[:60_000]}

    @app.get("/api/tickets/{name}")
    def ticket_image(name: str):
        p = cfg.fixtures / "tickets" / Path(name).name
        if not p.is_file():
            raise HTTPException(404, "no ticket image")
        with open(p, "rb") as fh:       # a damaged file must not reach the browser as a broken <img>
            head = fh.read(8)
        if not (head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xff\xd8\xff")):
            raise HTTPException(404, "this ticket image is damaged or not a PNG/JPEG")
        return FileResponse(p)

    @app.post("/api/runs/{run_id}/cases/{case_id}/decision", status_code=202)
    def decide(run_id: str, case_id: str, dec: Decision):
        get_run(run_id)
        try:
            apply_decision(run_id, case_id, dec.decision, dec.body)
        except DecisionRejected as e:
            raise HTTPException(e.status, {"errors": e.errors} if e.status == 422 else e.errors[0])
        return {"ok": True}

    @app.get("/api/photon")
    def photon_state():
        return bridge.snapshot()

    @app.post("/api/photon/inbound")
    def photon_inbound(m: Inbound, x_reclaim_secret: str | None = Header(default=None)):
        """A text from the owner's phone (simulator or a Photon sidecar). Non-owner senders are ignored."""
        secret = os.getenv("PHOTON_INBOUND_SECRET")
        if secret and x_reclaim_secret != secret:
            raise HTTPException(401, "bad secret")
        return {"reply": bridge.handle_inbound(m.sender, m.text)}

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
        return {"outcomes": memory.resolved_count(), "pending": memory.count() - memory.resolved_count(), "lessons": lessons.read_text() if lessons.exists() else ""}

    marker = cfg.data / "restart_pending.json"
    if marker.exists():     # the previous process stopped these runs because the code changed: start them fresh
        try:
            info = json.loads(marker.read_text())
        except ValueError:
            info = {"runs": []}
        marker.unlink(missing_ok=True)
        for item in info.get("runs", []):
            try:
                replaced[item["old_id"]] = launch(StartRun(**item["source"]))
            except Exception:                        # noqa: BLE001 - the old run stays "stopped" with no successor
                replaced[item["old_id"]] = None

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



def _matching_sample(upload: Path, fixtures: Path) -> Path | None:
    """If an uploaded report is byte-identical to a bundled sample, run it as that sample. The agent's prompt names the
    file, so this is what lets the recorded (offline) run apply to a file the owner drops in. Any other file is a new
    report: it needs a live model, or it shows the clear 'not in the offline cache' message."""
    if not upload.exists():
        return None
    h = hashlib.sha256(upload.read_bytes()).hexdigest()
    for p in sorted(fixtures.glob("*_payout.csv")):
        if hashlib.sha256(p.read_bytes()).hexdigest() == h:
            return p
    return None
