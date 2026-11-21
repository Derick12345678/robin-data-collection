# Structured live collection and review

## Supported milestone
The live adapter now connects Robin MCP search to durable sanitized observations,
query provenance, a resumable run manifest, and a quality report. This is a
metadata-only release. It does not retrieve result pages, send model prompts,
produce an approved dataset, or claim that an exposure is authentic.

Untrusted titles/excerpts are transformed inside the disposable container before
anything returns to the host. The output is strictly allowlisted. Provider keys,
source free text, raw URLs, and remote exception messages are not persisted.

## Commands
Run from the project directory:

```bash
python3 scripts/collect.py prepare
python3 scripts/collect.py plan --pilot
python3 scripts/collect.py run --pilot --run-id my-single-query-check
python3 scripts/collect.py resume --run-id my-single-query-check
python3 scripts/collect.py export --run-id my-single-query-check
```

On Windows, `python scripts/collect.py ...` launches the same command inside the
project's WSL distribution. SQLite always runs natively in WSL for a WSL checkout.
The Docker helper can use Docker Desktop's Windows CLI via WSL interop even when
distro integration is disabled; project paths are translated with `wslpath`.
Direct Linux Docker remains supported. No second Docker daemon is installed.

`prepare` creates a random 256-bit HMAC key under private `data/live/hmac.key`
without printing or replacing it. Keep this key backed up in the team's secret
manager, separate from exported records. Losing or changing it breaks matching;
an existing database refuses a replacement key. An existing database without its
key is not silently reinitialized. Do not copy keys into issues, PRs, or output.

`plan` has no network activity. `run --pilot` enables only approved q001 in an
effective per-run configuration. If dates are unset it uses a one-hour scheduling
window. The tracked query registry stays unchanged. A configured batch requires
enabled, reviewed short queries and explicit valid dates; no automatic query
refinement or pivots occur. Query text is represented by HMACs in the manifest.

## Sanitization policy
The default `structured_only` policy withholds every untrusted free-text field,
including identifiers that regex or named-entity recognition might miss.

- Source URLs become stable keyed source pseudonyms.
- Original titles become keyed title markers, never partial redacted originals.
- Excerpts, if available, become `[TEXT_WITHHELD]`.
- Summaries, categories, decisions, and reasons come only from finite templates.
- Known organizations can be matched against a private exact-alias registry and
  replaced by stable organization pseudonyms. Unknown organizations are marked
  unknown, not guessed.
- Missing snippets, dates, source type, and language remain explicit unknowns.
- Dates, booleans, counters, keys, and structured values are validated before storage.

This provides strong data minimization, with reduced analytical detail. It is not
a claim that every entity has been detected. No original title or source locator
can be recovered from a review file. Ambiguous records need a separately approved
source-context review workflow; changing a label cannot recreate missing evidence.

Optional private alias configuration: create `data/live/entities.json` with mode
0600, mapping canonical organization names to aliases. See the entirely synthetic
[example](../examples/entities.synthetic.json). The registry is never exported or
committed, and its keyed fingerprint is frozen per run. Entity-registry changes
require a new run; prior sanitized snapshots remain unchanged.

Regex categories can identify some emails, phone-like strings, IPv4-like values,
and labelled secrets. All other unstructured information is still withheld. This
also covers unknown personal names, addresses, government/financial identifiers,
source handles, and exposed sample records without attempting to retain them.
There is no temporary raw-source storage to expire; container files hold only
sanitized output and temporary configuration/key material and are removed on exit.
Any future raw review store must implement the approved seven-day retention limit.

## Observation identity
A source pseudonym uses the conservatively normalized full source URL, captured
before MCP listing truncation. An observation ID combines that source with the
normalized original title/excerpt under HMAC.

- Identical text at two source URLs produces two observations.
- The same source/content across queries or runs reuses the observation identity
  and keeps each query match and collection timestamp.
- Changed source content creates a new observation and a change-review flag.
- Formatting normalization collapses simple HTML/whitespace variants.
- Equal content across sources and high keyed-token overlap become review candidates,
  never automatic incident merges. The current overlap threshold is 0.8; it is a
  heuristic and is not semantic evidence of a meaningful change.

