"""Authenticated local review core and memory-only evidence cache."""
from datetime import datetime,timedelta,timezone
import hmac
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import struct
import threading
from .observations import pseudonym
from .enrichment import context_receipt,eligible_url,SECTORS,REGIONS,SOURCE_TYPES,EXPOSURES

REASONS={'explicit_organizational_exposure_claim','insufficient_context','unrelated','generic_advertising','out_of_date','unsupported_language','disallowed_content','requires_source_review'}
REVIEW_SCHEMA="""
CREATE TABLE IF NOT EXISTS release_review_events(
 event_id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,observation_id TEXT NOT NULL,
 reviewer TEXT NOT NULL,decision TEXT NOT NULL,reason TEXT NOT NULL,fields_json TEXT NOT NULL,
 context_receipt TEXT,created_at TEXT NOT NULL
);
"""
# Run/observation membership is validated before each inserted review.


def ensure_schema(store):store.db.executescript(REVIEW_SCHEMA)


def record_for(root,run_id,observation_id):
    path=(Path(root)/'data/live/collection.sqlite').resolve()
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    try:
        row=db.execute('SELECT safe_json FROM observation_matches WHERE run_id=? AND observation_id=? ORDER BY collected_at,query_id LIMIT 1',(run_id,observation_id)).fetchone()
        return json.loads(row['safe_json']) if row else None
    finally:db.close()


class ReviewMemory:
    def __init__(self,key,lookup,max_contexts=1000):
        self.key=key;self.lookup=lookup;self.limit=max_contexts;self.contexts={};self.lock=threading.RLock()
    def prune(self,now=None):
        now=now or datetime.now(timezone.utc)
        with self.lock:
            for identity,context in list(self.contexts.items()):
                if datetime.fromisoformat(context['expires_at_utc'])<=now:del self.contexts[identity]
    def accept(self,contexts,now=None):
        now=now or datetime.now(timezone.utc)
        self.prune(now);validated=[]
        required={'run_id','observation_id','source_pseudonym','url','title','text','fetched_at_utc','expires_at_utc','evidence_id','receipt'}
        for context in contexts:
            if not isinstance(context,dict) or set(context)!=required:raise ValueError('Invalid review context')
            if any(not isinstance(context[k],str) for k in required):raise ValueError('Invalid context value')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',context['run_id']) or any(not re.fullmatch(r'[0-9a-f]{64}',context[k]) for k in ['observation_id','source_pseudonym','evidence_id','receipt']):raise ValueError('Invalid context identifiers')
            if len(context['text'])>10000 or len(context['title'])>1000 or len(context['url'])>2048 or not eligible_url(context['url']):raise ValueError('Context bound exceeded')
            fetched=datetime.fromisoformat(context['fetched_at_utc']);expires=datetime.fromisoformat(context['expires_at_utc'])
            if fetched.tzinfo is None or expires.tzinfo is None or not fetched<=now<expires or expires-fetched>timedelta(days=7):raise ValueError('Context expired or invalid')
            if not hmac.compare_digest(context_receipt(self.key,context),context['receipt']):raise ValueError('Invalid evidence receipt')
            record=self.lookup(context['run_id'],context['observation_id'])
            if not record or record.get('context_receipt')!=context['receipt'] or record['source_pseudonym']!=context['source_pseudonym']:raise ValueError('Uncommitted evidence')
            validated.append(dict(context))
        with self.lock:
            if len(self.contexts)+len(validated)>self.limit:raise ValueError('Review memory full')
            for context in validated:self.contexts[(context['run_id'],context['observation_id'])]=context
        return len(validated)
    def get(self,run_id,observation_id):
        self.prune()
        with self.lock:
            value=self.contexts.get((run_id,observation_id))
            return dict(value) if value else None


