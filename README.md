# Re-Claim

Independent restaurants lose money when a delivery platform deducts a refund after a customer says an item was missing or wrong, and the owner has no back office to contest it. Re-Claim reads the payout report, finds those deductions, ranks them by what is realistically recoverable, gathers evidence from the order tickets and timestamps, and drafts a factual dispute. **The owner approves every dispute. Nothing is sent without that.**

> **All data in this repo is synthetic** (see `fixtures/SYNTHETIC.md`). The restaurants named in the samples are illustrative, not real records. The owner's "phone" is a simulator. The demo replays a recorded run of the real model so it works offline.

## Who it is for

Services that recover these deductions exist for chains with finance teams. Re-Claim is built for the independent owner who has a payout CSV and a drawer of order tickets, and nothing else: no POS integration, no back office.

## What it does

1. **Ingest** a DoorDash or Uber Eats payout CSV (plain code, tested; customer names are hashed on load).
2. **Triage** every refund deduction with a deterministic score: expected recovery = amount x win probability, earliest deadline breaks ties (14 days DoorDash, 30 days Uber Eats).
3. **Investigate** with a deep agent: an *evidence* subagent reads the ticket and runs three checks (ticket vs claim, pickup timestamps, repeat claimant); it can mark a case weak and the orchestrator **re-plans** around it.
4. **Draft** with a *dispute-writer* subagent: facts only, cites evidence ids, never accuses the customer. A wording lint and an evidence-id check run on every draft, including the owner's edits.
5. **Approve** in the web app or by text. Only a plain YES approves. Approving prepares a filing packet (the case shows **Ready to file**, with a link to the merchant portal, copy buttons and the deadline); the owner files it, because neither platform has a dispute API.
6. **Learn.** Recording the outcome (web or `WON 46.80` / `LOST` by text) goes into persistent memory: SQLite stats that adjust win probability for similar cases, plus a lessons file the agent reads on every run.

## How the Deep Agent is used

| Deep Agents feature | Use |
|---|---|
| Planning (`write_todos`) | The plan is shown live and rewritten when a case turns out weak |
| Subagents | `evidence` and `dispute-writer`, each with a narrow toolset and prompt |
| File system | Per-case notes in `/notes`, `/plan.md`; case folders hold case, evidence, draft, decision, packet and trace. The **Agent files** button in the UI shows them |
| Persistent memory | `/memory/AGENTS.md` loaded into every prompt, plus an outcomes database and a `recall_similar_cases` tool |
| Human-in-the-loop | `interrupt_on` the one tool that files a dispute, with a checkpointer to resume |
| Permissions | Writes allowed only to `/plan.md` and `/notes/**`, so the audit trail and memory cannot be deleted or overwritten |

A ticket that lists the claimed item is neutral evidence for a missing-item claim (it proves the item was ordered, not packed), so drafts cannot cite it as support; it still supports a wrong-item claim. Judgment (reading messy evidence, weighing it, writing prose) is the model's job. Parsing, date math, money math and scoring are plain code with tests (constitution rule 7).

## Run it

```bash
cp .env.example .env            # optional: only needed to record or to trace
make api                        # API on :8100, offline replay by default
make web                        # UI on :3100
```

Open http://localhost:3100 and pick a sample. No API key is needed: the default mode replays a recorded real-model run from `fixtures/llm_cache`.

| Command | What it does |
|---|---|
| `make test` | Backend test suite (241 tests, including edge cases for CSVs, races, restarts and API failures) |
| `backend/.venv/bin/python scripts/audit_offline.py` | Replays every sample, both decision paths, with the network blocked |
| `make record` / `scripts/record_cache.py` | Re-records the cache with a real model (needs `ANTHROPIC_API_KEY`) |
| `make reset` | Returns memory to the 3 seeded synthetic outcomes (clears pending cases and extra lessons); restart `make api` after |
| `make seed` | Adds the seed outcomes if missing (does not clear anything) |
| `make api LLM_MODE=scripted` | Dev-only scripted model, for UI work |

**Code changes during a run:** `make api` watches the backend source and prompts. If they change while a run is in progress, that run is stopped (the UI says "Restarting on new code"), the server restarts, and the run is relaunched fresh, so a run never continues on stale code. A server that is killed mid-run simply forgets its runs (clear "unknown run" response, the UI asks you to start again); case files are written atomically so none is left half-written.

**Cost control:** prompt caching is enabled inside the model wrapper (Deep Agents' automatic caching skips a wrapped model); on a full live run 89.6% of input tokens were cache reads. Model calls have a 60 s timeout and capped output.

**Replay covers the recorded decision paths**: approve the first dispute then skip the rest, or approve all of them. Any other order shows a clear "not in the offline cache" message instead of a wrong answer. Re-record to cover more.

## Safety rules (see `CONSTITUTION.md`)

Human approval gate; evidence or silence; honest scoring with written reasons; no fraud accusations; deadline awareness; works from what the owner has; deterministic core; traceable; offline-capable; private. Tests cover the approval gate, evidence validation, the wording lint, the text-approval parser (a bare YES approves, "yes but..." does not), and that raw customer names never reach model-visible output.

## Status and known limits

- **Text approval is simulated.** The bridge, parser and outcome-by-text loop are tested; an outbound webhook for a Photon sidecar exists (`PHOTON_BRIDGE_URL`) but has not been run against live Photon.
- **LangSmith tracing** works: a replayed run reached a LangSmith project with the orchestrator, subagent, tool and middleware spans, tagged `reclaim`, `llm:<mode>` and `replayed-from-cache`/`live-model`. It is off by default (`LANGSMITH_TRACING=false`) because tracing uploads run contents; set it to `true` with a key to turn it on. A replayed run's trace shows recorded model outputs, and says so in its tags. Every run also writes a local case folder with a `trace.jsonl`.
- **Approving prepares a packet; it does not call a platform.** There is no public dispute API, so the packet is what the owner files.
- **Inputs are CSV and ticket images.** Payout screenshots and PDFs are not supported yet. Grubhub is not supported.
- **Win probabilities are heuristics** (a fixed table plus evidence adjustments and a small memory prior), not measured platform win rates. The UI says "estimates, not guarantees".
- Deadlines are counted from the payout date; the platforms' exact rules should be confirmed before relying on them.
