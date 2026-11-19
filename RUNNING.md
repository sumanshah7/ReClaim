# Running Re-Claim (Path B: local, with a run log)

Re-Claim runs on your machine from the commands below. It was not deployed to a host: it calls an API and loads no
local model, so it could be hosted, but the course allows a documented local run and this is the one that is tested.

## Environment

| Need | Version / size |
|---|---|
| Python | 3.11 (built and tested on 3.11.8) |
| Node.js | 20 or newer, only for the web UI (tested on 22.20) |
| Python packages | `backend/pyproject.toml`; the versions used are in `backend/requirements-lock.txt` (deepagents 0.7.38, langchain-anthropic 1.7.10, langgraph 1.2.22, FastAPI 0.163.0, pydantic 2.14.3, pandas 3.1.1) |
| Model files | none. The model is Anthropic's `claude-sonnet-5-5` over the API |
| Recorded model responses | `fixtures/llm_cache/`, about 1.2 MB, committed |
| API key | **not needed** for the default offline replay. Needed only for live runs (`ANTHROPIC_API_KEY` in `.env`) |

## One-time setup (from a clean checkout)

```bash
git clone <this repo> reclaim && cd reclaim
python3.11 -m venv backend/.venv
backend/.venv/bin/pip install -e "backend[dev]"
cp .env.example .env              # leave the key empty for offline replay
(cd frontend && npm install)      # only if you want the web UI
make reset                        # REQUIRED for offline replay: seeds demo memory (3 synthetic outcomes)
```

Why `make reset` is required: the recorded model responses only replay while memory holds exactly the 3 seeded
outcomes (the lessons file is part of the prompt). On a fresh checkout there is no `data/` folder, and without this step
the first run stops with a `cache_miss` error (this was found by testing these instructions from a clean clone).

## Start it (single command for the API)

```bash
make api            # API on http://127.0.0.1:8100, offline replay of the recorded real-model run
```

Check it is up: `curl -s localhost:8100/api/health` returns `{"ok":true,"llm_mode":"replay",...}`.

Run one case without the UI (this is the same path the UI uses):

```bash
curl -s -X POST localhost:8100/api/runs -H 'content-type: application/json' -d '{"fixture":"doordash_payout.csv"}'
# -> {"run_id":"..."}; poll  curl -s localhost:8100/api/runs/<run_id>  until status is "waiting_approval"
```

Web UI (optional, second terminal): `make web`, then open http://localhost:3100.

## The run record

Every agent segment (a start or resume, until the agent finishes, pauses for approval, errors, or is stopped) and
every rejected input appends one JSON line to **`data/runs.jsonl`** (override with `RECLAIM_RUN_LOG`). Fields:
`ts`, `event` (`segment` or `rejected`), `run_id`, `llm_mode`, `input`, `output`, `duration_s`, `usage`
(model calls and tokens), `error` (kind and message, or null). Read it with:

```bash
tail -n 5 data/runs.jsonl
backend/.venv/bin/python -c "import json;[print(r['ts'],r['event'],r.get('duration_s'),r.get('error')) for r in map(json.loads,open('data/runs.jsonl'))]"
```

A real session's record is committed at `docs/capstone/run-log.jsonl` (10 live runs) and
`docs/capstone/failure-log.jsonl` (rejected and failed inputs).

## Measure the cost of one run (spends real money)

```bash
echo 'ANTHROPIC_API_KEY=...' >> .env
backend/.venv/bin/python scripts/measure_cost.py --runs 10     # about 20 minutes and a few dollars
```

It uses record mode with a temp cache directory, so every call is live, `fixtures/llm_cache` is untouched, and it
works on a throwaway copy of `data/`, so demo memory is not changed. Output: `docs/capstone/run-log.jsonl` and
`docs/capstone/cost-summary.json`.

## Tests and reset

```bash
make test           # 241+ tests, no network and no key needed
make reset          # demo memory back to its 3 seeded outcomes; restart make api afterwards
```

Before presenting the offline demo, run `make reset` and restart `make api`: recorded responses only replay while
memory matches the seeded state (pressing Won/Lost changes it).

## Ports

API 8100 and web 3100 (chosen to stay off 3000 and 8000). Override with `make api API_PORT=8101`.
