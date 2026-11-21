"""Loopback-only review UI; raw review context lives only in process memory."""
from datetime import datetime,timedelta,timezone
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socketserver
import struct
import threading
from urllib.parse import urlsplit,parse_qs
from .collection import prepare,load_key,exclusive,_run_id
from .collection_store import CollectionStore
from .review import ReviewMemory,record_for,record_vote,eligibility,ensure_schema,_read_exact

PAGE=r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Source review</title><style nonce="__NONCE__">
body{font:16px system-ui;margin:2rem auto;max-width:1150px;padding:0 1rem;color:#172535;background:#f6f8fb}h1{margin-bottom:.3rem}section{background:white;padding:1.3rem;border:1px solid #dae2ed;border-radius:10px;margin:1rem 0}button,input,select{font:inherit;padding:.5rem;margin:.3rem 0}button{background:#194b85;color:white;border:0;border-radius:5px;cursor:pointer}label{display:block;margin:.6rem 0}input:not([type=checkbox]),select{max-width:100%;box-sizing:border-box}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:420px;overflow:auto;background:#f1f4f8;padding:1rem}.grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem}.muted{color:#53667b}.notice{font-weight:600}#message{white-space:pre-wrap}select#records{width:100%}
</style></head><body><h1>Source review</h1><p class="muted">Review source statements as unverified claims. Original source text stays in this temporary local session.</p>
<section id="login"><label>Local session token <input id="token" type="password" autocomplete="off"></label><button id="signin">Open review</button></section>
<section><label>Collection run <input id="run" placeholder="Run ID"></label><button id="load">Load records</button><p id="message" role="status"></p><label>Observation <select id="records"></select></label><p id="state" class="notice"></p></section>
<section><h2>Bounded source context</h2><p id="source"></p><p id="expiry" class="muted"></p><pre id="context">Select an observation to review.</pre></section>
<section><h2>Structured record and duplicate flags</h2><pre id="structured"></pre></section>
<section><h2>Review decision</h2><div class="grid"><div><label>Reviewer ID <input id="reviewer" autocomplete="off" placeholder="reviewer01"></label><label>Decision <select id="decision"><option value="needs_review">Needs review</option><option value="include">Include</option><option value="reject">Reject</option></select></label><label>Reason <select id="reason"></select></label><label>Language <select id="language"><option value="unknown">Unknown</option><option value="en">English (checked)</option></select></label><label>Source category <select id="source_type"></select></label></div><div><label>Sector <select id="sector"></select></label><label>Broad geography <select id="broad_geography"></select></label><label>Claimed exposure <select id="claimed_exposure_type"></select></label><label>Organization name, if present in context <input id="organization_name" maxlength="200" autocomplete="off"></label><label>Source-claimed publication date, if established <input id="publication_date" type="date"></label></div></div>
<label><input id="source_context_checked" type="checkbox"> I checked the source context against the collection criteria.</label><label><input id="privacy_checked" type="checkbox"> I checked the proposed structured record for residual sensitive information.</label><label><input id="date_checked" type="checkbox"> I checked the date, or confirmed that it is unavailable.</label><label><input id="duplicate_checked" type="checkbox"> I checked duplicate and source-change flags.</label><button id="save">Record decision</button><p class="muted">Included records need two consistent reviewer decisions before release. Reviewer IDs are self-reported and must represent the actual reviewers.</p></section>
<script nonce="__NONCE__">
let bearer='',items=[],current=null,expires=0;const $=id=>document.getElementById(id);
const choices={reason:['requires_source_review','explicit_organizational_exposure_claim','insufficient_context','unrelated','generic_advertising','out_of_date','unsupported_language','disallowed_content'],source_type:['unknown','forum_post','marketplace_listing','leak_site_announcement','related_discussion'],sector:['unknown','healthcare','financial_services','education','retail','manufacturing','technology','public_sector','other'],broad_geography:['unknown','North America','South America','Europe','Asia','Africa','Oceania','Middle East','Global'],claimed_exposure_type:['unknown','database','customer_data','employee_data','financial_records','intellectual_property','organizational_data']};
for(const [id,values] of Object.entries(choices))for(const value of values){const option=document.createElement('option');option.value=value;option.textContent=value.replaceAll('_',' ');$(id).append(option)}
async function api(path,body){const response=await fetch(path,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+bearer,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});const result=await response.json();if(!response.ok)throw Error(result.message||'Review request failed');return result}
$('signin').onclick=()=>{bearer=$('token').value.trim();$('token').value='';$('login').hidden=true;$('message').textContent='Session opened. Enter the collection run ID.'};
if(location.hash.length>1){bearer=decodeURIComponent(location.hash.slice(1));history.replaceState(null,'',location.pathname);$('login').hidden=true}
async function select(){current=items.find(r=>r.observation_id===$('records').value);expires=0;$('context').textContent='Context is unavailable for this observation.';$('source').textContent='';$('expiry').textContent='';if(!current)return;$('structured').textContent=JSON.stringify(current,null,2);$('state').textContent='Release status: '+current.release.status.replaceAll('_',' ');for(const id of ['source_type','sector','broad_geography','claimed_exposure_type'])$(id).value=current[id]||'unknown';for(const id of ['source_context_checked','privacy_checked','date_checked','duplicate_checked'])$(id).checked=false;$('organization_name').value='';$('publication_date').value='';try{const context=await api('/api/context?run_id='+encodeURIComponent($('run').value)+'&observation_id='+encodeURIComponent(current.observation_id));$('source').textContent=context.title+' | '+context.url;$('context').textContent=context.text;expires=Date.parse(context.expires_at_utc);$('expiry').textContent='Context expires: '+new Date(expires).toLocaleString()}catch(error){$('expiry').textContent=error.message}}
$('records').onchange=select;
$('load').onclick=async()=>{try{const result=await api('/api/records?run_id='+encodeURIComponent($('run').value.trim()));items=result.records;$('records').replaceChildren();for(const row of items){const option=document.createElement('option');option.value=row.observation_id;option.textContent=row.observation_id.slice(0,12)+' | '+row.relevance_decision+' | '+row.release.status.replaceAll('_',' ');$('records').append(option)}$('message').textContent=items.length+' records loaded. Collection status: '+result.status;await select()}catch(error){$('message').textContent=error.message}};
$('save').onclick=async()=>{if(!current)return;const review={};for(const id of ['reviewer','decision','reason','language','source_type','sector','broad_geography','claimed_exposure_type','organization_name','publication_date'])review[id]=$(id).value;for(const id of ['source_context_checked','privacy_checked','date_checked','duplicate_checked'])review[id]=$(id).checked;try{const result=await api('/api/review',{run_id:$('run').value.trim(),observation_id:current.observation_id,review});$('message').textContent='Decision recorded. Release status: '+result.release.status.replaceAll('_',' ');$('state').textContent=$('message').textContent}catch(error){$('message').textContent=error.message}};
setInterval(()=>{if(expires&&Date.now()>=expires){$('context').textContent='Context expired. Fresh source context is required for inclusion.';$('source').textContent='';expires=0}},1000);
</script></body></html>"""


def serve(root,port=18601):
    root=Path(root);directory=prepare(root);key=load_key(root)
    with exclusive(directory/'review-service.lock'):
        with exclusive(directory/'collection.lock'):
            store=CollectionStore(directory/'collection.sqlite',key)
            try:ensure_schema(store)
            finally:store.close()
        memory=ReviewMemory(key,lambda run,obs:record_for(root,run,obs))
        token=secrets.token_urlsafe(32);session_end=datetime.now(timezone.utc)+timedelta(hours=24)
        stop=threading.Event()
        def authorized(value):return datetime.now(timezone.utc)<session_end and isinstance(value,str) and hmac.compare_digest(value,token)
        class HTTP(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def log_error(self,*args):pass
            def send(self,status,value,html=False,nonce=None):
                body=value.encode() if html else json.dumps(value).encode()
                self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8' if html else 'application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Content-Type-Options','nosniff')
                if html:self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'nonce-"+nonce+"'; style-src 'nonce-"+nonce+"'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
                self.end_headers();self.wfile.write(body)
            def valid_host(self):return self.headers.get('Host') in {f'127.0.0.1:{port}',f'localhost:{port}'}
            def authenticated(self):return self.valid_host() and authorized(self.headers.get('Authorization','').removeprefix('Bearer '))
            def do_GET(self):
                parsed=urlsplit(self.path)
                if not self.valid_host():return self.send(403,{'message':'Invalid local host.'})
                if parsed.path=='/':
                    nonce=secrets.token_urlsafe(18);return self.send(200,PAGE.replace('__NONCE__',nonce),True,nonce)
                if parsed.path=='/healthz':return self.send(200,{'ok':True})
                if not self.authenticated():return self.send(401,{'message':'A valid local session token is required.'})
                args=parse_qs(parsed.query)
                try:
                    run=_run_id(args['run_id'][0])
                    if parsed.path=='/api/context':
                        context=memory.get(run,args['observation_id'][0])
                        if context is None:return self.send(404,{'message':'No unexpired context is available. Fresh collection is required.'})
                        return self.send(200,context)
                    if parsed.path=='/api/records':
                        store=CollectionStore(directory/'collection.sqlite',key)
                        try:
                            rows=store.observations(run)
                            for row in rows:row['release']=eligibility(store,run,row)
                            return self.send(200,{'status':store.run(run)['status'],'records':rows})
                        finally:store.close()
                    return self.send(404,{'message':'Unknown review route.'})
                except Exception:return self.send(400,{'message':'The requested review records are unavailable.'})
            def do_POST(self):
                if not self.authenticated():return self.send(401,{'message':'A valid local session token is required.'})
                if self.headers.get('Origin') not in {f'http://127.0.0.1:{port}',f'http://localhost:{port}'}:return self.send(403,{'message':'Review requests must originate from this local page.'})
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=16384 or self.headers.get('Content-Type')!='application/json':raise ValueError()
                    data=json.loads(self.rfile.read(length))
                    if urlsplit(self.path).path!='/api/review' or set(data)!={'run_id','observation_id','review'}:raise ValueError()
                    run=_run_id(data['run_id'])
                    with exclusive(directory/'collection.lock'):
                        store=CollectionStore(directory/'collection.sqlite',key)
                        try:result=record_vote(store,memory,run,data['observation_id'],data['review'])
                        finally:store.close()
                    return self.send(200,result)
                except RuntimeError:return self.send(409,{'message':'Collection is running. Review will be available when it finishes.'})
                except Exception:return self.send(400,{'message':'Review not recorded. Inclusion requires fresh context, checked criteria, English, a source category, an exposure type, and an in-scope or unavailable date.'})
        class Unix(socketserver.BaseRequestHandler):
            def handle(self):
                result={'ok':False}
                try:
                    self.request.settimeout(5);length=struct.unpack('!I',_read_exact(self.request,4))[0]
                    if length>1_000_000:raise ValueError()
                    data=json.loads(_read_exact(self.request,length))
                    if set(data)!={'token','action','contexts'} or not authorized(data['token']):raise ValueError()
                    if data['action']=='ping':result={'ok':True,'ready':len(memory.contexts)<memory.limit}
                    elif data['action']=='publish':result={'ok':True,'accepted':memory.accept(data['contexts'])}
                except Exception:pass
                body=json.dumps(result).encode();self.request.sendall(struct.pack('!I',len(body))+body)
        class LocalUnix(socketserver.ThreadingUnixStreamServer):daemon_threads=True
        http=ThreadingHTTPServer(('127.0.0.1',port),HTTP);http.daemon_threads=True
        socket_path=directory/'review.sock'
        if socket_path.exists():
            if socket_path.is_symlink() or not socket_path.is_socket():http.server_close();raise RuntimeError('Unsafe review socket path')
            socket_path.unlink()
        unix=LocalUnix(str(socket_path),Unix);socket_path.chmod(0o600)
        session={'url':f'http://localhost:{port}/','token':token,'expires_at_utc':session_end.isoformat(),'pid':os.getpid()}
        path=directory/'review-session.json'
        if path.is_symlink():raise RuntimeError('Unsafe session path')
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(descriptor,'w') as stream:json.dump(session,stream)
        def expiry():
            while not stop.wait(30):memory.prune()
        threading.Thread(target=unix.serve_forever,daemon=True).start();threading.Thread(target=expiry,daemon=True).start()
        print('Local review service listening on '+session['url']+'; access token is in the private session file.',flush=True)
        try:http.serve_forever(poll_interval=0.25)
        finally:
            stop.set();memory.contexts.clear();http.server_close();unix.shutdown();unix.server_close()
            if socket_path.is_socket():socket_path.unlink()
