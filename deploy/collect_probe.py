"""MCP observation capture: sanitize in the disposable container before output."""
import asyncio
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import time


async def run(request):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    helpers = {"__name__": "collection_helpers"}
    exec(compile(request["pilot_source"], "pilot_probe.py", "exec"), helpers)
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        package = directory / "robin_collect"
        package.mkdir()
        for filename, source in request["modules"].items():
            if filename not in {"__init__.py","normalize.py","sanitize.py","observations.py","limits.py"}:
                raise ValueError("Unexpected module")
            (package / filename).write_text(source)
        sys.path.insert(0, str(directory))
        from robin_collect.limits import load_policy, LimitedExecutor
        config_path = directory / "config.json"
        config_path.write_text(json.dumps(request["config"]))
        key_path, entities_path = directory / "key", directory / "entities.json"
        descriptor = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(request["key"])
        entities_path.write_text(json.dumps(request["entities"]))
        request["key"] = None
        policy = load_policy(config_path)
        query = next(q for q in request["config"]["queries"] if q["id"] == request["query_id"])
        deadline_path, stats_path = directory / "deadline", directory / "stats.json"
        aggregate_source = request["aggregate_source"]
        aggregate_source += "\nbase_aggregate=aggregate\n"
        aggregate_source += "from robin_collect.observations import capture_observations\n"
        aggregate_source += "def aggregate(outcome,cap):\n"
        aggregate_source += " result=base_aggregate(outcome,cap)\n"
        aggregate_source += " records,invalid=capture_observations(outcome['results'][:cap]," + repr(query['id']) + ",Path(" + repr(str(key_path)) + ").read_text()," + repr(policy.start.isoformat()) + ",json.loads(Path(" + repr(str(entities_path)) + ").read_text())," + str(request['config']['scope']['collection_dates']['publication_lookback_days']) + ")\n"
        aggregate_source += " result.update(observations=records,invalid_locator_count=invalid)\n return result\n"
        code = helpers['server_source'](stats_path, policy.limits.results_per_query, aggregate_source, deadline_path)
        params = StdioServerParameters(command=sys.executable,args=["-c",code],env={**os.environ,"PYTHONPATH":str(directory)})
        with open(os.devnull, "w") as errors:
            async with stdio_client(params, errlog=errors) as (reader,writer):
                async with ClientSession(reader,writer,read_timeout_seconds=timedelta(seconds=95)) as session:
                    await session.initialize()
                    tools=await session.list_tools()
                    if not {'robin_search','robin_health'} <= {t.name for t in tools.tools}:
                        raise RuntimeError("Required MCP tools unavailable")
                    captured=None
                    status=None
                    async def callback(remaining):
                        nonlocal captured,status
                        operation_end=datetime.fromisoformat(request['operation_deadline_utc'])
                        remaining=min(remaining,(operation_end-datetime.now(timezone.utc)).total_seconds())
                        if remaining<=0:raise TimeoutError()
                        deadline_path.write_text(str(time.monotonic()+remaining))
                        try:
                            response=await session.call_tool('robin_search',{'query':query['text'],**policy.search_parameters(),'preset':'threat_intel','user_chose':True})
                        except BaseException:
                            if datetime.now(timezone.utc)>=operation_end:raise TimeoutError() from None
                            raise
                        if response.isError:raise RuntimeError("MCP search refused")
                        text='\n'.join(b.text for b in response.content if b.type=='text')
                        captured=json.loads(stats_path.read_text())
                        status=helpers['search_status'](text,captured)
                        return [{'id':str(i)} for i in range(captured['returned_count'])]
                    await LimitedExecutor(policy).search(query['id'],callback)
                    if captured['returned_count'] and not captured['observations']:
                        return {'status':'failed','code':'all_locators_invalid','observations':[], 'returned_count':captured['returned_count']}
                    return {**captured,'status':status,'page_fetch_attempts':0,'model_calls':0}


if __name__=='__main__':
    try:
        result=asyncio.run(run(json.load(sys.stdin)))
    except BaseException as error:
        def timeout(exc):
            return isinstance(exc,TimeoutError) or any(timeout(child) for child in getattr(exc,'exceptions',()))
        result={'status':'timed_out' if timeout(error) else 'failed','code':'operation_deadline' if timeout(error) else 'capture_failed','returned_count':None,'observations':[]}
    print(json.dumps(result))
