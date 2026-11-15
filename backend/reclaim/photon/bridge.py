"""Approval by text message. One gate, two front ends (constitution rule 1): this bridge never decides anything itself.
It formats the pending draft as a message, parses the owner's reply, and calls the same decision function the web UI
calls. Anything it cannot read unambiguously is NOT treated as approval; the owner is asked again.

Transports: a local simulator (default, no network) or an outbound webhook to a Photon sidecar (PHOTON_BRIDGE_URL).
The webhook transport is untested against live Photon; see docs in README before relying on it."""
from __future__ import annotations

import json
import re
import threading
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Callable, Protocol

from ..money import fmt_cents

DEMO_OWNER = "+15550100"   # the simulator's phone; never a real number

APPROVE = {"yes", "y", "approve", "send"}
SKIP = {"no", "n", "skip"}
_EDIT = re.compile(r"^edit\b[:\s]+(.+)$", re.I | re.S)
_WON = re.compile(r"^won\s+\$?(\d+(?:\.\d{1,2})?)$", re.I)

HELP = ("Reply YES to send this dispute, NO to skip it, or EDIT followed by new wording. "
        "After a dispute is sent: WON 46.80 or LOST records what the platform decided.")


@dataclass
class Reply:
    kind: str                      # approve | skip | edit | won | lost | unknown
    body: str = ""
    cents: int = 0


def parse_reply(text: str) -> Reply:
    """Strict on purpose: approval needs a bare yes. 'yes but change it' is unknown, not an approval."""
    t = (text or "").strip()
    word = t.rstrip(".!").strip().lower()
    if word in APPROVE:
        return Reply("approve")
    if word in SKIP:
        return Reply("skip")
    if word == "lost":
        return Reply("lost")
    if m := _EDIT.match(t):
        return Reply("edit", body=m.group(1).strip())
    if m := _WON.match(t.rstrip(".!")):
        try:
            return Reply("won", cents=int((Decimal(m.group(1)) * 100).to_integral_value()))
        except InvalidOperation:  # pragma: no cover - regex already restricts the shape
            pass
    return Reply("unknown")


def format_prompt(case, dispute_body: str) -> str:
    d = case.deduction
    return (f"Reclaim: {d.order_id}, {fmt_cents(d.amount_cents)} deducted ({d.reason.value.replace('_', ' ')}).\n"
            f"Win odds {case.p_win_bp // 100}%, {case.days_left} days left to file.\n\n"
            f"Draft dispute:\n{dispute_body}\n\n"
            f"Reply YES to send, NO to skip, or EDIT <new text>. Nothing is sent until you reply YES.")


class Transport(Protocol):
    name: str

    def send(self, to: str, text: str) -> None: ...


class SimulatorTransport:
    name = "simulator"

    def send(self, to: str, text: str) -> None:   # the bridge's message log is the simulator's phone
        return None


class WebhookTransport:
    """POSTs {"to","text"} to a Photon sidecar. Raises on failure; the bridge records that and carries on."""
    name = "webhook"

    def __init__(self, url: str, timeout: float = 5.0):
        self.url, self.timeout = url, timeout

    def send(self, to: str, text: str) -> None:
        req = urllib.request.Request(self.url, data=json.dumps({"to": to, "text": text}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=self.timeout).read()


class DecisionRejected(Exception):
    """The shared decision function refused (stale case, failed edit checks)."""

    def __init__(self, status: int, errors: list[str]):
        super().__init__("; ".join(errors))
        self.status, self.errors = status, errors


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


@dataclass
class Message:
    direction: str                 # out | in
    text: str
    at: str
    note: str = ""


@dataclass
class Bridge:
    transport: Transport = field(default_factory=SimulatorTransport)
    owner: str = DEMO_OWNER
    decide: Callable[[str, str, str, str | None], None] | None = None          # (run_id, case_id, kind, body)
    outcome: Callable[[str, str, str, int], None] | None = None                # (run_id, case_id, result, cents)
    clock: Callable[[], datetime] = datetime.now
    messages: list[Message] = field(default_factory=list)
    pending: tuple[str, str] | None = None         # newest prompt only; older ones stay decidable in the web UI
    awaiting_outcome: list[tuple[str, str]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _log(self, direction: str, text: str, note: str = "") -> None:
        with self._lock:
            self.messages.append(Message(direction, text, self.clock().isoformat(timespec="seconds"), note))

    def _say(self, text: str) -> None:
        note = ""
        try:
            self.transport.send(self.owner, text)
        except Exception as e:  # a down phone link must never break the run
            note = f"delivery failed: {type(e).__name__}"
        self._log("out", text, note)

    # ---- outbound ------------------------------------------------------------------------
    def notify(self, run_id: str, case, dispute_body: str) -> None:
        self.pending = (run_id, case.id)
        self._say(format_prompt(case, dispute_body))

    def notify_done(self, sent: int, skipped: int) -> None:
        self._say(f"Reclaim finished: {sent} sent, {skipped} skipped. "
                  f"When a platform decides, reply WON <amount> or LOST so the agent learns.")

    def decided_elsewhere(self, run_id: str, case_id: str) -> None:
        """The owner used the web UI instead; a later YES must not act on a stale prompt."""
        if self.pending == (run_id, case_id):
            self.pending = None

    # ---- inbound -------------------------------------------------------------------------
    def handle_inbound(self, sender: str, text: str) -> str | None:
        """Returns the reply that was sent, or None when the sender is not the owner (ignored silently)."""
        if _digits(sender) != _digits(self.owner):
            return None
        self._log("in", text)
        r = parse_reply(text)
        reply = self._act(r)
        self._say(reply)
        return reply

    def _act(self, r: Reply) -> str:
        if r.kind == "unknown":
            return "I could not tell what you meant, so nothing was sent. " + HELP
        if r.kind in ("won", "lost"):
            if not self.awaiting_outcome:
                return "No sent dispute is waiting for an outcome."
            run_id, case_id = self.awaiting_outcome[-1]
            cents = r.cents if r.kind == "won" else 0
            self.outcome(run_id, case_id, r.kind, cents)
            self.awaiting_outcome.pop()
            return (f"Recorded {case_id.split(':')[-1]}: {r.kind}"
                    f"{', ' + fmt_cents(cents) + ' recovered' if r.kind == 'won' else ''}. The agent will use it next time.")
        if not self.pending:
            return "Nothing is waiting for your decision right now."
        run_id, case_id = self.pending
        try:
            self.decide(run_id, case_id, r.kind, r.body or None)
        except DecisionRejected as e:
            if e.status == 409:
                self.pending = None
                return "That one was already handled in the app."
            return "I did not send it: " + "; ".join(e.errors) + " Reply EDIT with new wording, or NO to skip."
        self.pending = None
        if r.kind == "skip":
            return "Skipped. Nothing was sent."
        self.awaiting_outcome.append((run_id, case_id))
        return "Approved. The dispute packet is being prepared for filing." if r.kind == "approve" else \
            "Your edit passed the checks and is approved. The dispute packet is being prepared for filing."

    def snapshot(self) -> dict:
        with self._lock:
            msgs = [m.__dict__ for m in self.messages]
        return {"mode": self.transport.name, "owner": self.owner, "pending": self.pending, "messages": msgs}
