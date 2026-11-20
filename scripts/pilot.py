#!/usr/bin/env python3
"""Plan or run one metadata-only pilot; no page retrieval, model calls, or raw exports."""
import argparse
from dataclasses import replace, asdict
from datetime import datetime, timedelta, timezone
import inspect
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "deploy"))
from robin_collect.limits import load_policy
from robin import docker_binary
from robin_health import diagnose, capture
from pilot_probe import aggregate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Dispatch exactly one live approved query")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    policy = load_policy(ROOT / "config/queries.json")
    config = json.loads((ROOT / "config/queries.json").read_text(encoding="utf-8"))
    query = next(q for q in config["queries"] if q["id"] == "q001")
    # The explicit one-shot command enables only this approved generic query for one hour.
    # The tracked registry stays disabled and is never modified by the pilot.
    effective = replace(policy, enabled_ids=frozenset({"q001"}), start=policy.start or now, end=policy.end or now + timedelta(hours=1))
    effective.require_live("q001")
    for q in config["queries"]:
        q["enabled"] = q["id"] == "q001"
    config["scope"]["collection_dates"].update(start_date_utc=effective.start.isoformat(), end_date_utc=effective.end.isoformat())
    report = {"run_id": "pilot-" + uuid.uuid4().hex, "started_at_utc": now.isoformat(),
              "original_query": query["text"], "refined_query": query["text"],
              "refinement": "unchanged_short_registry_query_no_model", "query_id": "q001",
              "preset_mapping": "threat_intel", "mode": "single_query_metadata_only",
              "collection_window": {"start": effective.start.isoformat(), "end": effective.end.isoformat()},
              "base_config_sha256": policy.config_sha256, "limits": asdict(policy.limits),
              "transport_overrides": {"engine_connect_timeout_seconds": 3, "engine_read_timeout_seconds": 5, "http_retries": 0},
              "source_titles_and_urls_persisted": False, "page_retrieval_enabled": False,
              "model_calls_enabled": False, "research_search_performed": False}
    if not args.run:
        report["status"] = "planned"
        print(json.dumps(report, indent=2))
        return 0
    docker = docker_binary()
    health = diagnose(ROOT, docker)
    if health["exit_code"]:
        report.update(status="blocked", code="local_health_not_ready", health_code=health["code"])
    else:
        lock = json.loads((ROOT / "deploy/robin.lock.json").read_text(encoding="utf-8"))
        compose = [docker, "compose", "--project-directory", str(ROOT), "-f", str(ROOT / "compose.yaml")]
        ui = capture(compose + ["ps", "-q", "robin-ui"])
        name = "robin-" + report["run_id"]
        report.update(robin_release=lock["release"], image=lock["image"])
        payload = (ROOT / "deploy/pilot_probe.py").read_text(encoding="utf-8")
        request = {"config": config, "limits_source": (ROOT / "src/robin_collect/limits.py").read_text(encoding="utf-8"),
                   "aggregate_source": inspect.getsource(aggregate)}
        started = time.monotonic()
        try:
            capture([docker, "create", "-i", "--name", name, "--network", "container:" + ui,
                     "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                     "--entrypoint", "python3", lock["image"], "-c", payload], timeout=20)
            report["research_search_attempted"] = True
            report["research_search_performed"] = None
            # The server watchdog enforces the dispatched search deadline. This
            # larger host budget covers setup/reporting; container removal is final cleanup.
            result = subprocess.run([docker, "start", "--attach", "--interactive", name],
                                    input=json.dumps(request), text=True, encoding="utf-8",
                                    capture_output=True, timeout=110, check=False)
            if result.returncode:
                raise RuntimeError("Pilot process failed")
            observation = json.loads(result.stdout)
            if not isinstance(observation, dict) or observation.get("status") not in {"completed", "no_results", "engines_unreachable", "failed", "timed_out"}:
                raise RuntimeError("Unexpected pilot response")
            report.update(observation)
            if observation.get("search_tool_calls") == 1:
                report["research_search_performed"] = True
        except subprocess.TimeoutExpired:
            report.update(status="timed_out", returned_count=None, code="pilot_container_deadline")
        except Exception:
            report.update(status="failed", returned_count=None, code="pilot_execution_failed")
        finally:
            try:
                cleanup = subprocess.run([docker, "rm", "--force", name], capture_output=True, timeout=20)
                report["container_cleanup_confirmed"] = cleanup.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                report["container_cleanup_confirmed"] = False
            report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    output = ROOT / "outputs" / (report["run_id"] + ".json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output), **report}, indent=2))
    return 0 if report["status"] in {"completed", "no_results"} and report.get("container_cleanup_confirmed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
