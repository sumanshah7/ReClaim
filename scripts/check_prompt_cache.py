"""Live check that Anthropic prompt caching is hit (needs ANTHROPIC_API_KEY; costs a few cents).

Makes two calls with the same ~2.5K-token system prompt and prints cache_creation / cache_read from the API's own
usage report. Expect call 1 to write the cache and call 2 to read it (cache_read > 0).

  set -a; . ./.env; set +a; backend/.venv/bin/python scripts/check_prompt_cache.py
"""
import sys, tempfile, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

from reclaim import llm  # noqa: E402

m = llm.make_model(Path(tempfile.mkdtemp()), mode="record")
system = f"session {uuid.uuid4()}\n" + (ROOT / "backend/reclaim/agent/prompts/orchestrator.md").read_text() * 4
for i in (1, 2):
    r = m.invoke([SystemMessage(system), HumanMessage(f"Reply with the single word OK. ({i})")])
    u, d = r.usage_metadata, r.usage_metadata["input_token_details"]
    print(f"call {i}: input={u['input_tokens']} cache_creation={d.get('cache_creation')} cache_read={d.get('cache_read')}")
print("PASS" if llm.USAGE["cache_read"] > 0 else "FAIL: no cache read")
