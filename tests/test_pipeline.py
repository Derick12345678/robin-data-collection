import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from robin_collect.normalize import normalize_url
from robin_collect.pipeline import process
from robin_collect.sanitize import sanitize, csv_safe

KEY = "synthetic-test-key-never-use-in-production-123"
FIXTURE = Path(__file__).resolve().parents[1] / "examples/findings.synthetic.json"


class PipelineTests(unittest.TestCase):
    def test_redaction_html_and_formula_defense(self):
        text, kinds = sanitize("<p>a@example.invalid password=FAKE</p><script>discard</script>")
        self.assertNotIn("a@example.invalid", text)
        self.assertNotIn("FAKE", text)
        self.assertNotIn("discard", text)
        self.assertEqual(kinds, ["credential", "email"])
        for value in ["=1+1", " +1", "\t@SUM(A1)", "-1"]:
            self.assertTrue(csv_safe(value).startswith("'"))

    def test_url_keeps_semantic_parameters(self):
        self.assertEqual(normalize_url("http://EXAMPLE.invalid/post?id=2&utm_source=x#fragment"), "http://example.invalid/post?id=2")
        with self.assertRaises(ValueError):
            normalize_url("http://user:password@example.invalid/")

    def test_dedup_provenance_and_repeat_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = base / "collection.sqlite"
            output, report = process(FIXTURE, db, base / "out", KEY, "first")
            with output.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(report["unique_count"], 2)
            self.assertEqual(report["duplicates_within_batch"], 1)
            self.assertIn("q001;q002", [r["query_ids"] for r in rows])
            self.assertTrue(all(r["review_status"] == "pending_review" for r in rows))
            self.assertNotIn("analyst@example.invalid", output.read_text())
            self.assertTrue(any(r["title_sanitized"].startswith("'=") for r in rows))
            process(FIXTURE, db, base / "out", KEY, "second")
            with sqlite3.connect(db) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 2)
            with self.assertRaises(ValueError):
                process(FIXTURE, db, base / "out", "another-key-of-at-least-32-characters", "third")

    def test_changed_content_is_a_new_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rows = json.loads(FIXTURE.read_text())[:1]
            rows.append({**rows[0], "snippet": "Updated research observation"})
            source = base / "input.json"
            source.write_text(json.dumps(rows))
            _, report = process(source, base / "db.sqlite", base / "out", KEY)
            self.assertEqual(report["unique_count"], 2)

    def test_identical_text_from_different_sources_stays_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rows = json.loads(FIXTURE.read_text())[:1]
            rows.append({**rows[0], "url": "http://another.invalid/post/1"})
            source = base / "input.json"
            source.write_text(json.dumps(rows))
            _, report = process(source, base / "db.sqlite", base / "out", KEY)
            self.assertEqual(report["unique_count"], 2)

    def test_legacy_content_only_database_is_not_silently_mixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = base / "db.sqlite"
            process(FIXTURE, db, base / "out", KEY, "one")
            with sqlite3.connect(db) as connection:
                connection.execute("DELETE FROM metadata WHERE key='observation_identity_version'")
            with self.assertRaises(ValueError):
                process(FIXTURE, db, base / "out", KEY, "two")

    def test_invalid_batch_does_not_create_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rows = json.loads(FIXTURE.read_text())
            rows[1]["collected_at_utc"] = "2026-11-20T12:00:00"
            source = base / "bad.json"
            source.write_text(json.dumps(rows))
            with self.assertRaises(ValueError):
                process(source, base / "db.sqlite", base / "out", KEY)
            self.assertFalse((base / "db.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
