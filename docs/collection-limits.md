# Collection limits

`config/queries.json` version 1.2 retains the approved numeric caps and makes retry
and timeout accounting explicit. Inspect/validate the policy without any network:

```bash
python3 scripts/robin.py limits
```

On Windows use `python`. When installed, `robin-limits --config config/queries.json`
is equivalent. Validation rejects malformed limits, booleans used as integers,
unsupported collection modes, duplicate query IDs, and invalid date windows.
The command prints limits, the configuration SHA-256, query counts, and live blockers.
A valid policy can still be disabled for collection; valid does not mean live-ready.

## Effective limits

| Setting | Value | Accounting |
|---|---|---|
| Results per query | 20 | Retain at most 20 returned search entries before page selection |
| Page fetches per query | 10 | Every dispatched attempt counts, including failures and retries |
| Page fetches per batch | 30 | Shared across all queries; exhausted budgets are not refunded |
| Text characters per page | 10,000 | Retain at most this many Unicode code points |
| Text bytes per page | 100,000 | Retain at most this many UTF-8 bytes without splitting a character |
| Source request concurrency | 2 | Sequential MCP calls; search fan-out at most two workers |
| Operation timeout | 90 seconds | Total after dispatch, including retries and backoff; also bounded by the collection window |
| Retries | 2 | At most three attempts, only for explicitly classified transient failures |
| Retry backoff | 2, then 4 seconds | Exponential; maximum configured delay 10 seconds |

Text stops at whichever character/byte cap is reached first and carries a truncation
flag and retained counts. The byte cap applies to extracted text, not raw HTTP
transfer size. At this character limit the byte cap is normally redundant, but both
are checked. The result cap governs retained search entries; upstream Robin may
receive more entries from engines before applying its return cap.

The registry contains 15 queries, so enabling all would permit up to 300 retained
search entries. The shared page-attempt budget remains 30. It does not become 150.
A query can use its page budget on failed attempts and therefore return fewer than
10 usable pages. Once a cap is reached, stop scheduling that kind of work and log
the reason in the future run manifest. No automatic query pivots or recursive crawl.

## Conditional page collection
Search titles/snippets come first. Fetch only a retained direct result when metadata
cannot establish relevance (`insufficient_relevance`) or support required research
fields (`missing_research_fields`). The reason must be recorded when optional page collection is implemented.
Only current-query result IDs are eligible; beginning the next search invalidates
older IDs. Downloads, attachments, samples, credentials, source interaction, and
recursive links remain excluded by the approved scope.

## Implemented guard API
`robin_collect.limits` provides:
- `load_policy`: strict validation, immutable numeric limits, and live-window checks.
- `Policy.search_parameters`: explicit `max_results=20`, `threads=2`.
- `Policy.scrape_parameters`: one-page calls with `content_chars=10000`, `threads=1`,
  and `allow_clearweb=False`.
- `LimitedExecutor.search`: caps retained entries and registers direct result IDs.
- `LimitedExecutor.fetch_page`: requires an eligible ID/reason, charges every
  attempt atomically, applies retry/timeout rules, and bounds returned text.
- `bound_text`: UTF-8-safe output clipping with explicit truncation metadata.

Each executor represents one batch. It serializes MCP calls so Robin's internal
search workers cannot multiply concurrency across simultaneous queries. Callbacks
receive the remaining deadline and must honor cancellation. Only
`TransientCollectionError` is retried; authentication, scope refusals, malformed
responses, and unknown errors must not be classified as transient by default.

The collection window uses timezone-aware start/end timestamps, end-exclusive,
within the approved seven-day scheduling window. It is checked before dispatch,
before retries, and before accepting output. In-progress callbacks are cancelled
at the earlier operation/window deadline. Publication lookback is a separate
relevance rule, not the collection execution window.

## Integration boundary
These guards are implemented and tested with synthetic async callbacks. The
structured metadata adapter now persists charged attempts and shared deadlines;
see [live collection](live-collection.md). It does not retrieve result pages. Manual
UI actions and arbitrary MCP clients are not governed by this controller. The
offline CSV importer does not simulate source-fetch budgets.

For richer collection beyond the implemented metadata adapter, the integration must:
1. Pass explicit policy parameters instead of trusting editable UI defaults.
2. Route all source operations through one batch executor and classify retryable
   errors conservatively. Finish a query before starting the next one.
3. Persist counters/checkpoints and the policy hash. An interrupted run must resume
   the same budgets; recreating an executor must not reset a partially used batch.
4. Propagate deadlines and terminate/confirm completion of remote work before
   retrying or starting another request. Client cancellation alone does not prove
   Robin's background requests stopped.
5. Enforce MIME/download restrictions, raw-transfer bounds, source/date relevance,
   and sanitization before persistence. Text clipping after retrieval cannot enforce
   a raw network byte limit or prevent excluded content appearing on a page.
6. Record dropped result counts, fetch reasons, retries, timeouts, budget stops, and
   truncation metadata in a restricted manifest.

The UI defaults template currently matches the approved supported values. Numeric
policy changes need matching default-template updates until the live adapter is
wired to explicit parameters. Raw provider environment files are never printed or
overwritten by the limits command.

Queries remain disabled and collection dates unset. Policy inspection and tests
perform no live search, page retrieval, or model call. Model selection is still
required before model-dependent filtering/refinement; this milestone configures no
provider and makes no paid requests.
