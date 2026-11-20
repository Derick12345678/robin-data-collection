import importlib.util
import json
import inspect
import os
import signal
import subprocess
import sys
import tempfile
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


@unittest.skipUnless(os.name == "posix" and hasattr(signal, "setitimer"), "Production watchdog runs in Linux containers")
class RemoteDeadlineTests(unittest.TestCase):
    def run_worker(self, *, budget, work_seconds, cleanup_seconds=0):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            stats = directory / "stats.json"
            deadline_file = directory / "deadline"
            heartbeat = directory / "heartbeat"
            generated = pilot.server_source(stats, 20, inspect.getsource(pilot.aggregate), deadline_file)
            # Stub the transport/modules only: execute the production generated
            # observed() wrapper in a real subprocess with blocking worker threads.
            # No Tor, requests, MCP dependency, or network connection is used.
            fixture = outcome()
            setup = f"""
import sys,types,time,json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
heartbeat=Path({str(heartbeat)!r})
def blocking_search(query,max_workers):
 end=time.monotonic()+{work_seconds!r}
 while time.monotonic()<end:
  with heartbeat.open('a') as stream: stream.write(str(time.monotonic())+'\\n')
  time.sleep(0.005)
 return {fixture!r}
def build_server(search_fn):
 def run():
  with ThreadPoolExecutor(max_workers=1) as pool:
   pool.submit(search_fn,'synthetic',2).result()
  time.sleep({cleanup_seconds!r})
 return types.SimpleNamespace(run_stdio_async=run)
sys.modules['anyio']=types.SimpleNamespace(run=lambda function:function())
sys.modules['search']=types.SimpleNamespace(get_tor_session=lambda:None,get_search_results_detailed=blocking_search)
sys.modules['mcp_server']=types.SimpleNamespace(build_server=build_server)
sys.modules['requests']=types.ModuleType('requests')
sys.modules['requests.adapters']=types.SimpleNamespace(HTTPAdapter=object)
Path({str(deadline_file)!r}).write_text(str(time.monotonic()+{budget!r}))
"""
            result = subprocess.run([sys.executable, "-c", setup + "\n" + generated],
                                    capture_output=True, text=True, timeout=5)
            deadline = float(deadline_file.read_text())
            ticks = [float(value) for value in heartbeat.read_text().splitlines()] if heartbeat.exists() else []
            return result, deadline, ticks

    def test_deadline_stops_remote_blocking_worker_without_shutdown_grace(self):
        result, deadline, ticks = self.run_worker(budget=0.3, work_seconds=2)
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertTrue(ticks, "Blocking worker must actually start")
        self.assertLessEqual(max(ticks), deadline + 0.1)

    def test_expired_deadline_starts_no_source_work(self):
        result, _, ticks = self.run_worker(budget=-1, work_seconds=2)
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertEqual(ticks, [])

    def test_completed_source_work_disarms_watchdog_for_cleanup(self):
        result, _, _ = self.run_worker(budget=0.2, work_seconds=0, cleanup_seconds=0.35)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
