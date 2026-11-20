import importlib.util
import json
import inspect
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pilot_probe", ROOT / "deploy/pilot_probe.py")
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def outcome(rows=2, answered=1, empty=1, failed=1):
    return {"results": [{"title": "Synthetic name secret@example.invalid", "link": "http://example.invalid/private"} for _ in range(rows)],
            "stats": {"engines_queried": answered + empty + failed, "engines_answered": answered,
                      "engines_empty": empty, "engines_failed": failed, "results_raw": rows,
                      "results_after_dedup": rows, "results_kept": rows, "results_dropped_abuse": 0}}


class PilotTests(unittest.TestCase):
    def test_aggregation_caps_results_and_persists_no_titles_or_locators(self):
        stats = pilot.aggregate(outcome(rows=25), 20)
        self.assertEqual(stats["returned_count"], 20)
        self.assertTrue(stats["result_cap_applied"])
        self.assertEqual(stats["snippet_available_count"], 0)
        self.assertNotIn("example.invalid", json.dumps(stats))
        self.assertNotIn("Synthetic name", json.dumps(stats))

    def test_generated_server_bootstrap_is_valid_python(self):
        source = pilot.server_source(Path("/tmp/pilot-stats.json"), 20, inspect.getsource(pilot.aggregate))
        compile(source, "generated-pilot-server", "exec")

    def test_success_count_must_agree_with_mcp_header(self):
        stats = pilot.aggregate(outcome(), 20)
        self.assertEqual(pilot.search_status("status: ok\n2 results for synthetic", stats), "completed")
        with self.assertRaises(ValueError):
            pilot.search_status("status: ok\n3 results for synthetic", stats)

    def test_empty_and_outage_are_distinguished(self):
        empty = pilot.aggregate(outcome(rows=0, answered=0, empty=1, failed=2), 20)
        self.assertEqual(pilot.search_status("status: no_results\n", empty), "no_results")
        outage = pilot.aggregate(outcome(rows=0, answered=0, empty=0, failed=3), 20)
        self.assertEqual(pilot.search_status("status: engines_unreachable\n", outage), "engines_unreachable")
        with self.assertRaises(ValueError):
            pilot.search_status("status: no_results\n", outage)

    def test_missing_and_inconsistent_coverage_are_rejected(self):
        data = outcome()
        data["stats"]["engines_failed"] = 20
        with self.assertRaises(ValueError):
            pilot.aggregate(data, 20)
        data["stats"]["engines_queried"] = True
        with self.assertRaises(ValueError):
            pilot.aggregate(data, 20)


if __name__ == "__main__":
    unittest.main()
