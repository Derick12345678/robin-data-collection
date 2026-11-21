# Implementation plan and team work packages

## Status and phase boundary

The six-step installation-and-pilot checklist is complete and documented in
[pilot results](pilot-results.md). It is distinct from the full dataset lifecycle
below. A controlled search returned aggregate metadata only; no live findings CSV
has been produced. Complete the remaining adapter, sanitization, relevance,
deduplication, batch, and review/export work before calling data collection complete.

## Milestone 0 â€” scaffold (implemented)
Offline pipeline, synthetic fixtures, SQLite provenance, exact deduplication,
baseline sanitization, candidate CSV/quality report, tests, CI, and contribution guidance.

## Milestone 1 â€” scope and Robin setup
Owner: collection lead, reviewed by research lead.
Installation and diagnostic substeps are implemented: pinned deployment; strict
bootstrap evidence; Docker, UI, and MCP checks; optional two-worker engine probes.
Collection-limit policy validation and reusable enforcement guards are implemented
and synthetically tested; see `docs/collection-limits.md`. The live metadata path now persists those guards and attempt budgets.
Model configuration, richer page collection, and production collection dates remain
outstanding. A metadata-only controlled pilot is implemented and successfully run;
see `docs/controlled-pilot.md`. Relevance and analysis-ready exports are not part
of that transport test. See `docs/health-checks.md` for diagnostics.

- Approve research domain, inclusion/exclusion criteria, languages, collection dates,
  and 10â€“20 queries in the versioned registry.
- Pin a verified Robin image/release and inspect its MCP schemas.
- Implement health checks and explicit limits from configuration.
Acceptance: reproducible setup and one bounded, authorized query with complete
status reporting; unavailable engines are distinguished from zero results.

## Milestone 2 â€” live adapter and orchestration
Implemented for metadata: bounded MCP capture, sanitize-before-output, durable
charged attempts, frozen policies, cleanup/recovery, per-source observation IDs,
immutable run snapshots, and append-only review events. The live validation saved
10 structured records, all requiring more source context. See
[live collection](live-collection.md). Page retrieval and richer text remain deferred.

Owner: collection engineer.
- Implement `RobinMCPCollector`, result conversion, and scope enforcement.
- Capture original/refined queries and engine outcomes in a restricted manifest.
- Implement capped retries/backoff, per-stage checkpoints, partial-run recovery,
  result-ID lifecycle handling, and export-only recovery.
- Make bounded page collection optional; prevent unrestricted query pivots.
Acceptance: interruption/restart loses no provenance and repeats no completed work.

## Milestone 3 â€” quality and relevance
Owner: data-quality lead.
- Add relevance decisions/reasons, rejection audit, language/category fields,
  near-duplicate candidate review, and truncation/source-date metadata.
- Review retained and rejected samples against the research criteria.
Acceptance: documented sample findings and agreed relevance/duplicate thresholds.

## Milestone 4 â€” sanitization and release review
Owner: sanitization lead, reviewed by a second teammate.
- Extend policy and rules to the actual research risks using synthetic fixtures.
- Add a restricted URL mapping store only if retracing is needed.
- Implement review decisions and an audited approved-export path.
- Verify all text/metadata fields and report redaction limitations.
Acceptance: agreed redaction test suite passes and human review approves the pilot.

## Milestone 5 â€” scheduled operation
Owner: operations lead.
- Add a systemd timer only after the pilot passes; avoid live searches in CI.
- Store configuration/tool/policy versions with each run; monitor failures and
  enforce retention. Add dependency/image update and regression procedures.
Acceptance: repeated bounded batches produce reviewed CSVs and quality reports.

## Suggested division of work
A small team can combine roles, but keep a second reviewer for sanitization and
scope changes. Open one issue per work package using the repository template.
Collaborator access, branch protection, owners, final thresholds, licensing, and
scheduling are team decisions not configured by this scaffold.
