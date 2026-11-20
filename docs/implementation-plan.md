# Implementation plan and team work packages

## Milestone 0 — scaffold (implemented)
Offline pipeline, synthetic fixtures, SQLite provenance, exact deduplication,
baseline sanitization, candidate CSV/quality report, tests, CI, and contribution guidance.

## Milestone 1 — scope and Robin setup
Owner: collection lead, reviewed by research lead.
- Approve research domain, inclusion/exclusion criteria, languages, collection dates,
  and 10–20 queries in the versioned registry.
- Pin a verified Robin image/release and inspect its MCP schemas.
- Implement health checks and explicit limits from configuration.
Acceptance: reproducible setup and one bounded, authorized query with complete
status reporting; unavailable engines are distinguished from zero results.

## Milestone 2 — live adapter and orchestration
Owner: collection engineer.
- Implement `RobinMCPCollector`, result conversion, and scope enforcement.
- Capture original/refined queries and engine outcomes in a restricted manifest.
- Implement capped retries/backoff, per-stage checkpoints, partial-run recovery,
  result-ID lifecycle handling, and export-only recovery.
- Make bounded page collection optional; prevent unrestricted query pivots.
Acceptance: interruption/restart loses no provenance and repeats no completed work.

## Milestone 3 — quality and relevance
Owner: data-quality lead.
- Add relevance decisions/reasons, rejection audit, language/category fields,
  near-duplicate candidate review, and truncation/source-date metadata.
- Review retained and rejected samples against the research criteria.
Acceptance: documented sample findings and agreed relevance/duplicate thresholds.

## Milestone 4 — sanitization and release review
Owner: sanitization lead, reviewed by a second teammate.
- Extend policy and rules to the actual research risks using synthetic fixtures.
- Add a restricted URL mapping store only if retracing is needed.
- Implement review decisions and an audited approved-export path.
- Verify all text/metadata fields and report redaction limitations.
Acceptance: agreed redaction test suite passes and human review approves the pilot.

## Milestone 5 — scheduled operation
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
