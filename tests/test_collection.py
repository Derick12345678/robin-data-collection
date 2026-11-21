from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from robin_collect.collection import collect,prepare,load_key,exclusive
from robin_collect.collection_store import CollectionStore
from robin_collect.observations import observation,validate_observation,pseudonym

ROOT=Path(__file__).resolve().parents[1]
KEY='synthetic-private-hmac-key-for-tests-123456'
URL='http://'+'a'*56+'.onion/post/1'


def coverage(answered=1,empty=0,failed=0,results=1):
    return dict(engines_queried=answered+empty+failed,engines_answered=answered,engines_empty=empty,engines_failed=failed,
        results_raw=results,results_after_dedup=results,results_kept=results,results_dropped_abuse=0)


class FakeCollector:
    def __init__(self,interrupt_at=None,outages=0,cleanup=True):
        self.calls=[];self.cleanups=[];self.interrupt_at=interrupt_at;self.outages=outages;self.cleaned=cleanup
    def health(self):return {'exit_code':0}
    def cleanup(self,name):self.cleanups.append(name);return self.cleaned
    def collect(self,query,context):
        self.calls.append((query['id'],context['operation_deadline_utc']))
        if len(self.calls)==self.interrupt_at:raise KeyboardInterrupt('synthetic interruption')
        if len(self.calls)<=self.outages:return {'status':'engines_unreachable','coverage':coverage(0,0,16,0),'returned_count':0,'observations':[],'cleanup_confirmed':True}
        row=observation({'title':'We obtained Northwind company customer database records Alice Smith alice@example.invalid','link':URL},query['id'],context['key'],datetime.now(timezone.utc).isoformat(),datetime.fromisoformat(context['config']['scope']['collection_dates']['start_date_utc']),context['entities'])
        return {'status':'completed','coverage':coverage(),'returned_count':1,'observations':[row],'cleanup_confirmed':self.cleaned,'page_fetch_attempts':0,'model_calls':0}


