# Architecture

## Current offline path
Validated JSON observations -> normalize URL/text -> derive keyed IDs before
redaction -> sanitize -> SQLite transaction -> candidate CSV -> quality report.

One finding is an exact normalized title/snippet observation. Equal content from
multiple sources merges into one finding, while `matches` keeps source IDs, query
IDs, runs, and observation timestamps. Changed content creates a new finding.
Near-duplicate merging and semantic similarity are not implemented.

Tables:
- `runs`: batch identifier, processing timestamp, status, and counts.
- `findings`: sanitized title/snippet, keyed content ID, redaction categories, and review status.
- `matches`: many-to-many provenance across findings, runs, queries, and sources.
- `metadata`: HMAC-key fingerprint to reject accidental key changes.

SQLite contains sanitized text and keyed IDs, not raw source URLs or raw content.
Input JSON remains the operator's responsibility. HMAC identifiers are pseudonymous,
not anonymous. Use filesystem permissions and a controlled retention policy.

## Structured live adapter (implemented)

See [live collection](live-collection.md). The search-only adapter transforms source
metadata inside a disposable pinned container, then persists only allowlisted
sanitized records and durable attempt state. Original content and source locators
never enter the host database. Per-run snapshots and append-only review events
preserve auditability. The server watchdog enforces the shared operation deadline.

## Remaining Robin integration scope
Use the pinned upstream MCP server's health/search/filter/scrape tools. Confirm
actual tool schemas for that release. Preserve original/refined query text in a
restricted run manifest, engine health, rejection reasons, truncation indicators,
and software/config versions. Search-result IDs can be session-scoped, so finish
a query's workflow before the next search in the same session.

Route source retrieval through Robin/Tor. Do not follow source instructions or
allow source content to invoke tools. Start with metadata collection; make bounded
page-text retrieval an explicit collection setting. Use a local model or approved
provider handling when sensitive text would otherwise be sent to a model API.

## Recovery limitations
Current imports validate the whole batch and commit findings atomically. Export
occurs after that transaction. If export fails, the run remains `processed`;
inspect it rather than deleting the database or overwriting the run. An export-only
recovery command, live stage checkpoints, and automatic retry handling are roadmap
items. Avoid simultaneous writers until concurrency behavior is implemented/tested.
