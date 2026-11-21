# Bounded live collection, source review, and release

## Implemented workflow
The pinned Robin adapter collects search metadata and can conditionally retrieve
bounded text from direct result pages. Durable observations contain pseudonyms,
finite classifications, and withheld-text markers. Release requires actual human
source-context and privacy review. Source statements remain unverified claims.
No model is called, no recursive crawl occurs, and no source account is created.

The main query registry stays disabled. A separate private frozen policy enables
one batch with explicit dates and preserves original and shortened query wording.
There is no scheduler or automatic renewal.

## Start collection
Run from the project directory, using Python 3.11 or newer:

```bash
python3 scripts/collect.py prepare
# Keep this foreground process running in a separate terminal:
python3 scripts/review.py serve --port 18601
```

Then, in another terminal:

```bash
python3 scripts/collect.py plan --pilot
python3 scripts/collect.py run --pilot --enrich --run-id my-enriched-pilot
# After checking the pilot, freeze and dispatch a single batch:
python3 scripts/collect.py batch-policy
python3 scripts/collect.py plan --policy data/live/batch-policy.json
python3 scripts/collect.py run --enrich --policy data/live/batch-policy.json --run-id my-batch
python3 scripts/collect.py status --run-id my-batch
```

These are execution instructions, not a request to repeat the already completed
project validation runs. A batch policy is created exclusively with mode 0600
inside private `data/live` and never overwritten. Its window lasts 24 hours, within
the approved seven-day scheduling allowance. q008, q010, and q015 use deterministic
shortened phrases with their intent preserved. The original/refined query HMACs
are separate; the private policy keeps both original strings. Other queries are
unchanged. A new scope or subsequent collection needs its own reviewed policy.

On Windows, use `python scripts/collect.py ...` and `python scripts/review.py ...`.
The scripts launch native WSL Python for a WSL checkout, keeping SQLite off the UNC
filesystem protocol. Docker Desktop's CLI is available through WSL interop; native
Linux Docker is also supported.

`prepare` creates and preserves a private random HMAC key. Keep its backup in the
team's secret manager, separate from datasets. An existing database requires its
original key. Never put keys, tokens, local databases, or generated outputs in Git.
An optional mode-0600 `data/live/entities.json` holds known organization aliases;
see [the synthetic example](../examples/entities.synthetic.json).

## Bounds and recovery
The approved limits remain: 20 results per query, 10 page attempts per query,
30 page attempts per batch, 10,000 extracted characters, 100,000 UTF-8 extracted
bytes, concurrency two, and 90 seconds per query operation including retries and
backoff. The implementation targets five pages for an enriched pilot and two per
query for a full batch. Actual attempts may be fewer.

Every page slot is reserved durably before dispatch. Failed fetches count. Confirmed
unused reservations can be released; interrupted or uncertain attempts stay charged.
Retries share the original deadline and batch budget. Only a confirmed all-engine
outage is automatically retried, at most twice. Engine-level HTTP retries are
disabled. Search selection can return fewer than the configured result ceiling.

Direct page retrieval permits only HTTP(S) v3 onion result URLs and text/plain or
text/html. Redirects, attachments, compression, obvious download/sample paths, and
exposed-record patterns are refused. Each response reads at most 1 MB before text
extraction, then applies both extracted-text limits. Truncation is explicit. HTML
scripts, styles, images, and linked resources are not executed or fetched. These
checks reduce accidental collection; they are not a complete semantic classifier.

A server-side watchdog stops all source workers at the operation deadline. Each
capture uses a disposable container sharing only the project's Tor network
namespace, without host mounts, Docker socket, provider credentials, or elevated
capabilities. Docker logging is disabled. Temporary capture files use RAM-backed
`/tmp` and mode 0600. Container cleanup must be confirmed before observations are
committed. Capture cleanup never targets the existing ROBIN or project UI containers.

```bash
python3 scripts/collect.py resume --policy data/live/batch-policy.json --run-id my-batch
```

Resume requires the original policy, entity registry, and pinned image. It cleans
up outstanding capture containers and preserves charged uncertain work. Completed
queries are skipped; unstarted queries can proceed inside the original window.
Completed-run resume does not perform another search. Do not silently renew an
expired policy to replay incomplete work.

## Private source-context review
Sanitized SQLite records and normal artifacts never store original titles, source
text, or raw URLs. Raw source text is baseline-redacted and bounded before entering
the separate temporary local review channel. Unknown personal names and contextual
identifiers can remain in that private context; it is not a distributable dataset.

