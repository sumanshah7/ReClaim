# Capstone acceptance criteria (Shape A: deploy and instrument)

Written before any trial results exist. Each has a target and a reason. All five are about the extension (the run
log, the run path's failure behaviour, and the measured cost and latency); the original system's behaviour is
checked separately by the existing 241-test suite and offline audit, which must still pass.

"A run" means one payout file (`fixtures/doordash_payout.csv`) taken through the API: start, the owner approves the
first dispute and skips the rest, the agent finishes. "A trial" is one repeat of the whole check; each criterion is
tried three times with nothing changed in between. Live means every model call goes to the real API.

1. **Every run and every rejected input leaves a complete record.** In 10 offline-replay runs plus 5 rejected
   inputs, the log contains exactly the records expected (one `segment` per start or resume of the agent, one
   `rejected` per refused input), and every record has all of its named fields (`segment`: ts, event, run_id,
   llm_mode, input, output, duration_s, usage, error; `rejected`: ts, event, input, status, error).
   **Target: 100% of expected records present and 100% complete, in all 3 trials.**
   *Why:* the log is only useful if absence means "nothing happened". A missed record is the failure I would never
   find later, so anything under 100% defeats the purpose; a looser target would hide one lost record per hundred.

2. **Failures are visible, not silent (the bad path).** Six deliberate failures (payout file not found, no input
   given, a file that is not a payout report, an upload over 2 MB, a valid report the offline cache has never seen,
   a rejected API key): each must end as a clear 4xx response or a run that reaches status `error` within 30
   seconds (no hang, no 500), and each must leave a log record with a non-empty `error.kind`.
   **Target: 6 of 6 in each of the 3 trials.**
   *Why:* these are the failures an owner can actually hit. A hang or a 500 with nothing logged is the worst case, so
   the target is all six; 30 seconds is the longest I would make an owner wait before they think the app froze.

3. **A live run costs under $0.50 on average, and no run above $0.60.** Three consecutive live runs per trial,
   dollars computed from the token counts the API returned at the published `claude-sonnet-5-5` rates.
   **Target: mean of the 3 runs <= $0.50 and every run <= $0.60, in all 3 trials (9 runs).**
   *Why:* a pilot run cost $0.37. $0.50 leaves room for run-to-run variation in how many cases the agent works on;
   at that price 100 owners a day is $50, the most I would call affordable for something recovering ~$95 per owner
   payout. A stricter $0.40 would fail on normal variation; a looser $1.00 would hide a runaway loop.

4. **A live run finishes in under 180 seconds (warm start).** Wall time from start to `done`, the same 9 runs as
   criterion 3, where the "owner" answers instantly, so this is agent time only.
   **Target: all 3 runs under 180 s in each trial (9 of 9).**
   *Why:* the pilot took 119.5 s; 180 s is the length of my demo and about as long as an owner will wait for a
   payout analysis. The first run in a trial starts with a cold prompt cache, so I am measuring it too and not
   excluding it.

5. **Concurrent runs are billed to the right run.** With 2 live runs overlapping in time, the sum of the model
   calls logged across both runs equals the actual number of model calls made (counted independently at the model
   wrapper).
   **Target: exact match (difference 0) in each of 3 trials.**
   *Why:* the cost and token fields are only trustworthy per run if they are attributed per run. The usage counter I
   read from is process-wide, so I expect overlapping runs to be the case where this breaks; a tolerance would hide
   the double counting I am worried about.
