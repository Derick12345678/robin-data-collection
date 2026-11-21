import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen

class ReviewHTTPTests(unittest.TestCase):
    def test_loopback_auth_host_origin_and_content_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            from datetime import datetime,timedelta,timezone
            from robin_collect.collection import prepare,load_key
            from robin_collect.collection_store import CollectionStore
            from robin_collect.observations import observation
            directory=prepare(root);key=load_key(root);store=CollectionStore(directory/'collection.sqlite',key)
            now=datetime.now(timezone.utc);end=(now+timedelta(hours=1)).isoformat()
            limits=dict(results_per_query=20,pages_per_query=10,pages_per_batch=30)
            store.create_run('synthetic','config','entities',now.isoformat(),end,[{'id':'q001','text':'synthetic'}],limits,'image')
            number=store.reserve('synthetic','q001',3,end,'robin-capture-'+'c'*32)
            record=observation({'title':'Synthetic discovery without claim evidence','link':'http://'+'a'*56+'.onion/item'},'q001',key,now.isoformat(),now)
            coverage=dict(engines_queried=1,engines_answered=1,engines_empty=0,engines_failed=0,results_raw=1,results_after_dedup=1,results_kept=1,results_dropped_abuse=0)
            store.complete('synthetic','q001',number,dict(status='completed',observations=[record],coverage=coverage,returned_count=1,cleanup_confirmed=True));store.finish('synthetic');store.quarantine('synthetic');store.close()
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
            project=Path(__file__).resolve().parents[1]
            env={**os.environ,'PYTHONPATH':str(project/'src')}
            process=subprocess.Popen([sys.executable,'-c','from robin_collect.review_server import serve;import sys;serve(sys.argv[1],int(sys.argv[2]))',temp,str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                session_path=root/'data/live/review-session.json'
                for _ in range(100):
                    if session_path.exists():break
                    if process.poll() is not None:self.fail('Synthetic review server exited')
                    time.sleep(.02)
                session=json.loads(session_path.read_text());base=f'http://127.0.0.1:{port}'
                def request(path='/',headers=None,body=None):
                    return urlopen(Request(base+path,data=body,headers=headers or {}),timeout=2)
                with request() as response:
                    self.assertEqual(response.status,200)
                    self.assertIn("default-src 'none'",response.headers['Content-Security-Policy'])
                    self.assertIn(b'Structured record and duplicate flags',response.read())
                auth={'Authorization':'Bearer '+session['token']}
                with request('/api/records?run_id=synthetic',auth) as response:
                    data=json.load(response)
                self.assertEqual(data['research_suitability'],'quarantined')
                self.assertEqual(data['records'][0]['context_status'],'never_collected')
                self.assertEqual(data['records'][0]['release']['status'],'quarantined')
                with self.assertRaises(HTTPError) as missing:request('/api/context?run_id=synthetic&observation_id='+record['observation_id'],auth)
                message=json.load(missing.exception)
                self.assertEqual(message['context_status'],'never_collected')
                self.assertIn('never collected',message['message'])
                for headers,path,body,code in [
                    ({},'/api/records?run_id=synthetic',None,401),
                    ({'Host':'attacker.invalid'},'/',None,403),
                    ({'Authorization':'Bearer '+session['token'],'Origin':'https://attacker.invalid','Content-Type':'application/json'},'/api/review',b'{}',403),
                ]:
                    with self.assertRaises(HTTPError) as raised:request(path,headers,body)
                    self.assertEqual(raised.exception.code,code)
            finally:
                process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)

if __name__=='__main__':unittest.main()