def record_vote(store,memory,run_id,observation_id,payload,now=None):
    now=now or datetime.now(timezone.utc)
    required={'reviewer','decision','reason','source_context_checked','privacy_checked','language','source_type','sector','broad_geography','claimed_exposure_type','organization_name','publication_date','date_checked','duplicate_checked'}
    if not isinstance(payload,dict) or set(payload)!=required:raise ValueError('Unexpected review fields')
    reviewer=payload['reviewer']
    if not isinstance(reviewer,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',reviewer):raise ValueError('Use an opaque reviewer ID')
    if not isinstance(payload['decision'],str) or payload['decision'] not in {'include','reject','needs_review'} or not isinstance(payload['reason'],str) or payload['reason'] not in REASONS:raise ValueError('Invalid review decision')
    record=next((r for r in store.observations(run_id) if r['observation_id']==observation_id),None)
    if record is None:raise ValueError('Unknown observation')
    context=memory.get(run_id,observation_id)
    fields={}
    receipt=None
    if payload['decision']=='include':
        if not context or context['receipt']!=record.get('context_receipt'):raise ValueError('Fresh source context is required')
        if any(payload[k] is not True for k in ['source_context_checked','privacy_checked','date_checked','duplicate_checked']):raise ValueError('Review checks are required')
        if payload['reason']!='explicit_organizational_exposure_claim' or payload['language']!='en':raise ValueError('Inclusion must meet scope')
        for name,allowed in [('source_type',SOURCE_TYPES-{'unknown'}),('sector',SECTORS),('broad_geography',REGIONS),('claimed_exposure_type',EXPOSURES-{'unknown'})]:
            if not isinstance(payload[name],str) or payload[name] not in allowed:raise ValueError('Invalid classification')
        name=payload['organization_name']
        if not isinstance(name,str) or len(name)>200:raise ValueError('Invalid organization label')
        if name.strip() and name.strip().casefold() not in (context['title']+' '+context['text']).casefold():raise ValueError('Organization label must occur in reviewed context')
        organization=pseudonym(store.key,'organization',' '.join(name.split()).casefold()) if name.strip() else (record['organization_pseudonyms'][0] if record['organization_pseudonyms'] else '')
        published=None
        if payload['publication_date']:
            if not isinstance(payload['publication_date'],str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',payload['publication_date']):raise ValueError('Invalid source date')
            published=datetime.fromisoformat(payload['publication_date']).replace(tzinfo=timezone.utc)
            start=datetime.fromisoformat(store.run(run_id)['window_start'])
            if not start-timedelta(days=90)<=published<=now:raise ValueError('Source date is outside scope')
        fields={name:payload[name] for name in ['language','source_type','sector','broad_geography','claimed_exposure_type']}
        fields.update(organization_pseudonym=organization,source_claimed_publication_date=published.date().isoformat() if published else None,
            date_precision='day' if published else 'unknown',source_context_checked=True,privacy_checked=True,date_checked=True,duplicate_checked=True)
        receipt=context['receipt']
    ensure_schema(store)
    with store.db:
        store.db.execute('INSERT INTO release_review_events(run_id,observation_id,reviewer,decision,reason,fields_json,context_receipt,created_at) VALUES(?,?,?,?,?,?,?,?)',(run_id,observation_id,reviewer,payload['decision'],payload['reason'],json.dumps(fields,sort_keys=True),receipt,now.isoformat()))
    return {'decision':payload['decision'],'release':eligibility(store,run_id,record)}


def eligibility(store,run_id,record):
    ensure_schema(store)
    events=[dict(row) for row in store.db.execute('SELECT * FROM release_review_events WHERE run_id=? AND observation_id=? ORDER BY event_id',(run_id,record['observation_id']))]
    if not events:return {'status':'pending_review','reviewers':0}
    if events[-1]['decision']=='reject':return {'status':'rejected','reviewers':1}
    cutoff=max([e['event_id'] for e in events if e['decision']!='include'] or [0])
    latest={}
    for event in events:
        if event['event_id']>cutoff and event['context_receipt']==record.get('context_receipt'):latest[event['reviewer']]=event
    votes=sorted(latest.values(),key=lambda v:v['event_id'],reverse=True)
    if len(votes)<2:return {'status':'pending_second_review' if votes else 'pending_review','reviewers':len(votes)}
    if votes[0]['fields_json']!=votes[1]['fields_json']:return {'status':'review_disagreement','reviewers':len(votes)}
    return {'status':'eligible','reviewers':len(votes),'fields':json.loads(votes[0]['fields_json'])}


def _read_exact(connection,count):
    data=b''
    while len(data)<count:
        chunk=connection.recv(count-len(data))
        if not chunk:raise RuntimeError('Review service closed connection')
        data+=chunk
    return data


class ReviewClient:
    def __init__(self,root):self.directory=Path(root)/'data/live'
    def call(self,action,contexts=None):
        path=self.directory/'review-session.json'
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:raise RuntimeError('Private review session unavailable')
        session=json.loads(path.read_text())
        request=json.dumps({'token':session['token'],'action':action,'contexts':contexts or []}).encode()
        if len(request)>1_000_000:raise ValueError('Review message too large')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
            connection.settimeout(10);connection.connect(str(self.directory/'review.sock'))
            connection.sendall(struct.pack('!I',len(request))+request)
            length=struct.unpack('!I',_read_exact(connection,4))[0]
            if length>4096:raise RuntimeError('Invalid review service response')
            result=json.loads(_read_exact(connection,length))
        if not result.get('ok'):raise RuntimeError('Review service rejected request')
        return result
    def ready(self):
        try:return self.call('ping').get('ready') is True
        except (OSError,ValueError,RuntimeError):return False
    def publish(self,contexts):return self.call('publish',contexts)
