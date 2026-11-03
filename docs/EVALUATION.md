# MAVES Evaluation Procedure

Automated tests prove that the **software** behaves correctly for given model
outputs (they mock the LLM). They do not prove that the **model's** reasoning,
role choices or conclusions are good. This procedure covers the second part
and must be done by a person reading the output. Passing it does not make any
model conclusion objectively true.

## 0. Prerequisites

- Stack running: `docker compose up -d`, migrations at head
  (`docker compose exec backend alembic upgrade head` -> `011`).
- A Groq key with enough quota. On the on-demand tier `openai/gpt-oss-20b`
  is limited to **8,000 tokens per minute** plus longer-window limits; one
  3-round, 4-agent debate with judge and verdict uses roughly 60-90k tokens,
  so run debates one at a time and expect short rate-limit pauses.

## 1. Panel selection (cheap, scripted)

```bash
docker compose exec backend python -m scripts.evaluate_topics
```

Read-only. For each topic it prints the domains, key questions, built-in
agents with reasons, AI specialist roles and any proposals rejected by
validation. Check per topic:

- [ ] Every agent answers at least one key question; no obviously
      irrelevant agent (e.g. a Doctor on a pure legal question).
- [ ] Specialists only where a built-in covers the need only generically;
      none for everyday topics.
- [ ] No specialist duplicates a built-in; rejected items have sensible
      reasons.

## 2. Full debates (UI)

Run each topic below as: **New Debate -> Automatic selection -> review
the panel -> Start Debate (3 rounds)**, then **Final Verdict -> Generate**,
**Agent Performance -> Judge**, and **Download PDF Report**. For an
evidence-based verdict, first run **Claims & Verification -> Extract claims
-> Verify** on the most important claims, then regenerate the verdict.

| # | Topic | Notes |
|---|---|---|
| 1 | Should AI be allowed to make important decisions in healthcare? | |
| 2 | Does remote work improve productivity? | everyday topic: expect no specialists |
| 3 | Should governments prioritise renewable energy subsidies over fossil fuel investment? | |
| 4 | How should governments regulate cryptocurrency? | |
| 5 | Should governments be allowed to access encrypted personal data for cybersecurity? | |
| 6 | Is moderate red wine consumption good for heart health? | conflicting evidence: expect mixed/inconclusive with reason "conflicting_evidence" |
| 7 | Will brain-computer interfaces be common in classrooms by 2040? | insufficient evidence: expect inconclusive |

Checklist per debate:

- [ ] **Selection:** panel matches step 1; specialists labelled "AI specialist role".
- [ ] **Completion:** status Completed; "N of N rounds completed"; on failure the
      reason names round/turn/agent and **Resume** continues without duplicates.
- [ ] **Readability:** openings state one position + main argument; rebuttals
      link ("Responding to ...") to a real earlier turn and concede where fair;
      closings revise or address the strongest objection; turns stay within
      the word limits (200 / 180 / 160).
- [ ] **Evidence:** sources relate to the claims; nothing fabricated (every
      source has a real URL from retrieval).
- [ ] **Verification:** supported / contradicted / insufficient labels match
      what the sources say (spot-check 3 claims by reading the sources).
- [ ] **Verdict:** answers the question; position consistent with the verified
      evidence; inconclusive verdicts state *why*; confidence consistent with
      the evidence basis; not tied to the best-performing agent.
- [ ] **Uncertainty:** limitations and unresolved questions are specific.
- [ ] **Scores:** per-agent dimensions differ where contributions differ; equal
      scores carry the "same final score" note; ranking is labelled as
      argument quality only.
- [ ] **PDF:** verdict first, agent performance separate, transcript complete,
      partial-report notice when the debate is incomplete.

Record findings in a copy of this table; keep software defects (wrong
status, missing data, crashes) separate from model-quality observations.

## 3. Recorded live results (2026-10-26, `openai/gpt-oss-20b`)

Software findings, all fixed and covered by tests:

- Mid-debate failures: reasoning model spent the whole 1024-token turn
  budget on hidden reasoning (empty answer) and Groq's 8k-TPM limit asked
  for ~21 s waits that a 20 s cap refused. Fixed with a 2048-token budget,
  budget escalation on empty answers and a 60 s Retry-After cap.
- Identical judge scores: one-call judging let the model copy one score card
  to every agent (5.09 for all). Per-agent judging produced 8.17 / 7.92 /
  7.83 / 7.42 on the same debate.
- Topic analysis: 5 of 7 topics initially failed (malformed JSON, built-ins
  not matched, 413 rate-limit responses). With Groq JSON mode, one bounded
  re-ask, name matching, panel top-up and 413-as-transient: 7 of 7 analysed.

Model-quality observations (not defects; judge for yourself):

- Panels were too broad at first (5-6 agents nearly every time). After
  prompt tuning: 4 agents for healthcare and remote work.
- The model proposes specialists sparingly: crypto -> "Blockchain Technology
  Specialist"; brain-computer interfaces -> "Educational Technology
  Specialist" (first run); healthcare and remote work -> none (built-ins
  judged sufficient). This is allowed by design; it is not forced.
- Full 7-topic debates (section 2) were **not** run: the account's
  longer-window Groq limit was reached (a 429 asked to wait 19 minutes).
  Run section 2 when quota allows.
