# Setup and pilot results

## Outcome and completion boundary

The six-step installation-and-pilot checklist is complete. Robin can execute one
bounded metadata-only search through Tor and MCP, with verified cleanup and an
audit report. **The sanitized CSV collection deliverable is not complete.**
The pilot retained aggregate counts, not source findings. Its results cannot be
reconstructed into a findings CSV; the full collection phase requires new searches.

## Verified run

Evidence: local ignored report `outputs/pilot-45bba1a45cb542bd8c518683c19e7016.json`.
Report SHA-256: `cc6f76e509808b3df4617adddbcd016088611f29d4519469115be99044449590`.
This document records aggregate evidence only; it does not commit the report or
any raw titles, URLs, credentials, or source content.

| Item | Observed value |
|---|---|
| Run ID | `pilot-45bba1a45cb542bd8c518683c19e7016` |
| Date | 2026-11-20 |
| Query ID | `q001` |
| Original query | `organizational data breach announcement` |
| Refined query | Unchanged; already four words; no model refinement |
| Research domain mapping | `threat_intel` for the approved organizational-exposure scope |
| Collector started (UTC) | 2026-11-20T22:44:31.720668+00:00 |
| Collector finished (UTC) | 2026-11-20T22:45:07.638745+00:00 |
| Disposable execution/cleanup duration | 30.93 seconds |
| Overall duration including preparation/health | 35.918 seconds |
| Robin version | v3.1, pinned by immutable image digest |
| Base configuration hash | `82e3724c33e3d8cc4a1b58a7a9ead8eb6c820d28f13a4a4459d7cf899bced630` |
| Search calls | 1 |
| Result page fetches | 0 |
| Model calls | 0 |
| Disposable container cleanup | Confirmed |

The effective one-run window was 2026-11-20T22:44:31.720668+00:00 to
2026-11-20T23:44:31.720668+00:00 (end-exclusive). It was a scheduling bound,
not an hour of continuous collection. The tracked registry stayed disabled.

The validated host used Docker Desktop through its Windows CLI. Direct Ubuntu
Docker use still requires enabling Docker Desktop WSL integration; follow the
[setup guide](robin-setup.md). CI runs synthetic and configuration checks, not
live collection. The earlier implementation validation passed 30 synthetic tests.

## Engine coverage and result counts

| Measurement | Count |
|---|---:|
| Engines queried | 16 |
| Engines returning links | 5 |
| Engines returning an empty response | 1 |
| Engines failing | 10 |
| Raw links reported by Robin | 58 |
| Links after upstream deduplication | 41 |
| Entries returned under the requested cap | 20 |
| Returned entries with titles | 20 |
| Returned entries with URLs | 20 |
| Returned entries with snippets | 0 |
| Titles exceeding Robin's listing limit | 2 |
| URLs exceeding Robin's listing limit | 0 |

Six of sixteen engines responded, five with links and one empty. This is partial
coverage. The stricter pilot transport settings (3-second connect, 5-second read,
zero HTTP retries) can exclude slow engines; failures do not establish that their
content was absent. The earlier engine availability check and this query test
measure different things under different timeouts and should not be equated.

Twenty returned search entries are not twenty relevant findings or verified
breaches. Relevance, source publication dates, language/content eligibility, and
claim authenticity were not assessed. Upstream deduplication does not validate
the project's later source-observation and cross-source claim-grouping rules.

## Input mapping for the collection adapter

| Input field | Robin source | Required handling |
|---|---|---|
| `query_id` | Registry identifier | Preserve every matching query association |
| `url` | Result `link` | Validate/normalize in memory, derive a source pseudonym; never use a truncated locator as a complete URL |
| `title` | Result `title` | Sanitize and pseudonymize under the approved policy before persistence; preserve truncation evidence |
| `snippet` | Absent from the MCP search listing | Use an empty string for the current import contract and record unavailable in the run manifest; do not invent text |
| `collected_at_utc` | Collector timestamp | Assign a timezone-aware UTC timestamp, separate from source-claimed publication date |

Engine counters, result caps, missing fields, and truncation belong in the run
manifest. The current CSV does not implement every proposed provenance field.
The aggregate pilot report cannot supply the discarded per-result titles/URLs.
See [input format](input-format.md) and [controlled pilot](controlled-pilot.md).

## Installation-and-pilot checklist

- [x] Approved research scope and query registry recorded.
- [x] Robin v3.1 installed and pinned with reproducible team instructions.
- [x] Docker, UI, strict Tor bootstrap, and real MCP connectivity verified.
- [x] Numeric collection limits validated, with reusable guarded execution code.
- [x] One controlled metadata-only query run and cleanup confirmed.
- [x] Observed results, field mapping, limitations, and handoff documented here.

The setup checklist confirms technical readiness for the next implementation phase.
A model was unnecessary for this transport test; model-dependent filtering and
refinement still require a selected, approved configuration. Production collection
dates are not set, and this completed pilot window does not authorize recurring runs.

## Subsequent implementation status

The [live collection guide](live-collection.md) now documents the completed
structured metadata adapter milestone. The remaining-work table below records the
handoff state at the initial aggregate-only pilot; consult the live guide for
current implementation and validation status.

## Remaining work for the dataset deliverable

| Work package | Required output | Completion evidence |
|---|---|---|
| Live adapter and resumable orchestration | Structured observations, restricted manifests, persisted budgets/checkpoints | Synthetic interruption/restart tests preserve provenance and budgets |
| Approved sanitization | Organization/source pseudonyms, required personal-data/secret removal, retention handling | Policy-specific tests and a second-person residual-content review |
| Relevance and source eligibility | Inclusion/exclusion decisions, rejection reasons, dates, language, categories | Reviewed retained/rejected samples against the approved scope |
| Dataset identity and deduplication | Distinct source observations and query associations; near-duplicate review | Cross-source claims remain distinct; repeated retrievals and meaningful changes are handled correctly |
| Agreed query batch | Bounded run of the frozen query set during explicit dates | Traceable run outcomes; failures distinguished from successful empty searches |
| Review and export | Sanitized CSV, data dictionary, quality report | Required fields, parse/encoding checks, formula defense, sanitization review, and approved sharing destination |

The immediate implementation target is the live adapter and manifest contract,
using synthetic records first. Approved sanitization must be in place before real
source content is persisted. The current baseline sanitizer and content-only exact
deduplication do not yet fulfill the approved policy's organization pseudonymization
and separate-source observation requirements. See [implementation plan](implementation-plan.md).
