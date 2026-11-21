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
