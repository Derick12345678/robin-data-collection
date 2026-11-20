"""Transactional import, exact deduplication, sanitization, and candidate export."""
import csv
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import uuid
from .adapters import load_observations
from .normalize import normalize_text, normalize_url
from .sanitize import sanitize, csv_safe
from .storage import connect

FIELDS = ["finding_id", "run_id", "query_ids", "collected_at_utc", "source_ids",
          "title_sanitized", "snippet_sanitized", "duplicate_group_id",
          "redaction_types", "review_status"]
POLICY_VERSION = "baseline-1"


def digest(key: str, namespace: str, value: str) -> str:
    return hmac.new(key.encode(), (namespace + "\0" + value).encode(), hashlib.sha256).hexdigest()


def timestamp(value=None):
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if not isinstance(value, str):
        raise ValueError("collected_at_utc must be an ISO 8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Collection timestamps must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def process(input_path: Path, db_path: Path, output_dir: Path, key: str, run_id=None):
    if len(key) < 32 or key.startswith("REPLACE_"):
        raise ValueError("Set COLLECTION_HMAC_KEY to a random secret of at least 32 characters")
    rows = load_observations(input_path)
    # Validate the entire batch before touching persistent observations.
    prepared = []
    for row in rows:
        url = normalize_url(row["url"])
        collected = timestamp(row.get("collected_at_utc"))
        title, title_types = sanitize(row["title"])
        snippet, snippet_types = sanitize(row["snippet"])
        if not (title or snippet):
            raise ValueError("Observation has no usable plain text")
        content = json.dumps([normalize_text(row["title"]), normalize_text(row["snippet"])], ensure_ascii=False)
        prepared.append((digest(key, "finding", content), digest(key, "source", url),
                         row["query_id"], collected, title, snippet,
                         ";".join(sorted(set(title_types + snippet_types)))))
    run_id = run_id or str(uuid.uuid4())
    if not run_id or len(run_id) > 100 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in run_id):
        raise ValueError("run_id must contain only letters, numbers, underscores, or hyphens")
    connection = connect(db_path)
    try:
        with connection:
            fingerprint = digest(key, "key-check", "robin-data-collection")
            previous = connection.execute("SELECT value FROM metadata WHERE key='key_fingerprint'").fetchone()
            if previous and previous[0] != fingerprint:
                raise ValueError("HMAC key differs from this database; use the original key or a new database")
            connection.execute("INSERT OR IGNORE INTO metadata VALUES ('key_fingerprint', ?)", (fingerprint,))
            if connection.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
                raise ValueError("run_id already exists; use a new run ID or inspect the existing run")
            connection.execute("INSERT INTO runs VALUES (?, ?, 'processing', ?, 0)", (run_id, timestamp(), len(rows)))
            for fid, sid, qid, collected, title, snippet, types in prepared:
                connection.execute("INSERT OR IGNORE INTO findings VALUES (?, ?, ?, ?, 'pending_review')", (fid, title, snippet, types))
                connection.execute("INSERT OR IGNORE INTO matches VALUES (?, ?, ?, ?, ?)", (run_id, fid, qid, sid, collected))
            unique = connection.execute("SELECT COUNT(DISTINCT finding_id) FROM matches WHERE run_id=?", (run_id,)).fetchone()[0]
            connection.execute("UPDATE runs SET status='processed', unique_count=? WHERE run_id=?", (unique, run_id))
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{run_id}_findings_sanitized_candidate.csv"
        with output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            findings = connection.execute("SELECT f.* FROM findings f WHERE EXISTS (SELECT 1 FROM matches m WHERE m.finding_id=f.finding_id AND m.run_id=?) ORDER BY f.finding_id", (run_id,))
            for fid, title, snippet, types, review in findings:
                matches = connection.execute("SELECT query_id, source_id, collected_at_utc FROM matches WHERE run_id=? AND finding_id=?", (run_id, fid)).fetchall()
                record = dict(zip(FIELDS, [fid, run_id, ";".join(sorted({m[0] for m in matches})),
                    min(m[2] for m in matches), ";".join(sorted({m[1] for m in matches})),
                    title, snippet, fid, types, review]))
                writer.writerow({k: csv_safe(str(v)) for k, v in record.items()})
        with output.open(newline="", encoding="utf-8") as stream:
            exported = list(csv.DictReader(stream))
        if len(exported) != unique:
            raise RuntimeError("Export row count validation failed")
        report = {"run_id": run_id, "input_count": len(rows), "unique_count": unique,
                  "duplicates_within_batch": len(rows) - unique,
                  "redacted_findings": sum(bool(r["redaction_types"]) for r in exported),
                  "policy_version": POLICY_VERSION, "csv_round_trip": "passed",
                  "review_status": "pending_review", "contains_raw_urls": False,
                  "limitations": ["Regex redaction does not detect all PII or secrets", "Relevance and near-duplicate review are manual", "Candidate export is not approved for sharing"]}
        (output_dir / f"{run_id}_quality.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        with connection:
            connection.execute("UPDATE runs SET status='exported' WHERE run_id=?", (run_id,))
        return output, report
    finally:
        connection.close()
