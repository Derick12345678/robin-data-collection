# Robin Data Collection

Team scaffold for reproducible dark-web research collection with Robin and a sanitized CSV deliverable.

## Current status

**Working now:** an offline JSON import pipeline, conservative URL normalization,
exact content deduplication across batches, preservation of query/source matches,
baseline redaction, keyed identifiers, SQLite storage, candidate CSV exports,
quality reports, synthetic tests, and GitHub Actions CI.

**Next milestone:** connect the runner to a pinned Robin MCP server. The live
adapter is deliberately unimplemented; the scaffold does not contact search
engines, start Tor, or automatically run live searches. Query configuration is a
team planning template and is not yet consumed by the offline import command.

## Robin installation

Robin v3.1 is pinned by immutable Docker digest in `compose.yaml`, with release
provenance in `deploy/robin.lock.json`. Follow [the setup guide](docs/robin-setup.md)
for WSL or Windows commands, local credentials, persistent storage, and verification.
The pinned environment is separate from the unimplemented live collection adapter.
Run `python scripts/robin.py health` for local Docker/Tor/MCP diagnostics, or add
`--check-engines` for bounded engine availability probes. See [health checks](docs/health-checks.md).

## Collection limits

Run `python scripts/robin.py limits` to validate and inspect the approved limits
without contacting Robin. The reusable guards cap results, page attempts, text,
retries, and operation time; [collection limits](docs/collection-limits.md) explains
accounting and the remaining live-adapter integration. Queries remain disabled.

## Controlled pilot

`python scripts/pilot.py` prints a no-network plan. Add `--run` to explicitly dispatch
one approved metadata-only query in a disposable container and save an aggregate
report. See [the controlled pilot guide](docs/controlled-pilot.md) for limits, cleanup,
and the distinction between this transport test and the analytical dataset.

## Quick start (WSL/Linux, Python 3.11+)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
export COLLECTION_HMAC_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
robin-collect --input examples/findings.synthetic.json --run-id demo
python -m unittest discover -s tests -v
```

Run both Python and SQLite inside WSL when the project lives in the WSL filesystem;
Windows access through a network path can interfere with SQLite locking.

Keep the generated key in your team's secret manager for repeat collection with
that database. A new key is rejected for an existing database. `.env.example`
is documentation only; this project does not automatically load `.env` files.

The demo produces two findings from three synthetic inputs. Inspect
`outputs/demo_findings_sanitized_candidate.csv` and `outputs/demo_quality.json`.
Generated files and the local database are ignored by Git. For another run, use
a new run ID. Identical observations reuse the existing finding while preserving
each run's matches. Reusing a run ID is rejected to avoid overwriting provenance.

## Structure

```text
config/queries.json             Versioned scope, query, and limit template
src/robin_collect/
  adapters.py                   Validated JSON input and future live adapter contract
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
