"""Run inside the pinned UI container; emit only structured health metadata."""
import argparse
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import re
import socket
import sys
from urllib.request import urlopen

REQUIRED_TOOLS = {
    "robin_search", "robin_refine", "robin_filter", "robin_scrape",
    "robin_investigate", "robin_list_models", "robin_health",
    "robin_list_investigations", "robin_save_investigation",
}


def local_checks():
    checks = {}
    try:
        with urlopen("http://127.0.0.1:8501/_stcore/health", timeout=3) as response:
            checks["ui"] = "up" if response.status == 200 and response.read(16).strip() == b"ok" else "down"
    except Exception:
        checks["ui"] = "down"
    try:
        with socket.create_connection(("127.0.0.1", 9050), timeout=3):
            checks["socks"] = "open"
    except OSError:
        checks["socks"] = "closed"
    path = os.environ.get("ROBIN_TOR_LOG", "")
    try:
        if not path:
            raise OSError("No log configured")
        with Path(path).open("r", encoding="utf-8", errors="replace") as stream:
            text = stream.read(1_048_576)
        checks["bootstrap"] = "complete" if "Bootstrapped 100%" in text else "starting"
    except OSError:
        # Upstream treats an unreadable log as bootstrapped; do not repeat that fallback.
        checks["bootstrap"] = "unknown"
    return checks


async def mcp_checks(check_engines):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # Reuse this container's Tor daemon. No new entrypoint, model refresh, or reports.
    # Override only engine concurrency to respect the approved two-worker limit.
    server_code = (
        "import anyio,health,mcp_server; "
        "server=mcp_server.build_server(engines_fn=lambda:health.check_search_engines(max_workers=2)); "
        "anyio.run(server.run_stdio_async)"
    )
    params = StdioServerParameters(command=sys.executable, args=["-c", server_code], env=dict(os.environ))
    with open(os.devnull, "w") as errors:
        async with stdio_client(params, errlog=errors) as (reader, writer):
            async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=200 if check_engines else 20)) as session:
                initialized = await session.initialize()
                tools = set()
                cursor = None
                for _ in range(10):
                    page = await session.list_tools(cursor=cursor)
                    tools.update(tool.name for tool in page.tools)
                    cursor = page.nextCursor
                    if not cursor:
                        break
                else:
                    raise RuntimeError("Tool pagination exceeded limit")
                result = await session.call_tool("robin_health", {"model": "", "check_engines": check_engines})
                if result.isError:
                    raise RuntimeError("Health tool returned error")
                text = "\n".join(block.text for block in result.content if block.type == "text")
                tor = re.search(r"^tor: (up|down)\b", text, re.M)
                if not tor or not re.search(r"^status: ok$", text, re.M):
                    raise RuntimeError("Unexpected health response")
                engines = {"status": "not_checked"}
                if check_engines:
                    match = re.search(r"^engines: (\d+) of (\d+) up$", text, re.M)
                    if match:
                        up, total = map(int, match.groups())
                        if total < 1 or not 0 <= up <= total:
                            raise RuntimeError("Invalid engine counts")
                        engines = {"status": "checked", "up": up, "total": total}
                    else:
                        engines = {"status": "not_checked_tor_unavailable"}
                return {
                    "status": "connected", "initialized": True,
                    "protocol_version": initialized.protocolVersion,
                    "required_tools_present": REQUIRED_TOOLS <= tools,
                    "tools": sorted(REQUIRED_TOOLS & tools),
                    "missing_tools": sorted(REQUIRED_TOOLS - tools),
                    "tor": tor.group(1), "engines": engines,
                }


async def run(check_engines):
    report = local_checks()
    # Unknown bootstrap evidence must not result in traffic to engine endpoints.
    effective = check_engines and report["socks"] == "open" and report["bootstrap"] == "complete"
    try:
        report["mcp"] = await asyncio.wait_for(mcp_checks(effective), timeout=205 if effective else 25)
        if check_engines and not effective:
            report["mcp"]["engines"] = {"status": "not_checked_tor_unavailable"}
    except Exception:
        # Provider/transport exception payloads can contain secrets and raw URLs.
        report["mcp"] = {"status": "error", "code": "mcp_probe_failed"}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-engines", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.check_engines))))
