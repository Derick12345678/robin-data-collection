"""Bounded Docker/Robin/Tor/MCP diagnostics; no research search or model calls."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess


class ProbeFailure(Exception):
    def __init__(self, code):
        self.code = code


def capture(command, *, stdin=None, timeout=10):
    try:
        result = subprocess.run(command, input=stdin, text=True, encoding="utf-8",
                                capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise ProbeFailure("timeout") from None
    except OSError:
        raise ProbeFailure("command_unavailable") from None
    if result.returncode:
        raise ProbeFailure("command_failed")
    return result.stdout.strip()


def assess(probe, check_engines=False):
    """Fail closed on missing bootstrap evidence, protocol failures, or bad counts."""
    if probe.get("ui") != "up":
        return "unavailable", "robin_ui_unavailable"
    if probe.get("socks") != "open":
        return "unavailable", "tor_socks_unavailable"
    if probe.get("bootstrap") == "starting":
        return "starting", "tor_bootstrapping"
    if probe.get("bootstrap") != "complete":
        return "unknown", "tor_bootstrap_unverified"
    mcp = probe.get("mcp", {})
    if not isinstance(mcp, dict) or mcp.get("status") != "connected" or not mcp.get("initialized"):
        return "unavailable", "mcp_unavailable"
    if not mcp.get("required_tools_present"):
        return "unavailable", "mcp_tools_missing"
    if mcp.get("tor") != "up":
        return "unavailable", "mcp_tor_unavailable"
    if not check_engines:
        return "ready_engines_unchecked", "local_checks_passed"
    engines = mcp.get("engines", {})
    if not isinstance(engines, dict):
        return "unknown", "engine_probe_incomplete"
    up, total = engines.get("up"), engines.get("total")
    if (engines.get("status") != "checked" or type(up) is not int or type(total) is not int
            or total < 1 or not 0 <= up <= total):
        return "unknown", "engine_probe_incomplete"
    if up == 0:
        return "unavailable", "all_engines_unavailable"
    if up < total:
        return "degraded", "some_engines_unavailable"
    return "ready", "all_checks_passed"


def diagnose(root: Path, docker: str, check_engines=False):
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "research_search_performed": False, "model_probe_performed": False,
              "engine_probe_requested": check_engines, "checks": {}}
    checks = report["checks"]
    try:
        report["stage"] = "docker"
        version = capture([docker, "version", "--format", "{{.Server.Version}}"])
        if not version:
            raise ProbeFailure("docker_engine_unavailable")
        checks["docker"] = {"status": "up", "server_version": version}
        report["stage"] = "compose"
        capture([docker, "compose", "version", "--short"])
        checks["compose"] = {"status": "available"}
        compose = [docker, "compose", "--project-directory", str(root), "-f", str(root / "compose.yaml")]
        report["stage"] = "container"
        ids = capture(compose + ["ps", "-q", "robin-ui"])
        if not re.fullmatch(r"[0-9a-f]{12,64}", ids):
            raise ProbeFailure("robin_container_not_running")
        state = capture([docker, "inspect", "--format", "{{.State.Running}} {{.Config.Image}}", ids]).split()
        lock = json.loads((root / "deploy" / "robin.lock.json").read_text(encoding="utf-8"))
        if state != ["true", lock["image"]]:
            raise ProbeFailure("running_image_mismatch")
        checks["container"] = {"status": "running", "pinned_image": True}
        payload = (root / "deploy" / "health_probe.py").read_text(encoding="utf-8")
        # Container timeout also kills the probe if the host CLI is interrupted later.
        command = [docker, "exec", "-i", ids, "timeout", "215" if check_engines else "35", "python3", "-"]
        if check_engines:
            command.append("--check-engines")
        report["stage"] = "robin_tor_mcp"
        raw = capture(command, stdin=payload, timeout=225 if check_engines else 45)
        probe = json.loads(raw)
        if not isinstance(probe, dict):
            raise ProbeFailure("invalid_probe_response")
        checks["robin"] = probe
        report["status"], report["code"] = assess(probe, check_engines)
    except ProbeFailure as exc:
        report.update(status="unknown" if exc.code == "timeout" else "unavailable", code=exc.code)
    except (OSError, ValueError, KeyError, TypeError):
        report.update(status="unknown", code="diagnostic_configuration_or_response_invalid")
    report["exit_code"] = 0 if report["status"] in {"ready", "degraded", "ready_engines_unchecked"} else 1
    return report
