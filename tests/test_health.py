import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("robin_health", ROOT / "scripts/robin_health.py")
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)
probe_spec = importlib.util.spec_from_file_location("health_probe", ROOT / "deploy/health_probe.py")
probe_module = importlib.util.module_from_spec(probe_spec)
probe_spec.loader.exec_module(probe_module)


def healthy():
    return {"ui": "up", "socks": "open", "bootstrap": "complete",
            "mcp": {"status": "connected", "initialized": True,
                    "required_tools_present": True, "tor": "up",
                    "engines": {"status": "not_checked"}}}


class HealthTests(unittest.TestCase):
    def test_local_success_does_not_claim_engine_availability(self):
        self.assertEqual(health.assess(healthy())[0], "ready_engines_unchecked")
        self.assertEqual(health.assess(healthy(), True)[1], "engine_probe_incomplete")

    def test_open_socks_and_upstream_up_cannot_replace_bootstrap_evidence(self):
        probe = healthy()
        probe["bootstrap"] = "unknown"
        self.assertEqual(health.assess(probe)[1], "tor_bootstrap_unverified")
        probe["bootstrap"] = "starting"
        self.assertEqual(health.assess(probe)[0], "starting")
        probe["socks"] = "closed"
        self.assertEqual(health.assess(probe)[1], "tor_socks_unavailable")

    def test_missing_tools_and_failed_mcp_are_not_ready(self):
        probe = healthy()
        probe["mcp"]["required_tools_present"] = False
        self.assertEqual(health.assess(probe)[1], "mcp_tools_missing")
        probe["mcp"] = {"status": "error"}
        self.assertEqual(health.assess(probe)[1], "mcp_unavailable")

    def test_all_partial_and_zero_engines(self):
        probe = healthy()
        for up, expected in [(16, "ready"), (3, "degraded"), (0, "unavailable")]:
            probe["mcp"]["engines"] = {"status": "checked", "up": up, "total": 16}
            self.assertEqual(health.assess(probe, True)[0], expected)
        for up, total in [(True, 16), (17, 16), (0, 0), (-1, 16)]:
            probe["mcp"]["engines"] = {"status": "checked", "up": up, "total": total}
            self.assertEqual(health.assess(probe, True)[0], "unknown")

    def test_timeout_does_not_disclose_captured_text(self):
        with patch.object(health.subprocess, "run", side_effect=subprocess.TimeoutExpired("secret-command", 1, output="secret-token")):
            with self.assertRaises(health.ProbeFailure) as caught:
                health.capture(["docker"])
        self.assertEqual(caught.exception.code, "timeout")
        self.assertNotIn("secret", str(caught.exception))

    def test_missing_container_skips_execution(self):
        with patch.object(health, "capture", side_effect=["27.3.1", "2.29.7", ""]) as capture:
            report = health.diagnose(ROOT, "docker")
        self.assertEqual(report["code"], "robin_container_not_running")
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(capture.call_count, 3)

    def test_host_success_and_explicit_engine_request(self):
        image = json.loads((ROOT / "deploy/robin.lock.json").read_text())["image"]
        probe = healthy()
        probe["mcp"]["engines"] = {"status": "checked", "up": 2, "total": 16}
        with patch.object(health, "capture", side_effect=["27.3.1", "2.29.7", "a" * 64, "true " + image, json.dumps(probe)]) as capture:
            report = health.diagnose(ROOT, "docker", True)
        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["exit_code"], 0)
        self.assertIn("--check-engines", capture.call_args.args[0])
        self.assertFalse(report["research_search_performed"])
        self.assertFalse(report["model_probe_performed"])

    def test_strict_bootstrap_requires_a_readable_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "tor.log"
            with patch.dict(probe_module.os.environ, {"ROBIN_TOR_LOG": str(log)}), patch.object(probe_module, "urlopen", side_effect=OSError), patch.object(probe_module.socket, "create_connection", side_effect=OSError):
                self.assertEqual(probe_module.local_checks()["bootstrap"], "unknown")
                log.write_text("Bootstrapped 50%")
                self.assertEqual(probe_module.local_checks()["bootstrap"], "starting")
                log.write_text("Bootstrapped 100% (done)")
                self.assertEqual(probe_module.local_checks()["bootstrap"], "complete")


if __name__ == "__main__":
    unittest.main()
