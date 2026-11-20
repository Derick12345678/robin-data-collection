"""Disposable-container single-query MCP pilot; emits aggregate metadata only."""
import asyncio
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import types


def aggregate(outcome, cap):
    rows = outcome["results"][:cap]
    stats = outcome["stats"]
    names = ["engines_queried", "engines_answered", "engines_empty", "engines_failed",
             "results_raw", "results_after_dedup", "results_kept", "results_dropped_abuse"]
    counts = {name: stats[name] for name in names}
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise ValueError("Invalid coverage counters")
    if counts["engines_answered"] + counts["engines_empty"] + counts["engines_failed"] != counts["engines_queried"]:
        raise ValueError("Inconsistent engine coverage")
    return {"coverage": counts, "returned_count": len(rows),
            "title_available_count": sum(bool(row.get("title")) for row in rows),
            "url_available_count": sum(bool(row.get("link")) for row in rows),
            "snippet_available_count": 0,
            "titles_exceeding_robin_character_cap": sum(len(row.get("title", "")) > 200 for row in rows),
            "urls_exceeding_robin_character_cap": sum(len(row.get("link", "")) > 500 for row in rows),
            "result_cap_applied": len(outcome["results"]) > cap}


def search_status(text, stats):
    status = text.split("\n", 1)[0]
    if status not in {"status: ok", "status: no_results", "status: engines_unreachable"}:
        raise ValueError("Unexpected search response")
    if status == "status: ok":
        match = re.match(r"status: ok\n(\d+) results", text)
        if not match or int(match.group(1)) != stats["returned_count"] or stats["returned_count"] < 1:
            raise ValueError("MCP returned count does not match adapter coverage")
        return "completed"
    if stats["returned_count"] != 0:
        raise ValueError("Empty status with nonempty results")
    answered = stats["coverage"]["engines_answered"] + stats["coverage"]["engines_empty"]
    if status == "status: no_results" and answered > 0:
        return "no_results"
    if status == "status: engines_unreachable" and answered == 0:
        return "engines_unreachable"
    raise ValueError("Search status and coverage disagree")


def server_source(stats_path, cap, aggregate_source):
    return (
    "import anyio,json,search,mcp_server; from requests.adapters import HTTPAdapter; "
    "original=search.get_tor_session; "
    "search.ENGINE_TIMEOUT=(3,5)\n"
    "def session():\n"
    " s=original()\n"
    " s.mount('http://',HTTPAdapter(max_retries=0))\n"
    " s.mount('https://',HTTPAdapter(max_retries=0))\n"
    " return s\n"
    "search.get_tor_session=session\n"
    + aggregate_source + "\n"
    "def observed(query,threads):\n"
    " outcome=search.get_search_results_detailed(query,max_workers=threads)\n"
    " with open(" + repr(str(stats_path)) + ",'w') as stream: json.dump(aggregate(outcome," + str(cap) + "),stream)\n"
    " return outcome\n"
    "anyio.run(mcp_server.build_server(search_fn=observed).run_stdio_async)"
)


async def run(request):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    module = types.ModuleType("pilot_limits")
    sys.modules[module.__name__] = module
    exec(compile(request["limits_source"], "limits.py", "exec"), module.__dict__)
    config = request["config"]
    query = next(q for q in config["queries"] if q["id"] == "q001")
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary)
        policy_path, stats_path = path / "policy.json", path / "stats.json"
        policy_path.write_text(json.dumps(config))
        policy = module.load_policy(policy_path)
        executor = module.LimitedExecutor(policy)
        # Adapter instrumentation writes only numeric coverage, never source material.
        server_code = server_source(stats_path, policy.limits.results_per_query, request["aggregate_source"])
        params = StdioServerParameters(command=sys.executable, args=["-c", server_code], env=dict(os.environ))
        with open(os.devnull, "w") as errors:
            async with stdio_client(params, errlog=errors) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=95)) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    if "robin_search" not in {tool.name for tool in tools.tools}:
                        raise RuntimeError("Search tool unavailable")
                    result_status = None
                    stats = None
                    async def callback(remaining):
                        nonlocal result_status, stats
                        response = await session.call_tool("robin_search", {
                            "query": query["text"], **policy.search_parameters(),
                            "preset": "threat_intel", "user_chose": True,
                        })
                        if response.isError:
                            raise RuntimeError("MCP search refused")
                        text = "\n".join(block.text for block in response.content if block.type == "text")
                        stats = json.loads(stats_path.read_text())
                        result_status = search_status(text, stats)
                        return [{"id": f"pilot-{index}"} for index in range(stats["returned_count"])]
                    await executor.search("q001", callback)
                    return {"status": result_status, **stats, "page_fetch_attempts": executor.page_attempts,
                            "model_calls": 0, "search_tool_calls": 1, "raw_result_persistence": False,
                            "relevance_assessed": False, "protocol": "mcp_stdio"}


if __name__ == "__main__":
    try:
        request = json.load(sys.stdin)
        # The parent removes the entire container on timeout, including remote work.
        result = asyncio.run(run(request))
    except BaseException as exc:
        def timed_out(error):
            return isinstance(error, TimeoutError) or any(timed_out(child) for child in getattr(error, "exceptions", ()))
        result = {"status": "timed_out" if timed_out(exc) else "failed", "code": "pilot_operation_deadline" if timed_out(exc) else "pilot_transport_or_search_failed",
                  "returned_count": None, "raw_result_persistence": False}
    print(json.dumps(result))
