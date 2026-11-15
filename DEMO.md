# Demo script (about 3 minutes)

Sample: **Chutney, Montclair NJ (synthetic)**, DoorDash. Backup sample: Demo Bowl Shop.
Numbers below come from the recorded run: $98.08 expected of $149.20 deducted, 7 workable cases, nearest deadline in 10 days.

## Before you go on (2 minutes)

```bash
make reset      # memory back to the 3 seeded outcomes and the seeded AGENTS.md (no pending cases)
make api        # terminal 1, offline replay (restart it so the text panel starts empty)
make web        # terminal 2
```
Check: header shows **Memory · 3 past outcomes** and **Text approval**. No "Scripted dev model" badge. Wi-Fi can stay off.
Decision paths that are recorded: approve the first dispute then skip the rest, or approve everything. Stay on one of them.

## Beats

**1. Hook (20s).** "A customer says an item was missing and the platform just takes the money back. A chain has a finance team to fight that. An independent owner has a CSV and a drawer of tickets, so they eat it. Reclaim is for that owner. The data here is synthetic, modeled on a momo menu, and the owner approves everything."

**2. Drop in the payout (15s).** Choose the Chutney sample. The counter animates to **$98.08 recoverable this week** and the nearest deadline. Say: "estimates, not guarantees".

**3. Plan streams (25s).** Point at the agent panel: the plan, ordered by expected value. "Deterministic code scored these. The model never does the money math."

**4. The re-plan (30s).** The evidence subagent finds the biggest claim, the $46.80 party tray (DD-51102), has no readable ticket. It marks the case weak, the queue re-sorts, and the plan line becomes "DD-51102 WEAK (no ticket) - request ticket photo for order DD-51102". Say: "It would rather tell me it's weak than pad the case. That's a rule, not a prompt."

**5. Case detail (30s).** Open DD-51152 (Chicken Thukpa). Ticket image on the left, with the claimed item flagged as **not on the ticket**. Read one line of the draft: facts and evidence ids, no accusation. "Every edit I make is checked by the same rules, so I can't type an accusation in either."

**6. Owner approval (30s).** Open **Text approval**. The same draft arrived as a message. Tap YES. The case shows **Ready to file** and a panel appears with the portal link, copy buttons and the filing deadline. Say plainly: "Approving prepares the packet. DoorDash has no API for this, so the owner files it in their portal." "One gate, two front ends. Only a plain yes approves: 'yes, but change it' does nothing." Say it is a simulated phone.

**7. Memory (20s).** Open Memory: three past outcomes with lessons. "Similar cases start from what happened before." Then text `WON 28.40` in the Text approval panel: the strip goes from 3 to 4 within a couple of seconds (it counts won and lost results only, not disputes still awaiting an answer) and the new lesson ("won, $28.40 recovered") appears at the top of the list.

**8. Close (10s).** "Services exist for chains. Reclaim is for independents with no back office. Next: real payout screenshots and the live phone link."

## Showing it with a real file (the CSV)

On the start screen, use **Choose file** (or drop a file) and pick `fixtures/chutney_montclair_doordash_payout.csv`. Open the file first in a spreadsheet so they can see the raw rows: one row per order, and the refund rows are the "Refund" lines with a customer, an item and an amount. Say: "This is what an owner already gets from DoorDash. No integration."

- A file that is **byte-identical to a bundled sample** runs as that sample, so the recorded run replays offline.
- **Any other file** is a new report. Offline it shows the "not in the offline cache" card, honestly. With `ANTHROPIC_API_KEY` set and `make api LLM_MODE=auto` it runs the real model live.
- A file that is not a payout report is refused with a plain message before any model call.

## Showing the agent side (what is "LangChain" here)

