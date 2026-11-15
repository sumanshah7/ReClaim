from __future__ import annotations

from pathlib import Path

PROMPTS = Path(__file__).parent / "prompts"


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()


def build_subagents(tools: dict) -> list[dict]:
    return [
        {
            "name": "evidence",
            "description": "Gathers and weighs evidence for ONE case: compares the claimed item to the order ticket, "
                           "checks pickup timestamps and repeat claims. Pass the exact case_id. Returns a verdict "
                           "(strong, moderate or weak) with evidence ids.",
            "system_prompt": prompt("evidence"),
            "tools": [tools[n] for n in ("get_case", "read_ticket_image", "check_ticket_vs_claim",
                                         "check_pickup_timestamps", "check_repeat_claimant")],
        },
        {
            "name": "dispute-writer",
            "description": "Drafts a factual, non-accusatory dispute for ONE case and submits it for owner approval. "
                           "Pass the exact case_id. Only use on cases with supporting evidence.",
            "system_prompt": prompt("dispute_writer"),
            "tools": [tools[n] for n in ("get_case", "lint_dispute", "submit_dispute")],
        },
    ]
