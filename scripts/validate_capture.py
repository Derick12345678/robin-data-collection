#!/usr/bin/env python3
"""Run the actual pinned MCP capture with synthetic pages and Docker network disabled."""
import ast
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from robin_collect.deployment import docker_binary


def main():
    config=json.loads((ROOT/'config/queries.json').read_text())
    now=datetime.now(timezone.utc)
    config['scope']['collection_dates'].update(start_date_utc=now.isoformat(),end_date_utc=(now+timedelta(hours=1)).isoformat())
    for query in config['queries']:query['enabled']=query['id']=='q001'
    source=(ROOT/'deploy/pilot_probe.py').read_text()
    function=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='aggregate')
    aggregate=ast.get_source_segment(source,function)
    synthetic='http://'+'a'*56+'.onion/claim/123'
    html='<nav><a href="http://'+'b'*56+'.onion/">Hidden wiki directory</a></nav><div id="ahmiaResultsPage"><ol class="searchResults"><li class="result"><h4><a href="/redirect/?redirect_url='+synthetic+'">Northwind company customer database breach claim</a></h4><p>Northwind customer data reportedly leaked</p></li></ol></div>'
    aggregate+='\nimport io\nclass FakeResponse:\n def __init__(self,body): self.body=body; self.status_code=200; self.headers={"Content-Type":"text/plain"}; self.raw=io.BytesIO(body)\n def close(self): pass\nclass FakeRaw:\n def __init__(self,body): self.body=io.BytesIO(body)\n def read(self,count,decode_content=False): return self.body.read(count)\nclass FakeSession:\n def get(self,*args,**kwargs):\n  r=FakeResponse(b"Northwind company customer database breach claim forum hospital Canada"); r.raw=FakeRaw(r.body); return r\n'
    html='<form id="searchForm" action="/search/" method="get"><input type="search" name="q"><input type="hidden" name="abcdef" value="123456"></form>'+html
    aggregate+='search.get_tor_session=lambda:FakeSession()\nsearch.get_over_tor=lambda *args,**kwargs:(FakeResponse('+repr(html.encode())+'),None)\nsearch.read_capped=lambda response,cap:response.body[:cap]\nsearch.decode_capped=lambda response,body:body.decode()\nmcp_server.probe_tor=lambda **kwargs:True\n'
    request=dict(config=config,key='synthetic-network-disabled-hmac-key-123456',entities={},run_id='synthetic-integration',page_tokens=['a'*32],seen_sources=[],query_id='q001',operation_deadline_utc=(now+timedelta(seconds=90)).isoformat(),pilot_source=source,aggregate_source=aggregate,modules={name:(ROOT/'src/robin_collect'/name).read_text() for name in ['__init__.py','normalize.py','sanitize.py','observations.py','limits.py','enrichment.py','screening.py','retrieval.py']})
    image=json.loads((ROOT/'deploy/robin.lock.json').read_text())['image']
    result=subprocess.run([docker_binary(),'run','--rm','-i','--network','none','--log-driver','none','--tmpfs','/tmp:rw,noexec,nosuid,size=32m,mode=1777','--entrypoint','python3',image,'-c',(ROOT/'deploy/collect_probe.py').read_text()],input=json.dumps(request),capture_output=True,text=True,timeout=110)
    if result.returncode:raise SystemExit('Synthetic MCP integration failed; output suppressed.')
    data=json.loads(result.stdout)
    assert data['status']=='completed',data.get('code')
    assert data['returned_count']==1 and len(data['observations'])==1
    assert data['page_fetch_attempts']==1 and len(data['_review_contexts'])==1
    assert data['retrieval_diagnostics']['engines_skipped']==15
    assert data['retrieval_diagnostics']['recognized_results']==1
    assert data['observations'][0]['source_engine']=='ahmia'
    assert data['observations'][0]['page_selection']=='captured'
    assert 'Northwind' not in json.dumps(data['observations'])
    print(json.dumps({'status':'passed','network':'disabled','navigation_links_retained':0,'result_records':1,'page_attempts':1,'model_calls':data['model_calls']}))

if __name__=='__main__':main()