The agent is built with LangChain's Deep Agents. In the app you can point at three things:
1. **Plan and subagents** in the Agent panel: the plan is the Deep Agents planning tool; "evidence" and "dispute-writer" are subagents.
2. **Agent files** (header button): the files the agent wrote to its file system. Open `notes/DD-51102-evidence.md` (the evidence subagent's note), a case's `draft.md`, and `trace.jsonl`. Say: "It can only write plan and note files. It cannot delete or overwrite anything else."
3. **Memory** (header button): the persistent memory file the agent reads on every run.

**Say it like this (30 seconds):** "The agent is built on LangChain's Deep Agents. There is one main agent that plans. It hands each case to a specialist subagent: one that gathers evidence, one that writes the dispute. Each specialist works on one case in a clean context, so cases can't contaminate each other. Everything involving money or dates is plain code. The agent stops and waits for me before anything is approved. Click **How it works** in the Agent panel for the picture, and the cards in the Activity list for what each specialist did."

**What the Activity list shows:** each subagent is one card (Evidence agent · UE-9b02, WEAK; Dispute-writer agent · UE-9a31, DONE). Click a card to see its tool calls. "Waiting for you" appears only while a decision is pending; afterward it turns into "You approved UE-9a31".

**What "approved" means:** the app cannot file with DoorDash or Uber Eats for the owner, because neither offers a public dispute API. Approving prepares a packet (the case shows **Ready to file**). The owner then opens the portal link in the case panel, pastes the dispute text (copy buttons are there) and files it before the deadline. When the platform answers, the owner records Won or Lost, or texts `WON 28.40` / `LOST`, and that is what the memory learns from.

## Showing LangSmith

LangSmith is a tracing service. It is not a model. It records every step of a run as a tree, so you can audit why the agent did something (constitution rule 8). Turn it on before the demo: in `.env` set `LANGSMITH_TRACING=true` (the key is already there), restart `make api`, and run a sample. Then click the **Traced · reclaim** badge in the header (it opens your LangSmith project).

In LangSmith, open the newest `reclaim-run` trace and point at:
- the orchestrator's model calls and its plan;
- the two **subagent** calls (evidence, dispute-writer) nested under it, each with its own tool calls (`check_ticket_vs_claim`, `check_pickup_timestamps`, `check_repeat_claimant`, `submit_dispute`);
- the **human-approval** step where the run paused until the owner answered;
- tags on the trace: `replayed-from-cache` means the model outputs were replayed from a recorded real run. Say so.

Tracing uploads the run's contents (items, amounts, evidence text, drafts) to LangSmith. The data here is synthetic, so that is fine. Turn it back off for anything real.

## Backup if the live demo fails

`docs/demo-backup/` holds a numbered screenshot sequence of the full flow (start, re-plan, memory reasoning, approve, skip, packet panel, memory, how it works). Walk through it in order with the same talk track.

## Rehearsal notes

The whole app side of beats 2 to 7 took about 7 seconds in a timed run, so the 3 minutes is you talking. Pause on the re-plan (beat 4) and the YES (beat 6); those are the two moments that sell it. The strip and the lesson list update by polling every 2.5 seconds, so after texting WON, give it a beat before opening Memory.

## If something goes wrong

| Symptom | Do |
|---|---|
| "Not in the offline cache" card | You left the recorded paths. Click New report and use approve-first-then-skip |
| Stuck on Planning | Check terminal 1 is running; reload the page |
| Memory shows more than 3 | `make reset`, then restart `make api` |
| Port busy | `make api API_PORT=8101` and `make web API_PORT=8101 WEB_PORT=3101` |

## Questions you may get

- **Is the model real?** Yes: the run was recorded from a real model, then replayed offline so the demo cannot fail on Wi-Fi. `make record` re-records it.
- **Will it win disputes?** Unknown. Win rates are heuristics until real outcomes accumulate; that is what the memory is for.
- **Does it file with the platform?** It produces the packet; the owner files it.
- **Is the text approval live?** Simulated. The bridge and parser are tested; the live Photon link is not built.
- **Real restaurants?** All data is synthetic. Two owners described this problem as a few issues, not a crisis; this is built to be cheap to try, not claimed as a big loss.