class PrivacyTests(unittest.TestCase):
    def row(self,**changes):
        source={'title':'We obtained Northwind company database records Alice Smith alice@example.invalid','snippet':'SSN 123-45-6789, 123 Main Street, token=synthetic-secret','link':URL,**changes}
        return observation(source,'q001',KEY,datetime.now(timezone.utc).isoformat(),datetime.now(timezone.utc),{'Northwind':['Northwind']})
    def test_every_unstructured_field_is_withheld_and_entities_are_stable(self):
        row=self.row();encoded=json.dumps(row)
        for sensitive in ['Northwind','Alice Smith','alice@example.invalid','123-45-6789','Main Street','synthetic-secret',URL]:self.assertNotIn(sensitive,encoded)
        self.assertEqual(row['organization_pseudonyms'],[pseudonym(KEY,'organization','northwind')])
        self.assertEqual(row['relevance_reason'],'disallowed_content')
        self.assertEqual(row['review_status'],'pending_review')
        validate_observation(row,'q001')
    def test_source_identity_preserves_cross_source_and_changed_items(self):
        one=self.row();two=self.row(link=URL.replace('/1','/2'))
        self.assertNotEqual(one['observation_id'],two['observation_id'])
        self.assertEqual(one['content_pseudonym'],two['content_pseudonym'])
        changed=self.row(title='We obtained Northwind company database records update')
        self.assertNotEqual(one['observation_id'],changed['observation_id'])
        formatting=self.row(title='  We   obtained Northwind company database records Alice Smith alice@example.invalid  ')
        self.assertEqual(one['observation_id'],formatting['observation_id'])
    def test_unsafe_expansion_or_arbitrary_title_is_rejected(self):
        for field,value in [('title_sanitized','Alice Smith'),('extra','raw text'),('relevance_reason','secret source title'),('relevance_reason',[]),('title_sanitized',{}),('redaction_categories',[[]])]:
            row=self.row();row[field]=value
            with self.assertRaises(ValueError):validate_observation(row,'q001')
    def test_missing_dates_and_old_dates_have_explicit_decisions(self):
        row=self.row(snippet='')
        self.assertEqual(row['publication_date_status'],'unknown')
        self.assertEqual(row['relevance_decision'],'candidate')
        old=(datetime.now(timezone.utc)-timedelta(days=100)).isoformat()
        self.assertEqual(self.row(snippet='',publication_date=old)['relevance_reason'],'out_of_date')


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        (self.root/'config').mkdir();(self.root/'deploy').mkdir()
        self.config=json.loads((ROOT/'config/queries.json').read_text())
        now=datetime.now(timezone.utc)
        self.config['scope']['collection_dates'].update(start_date_utc=(now-timedelta(minutes=1)).isoformat(),end_date_utc=(now+timedelta(hours=1)).isoformat())
        self.config['queries']=[{**q,'enabled':True} for q in self.config['queries'][:1]]
        self.write_config()
        (self.root/'deploy/robin.lock.json').write_text((ROOT/'deploy/robin.lock.json').read_text())
        directory=prepare(self.root);(directory/'hmac.key').write_text(KEY);(directory/'hmac.key').chmod(0o600)
    def tearDown(self):self.temporary.cleanup()
    def write_config(self):(self.root/'config/queries.json').write_text(json.dumps(self.config))
    def store(self):return CollectionStore(self.root/'data/live/collection.sqlite',KEY)
    def test_enrichment_history_is_shared_and_repeated_query_matches_reuse_evidence(self):
        from robin_collect.enrichment import enrich_results
        from test_enrichment import Session,LIMITS
        import time
        class EnrichedCollector(FakeCollector):
            def review_ready(self):return True
            def publish_contexts(self):return True
            def collect(inner,query,context):
                raw={'title':'We obtained Northwind company customer database records claim','link':URL}
                now=datetime.now(timezone.utc)
                base=observation(raw,query['id'],context['key'],now.isoformat(),now)
                session=Session()
                rows,events,_=enrich_results([raw],[base],query['id'],context['key'],now.isoformat(),{},90,context['page_tokens'],LIMITS,time.monotonic()+20,context['run_id'],session,context['seen_sources'])
                inner.calls.extend(session.calls)
                return dict(status='completed',observations=rows,page_events=events,page_fetch_attempts=len(events),returned_count=1,coverage=coverage(),cleanup_confirmed=True)
        base=json.loads((ROOT/'config/queries.json').read_text())
        self.config['queries']=[{**q,'enabled':True} for q in base['queries'][:2]];self.write_config()
        collector=EnrichedCollector();result=collect(self.root,'shared',collector=collector,enrich=True,validation=True)
        self.assertEqual(len(collector.calls),1);self.assertEqual(result['record_count'],1);self.assertEqual(result['page_fetch_attempts'],1)
        store=self.store()
        try:self.assertEqual(store.observations('shared')[0]['query_ids'],['q001','q002'])
        finally:store.close()
    def test_layout_refusal_stops_remaining_queries_and_releases_unused_pages(self):
        class LayoutFailure(FakeCollector):
            def review_ready(self):return True
            def collect(inner,query,context):
                inner.calls.append(query['id'])
                return dict(status='failed',code='unsupported_layout',returned_count=0,observations=[],cleanup_confirmed=True,coverage=coverage(0,0,1,0),page_fetch_attempts=0,page_events=[],retrieval_diagnostics=dict(engines_skipped=15,recognized_results=0,recognized_empty=0,unsupported_layout=1,fetch_failed=0,engine_http_requests=2))
        base=json.loads((ROOT/'config/queries.json').read_text());self.config['queries']=[{**q,'enabled':True} for q in base['queries'][:2]];self.write_config()
        collector=LayoutFailure();result=collect(self.root,'layout-refused',collector=collector,enrich=True,validation=True)
        self.assertEqual(collector.calls,['q001']);self.assertEqual(result['page_fetch_attempts'],0)
        store=self.store()
        try:self.assertEqual(store.query('layout-refused','q002')['state'],'blocked')
        finally:store.close()
    def test_larger_batches_are_blocked_before_collection_without_a_reviewed_pilot(self):
        from robin_collect.limits import PolicyError
        base=json.loads((ROOT/'config/queries.json').read_text())
        self.config['queries']=[{**q,'enabled':True} for q in base['queries'][:4]];self.write_config()
        collector=FakeCollector()
        with self.assertRaises(PolicyError):collect(self.root,'too-soon',collector=collector)
        self.assertFalse(collector.calls)
    def test_quarantine_preserves_completed_run_and_prevents_resume(self):
        from robin_collect.limits import PolicyError
        collect(self.root,'quarantined',collector=FakeCollector())
        store=self.store()
        try:store.quarantine('quarantined');self.assertEqual(len(store.observations('quarantined')),1)
        finally:store.close()
        collector=FakeCollector()
        with self.assertRaises(PolicyError):collect(self.root,'quarantined',resume=True,collector=collector)
        self.assertFalse(collector.calls)
    def test_completed_query_resumes_without_a_second_network_dispatch(self):
        collector=FakeCollector();result=collect(self.root,'run1',collector=collector)
        self.assertEqual(result['status'],'completed');self.assertEqual(len(collector.calls),1)
        result=collect(self.root,'run1',resume=True,collector=collector)
        self.assertEqual(len(collector.calls),1)
        self.assertFalse(result['approved_export_available'])
        records=(Path(result['output_directory'])/'observations.review.jsonl').read_text()
        database=(self.root/'data/live/collection.sqlite').read_bytes()
        for raw in [b'Northwind',b'Alice Smith',b'alice@example.invalid',URL.encode()]:self.assertNotIn(raw,database)
        self.assertNotIn('Northwind',records)
    def test_interruption_preserves_completed_work_and_charges_uncertain_attempt(self):
        original=json.loads((ROOT/'config/queries.json').read_text())['queries']
        self.config['queries']=[{**q,'enabled':True} for q in original[:3]];self.write_config()
        collector=FakeCollector(interrupt_at=2)
        with self.assertRaises(KeyboardInterrupt):collect(self.root,'interrupted',collector=collector)
        replacement=FakeCollector();result=collect(self.root,'interrupted',resume=True,collector=replacement)
        self.assertEqual([q for q,_ in replacement.calls],['q003'])
        self.assertEqual(len(replacement.cleanups),1)
        store=self.store()
        try:
            manifest=store.manifest('interrupted')
            q2=store.query('interrupted','q002');self.assertEqual(q2['state'],'uncertain');self.assertEqual(q2['attempts'],1)
            self.assertEqual(store.query('interrupted','q001')['attempts'],1)
            self.assertEqual(store.observations('interrupted')[0]['query_ids'],['q001','q003'])
        finally:store.close()
        self.assertEqual(result['status'],'needs_attention')
    def test_outage_retries_share_deadline_and_have_durable_reports(self):
        collector=FakeCollector(outages=1)
        with patch('robin_collect.collection.time.sleep'):
            result=collect(self.root,'retry',collector=collector)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(len(collector.calls),2)
        self.assertEqual(collector.calls[0][1],collector.calls[1][1])
        store=self.store()
        try:
            attempts=store.manifest('retry')['attempts']
            self.assertEqual(len(attempts),2)
            self.assertEqual(attempts[0]['report']['coverage']['engines_failed'],16)
        finally:store.close()
    def test_unconfirmed_cleanup_never_commits_observations(self):
        result=collect(self.root,'uncertain',collector=FakeCollector(cleanup=False))
        self.assertEqual(result['record_count'],0)
        self.assertEqual(result['status'],'needs_attention')
    def test_unconfirmed_cleanup_is_retried_without_refunding_or_searching(self):
        collect(self.root,'cleanup-retry',collector=FakeCollector(cleanup=False))
        replacement=FakeCollector()
        result=collect(self.root,'cleanup-retry',resume=True,collector=replacement)
        self.assertEqual(replacement.calls,[])
        self.assertEqual(len(replacement.cleanups),1)
        self.assertEqual(result['status'],'needs_attention')
        store=self.store()
        try:
            manifest=store.manifest('cleanup-retry')
            self.assertEqual(manifest['queries'][0]['attempts'],1)
            self.assertTrue(manifest['attempts'][0]['cleanup_confirmed'])
        finally:store.close()

    def test_policy_or_key_drift_cannot_resume(self):
        collect(self.root,'frozen',collector=FakeCollector())
        self.config['version']='changed';self.write_config()
        with self.assertRaises(RuntimeError):collect(self.root,'frozen',resume=True,collector=FakeCollector())
        with self.assertRaises(ValueError):CollectionStore(self.root/'data/live/collection.sqlite','another-key-long-enough-to-pass-validation')
    def test_exclusive_controller_lock_prevents_competing_resume(self):
        with exclusive(self.root/'data/live/collection.lock'):
            with self.assertRaises(RuntimeError):collect(self.root,'concurrent',collector=FakeCollector())
    def test_two_reservations_cannot_dispatch_same_query(self):
        collector=FakeCollector(interrupt_at=1)
        with self.assertRaises(KeyboardInterrupt):collect(self.root,'charged',collector=collector)
        store=self.store()
        try:
            with self.assertRaises(RuntimeError):store.reserve('charged','q001',3,datetime.now(timezone.utc).isoformat(),'robin-capture-'+'c'*32)
            self.assertEqual(store.query('charged','q001')['attempts'],1)
        finally:store.close()
    def test_per_run_snapshots_and_append_only_review_history(self):
        collect(self.root,'snapshot1',collector=FakeCollector())
        entities=self.root/'data/live/entities.json'
        entities.write_text(json.dumps({'Northwind':['Northwind']}));entities.chmod(0o600)
        collect(self.root,'snapshot2',collector=FakeCollector())
        store=self.store()
        try:
            first=store.observations('snapshot1')[0];second=store.observations('snapshot2')[0]
            self.assertEqual(first['organization_detection'],'unknown')
            self.assertEqual(second['organization_detection'],'registry_match')
            self.assertEqual(first['observation_id'],second['observation_id'])
            self.assertNotEqual(first['collected_at_utc'],second['collected_at_utc'])
            identity=second['observation_id']
            store.review(identity,'candidate','consistent_with_scope','reviewer01','snapshot2')
            store.review(identity,'needs_review','requires_source_review','reviewer02','snapshot2')
            self.assertEqual(len(store.observations('snapshot2')[0]['review_history']),2)
            self.assertEqual(len(store.observations('snapshot1')[0]['review_history']),0)
            self.assertEqual(store.manifest('snapshot2')['dataset_approval'],'not_approved')
        finally:store.close()

    def test_cross_source_duplicates_are_review_candidates_and_changes_remain_distinct(self):
        collect(self.root,'one',collector=FakeCollector())
        store=self.store()
        try:
            start=self.config['scope']['collection_dates']['start_date_utc'];end=self.config['scope']['collection_dates']['end_date_utc']
            store.create_run('two','hash','entities',start,end,self.config['queries'],self.config['limits'],'image')
            number=store.reserve('two','q001',3,end,'robin-capture-'+'d'*32)
            rows=[observation({'title':'We obtained Northwind company customer database records Alice Smith alice@example.invalid','link':URL.replace('/1','/2')},'q001',KEY,datetime.now(timezone.utc).isoformat(),datetime.fromisoformat(start)),observation({'title':'We obtained Northwind company customer database records Alice Smith alice@example.invalid update','link':URL},'q001',KEY,datetime.now(timezone.utc).isoformat(),datetime.fromisoformat(start))]
            store.complete('two','q001',number,{'status':'completed','coverage':coverage(results=2),'returned_count':2,'observations':rows,'cleanup_confirmed':True})
            result=store.observations('two')
            self.assertEqual(len(result),2)
            self.assertTrue(any(r['cross_source_duplicate_candidate'] for r in result))
            self.assertTrue(any(r['near_duplicate_candidates'] for r in result))
            self.assertTrue(any(r['change_review']=='requires_review' for r in result))
        finally:store.close()


if __name__=='__main__':unittest.main()
