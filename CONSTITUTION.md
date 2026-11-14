# Reclaim Constitution

These rules govern every design and coding decision.

1.  Human approval gate. Nothing is ever sent to a delivery platform without the owner's explicit approval. The agent drafts, the human decides.
2.  Evidence or silence. The agent never invents evidence. A claim in a dispute must trace to a real document, timestamp or record. If proof is missing, the case is marked weak, not padded.
3.  Honest scoring. Every case gets a confidence score with written reasons. The agent may recommend skipping a case.
4.  No fraud accusations. Dispute drafts state facts (the ticket lists the item, the timestamps show handoff) and never accuse the customer of lying.
5.  Deadline awareness. Every case carries its filing deadline (14 days DoorDash, about 30 days Uber Eats). The queue sorts by recoverable value times win probability, with deadline as tiebreaker.
6.  Works with what the owner has. No POS integration required. Inputs are a payout CSV or screenshot, and photos of tickets.
7.  Deterministic where possible. Parsing, date math and money math are plain code with tests. The LLM handles only what needs judgment: reading messy images, weighing evidence, writing prose.
8.  Everything is traceable. Each run produces a LangSmith trace and a saved case folder, so any decision can be audited.
9.  Demo resilience. All external calls are cacheable. The demo must run offline from cached data.
10.  Privacy. Customer names and order details stay local. Nothing is logged to third parties beyond the model and tracing calls the user has enabled.
11.  Scope discipline. Solo build. Cut features before cutting tests for the core pipeline.
12.  Honest pitch. Never claim nobody has done this. Existing services target chains. Reclaim targets independents with no back office.
