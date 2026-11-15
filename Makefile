PY=backend/.venv/bin/python

test:
	cd backend && .venv/bin/python -m pytest -q

fixtures:
	$(PY) scripts/gen_fixtures.py

seed:
	$(PY) scripts/seed_memory.py

reset:
	$(PY) scripts/reset_demo.py

record:
	$(PY) scripts/record_cache.py --decisions approve,skip

LLM_MODE ?= replay
# Ports are off the common 3000/8000 defaults so Reclaim can run beside other local projects.
API_PORT ?= 8100
WEB_PORT ?= 3100

# Offline replay by default. `make api LLM_MODE=scripted` uses the dev-only scripted model (UI work, no key needed).
api:
	cd backend && RECLAIM_LLM_MODE=$(LLM_MODE) .venv/bin/uvicorn reclaim.api.main:create_app --factory --port $(API_PORT)

web:
	cd frontend && RECLAIM_API=http://127.0.0.1:$(API_PORT) npm run dev -- --port $(WEB_PORT)