The review service holds contexts only in memory for 24 hours from retrieval,
shorter than the approved seven-day ceiling. Expiry removes them; process exit or
restart loses them immediately. The capture tmpfs disappears with its container.
No raw-context host files or browser localStorage are used. Review publication
failure is reported, and the missing evidence blocks inclusion. Do not restart the
service during collection or before your team has finished reviewing its contexts.

```bash
python3 scripts/review.py access
```

This prints a private loopback URL with a session token. Open it locally, enter the
run ID, and inspect the bounded source context and sanitized record/duplicate flags.
The token is removed from the address bar. Keep the URL out of messages, issues,
and logs. A currently running service started before the structured-record panel
was added can use `outputs/live/<run-id>/observations.review.jsonl` alongside the UI
for its duplicate/change flags; restarting would discard that session's contexts.

The server binds 127.0.0.1 and uses token authentication, exact Host checks, same-origin
POST checks, a restrictive content policy, text-only rendering, no request logs,
and no-store responses. Its owner-only Unix socket receives contexts from capture.
It is intended for the local workstation, not network deployment or public hosting.
A team's second reviewer must review on that workstation or through an independently
approved secure access arrangement; do not expose the port publicly.

For inclusion, reviewers must check relevance, residual privacy risk, duplicates,
source category, English language, and the source-claimed publication date or its
absence. Known dates must fit the 90-day lookback. Enter an organization name only
when it occurs in context; only its keyed pseudonym is saved. Taxonomy hints are
unverified suggestions. Unknown sector/region can remain unknown. Missing context
cannot be replaced by changing a label.

Two distinct actual reviewers must submit consistent include decisions for the
same evidence receipt. Reviewer IDs are self-reported audit labels, not verified
identities. The software cannot establish reviewer independence. Disagreement or a
new uncertainty blocks release; a rejection excludes the record. Each decision is
append-only. Review is blocked while the collection writer is active.

The legacy CLI `review` action only annotates metadata; it does not count as a
source-context release approval. Neither plan approval nor automated classification
counts as a human record review.

## Release and artifacts
Ignored `outputs/live/<run-id>/` contains sanitized review JSONL, a run manifest,
and quality counters. The manifest records query/attempt states, pinned image,
versions, fingerprints, coverage, cleanup, page ledger, and review-context delivery.
Near-duplicate candidates stay separate pending human judgment; different URLs
remain separate source observations. Enrichment links its metadata parent without
creating a false material-change flag. Per-run safe snapshots preserve capture fields.

After actual record reviews:

```bash
python3 scripts/collect.py release --run-id my-batch
```

Each call creates an immutable bundle in `outputs/releases/<run-id>/release-<id>/`:

- `DATA_DICTIONARY.md`: exact CSV fields, missing-value conventions, and limitations.
- `manifest.json`: frozen collection provenance and append-only review audit.
- `quality.json`: eligible, rejected, pending, incomplete, and release status.
- `findings_sanitized.csv`: created only if the review gate passes.

The default blocks CSV creation while records or queries remain unresolved. Explicit
`--allow-partial` can export a nonempty eligible subset with exclusions recorded;
it never converts an entirely unreviewed batch into an empty approved dataset.
The CSV uses UTF-8, standard quoting, formula-prefix defense, pseudonyms, finite
reviewed fields, a finite summary, SHA-256, and a read-back row-count check. No
original titles, summaries, URLs, reviewer organization strings, or source records
are released. An all-rejected resolved run can legitimately produce a header-only
CSV. Do not fabricate relevant findings to increase yield.

The offline synthetic importer remains a separate candidate exporter and must not
be used to bypass this release gate. Its source-scoped identity is version two;
legacy populated content-only databases need explicit migration or a fresh path.

## Evidence and limits
The earlier metadata validation saved 10 insufficient-context records. The enriched
pilot `enriched-pilot-01` saved nine observations, attempted five direct pages,
and captured three page texts with confirmed cleanup and review-context delivery.
All remained unapproved. Synthetic tests verify capture bounds, source identity,
recovery, shared budgets, authenticated review, context expiry, and CSV release gating.

Engine failures, missing pages, query/host selection, English-only searching,
limited page budgets, and unavailable source dates restrict coverage. Search
results are not a representative dark-web sample. Human review classifies source
statements; it does not establish breach authenticity or prevalence.