Keyed similarity tokens stay internal to SQLite and are omitted from review files.
Per-run sanitized capture snapshots prevent later alias or policy processing from
rewriting earlier capture fields. Global history timestamps, change flags, and
duplicate-review candidates may evolve as later observations arrive. Global first/last observation timestamps are accompanied by the
run's own collection timestamp and query associations.

## Durable execution and recovery
`data/live/collection.sqlite` records run configuration/versions, query states,
charged attempts, safe per-attempt coverage, observations, matches, and review events.
A nonblocking OS lock prevents competing controllers from operating on this store.

Attempts are committed before container creation. Retries never reset a query's
90-second operation deadline or the collection window. Only a confirmed all-engine
outage is automatically retried, within the configured two-retry limit and shared
backoff budget. Unknown errors, malformed responses, and timeouts are not blindly
retried. Engine-level HTTP retries are disabled in the capture process.

The already-tested server-side watchdog stops blocking source workers at the
operation deadline. The parent removes the complete disposable container afterward.
An unconfirmed cleanup prevents committing observations. On resume, outstanding
containers are removed first. An interrupted attempt is marked uncertain and its
budget remains consumed; it is not automatically replayed. Completed queries are
skipped, while unstarted queries can proceed within the frozen policy/window.
Failed cleanup can be retried on subsequent resume without refunding the attempt.

Each attempt has a unique, validated container name; cleanup cannot target the
existing ROBIN container or the project UI. The capture container shares only the
UI's network namespace for Tor. It mounts no host directories, investigation
volumes, provider credentials, or Docker socket. No temporary MCP IDs are persisted.

## Review and artifacts
Outputs under `outputs/live/<run-id>/` are ignored by Git:
- `observations.review.jsonl`: sanitized structured records, including rejected and
  uncertain observations so exclusion decisions can be audited.
- `manifest.json`: policy/image/version fingerprints, query/attempt states, engine
  counters, deadlines, cleanup evidence, and query pseudonyms.
- `quality.json`: decision, missing-field, change, duplicate, and review counts.

Record a metadata review with an opaque reviewer ID and finite reason code:

```bash
python3 scripts/collect.py review --run-id my-single-query-check \
  --observation-id OBSERVATION_HASH --decision needs_review \
  --reason requires_source_review --reviewer reviewer01
```

Decisions: `candidate`, `rejected`, `needs_review`. Supported reasons:
`insufficient_context`, `unrelated`, `generic_advertising`, `out_of_date`,
`disallowed_content`, `requires_source_review`, `consistent_with_scope`.
Every review appends an event; review history is scoped to its run. A review does
not approve release. Every artifact remains `not_approved`; no approved-export
command is exposed in this milestone. Uncertain records cannot be promoted by a
silent automatic rule.

The legacy `robin-collect --input ...` command remains an offline candidate CSV
importer using baseline redaction. Do not use it to bypass the live privacy policy.
Its source-scoped identity is version 2; a legacy populated content-only database
requires an explicit migration or a fresh database path. Existing data is preserved,
not deleted or silently mixed.

## Validation and limitations
Synthetic tests cover privacy, separate-source identity, changes, duplicate flags,
retries/shared deadlines, interruption/resume, budget preservation, cleanup failure,
locking, key/policy drift, immutable snapshots, and append-only review history.
A network-disabled test through real MCP verified that raw synthetic source values
never escaped capture and two sources remained distinct.

The controlled live validation `live-validation-20261120-01` completed with one
charged attempt and confirmed cleanup. Sixteen engines were queried: three returned
links, three empty responses, ten failures. Robin reported 27 raw links, 20 after
deduplication, and 10 after its source-host/result selection. Ten sanitized records
were persisted, all `needs_review` for insufficient context; every snippet and
publication date was unavailable. A completed-run resume kept the attempt count at
one, without a second search.

This validates safe technical capture, not collection relevance or sufficient
analytical coverage. Broader collection, optional page retrieval, richer retained
text, entity resolution beyond known aliases, model selection, and release-approved
CSV export remain subsequent work. The main query registry remains disabled.
