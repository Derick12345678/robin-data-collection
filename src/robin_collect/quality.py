"""Run quarantine and a human-measured pilot gate for larger collections."""
import hashlib
import json
from pathlib import Path
from .review import ensure_schema

FINGERPRINT_FILES=['screening.py','retrieval.py','enrichment.py','observations.py','collection.py','collection_store.py','live_adapter.py','quality.py','review.py']

def fingerprint():
    root=Path(__file__).parent
    digest=hashlib.sha256()
    for name in FINGERPRINT_FILES:digest.update(name.encode()+b'\0'+(root/name).read_bytes())
    deploy=root.parents[1]/'deploy'
    for name in ['collect_probe.py','pilot_probe.py']:digest.update(name.encode()+b'\0'+(deploy/name).read_bytes())
    return digest.hexdigest()


def scope_fingerprint(config):
    scope=json.loads(json.dumps(config['scope']))
    scope['collection_dates'].pop('start_date_utc',None);scope['collection_dates'].pop('end_date_utc',None)
    value={'scope':scope,'limits':config['limits'],'sanitization':config['sanitization'],
        'queries':sorted([(q['id'],q.get('original_text',q['text']),q['category'],q['language']) for q in config['queries']])}
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def validation_report(store,run_id):
    from .screening import primary_claim_supported
    run=store.run(run_id);options=json.loads(run['options_json']);records=store.observations(run_id)
    ensure_schema(store)
    sample=[];included=0;disagreed=0
    for record in records:
        if record.get('page_status')!='ok':continue
        events=[dict(row) for row in store.db.execute('SELECT * FROM release_review_events WHERE run_id=? AND observation_id=? ORDER BY event_id',(run_id,record['observation_id']))]
        latest={}
        for event in events:latest[event['reviewer']]=event
        decisions={event['decision'] for event in latest.values()}
        if not decisions or 'needs_review' in decisions:continue
        if len(decisions)>1:disagreed+=1;continue
        if decisions=={'include'} and not primary_claim_supported(record,require_page=True):continue
        if decisions=={'include'} and any(event['context_receipt']!=record.get('context_receipt') for event in latest.values()):continue
        sample.append(record['observation_id']);included+=decisions=={'include'}
    count=len(sample);precision=included/count if count else None
    completed=run['status']=='completed'
    current=options.get('retrieval_fingerprint')==fingerprint()
    quarantined=bool(store.quarantine_events(run_id))
    passed=bool(options.get('quality_validation') and completed and current and not quarantined and 10<=count<=20 and precision>=.8 and not disagreed)
    return {'run_id':run_id,'status':'passed' if passed else 'blocked_quality_validation','reviewed_unique_pages':count,
        'relevant_pages':included,'relevance_precision':precision,'minimum_reviewed':10,'maximum_reviewed':20,
        'required_precision':.8,'disagreements':disagreed,'is_validation_run':bool(options.get('quality_validation')),
        'collector_matches':current,'run_completed':completed,'quarantined':quarantined,'model_calls':0}
