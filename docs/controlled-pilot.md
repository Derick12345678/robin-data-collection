# Controlled single-query pilot

The pilot verifies live MCP search transport and source-result metadata shape.
It does not assess relevance, verify organizational exposure claims, fetch result
pages, or produce the analytical dataset.

## Commands

```bash
python3 scripts/pilot.py
python3 scripts/pilot.py --run
```

The first command is a no-network plan. The second explicitly runs one query:
`q001`, `organizational data breach announcement`, unchanged because it is already
a short query. The approved research domain maps to Robin's `threat_intel` preset.
No model is selected or called. On Windows use `python`.

The run checks local Docker/UI/Tor/MCP health first. It creates a disposable pinned
Robin container sharing only the project UI container's network namespace, so the
search uses that container's existing Tor SOCKS listener. No investigation volumes,
host directories, provider keys, or Docker socket are mounted into the pilot.
The normal Robin entrypoint is bypassed: no second Tor daemon or model refresh.

The main tracked query registry remains disabled. An effective per-run configuration
enables only q001 and, when collection dates are unset, assigns a one-hour window
starting at invocation. Existing configured dates are respected. The report records
this effective window and the base policy hash. This is one explicit command, not
a schedule or authorization to run the entire registry.

## Bounds and cleanup
The pilot calls `robin_search` once, with 20 results and two workers, through the
shared `LimitedExecutor` guard. Page fetches are disabled. Per-engine connect/read
waits are tightened to 3/5 seconds and HTTP retries are disabled in this isolated
search process. These are stricter than the approved maximums and do not change
the running UI's settings. Tight waits may reduce coverage on slow onion services.

The dispatched operation has the approved 90-second deadline. The outer container
budget is 110 seconds to allow MCP initialization/cleanup. On every exit the parent
force-removes the entire disposable container, which terminates remote work rather
than merely cancelling an MCP client. Cleanup must be confirmed before a run is
reported successful. A timeout is recorded as incomplete, with an unknown result
count; it must never be reported as a successful empty search.

## Report and data handling
Each live run writes `outputs/pilot-<uuid>.json`, ignored by Git. It contains the
original/refined query, UTC timestamps/window, policy hash, pinned release/image,
effective limits, aggregate engine coverage, returned-result count, field-availability
counts, truncation indicators, and cleanup confirmation. It records whether the
search was completed, returned no results, failed, or could not reach engines.

Only aggregate numeric metadata is retained. Raw titles and source URLs remain
inside the disposable process and are not printed, exported, or saved. This avoids
using the incomplete baseline sanitizer as though it met the approved organization
pseudonymization policy. No raw findings are saved into Robin investigations.

A successful transport test does not demonstrate source relevance, publication-date
eligibility, model quality, or the completeness of dark-web coverage. A true empty
result requires an engine response; an engine outage is a separate status.

## Mapping for the next adapter milestone

| Pipeline input | Robin search source | Pilot handling |
|---|---|---|
| query_id | Registry ID q001 | Recorded in report |
| url | Search result link | Availability counted; raw value discarded |
| title | Search result title | Availability counted; raw value discarded |
| snippet | Not supplied by the current MCP search listing | Mark unavailable; never invent source text |
| collected_at_utc | Collector timestamp | Recorded as collection time |

The bounded listing truncates titles/links under upstream limits; the aggregate
report notes entries that exceed those limits. The next adapter must preserve
truncation/provenance and implement the approved sanitizer and review process before
persisting content. Full batch orchestration, resumable budgets, relevance/date
filtering, approved exports, and optional bounded page collection remain separate.
