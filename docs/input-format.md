# Input format

The current adapter accepts an array of observation objects, not a Robin report
or an arbitrary upstream JSON export. Convert source result objects to this contract.
Robin's saved narrative reports are not sufficient to recover all observed content.

```json
[
  {
    "query_id": "q001",
    "url": "http://example.invalid/research/1",
    "title": "Synthetic observation",
    "snippet": "Synthetic source excerpt",
    "collected_at_utc": "2026-11-20T12:00:00Z"
  }
]
```

Required strings: `query_id`, `url`, `title`, `snippet`. At least one title or snippet
must contain usable text. `collected_at_utc` is optional; when absent the importer
uses processing time. When present it must include a timezone and is normalized
to UTC. It describes collection time, not source publication time.

Use opaque query IDs rather than sensitive search terms. HTTP(S) URLs are accepted
as locators; the offline pipeline never fetches them. URLs containing user/password
credentials are rejected. The batch limit is 10 MB, query IDs are limited to 80
characters, and title/snippet/URL fields to 100,000 characters each.

Do not commit real input files. Store them under `data/` with appropriate access
controls, then delete them according to the agreed retention policy.
