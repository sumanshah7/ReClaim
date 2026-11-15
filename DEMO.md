# Demo script (about 3 minutes)

Sample: **Chutney, Montclair NJ (synthetic)**, DoorDash. Backup sample: Demo Bowl Shop.
Numbers below come from the recorded run: $98.08 expected of $149.20 deducted, 7 workable cases, nearest deadline in 10 days.

## Before you go on (2 minutes)

```bash
sqlite3 data/reclaim.db "delete from outcomes where case_id not like 'seed-%'"   # memory back to 3 seeded outcomes
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

**6. Owner approval (30s).** Open **Text approval**. The same draft arrived as a message. Tap YES. Case shows SENT and the packet is written. "One gate, two front ends. Only a plain yes sends: 'yes, but change it' does nothing." Say it is a simulated phone.

**7. Memory (20s).** Open Memory: three past outcomes with lessons. "Similar cases start from what happened before." Then text `WON 28.40` in the Text approval panel: the strip goes to 4 within a couple of seconds and the new lesson ("won, $28.40 recovered") appears at the top of the list.

**8. Close (10s).** "Services exist for chains. Reclaim is for independents with no back office. Next: real payout screenshots and the live phone link."

## Rehearsal notes

The whole app side of beats 2 to 7 took about 7 seconds in a timed run, so the 3 minutes is you talking. Pause on the re-plan (beat 4) and the YES (beat 6); those are the two moments that sell it. The strip and the lesson list update by polling every 2.5 seconds, so after texting WON, give it a beat before opening Memory.

## If something goes wrong

| Symptom | Do |
|---|---|
| "Not in the offline cache" card | You left the recorded paths. Click New report and use approve-first-then-skip |
| Stuck on Planning | Check terminal 1 is running; reload the page |
| Memory shows more than 3 | Run the sqlite reset above |
| Port busy | `make api API_PORT=8101` and `make web API_PORT=8101 WEB_PORT=3101` |

## Questions you may get

- **Is the model real?** Yes: the run was recorded from a real model, then replayed offline so the demo cannot fail on Wi-Fi. `make record` re-records it.
- **Will it win disputes?** Unknown. Win rates are heuristics until real outcomes accumulate; that is what the memory is for.
- **Does it file with the platform?** It produces the packet; the owner files it.
- **Is the text approval live?** Simulated. The bridge and parser are tested; the live Photon link is not built.
- **Real restaurants?** All data is synthetic. Two owners described this problem as a few issues, not a crisis; this is built to be cheap to try, not claimed as a big loss.
