# Retrieval repair validation handoff

**Current scope:** see [primary-source claim screening](primary-claim-screening.md).
The owner rejected the latest three readable pages; that pilot is quarantined.
News, tutorials, and generic service offers cannot qualify as primary findings.


The original `agreed-batch-01` is quarantined following the owner's relevance
assessment. Its 115 observations remain in the audit store and cannot be released.
No human votes were fabricated and no old observations were relabelled as findings.

## What was verified
The pinned Robin parser could accept navigation and advertising as results, and
its query-only Ahmia request omitted the public form's current hidden field.
Ahmia's source code redirects requests without that field to its homepage. The
adapter now follows the ordinary same-origin public search form and parses only
recognized result items. It does not generate hidden-field values or bypass a
challenge. An unrecognized form or result layout stops the run.

`relevance-validation-01` used the initial strict parser but the old request flow.
It retained zero observations and failed explicitly on unsupported layouts after
two initial engine connection failures. Cleanup was confirmed. Its conservative
ledger retains 15 uncertain page reservations despite zero confirmed page requests;
the historical ledger has not been silently refunded. The subsequent code handles
confirmed no-fetch layout refusal separately and releases unused reservations.

The corrected `relevance-validation-02` completed three approved queries under the
same private one-hour validation policy:

| Measure | Result |
|---|---:|
| Queries completed / search attempts | 3 / 3 |
| Distinct retained discoveries | 58 |
| Discoveries with search descriptions | 58 |
| Screened eligible / deferred / excluded | 25 / 26 / 7 |
| Distinct page URLs attempted | 15 |
| Repeated page requests | 0 |
| Readable page captures / fetch failures | 3 / 12 |
| Truncated page contexts | 1 |
| Uncertain page reservations | 0 |
| Model calls | 0 |
| Human relevance reviews | 0 |
| Approved findings / final CSV | 0 / none |

Each query made two engine HTTP requests (form and results). Fifteen unsupported
engines were skipped per query without network requests. Engine coverage counts
exclude those skips. All three responses matched the result profile. Each query
retained at most 20 records, with ranking applied before the cap; repeated matches
were deduplicated into 58 source/content observations.

All three captured pages use specific paths rather than site-root URLs. Two have
provisional exposure-claim hints; the truncated third was automatically flagged
outside the inclusion criteria. These labels are not human relevance decisions
or authentication of the alleged exposure. The 12 failed requests and English-only,
single-engine coverage limit what can be concluded.

## Review next
Obtain the updated service's private access link:

```bash
python3 scripts/review.py access
```

Enter **`relevance-validation-02`**. The default view shows only the three available
page contexts. The all-discoveries view exposes the remaining discoveries and why
they lack page evidence. Source contexts expire 24 hours after their original
retrieval and are lost on service restart. The old service was restarted to apply
the approved UI corrections, discarding its irrelevant temporary contexts.

Reviewers must judge actual relevance and privacy; do not approve the automated
labels by default. A final CSV still requires two consistent actual reviewers for
included records. The larger-batch quality gate remains **blocked**: there are
zero actual reviews and only three readable page captures, below the ten-page
minimum. At least 80% relevance across 10â€“20 reviewed unique pages is required.

Do not expand collection automatically or keep retrying inaccessible sources to
manufacture a passing sample. The next evidence-informed decision is whether the
three accessible pages are useful and whether a revised, separately dated pilot
should improve source availability or add another independently verified engine.
The current implementation does not claim that the research dataset is finished.

Implementation checks: 84 unit/regression tests passed; the pinned MCP integration
passed with Docker networking disabled. The synthetic integration demonstrates
parser/capture behavior only and never counts toward measured live precision.
