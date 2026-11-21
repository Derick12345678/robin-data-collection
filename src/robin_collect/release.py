"""Release-reviewed sanitized CSV bundles; unresolved records never enter by default."""
from datetime import datetime,timezone
import csv
import hashlib
import json
from pathlib import Path
import uuid
from .collection import prepare,load_key,exclusive,_run_id
from .collection_store import CollectionStore
from .review import eligibility
from .sanitize import csv_safe

FIELDS=['observation_id','source_pseudonym','organization_pseudonym','source_type','sector','broad_geography',
    'claimed_exposure_type','language','source_claimed_publication_date','date_precision','title_sanitized',
    'summary_sanitized','first_collected_at_utc','last_collected_at_utc','query_ids','run_id','page_truncated',
    'claim_status','reviewer_count']
DESCRIPTIONS={
'observation_id':'Keyed source-and-content observation identity; enrichment links remain in the source manifest.',
'source_pseudonym':'Stable keyed pseudonym of the normalized source locator; raw URL is absent.',
'organization_pseudonym':'Reviewer-established organization pseudonym, or blank when not established.',
'source_type':'Reviewed source category: forum post, marketplace listing, leak announcement, or related discussion.',
'sector':'Reviewed broad sector; unknown remains explicit.',
'broad_geography':'Reviewed broad region; unknown remains explicit.',
'claimed_exposure_type':'Reviewed alleged data exposure category; never a verified breach assertion.',
'language':'Reviewed source language; this scope permits English.',
'source_claimed_publication_date':'Reviewed source-claimed calendar date, or blank if unavailable.',
'date_precision':'day when a claimed date is established; otherwise unknown.',
'title_sanitized':'Keyed title marker; original source title is withheld.',
'summary_sanitized':'Finite template derived from reviewed classification; not a source quotation.',
'first_collected_at_utc':'First recorded collection timestamp for this observation.',
'last_collected_at_utc':'Most recent recorded collection timestamp for this observation.',
'query_ids':'Semicolon-separated matching registry IDs within this run.',
'run_id':'Frozen collection run identifier.',
'page_truncated':'Whether the bounded source/review text was truncated.',
'claim_status':'Always unverified_source_claim; review does not authenticate the alleged exposure.',
'reviewer_count':'Number of consistent, distinct reviewer IDs supporting inclusion (minimum two).'}


def release_bundle(root,run_id,allow_partial=False):
    root=Path(root);run_id=_run_id(run_id);directory=prepare(root)
    with exclusive(directory/'collection.lock'):
        store=CollectionStore(directory/'collection.sqlite',load_key(root))
        try:
            manifest=store.manifest(run_id);records=store.observations(run_id)
            decisions={record['observation_id']:eligibility(store,run_id,record) for record in records}
            eligible=[r for r in records if decisions[r['observation_id']]['status']=='eligible']
            rejected=[r for r in records if decisions[r['observation_id']]['status']=='rejected']
            pending=[r for r in records if decisions[r['observation_id']]['status'] not in {'eligible','rejected'}]
            incomplete=[q['query_id'] for q in manifest['queries'] if q['state'] not in {'completed','no_results'}]
            quarantined=bool(manifest['quarantine_events'])
            blocked=quarantined or (bool(pending or incomplete) and (not allow_partial or not eligible))
            report={'run_id':run_id,'created_at_utc':datetime.now(timezone.utc).isoformat(),
                'status':'blocked_quarantined' if quarantined else 'blocked_pending_review' if blocked else 'approved_partial' if pending or incomplete else 'approved',
                'approved_csv_created':not blocked,'partial_requested':allow_partial,'eligible_count':len(eligible),
                'rejected_count':len(rejected),'pending_count':len(pending),'incomplete_queries':incomplete,
                'excluded_observation_ids':[r['observation_id'] for r in records if r not in eligible],
                'required_consistent_reviewers':2,'claim_authenticity':'not_verified','raw_content_included':False}
            target=root/'outputs/releases'/run_id/('release-'+uuid.uuid4().hex)
            target.mkdir(parents=True,mode=0o700)
            dictionary='# Sanitized findings data dictionary\n\nUTF-8 CSV with standard quoting. Empty dates/organization identifiers mean unavailable; unknown categories remain explicit. Text formula prefixes are neutralized. Every included claim remains unverified. Reviewer IDs are self-reported audit identifiers, not independently authenticated identities.\n\n| Field | Meaning |\n|---|---|\n'+''.join('| '+name+' | '+DESCRIPTIONS[name]+' |\n' for name in FIELDS)
            (target/'DATA_DICTIONARY.md').write_text(dictionary,encoding='utf-8')
            if not blocked:
                path=target/'findings_sanitized.csv'
                with path.open('w',newline='',encoding='utf-8') as stream:
                    writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader()
                    for record in eligible:
                        decision=decisions[record['observation_id']];fields=decision['fields']
                        row={name:fields.get(name,'') for name in FIELDS}
                        row.update(observation_id=record['observation_id'],source_pseudonym=record['source_pseudonym'],
                            title_sanitized=record['title_sanitized'],summary_sanitized='Unverified organizational '+fields['claimed_exposure_type'].replace('_',' ')+' claim.',
                            first_collected_at_utc=record['first_collected_at_utc'],last_collected_at_utc=record['last_collected_at_utc'],
                            query_ids=';'.join(record['query_ids']),run_id=run_id,page_truncated=record.get('page_truncated',False),
                            claim_status='unverified_source_claim',reviewer_count=decision['reviewers'])
                        writer.writerow({name:csv_safe('' if value is None else str(value)) for name,value in row.items()})
                with path.open(newline='',encoding='utf-8') as stream:roundtrip=list(csv.DictReader(stream))
                if len(roundtrip)!=len(eligible):raise RuntimeError('CSV round-trip failed')
                report.update(csv_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),csv_round_trip='passed',csv_rows=len(roundtrip))
            snapshot={'source_run':manifest,'release_decisions':decisions,'review_events':[dict(row) for row in store.db.execute('SELECT * FROM release_review_events WHERE run_id=? ORDER BY event_id',(run_id,))]}
            (target/'manifest.json').write_text(json.dumps(snapshot,indent=2)+'\n',encoding='utf-8')
            (target/'quality.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
            return {**report,'output_directory':str(target)}
        finally:store.close()
