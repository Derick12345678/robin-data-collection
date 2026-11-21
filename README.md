# Robin Data Collection

Team scaffold for reproducible dark-web research collection with Robin and a sanitized CSV deliverable.

## Current status

**Working now:** pinned Robin deployment, strict Docker/Tor/MCP diagnostics, validated
limits, and a live metadata adapter producing durable sanitized observations,
provenance, manifests, and review artifacts. A controlled live run saved 10 records;
all need review because the returned metadata provided insufficient context.

**Privacy default:** original titles, excerpts, and URLs are withheld. Records use
keyed pseudonyms and finite structured fields. Known organization aliases can be
pseudonymized; unknown entities remain unknown. Read the
[live collection guide](docs/live-collection.md) before retaining real observations.

**Dataset work remains:** assess source context/relevance, configure the agreed
query batch and dates, and validate/approve the final sanitized CSV. The review
artifacts are not release-approved datasets. The main query registry stays disabled.
The [initial pilot handoff](docs/pilot-results.md) describes the earlier aggregate-only
phase; the live guide documents the current adapter milestone.

## Robin installation

Robin v3.1 is pinned by immutable Docker digest in `compose.yaml`, with release
provenance in `deploy/robin.lock.json`. Follow [the setup guide](docs/robin-setup.md)
for WSL or Windows commands, local credentials, persistent storage, and verification.
The pinned environment is used by the structured metadata adapter.
Run `python scripts/robin.py health` for local Docker/Tor/MCP diagnostics, or add
`--check-engines` for bounded engine availability probes. See [health checks](docs/health-checks.md).

## Collection limits

Run `python scripts/robin.py limits` to validate and inspect the approved limits
without contacting Robin. The reusable guards cap results, page attempts, text,
retries, and operation time; [collection limits](docs/collection-limits.md) explains
accounting. The live metadata controller persists attempt budgets and deadlines.
The main registry remains disabled.

## Controlled pilot

`python scripts/pilot.py` prints a no-network plan. Add `--run` to explicitly dispatch
one approved metadata-only query in a disposable container and save an aggregate
report. See [the controlled pilot guide](docs/controlled-pilot.md) for limits, cleanup,
and the distinction between this transport test and the analytical dataset.

## Live metadata workflow

```bash
python3 scripts/collect.py prepare
python3 scripts/collect.py plan --pilot
# Explicitly run one approved query and retain only sanitized structured records:
python3 scripts/collect.py run --pilot --run-id my-validation
python3 scripts/collect.py resume --run-id my-validation
```

Windows users can invoke `python scripts/collect.py ...`; a WSL checkout runs its
SQLite controller inside WSL automatically. See [live collection](docs/live-collection.md)
for storage, review, recovery, privacy tradeoffs, and configured-batch requirements.

## Offline synthetic quick start (WSL/Linux, Python 3.11+)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
export COLLECTION_HMAC_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
robin-collect --input examples/findings.synthetic.json --db data/demo-v2.sqlite --run-id demo-v2
python -m unittest discover -s tests -v
```

Run both Python and SQLite inside WSL when the project lives in the WSL filesystem;
Windows access through a network path can interfere with SQLite locking.

Keep the generated key in your team's secret manager for repeat collection with
that database. A new key is rejected for an existing database. `.env.example`
is documentation only; this project does not automatically load `.env` files.

The demo produces two findings from three synthetic inputs. Inspect
`outputs/demo-v2_findings_sanitized_candidate.csv` and `outputs/demo-v2_quality.json`.
Generated files and the local database are ignored by Git. For another run, use
a new run ID. Identical observations reuse the existing finding while preserving
each run's matches. Reusing a run ID is rejected to avoid overwriting provenance.

## Structure

```text
config/queries.json             Versioned scope, query, and limit template
src/robin_collect/
  adapters.py                   Offline input and bounded live adapter contract
  live_adapter.py               Disposable Docker/MCP capture transport
  collection.py                 Durable collection/recovery and artifacts
  collection_store.py           Run, attempt, snapshot, and review storage
  observations.py               Structured-only privacy and source identity
  cli.py                        Offline import command
  normalize.py                  Text and URL normalization
  sanitize.py                   Baseline redaction and spreadsheet formula defense
  storage.py                    SQLite schema
  pipeline.py                   Transactional processing and candidate export
examples/                       Synthetic input only
tests/                         Pipeline and sanitization checks
docs/                          Architecture, input format, dictionary, and roadmap
data/                          Ignored working data
outputs/                       Ignored exports and quality reports
.github/                        CI and team templates
```

## Team workflow

1. Agree on the scope and sanitization policy in `config/queries.json` and
   `docs/sanitization-policy.md` before collecting real material.
2. Divide implementation using `docs/implementation-plan.md`.
3. Work in branches and submit pull requests using the provided template.
4. Require CI and a second team member's review for query, schema, or sanitization changes.
5. Keep datasets in a controlled shared destination separate from source control.

See [Contributing](CONTRIBUTING.md), [architecture](docs/architecture.md),
[input format](docs/input-format.md), and [data dictionary](docs/data-dictionary.md).

## Dataset review

All exported records are `pending_review`. The exporter creates a **candidate**,
not an approval or guarantee of anonymization. Regex rules do not reliably find
names, physical addresses, all secrets, or contextual identifiers. Review relevance,
near duplicates, and residual sensitive information before distributing a dataset.
Raw URLs are replaced with HMAC source IDs in exports. Query text is not exported.

## Upstream

Robin is maintained independently at https://github.com/apurvsinghgautam/robin.
This repository does not bundle Robin or claim affiliation. Pin and verify the
chosen release and inspect its MCP schemas when implementing the live adapter.
No project license has been chosen yet; the team should agree on one before
external redistribution.
