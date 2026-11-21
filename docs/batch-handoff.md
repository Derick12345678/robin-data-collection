# First frozen batch handoff

Run `agreed-batch-01` completed all 15 approved queries on 2026-11-21 UTC.
Its frozen scheduling window is 2026-11-21 01:42:21 UTC through
2026-11-22 01:42:21 UTC. This was one batch, with no recurring schedule.

## Collection outcome

| Measure | Result |
|---|---:|
| Completed queries / charged search attempts | 15 / 15 |
| Distinct sanitized observations | 115 |
| Automatic candidate / needs-review labels | 3 / 112 |
| Direct page attempts / batch ceiling | 30 / 30 |
| Successful page fetches / failures | 28 / 2 |
| Distinct observations with page text | 2 |
| Unknown source publication dates | 115 |
| Near-duplicate candidates | 21 |
| Source-change candidates | 27 |
| Uncertain page reservations | 0 |
| Capture containers left behind | 0 |
| Actual release-review votes | 0 |

The source/change and duplicate flags include global observation history and are
heuristics for review, not verified incidents. Automatic candidate labels do not
establish relevance or authenticity.

Across query-engine attempts: 240 were dispatched, 95 returned links, 82 returned
empty responses, and 63 failed. Upstream counters reported 1,123 raw links, 838 after
per-query deduplication, and 688 after upstream selection. These upstream diagnostic
counts precede the adapter's retained-result ceiling and cross-query observation
deduplication; they are not distinct dataset rows. At most 20 result records were
retained per query.

The 28 successful page requests repeatedly captured the same two observations.
Query overlap and repeated page selection consumed the page budget. Both canonical
contexts are currently available in the local review session; the other 113
observations lack page context. This yield does not demonstrate adequate claim-level
research coverage. A subsequent approved batch should prioritize unseen source
items before spending more page requests; the current batch was not extended.

Thirteen per-query reports mark review-context delivery failed because a redundant
later receipt did not match the immutable first capture. The original two bound
contexts remain available. The implementation now filters redundant receipts so
one cannot block delivery of unrelated new contexts, while conservatively reporting
incomplete delivery. No raw text was retained to repair unavailable evidence later.

## Team action

Run `python3 scripts/review.py access` from the project directory to obtain the
private local review link. Enter `agreed-batch-01`. Keep the service running: contexts
are held only in memory and expire 24 hours after their original page retrieval.
Use the sanitized JSONL alongside the existing session for duplicate/change flags
if that session predates the structured-record UI panel.

Actual reviewers must assess source context and privacy. Included records need two
consistent distinct reviewer IDs. All 115 currently remain unresolved for release;
records with no context cannot be included. Rejection or a later separately approved
collection can resolve insufficient evidence. Do not manufacture positive findings.

A local release-readiness bundle was generated with its dictionary, provenance,
review audit, and quality report. Its status is `blocked_pending_review`; it contains
no approved CSV. Once actual decisions resolve the batch, use:

```bash
python3 scripts/collect.py release --run-id agreed-batch-01
```

An explicit `--allow-partial` can release a nonempty eligible subset with exclusions
recorded. It cannot approve the current entirely unreviewed batch. See
[the live workflow](live-collection.md) for full instructions.

Local data stays in ignored `outputs/live/agreed-batch-01/` and
`outputs/releases/agreed-batch-01/`. Only this aggregate handoff is committed.
The implementation passed 68 local tests and GitHub CI on Python 3.11, 3.12, and 3.13,
plus deployment configuration checks. No human record decisions were made by the agent.
