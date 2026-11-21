# Retrieval quality repair and validation

**Current scope:** see [primary-source claim screening](primary-claim-screening.md).
The owner rejected the latest three readable pages; that pilot is quarantined.
News, tutorials, and generic service offers cannot qualify as primary findings.


## Why the first batch is quarantined
The owner assessed the two captured sites and the remaining discoveries as outside
scope. `agreed-batch-01` is quarantined with an append-only run event; its 115
observations, query matches, and original reports remain for audit. Inclusion,
release (including partial release), and resume are blocked for a quarantined run.
This lifecycle action is not a fabricated record-level human review.

The failed batch spent all 30 page attempts on two URLs. Generic link extraction,
arrival-order selection, broad keyword hints, and no shared attempted-source check
produced transport success without useful research evidence.

## Implemented controls

1. **Request flow:** Ahmia currently requires the ordinary public GET search form.
   The adapter first reads its publicly provided hidden field, submits it only to
   the expected same-origin search endpoint, and never guesses or stores the value.
   The old query-only request can be redirected to the homepage. See
   [Ahmia request handling](https://github.com/ahmia/ahmia-site/blob/master/ahmia/views.py).
2. **Result extraction:** only the Ahmia result profile is enabled. It recognizes
   `#ahmiaResultsPage ol.searchResults > li.result` and heading links, with bounded
   descriptions. Navigation, outside anchors, and marked advertising are ignored.
   Explicit `#noResults` is an empty answer; an unrecognized layout is an explicit
   failure. There is no generic all-anchor fallback. Unsupported engines make no
   source request and count as skipped, separately from engine failures.
3. **Screening:** finite deterministic hints prioritize a specific named target,
   exposure claim, and data subject in nearby text. Directories, generic advertising,
   and educational pages are excluded from page selection. Weak or ambiguous matches
   remain discoveries, not findings. Title capitalization is only a heuristic;
   humans must establish actual relevance. Results are ranked before the 20-result
   retention ceiling, with a stable URL tie-breaker instead of worker arrival order.
4. **Page prioritization:** only screened candidates spend page slots. A durable
   HMAC source ledger is shared across queries; a prior success or failure is not
   fetched again in that run. Same-query duplicates are also skipped. Exact metadata
   rediscovery reuses canonical enriched evidence and adds the new query association.
   A root URL is penalized, rather than universally banned: legitimate announcements
   can appear on a landing page. No recursive crawl is introduced.
5. **Review:** the default view shows discoveries with available page context.
   An optional all-discoveries view shows missing-evidence items. Context states
   distinguish never collected, failed fetch, expired, and lost session/delivery.
   Screening reason, score, engine/profile, selection reason, and quarantine status
   are visible. No original source free text enters the durable database or exports.
6. **Expansion gate:** a larger run (more than three queries) requires a completed
   validation run with 10Ã¢â‚¬â€œ20 unique captured pages actually reviewed, at least 80%
   relevance, no reviewer disagreement, matching collector fingerprint, and matching
   scope/limits. No automatic label or synthetic fixture counts as a human review.
   Included CSV rows still require two consistent actual reviewers, independently
   of the pilot relevance gate. If the pilot yields too few candidates, stop and
   revise retrieval under a new policy; do not manufacture yield or expand budgets.

The parser profile was checked against [Ahmia's published result template](https://github.com/ahmia/ahmia-site/blob/master/ahmia/templates/tor_results.html).
Published layout compatibility does not guarantee current live availability. Add
another engine only with its own verified layout, explicit empty/error handling,
and regression fixtures. An engine HTTP 200 alone is not evidence of useful search.

## Model use and cost
The collection path calls **no AI model**. Python performs extraction and screening;
requests travel through Tor. There are no model API calls or model charges for this
workflow. Robin supports optional model-assisted refinement/filtering, but those
features are not enabled here. A future local or hosted model needs its own
configuration and privacy/cost review; deterministic screening does not imply
semantic understanding or verified breach authenticity.

## Commands
The local validation run uses a separate, exclusively created one-hour policy:

```bash
python3 scripts/collect.py validation-policy
python3 scripts/collect.py run --validation --enrich \
  --policy data/live/validation-policy.json --run-id relevance-validation-01
python3 scripts/collect.py quality-status --run-id relevance-validation-01
python3 scripts/review.py access
```

These document the already dispatched project validation run; do not repeat it
blindly. The reviewed sample target is 10Ã¢â‚¬â€œ20 unique pages; validation dispatch is
limited to the first three approved queries, at most 20 retained results each and
five page attempts each. The approved 30/batch, 10/query, text, timeout, and retry
ceilings still apply. No recurrent collection or policy renewal occurs.

Once actual human reviews pass the gate, a separately frozen larger policy can
reference that run:

```bash
python3 scripts/collect.py run --enrich --policy data/live/batch-policy.json \
  --validated-run relevance-validation-01 --run-id separately-approved-batch
```

The old batch policy is not renewed automatically. Collector code or scope changes
invalidate a previous gate result. Review contexts are private process memory,
expire after 24 hours, and disappear on restart. Obtain a new local access link
with `scripts/review.py access` after the service restarts. Never share its token.

## Verification
Run `PYTHONPATH=src python3 -m unittest discover -s tests` in the WSL project.
`python3 scripts/validate_capture.py` additionally exercises the pinned MCP capture
with synthetic navigation, a real result-shaped item, and page text inside Docker
with `--network none`. It verifies result extraction, bounds, private context
separation, and zero model calls without contacting a source site.

Synthetic fixtures test implementation behavior only. They cannot establish live
relevance precision. A blocked pilot is an honest outcome and must remain blocked.
