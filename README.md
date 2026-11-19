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

## Capstone

**What This Extends**

The system is Re-Claim (this repository), the hackathon project that recovers money DoorDash and Uber Eats deduct after "missing or wrong item" claims. Before the capstone it ran from a terminal and a browser, and left a per-case folder, but no record of a run as a whole: nothing recorded how long a run took, how many model calls it made, what it cost, or why one failed. What is new: a structured run log (one JSON line per agent segment and per rejected input), a documented run path (`RUNNING.md`), a measurement script for cost and latency per run, and a probe that triggers the failure paths on purpose.

**The Shape**

Shape A, deploy and instrument. Out of scope, on purpose: no change to the agent prompts, the scoring rules, or the recorded replay cache (the live demo depends on them); no hosting (Path B, local with a run record); no new agent capability; no rewrite of the interface; no live Photon text channel.

**Running It**

Path B, local with logs. The start command, environment and the run record are in [RUNNING.md](RUNNING.md).

**Instrumentation**

Every agent segment (a start or a resume, until the agent finishes, pauses for approval, errors or is stopped) and every rejected input appends one JSON line to `data/runs.jsonl` (`RECLAIM_RUN_LOG` overrides the path). Code: `backend/reclaim/runlog.py` (`log_event`), written from `drive()` and `launch()` in `backend/reclaim/api/main.py`. A `segment` record holds `ts`, `event`, `run_id`, `llm_mode`, `input` (start source or the owner's decisions), `output` (status, pending case, cases triaged, drafts), `duration_s`, `usage` (model calls and input, cache-read, cache-write and output tokens) and `error` (kind and message, or null). A `rejected` record holds `ts`, `event`, `input`, `status` and `error`. Logging never raises, so it cannot break a run.

Ten entries from the 10-run live measurement (`docs/capstone/run-log.jsonl`, the first two runs: one start and four resumes each):

```
{"ts": "2026-11-18T23:27:33.029+00:00", "event": "segment", "run_id": "721dd4921c", "llm_mode": "record", "input": {"kind": "start", "source": {"fixture": "doordash_payout.csv"}}, "output": {"status": "waiting_approval", "pending_case": "doordash:DD-48290", "cases_triaged": 9, "drafts": 4}, "duration_s": 102.698, "usage": {"calls": 67, "input": 506368, "cache_read": 479460, "cache_creation": 26754, "output": 13783}, "error": null}
{"ts": "2026-11-18T23:27:34.309+00:00", "event": "segment", "run_id": "721dd4921c", "llm_mode": "record", "input": {"kind": "resume", "decisions": ["approve"]}, "output": {"status": "waiting_approval", "pending_case": "doordash:DD-48251", "cases_triaged": 9, "drafts": 4}, "duration_s": 1.222, "usage": {"calls": 1, "input": 24100, "cache_read": 23992, "cache_creation": 106, "output": 59}, "error": null}
{"ts": "2026-11-18T23:27:35.617+00:00", "event": "segment", "run_id": "721dd4921c", "llm_mode": "record", "input": {"kind": "resume", "decisions": ["reject"]}, "output": {"status": "waiting_approval", "pending_case": "doordash:DD-48267", "cases_triaged": 9, "drafts": 4}, "duration_s": 1.203, "usage": {"calls": 1, "input": 24201, "cache_read": 24098, "cache_creation": 101, "output": 84}, "error": null}
{"ts": "2026-11-18T23:27:36.669+00:00", "event": "segment", "run_id": "721dd4921c", "llm_mode": "record", "input": {"kind": "resume", "decisions": ["reject"]}, "output": {"status": "waiting_approval", "pending_case": "doordash:DD-48230", "cases_triaged": 9, "drafts": 4}, "duration_s": 0.933, "usage": {"calls": 1, "input": 24327, "cache_read": 24199, "cache_creation": 126, "output": 59}, "error": null}
{"ts": "2026-11-18T23:27:47.199+00:00", "event": "segment", "run_id": "721dd4921c", "llm_mode": "record", "input": {"kind": "resume", "decisions": ["reject"]}, "output": {"status": "done", "pending_case": null, "cases_triaged": 9, "drafts": 4}, "duration_s": 10.094, "usage": {"calls": 2, "input": 49812, "cache_read": 48751, "cache_creation": 1057, "output": 1535}, "error": null}
{"ts": "2026-11-18T23:29:26.341+00:00", "event": "segment", "run_id": "0447d417d9", "llm_mode": "record", "input": {"kind": "start", "source": {"fixture": "doordash_payout.csv"}}, "output": {"status": "waiting_approval", "pending_case": "doordash:DD-48290", "cases_triaged": 9, "drafts": 4}, "duration_s": 98.387, "usage": {"calls": 65, "input": 495992, "cache_read": 464030, "cache_creation": 31812, "output": 13127}, "error": null}
{"ts": "2026-11-18T23:29:27.649+00:00", "event": "segment", "run_id": "0447d417d9", "llm_mode": "record", "input": {"kind": "resume", "decisions": ["approve"]}, "output": {"status": "waiting_approval", "pending_case": "doordash:DD-48251", "cases_triaged": 9, "drafts": 4}, "duration_s": 0.942, "usage": {"calls": 1, "input": 24252, "cache_read": 24146, "cache_creation": 104, "output": 59}, "error": null}
{"ts": "2026-11-18T23:29:29.255+00:00", "event": "segment", "run_id": "0447d417d9", "llm_mode": "record", "input": {"kind": "resume", "decisions": ["reject"]}, "output": {"status": "waiting_approval", "pending_case": "doordash:DD-48267", "cases_triaged": 9, "drafts": 4}, "duration_s": 1.224, "usage": {"calls": 1, "input": 24353, "cache_read": 24250, "cache_creation": 101, "output": 87}, "error": null}
{"ts": "2026-11-18T23:29:30.325+00:00", "event": "segment", "run_id": "0447d417d9", "llm_mode": "record", "input": {"kind": "resume", "decisions": ["reject"]}, "output": {"status": "waiting_approval", "pending_case": "doordash:DD-48230", "cases_triaged": 9, "drafts": 4}, "duration_s": 0.957, "usage": {"calls": 1, "input": 24482, "cache_read": 24351, "cache_creation": 129, "output": 59}, "error": null}
{"ts": "2026-11-18T23:29:40.047+00:00", "event": "segment", "run_id": "0447d417d9", "llm_mode": "record", "input": {"kind": "resume", "decisions": ["reject"]}, "output": {"status": "done", "pending_case": null, "cases_triaged": 9, "drafts": 4}, "duration_s": 9.352, "usage": {"calls": 2, "input": 49975, "cache_read": 49061, "cache_creation": 910, "output": 1344}, "error": null}
```

Failed runs from the same measurement. The API account's usage limit was reached during run 8, so runs 8 to 10 failed. The failures were logged, with the error text and zero tokens for runs 9 and 10:

```
{"ts": "2026-11-18T23:40:05.031+00:00", "event": "segment", "run_id": "388db8695b", "llm_mode": "record", "input": {"kind": "start", "source": {"fixture": "doordash_payout.csv"}}, "output": {"status": "error", "pending_case": null, "cases_triaged": 9, "drafts": 0}, "duration_s": 14.054, "usage": {"calls": 9, "input": 65758, "cache_read": 65082, "cache_creation": 654, "output": 1222}, "error": {"kind": "AnthropicInvalidRequestError", "message": "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'You have reached your specified API usage limits. You will regain access on 2026-12-01 at 00:00 UTC.'}, 'request_id': 'req_011ChBGztjBS5dnqXtFLRT4g'}"}}
{"ts": "2026-11-18T23:40:06.025+00:00", "event": "segment", "run_id": "512d7b52e2", "llm_mode": "record", "input": {"kind": "start", "source": {"fixture": "doordash_payout.csv"}}, "output": {"status": "error", "pending_case": null, "cases_triaged": 0, "drafts": 0}, "duration_s": 0.237, "usage": {"calls": 0, "input": 0, "cache_read": 0, "cache_creation": 0, "output": 0}, "error": {"kind": "AnthropicInvalidRequestError", "message": "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'You have reached your specified API usage limits. You will regain access on 2026-12-01 at 00:00 UTC.'}, 'request_id': 'req_011ChBGzy9qzY8uRKFAfRhTr'}"}}
{"ts": "2026-11-18T23:40:06.857+00:00", "event": "segment", "run_id": "fbdf8a18c0", "llm_mode": "record", "input": {"kind": "start", "source": {"fixture": "doordash_payout.csv"}}, "output": {"status": "error", "pending_case": null, "cases_triaged": 0, "drafts": 0}, "duration_s": 0.187, "usage": {"calls": 0, "input": 0, "cache_read": 0, "cache_creation": 0, "output": 0}, "error": {"kind": "AnthropicInvalidRequestError", "message": "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'You have reached your specified API usage limits. You will regain access on 2026-12-01 at 00:00 UTC.'}, 'request_id': 'req_011ChBH12w3iuUnG92RWg4e8'}"}}
```

Rejected inputs and other failures triggered on purpose (`docs/capstone/failure-log.jsonl`, from `scripts/capstone_failure_probe.py`):

```
{"ts": "2026-11-18T23:26:32.373+00:00", "event": "rejected", "input": {"fixture": "nope.csv"}, "status": 404, "error": {"kind": "http_404", "message": "payout file not found"}}
{"ts": "2026-11-18T23:26:32.376+00:00", "event": "rejected", "input": {}, "status": 422, "error": {"kind": "http_422", "message": "give a fixture name or an upload_id"}}
{"ts": "2026-11-18T23:26:32.381+00:00", "event": "rejected", "input": {"upload_id": "215771723801"}, "status": 422, "error": {"kind": "http_422", "message": "could not read this payout report: could not recognise payout format (expected a DoorDash or Uber Eats CSV)"}}
{"ts": "2026-11-18T23:26:32.386+00:00", "event": "rejected", "input": {"upload_bytes": ">2097152"}, "status": 413, "error": {"kind": "http_413", "message": "file too large"}}
{"ts": "2026-11-18T23:26:32.481+00:00", "event": "segment", "run_id": "08fbe01f93", "llm_mode": "replay", "input": {"kind": "start", "source": {"upload_id": "df146c8cc7b5"}}, "output": {"status": "error", "pending_case": null, "cases_triaged": 0, "drafts": 0}, "duration_s": 0.015, "usage": {"calls": 0, "input": 0, "cache_read": 0, "cache_creation": 0, "output": 0}, "error": {"kind": "cache_miss", "message": "no cached LLM response for request 4af50f211282 (mode=replay); re-record with scripts/record_cache.py"}}
{"ts": "2026-11-18T23:26:33.902+00:00", "event": "segment", "run_id": "c5f0721782", "llm_mode": "record", "input": {"kind": "start", "source": {"fixture": "doordash_payout.csv"}}, "output": {"status": "error", "pending_case": null, "cases_triaged": 0, "drafts": 0}, "duration_s": 0.249, "usage": {"calls": 0, "input": 0, "cache_read": 0, "cache_creation": 0, "output": 0}, "error": {"kind": "auth", "message": "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in .env. Nothing was sent."}}
```

**What It Costs**

Measured, not estimated from the pricing page: `scripts/measure_cost.py` took `fixtures/doordash_payout.csv` through the real API 10 times with the real model (`claude-sonnet-5-5`, every call live; a temp cache so nothing was replayed). **7 runs completed; runs 8 to 10 failed because the API account hit its usage limit**, so the average is over 7 runs, not 10. Each run is one start plus four resumes, about 73 model calls. Dollars are computed from the token counts the API returned, at the published rates ($2.00 per million input tokens, $10.00 output, $2.50 cache write, $0.10 cache read), summed over the run.

```
{"run": 1, "status": "done", "wall_s": 118.3, "calls": 72, "input": 628808, "cache_read": 600500, "cache_creation": 28144, "output": 15520, "cost_usd": 0.2859}
{"run": 2, "status": "done", "wall_s": 112.5, "calls": 70, "input": 619054, "cache_read": 585838, "cache_creation": 33056, "output": 14676, "cost_usd": 0.2883}
{"run": 3, "status": "done", "wall_s": 128.9, "calls": 73, "input": 654035, "cache_read": 626249, "cache_creation": 27620, "output": 15245, "cost_usd": 0.2845}
{"run": 4, "status": "done", "wall_s": 137.8, "calls": 74, "input": 668172, "cache_read": 644191, "cache_creation": 23813, "output": 14348, "cost_usd": 0.2678}
{"run": 5, "status": "done", "wall_s": 119.0, "calls": 78, "input": 749145, "cache_read": 722847, "cache_creation": 26122, "output": 15471, "cost_usd": 0.2927}
{"run": 6, "status": "done", "wall_s": 115.8, "calls": 72, "input": 625295, "cache_read": 598394, "cache_creation": 26737, "output": 15192, "cost_usd": 0.2789}
{"run": 7, "status": "done", "wall_s": 107.2, "calls": 72, "input": 621020, "cache_read": 596852, "cache_creation": 24004, "output": 14399, "cost_usd": 0.264}
```

- Mean **$0.28 per run** (range $0.264 to $0.293), mean 120 s wall time (range 107 to 138 s). 96% of input tokens were prompt-cache reads, which is why it is cheap. A single cold-cache pilot run cost $0.37 and took 119.5 s.
- A hundred owners a day, one run each: 100 x $0.28 = **$28 a day** (about $840 a month). Runs more than five minutes apart start with a cold cache, so the safer figure is 100 x $0.37 = $37 a day.
- The after-fix code changes how usage is tallied, and this cost number comes from before that change. It could not be re-measured live (usage limit), so it is not re-verified. See What's Still Broken.

**Run Log and Verdicts**

Each criterion in `criteria.md` was run three times with nothing changed in between (`scripts/capstone_trials.py`, raw logs and results in `docs/capstone/trials/before/`). Criteria 1, 2 and 5 are free and complete. **Criteria 3 and 4 need live runs and the API usage limit was reached, so they have 7 of the 9 planned runs**: trial 1 is runs 1 to 3, trial 2 is runs 4 to 6, trial 3 is run 7 alone. Criterion 5 was run with a stand-in model instead of 2 live runs (a deviation from `criteria.md`): the stand-in goes through the real graph, subagents and API, sleeps 20 ms per call so the two runs genuinely overlap, reports usage through the same `record_usage` and counts its own calls independently.

| Criterion | Target | Run 1 | Run 2 | Run 3 | Verdict |
|---|---|---|---|---|---|
| 1. Every run and rejected input leaves a complete record | 100% present and complete | 55/55 | 55/55 | 55/55 | MET |
| 2. Six deliberate failures visible (4xx or run `error` within 30 s, with a logged error kind) | 6 of 6 | 6/6 | 6/6 | 6/6 | MET |
| 3. Live run cost, mean <= $0.50 and each <= $0.60 | per trial | mean $0.286 (3 runs) | mean $0.280 (3 runs) | $0.264 (1 run) | MET, on 7 of 9 runs |
| 4. Live run under 180 s | every run | 3/3 (max 128.9 s) | 3/3 (max 137.8 s) | 1/1 (107.2 s) | MET, on 7 of 9 runs |
| 5. Overlapping runs attributed exactly | difference 0 | +74 (152 vs 78) | +71 (149 vs 78) | +75 (153 vs 78) | MISSED |

Pasted output (real, from the files named):

Criterion 1, `scripts/capstone_trials.py` `c1`, `before/results-c1.json`, trial 1: `{"trial": 1, "expected_records": 55, "records": 55, "complete_records": 55, "segments_expected": 50, "segments_found": 50, "rejected_found": 5, "pass": true}`

Criterion 2, `c2`, `before/results-c2.json`, trial 1:
```
file not found           http=404 run=None 0.0s error_kind_logged=http_404 pass=True
no input                 http=422 run=None 0.0s error_kind_logged=http_422 pass=True
not a payout file        http=422 run=None 0.0s error_kind_logged=http_422 pass=True
upload over 2 MB         http=413 run=None 0.0s error_kind_logged=http_413 pass=True
unseen report, replay    http=None run=error 0.7s error_kind_logged=cache_miss pass=True
rejected API key         http=None run=error 1.7s error_kind_logged=auth pass=True
```

Criteria 3 and 4, `scripts/measure_cost.py`, `docs/capstone/cost-summary.json` (the seven completed runs listed under What It Costs).

Criterion 5, `c5`, `before/results-c5.json`, trial 1: `{"trial": 1, "actual_model_calls": 78, "logged_calls_sum": 152, "difference": 74, "logged_per_run": {"46af06421b": 75, "15aef70e6d": 77}, "statuses": {"15aef70e6d": "done", "46af06421b": "done"}, "pass": false}`

**Diagnosis of the one miss (criterion 5).** The stage is the run log's usage field in `drive()` (`backend/reclaim/api/main.py`), and the mechanism is that it computed each segment's usage as the change in a process-wide counter (`llm.USAGE`) between the segment's start and end. When two runs overlap, each segment's change includes the other run's calls, so the log counted about 1.9 times the real number (152, 149 and 153 logged against 78 actual). Criteria 3 and 4 and the first two passed, so this was one problem with one symptom, and it only appears when runs overlap.

**The Improvement**

One change, aimed at that diagnosis: `record_usage` in `backend/reclaim/llm.py` now also adds each call to a per-segment tally held in a context variable, and `drive()` sets a fresh tally for each segment and logs that instead of a difference of the global counter. A lock protects the counters. I re-ran the whole set (`docs/capstone/trials/after/`), with no other change in between. The 241 tests and the offline audit (all samples, both decision paths) still pass.

| Criterion | Target | Before (R1 / R2 / R3) | After (R1 / R2 / R3) | Verdict now |
|---|---|---|---|---|
| 1. Complete records | 100% | 55/55, 55/55, 55/55 | 55/55, 55/55, 55/55 | MET |
| 2. Six failures visible | 6 of 6 | 6/6, 6/6, 6/6 | 6/6, 6/6, 6/6 | MET |
| 3. Live cost | mean <= $0.50 | $0.286, $0.280, $0.264 | not re-run (usage limit) | MET before; not re-verified after |
| 4. Live time | < 180 s | 3/3, 3/3, 1/1 | not re-run (usage limit) | MET before; not re-verified after |
| 5. Concurrent attribution | difference 0 | +74, +71, +75 | 0, 0, 0 (78 logged vs 78 actual, every trial) | MET (was MISSED) |

It helped: the double counting is gone, 39 calls logged for each of the two runs. The caveat is that criterion 5 after the fix was shown with the stand-in model, not 2 live runs, and the live criteria 3 and 4 were not repeated. While testing the "after" set I also found my own test setup was wrong, not the app: copying the demo `data/` folder carried a stale `restart_pending.json`, which made each test app relaunch about 20 old runs and inflate the log. I deleted the marker, excluded it from the copy in the three scripts, discarded that contaminated run and re-ran, so the "after" results above are the clean ones.

**What's Still Broken**

- **Criteria 3 and 4 are met on 7 of 9 planned runs, and not re-run after the fix.** The API account's usage limit was reached during the 10-run measurement (it regains access on 2026-12-01). First thing I would do: raise the limit and run `scripts/capstone_trials.py --criteria 3` for the full 3 x 3 after the fix, because that is the only claim I have not seen with my own eyes since the change. I stopped because I could not make live calls.
- **Criterion 5 was tested with a stand-in model, not two live runs.** It exercises the real graph and the same `record_usage`, but not the real API's usage fields.
- **A usage-limit error shows the owner raw API text** (`AnthropicInvalidRequestError ... You have reached your specified API usage limits`). It is logged correctly, but `explain_model_error` has no friendly message for it. Cheap to fix; I kept to one improvement.
- **My targets were loose.** Measured: about $0.28 against a $0.50 target, and at most 137.8 s against 180 s. I would tighten to $0.35 and 150 s.
- **Not hosted.** Path B (local with logs); I did not try a host. The process-wide `USAGE` counter still exists for the dev scripts; only the log no longer depends on it.
- **No real-world validation.** Win probabilities are still heuristics, and all data is synthetic.

If I had another unit I would do the live 3 x 3 re-run first, then record real dispute outcomes, so the win percentages stop being guesses.

**How I Used AI**

1. *The criteria and the measurement plan.* I told Claude to carry out every remaining capstone step. It drafted the five criteria in `criteria.md` (the course says to write them myself, so I am disclosing that) and committed them before any results. It wrote criterion 5 expecting it to fail, because it had read that the usage counter was process-wide. What I changed: [state here what you edited or kept, or "nothing"].
2. *The API usage limit.* Claude ran the 10 live runs. When runs 8 to 10 came back failed, it read the run log, found the account's usage limit in the error text, stopped the trials that were about to fail, and told me plainly. I chose to finish without further live runs. It then replaced the live concurrency test with a stand-in model and said that was a deviation from the criterion.
