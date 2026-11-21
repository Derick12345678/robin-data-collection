"""Resumable, structured-only collection orchestration with durable attempt budgets."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import secrets
import time
import uuid
from .adapters import RobinMCPCollector
from .collection_store import CollectionStore, utc
from .limits import load_policy, PolicyError
from .observations import validate_entities, pseudonym


def prepare(root):
    directory=Path(root)/'data/live'
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    directory.chmod(0o700)
    key_path=directory/'hmac.key'
    if not key_path.exists():
        if (directory/'collection.sqlite').exists():raise RuntimeError('Existing database requires its original key')
        descriptor=os.open(key_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w') as stream:stream.write(secrets.token_hex(32))
    return directory


def load_key(root):
    path=Path(root)/'data/live/hmac.key'
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:raise RuntimeError('HMAC key requires private regular-file permissions')
    key=path.read_text().strip()
    if len(key)<32:raise RuntimeError('Invalid HMAC key')
    return key


@contextmanager
def exclusive(path):
    import fcntl
    descriptor=os.open(path,os.O_RDWR|os.O_CREAT,0o600)
    with os.fdopen(descriptor,'a') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('A collection process is already active') from None
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)


def entities_for(root):
    path=Path(root)/'data/live/entities.json'
    if not path.exists():return {}
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:raise RuntimeError('Entity registry requires private permissions')
    return validate_entities(json.loads(path.read_text()))


def _run_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value):raise ValueError('Invalid run ID')
    return value


def plan(root,pilot=False,policy_path=None):
    path=Path(policy_path) if policy_path else Path(root)/'config/queries.json'
    policy=load_policy(path)
    config=json.loads(path.read_text())
    if pilot:
        chosen=next(q for q in config['queries'] if q['id']=='q001')
        if len(chosen['text'].split())>5 or re.search(r'\b(?:AND|OR|NOT)\b',chosen['text']):raise PolicyError('Pilot query requires reviewed short refinement')
        ids=['q001']
    else:ids=sorted(policy.enabled_ids)
    for query in config['queries']:
        if query['id'] in ids and (len(query['text'].split())>5 or re.search(r'\b(?:AND|OR|NOT)\b',query['text'])):
            raise PolicyError('Enabled queries require reviewed short refinements')
    return {'mode':'single_query_pilot' if pilot else 'configured_batch','query_ids':ids,
        'base_config_sha256':policy.config_sha256,'limits':asdict(policy.limits),
        'main_registry_blockers':policy.blockers(),'network_activity':False,
        'privacy_mode':'structured_only','dataset_approval':'not_approved'}


def freeze_batch_policy(root, destination=None, now=None):
    """Freeze one approved batch; never overwrite or renew an existing policy."""
    root=Path(root)
    directory=prepare(root)
    destination=Path(destination) if destination else directory/'batch-policy.json'
    if not destination.is_absolute():destination=root/destination
    if destination.parent.resolve()!=directory.resolve() or destination.is_symlink():
        raise PolicyError('Batch policies must be private files directly inside data/live')
    config=json.loads((root/'config/queries.json').read_text())
    if config.get('status')!='approved':raise PolicyError('Approved scope required')
    refinements={
        'q008':'corporate leak claim evidence description',
        'q010':'financial services company leak announcement',
        'q015':'public sector organizational breach announcement',
    }
    for query in config['queries']:
        query['original_text']=query['text']
        query['text']=refinements.get(query['id'],query['text'])
        query['enabled']=True
        if len(query['text'].split())>5 or re.search(r'\b(?:AND|OR|NOT)\b',query['text']):
            raise PolicyError('Batch query requires reviewed short refinement')
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise PolicyError('UTC-aware batch start required')
    config['version']='1.3-frozen-batch'
    config['scope']['collection_dates'].update(start_date_utc=now.isoformat(),end_date_utc=(now+timedelta(hours=24)).isoformat())
    raw=json.dumps(config,indent=2)+'\n'
    descriptor=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w',encoding='utf-8') as stream:stream.write(raw)
    return {'status':'frozen','policy_path':str(destination),**plan(root,False,destination)}


def collect(root,run_id=None,pilot=False,resume=False,collector=None,enrich=False,policy_path=None):
    root=Path(root)
    run_id=_run_id(run_id or 'collection-'+uuid.uuid4().hex)
    directory=prepare(root)
    key=load_key(root)
    entities=entities_for(root)
    entities_hash=pseudonym(key,'entities',json.dumps(entities,sort_keys=True))
    path=Path(policy_path) if policy_path else root/'config/queries.json'
    policy=load_policy(path)
    config=json.loads(path.read_text())
    options={'enrich':bool(enrich),'pages_per_query_target':5 if pilot else 2,'raw_response_bytes':1_000_000,'context_ttl_seconds':86400}
    image=json.loads((root/'deploy/robin.lock.json').read_text())['image']
    with exclusive(directory/'collection.lock'):
        store=CollectionStore(directory/'collection.sqlite',key)
        try:
            if resume:
                metadata=store.run(run_id)
                if metadata['config_hash']!=policy.config_sha256 or metadata['entities_hash']!=entities_hash or metadata['image']!=image:
                    raise RuntimeError('Resume requires the original policy, entity registry, and image')
                options=json.loads(metadata['options_json'])
                start,end=metadata['window_start'],metadata['window_end']
                ids=json.loads(metadata['query_ids'])
            else:
                requested=plan(root,pilot,path)
                ids=requested['query_ids']
                if not ids:raise PolicyError('No enabled queries')
                now=datetime.now(timezone.utc)
                start=(policy.start or now).isoformat()
                end=(policy.end or now+timedelta(hours=1)).isoformat()
                if not pilot and policy.blockers():raise PolicyError('Configure enabled queries and collection dates')
                queries=[q for q in config['queries'] if q['id'] in ids]
                store.create_run(run_id,policy.config_sha256,entities_hash,start,end,queries,asdict(policy.limits),image,options)
            config['scope']['collection_dates'].update(start_date_utc=start,end_date_utc=end)
            for query in config['queries']:query['enabled']=query['id'] in ids
            # Validate the effective pilot window with the same strict parser.
            from tempfile import TemporaryDirectory
            with TemporaryDirectory() as tmp:
                effective_path=Path(tmp)/'policy.json';effective_path.write_text(json.dumps(config))
                effective=load_policy(effective_path)
            # Completed queries can be exported/resumed even after the window closes.
            unfinished=[qid for qid in ids if store.query(run_id,qid)['state'] not in {'completed','no_results'}]
            if not unfinished:
                return write_artifacts(root,store,run_id)
            collector=collector or RobinMCPCollector(root)
            for attempt in store.inflight(run_id):
                cleanup=collector.cleanup(attempt['container_name'])
                store.recover(run_id,attempt['query_id'],attempt['attempt'],cleanup)
            if (options.get('enrich') and not collector.review_ready()) or collector.health().get('exit_code')!=0:
                store.finish(run_id)
                return write_artifacts(root,store,run_id)
            for query in config['queries']:
                if query['id'] not in ids:continue
                state=store.query(run_id,query['id'])
                if state['state'] not in {'pending','retryable','engines_unreachable'}:continue
                while state['attempts']<1+policy.limits.max_retries:
                    try:effective.require_live(query['id'])
                    except PolicyError:
                        with store.db:
                            store.db.execute("UPDATE collection_queries SET state='blocked',error_code='collection_window_closed' WHERE run_id=? AND query_id=?",(run_id,query['id']))
                        break
                    if state['operation_deadline']:
                        deadline=datetime.fromisoformat(state['operation_deadline'])
                    else:
                        deadline=min(datetime.now(timezone.utc)+timedelta(seconds=policy.limits.timeout_seconds),effective.end)
                    if deadline<=datetime.now(timezone.utc):break
                    if state['state']=='engines_unreachable':store.allow_retry(run_id,query['id'])
                    name='robin-capture-'+uuid.uuid4().hex
                    if options.get('enrich') and not collector.review_ready():break
                    number=store.reserve(run_id,query['id'],1+policy.limits.max_retries,deadline.isoformat(),name)
                    tokens=store.reserve_pages(run_id,query['id'],number,options['pages_per_query_target']) if options.get('enrich') else []
                    context={'run_id':run_id,'page_tokens':tokens,'container_name':name,'config':config,'key':key,'entities':entities,'operation_deadline_utc':deadline.isoformat()}
                    # Unexpected interruption leaves the reserved attempt in flight;
                    # resume first cleans it up and marks it uncertain, never refunds it.
                    try:
                        outcome=collector.collect(query,context)
                        store.complete(run_id,query['id'],number,outcome)
                    except (ValueError,RuntimeError):
                        cleanup=collector.cleanup(name)
                        store.complete(run_id,query['id'],number,{'status':'failed','code':'capture_failed','observations':[],'returned_count':None,'cleanup_confirmed':cleanup})
                    state=store.query(run_id,query['id'])
                    if options.get('enrich') and state['state']=='completed':
                        try:delivered=collector.publish_contexts()
                        except Exception:delivered=False
                        with store.db:
                            saved=json.loads(state['report_json'])
                            saved['review_context_delivery']='available' if delivered else 'failed'
                            store.db.execute('UPDATE collection_queries SET report_json=? WHERE run_id=? AND query_id=?',(json.dumps(saved),run_id,query['id']))
                    if state['state']!='engines_unreachable' or state['attempts']>=1+policy.limits.max_retries:break
                    delay=min(policy.limits.retry_backoff_initial_seconds*2**(state['attempts']-1),policy.limits.retry_backoff_max_seconds)
                    if datetime.now(timezone.utc)+timedelta(seconds=delay)>=deadline:break
                    time.sleep(delay)
            store.finish(run_id)
            return write_artifacts(root,store,run_id)
        finally:store.close()


def write_artifacts(root,store,run_id):
    records=store.observations(run_id)
    manifest=store.manifest(run_id)
    quality={'run_id':run_id,'record_count':len(records),'privacy_mode':'structured_only','dataset_approval':'not_approved',
        'relevance_counts':{state:sum(r['relevance_decision']==state for r in records) for state in ['candidate','rejected','needs_review']},
        'missing_snippets':sum(not r['snippet_available'] for r in records),
        'publication_dates_unknown':sum(r['publication_date_status']!='known' for r in records),
        'changed_source_candidates':sum(r['change_review']=='requires_review' for r in records),
        'near_duplicate_candidates':sum(bool(r['near_duplicate_candidates']) for r in records),
        'review_required':True,'approved_export_available':False,'release_command_available':True,
        'page_fetch_attempts':manifest['page_fetch_attempts'],
        'enriched_records':sum(r.get('page_status')=='ok' for r in records),
        'truncated_page_records':sum(r.get('page_truncated',False) for r in records),
        'source_claims_verified':False}
    directory=Path(root)/'outputs/live'/run_id
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    for name,content in [('observations.review.jsonl',''.join(json.dumps(r,sort_keys=True)+'\n' for r in records)),('manifest.json',json.dumps(manifest,indent=2)+'\n'),('quality.json',json.dumps(quality,indent=2)+'\n')]:
        temporary=directory/(name+'.tmp')
        temporary.write_text(content,encoding='utf-8')
        temporary.replace(directory/name)
    return {'run_id':run_id,'status':manifest['status'],'output_directory':str(directory),**quality}
