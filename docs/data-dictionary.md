# CSV data dictionary

Format: UTF-8, comma-separated, header row, standard CSV quoting. Multi-valued IDs
use semicolons. Text fields that could be spreadsheet formulas receive a leading
apostrophe. Each export includes only observations associated with its run.

| Field | Meaning |
|---|---|
| finding_id | Full keyed HMAC of normalized source URL plus original title/snippet; identity version 2 |
| run_id | Batch UUID or supplied opaque run identifier |
| query_ids | Sorted unique query IDs that retrieved the finding during this run |
| collected_at_utc | Earliest recorded collection timestamp for this finding within the run |
| source_ids | Sorted unique keyed HMAC IDs of normalized source URLs |
| title_sanitized | Plain-text title after baseline redaction and CSV formula defense |
| snippet_sanitized | Plain-text excerpt after baseline redaction and CSV formula defense |
| duplicate_group_id | Equals finding_id for the current exact-duplicate implementation |
| redaction_types | Semicolon-separated redaction categories detected |
| review_status | Always pending_review in this scaffold |

Source URLs are deliberately omitted from the CSV. The current database also does
not keep a raw source mapping. If source retracing is required, implement a separate
restricted mapping store before live collection and document its retention/access.

Planned fields include relevance decision/reason, category, language, publication
date with uncertainty, content truncation, collector version, and review audit.
They are not fabricated in the current exporter.

## Live structured observations

The live adapter uses a separate JSONL contract documented in
[live collection](live-collection.md). It stores source/organization pseudonyms,
source-scoped observation IDs, template-only titles/summaries, category and
relevance hints, missing-field/truncation markers, first/last and per-run collection
timestamps, query associations, change/duplicate review candidates, and review
history. It does not export raw snippets or locators. These records remain
`not_approved`; they are not the final analytical CSV.
