from datetime import datetime,timedelta,timezone
import json,tempfile,time
from pathlib import Path
import unittest
from robin_collect.collection import prepare
from robin_collect.collection_store import CollectionStore
from robin_collect.enrichment import enrich_results
from robin_collect.observations import observation
from robin_collect.review import ReviewMemory,record_vote,eligibility
from robin_collect.release import release_bundle
from test_enrichment import KEY,URL,LIMITS,Session

ROOT=Path(__file__).resolve().parents[1]


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);directory=prepare(self.root)
        (directory/'hmac.key').write_text(KEY);(directory/'hmac.key').chmod(0o600)
        self.store=CollectionStore(directory/'collection.sqlite',KEY)
        now=datetime.now(timezone.utc);self.start=(now-timedelta(minutes=1)).isoformat();self.end=(now+timedelta(hours=1)).isoformat()
        config=json.loads((ROOT/'config/queries.json').read_text());self.limits=config['limits']
        self.store.create_run('review-run','config','entities',self.start,self.end,[{'id':'q001','text':'synthetic query'}],self.limits,'image',{'enrich':True})
        attempt=self.store.reserve('review-run','q001',3,self.end,'robin-capture-'+'d'*32)
        tokens=self.store.reserve_pages('review-run','q001',attempt,5)
        raw={'title':'We obtained Northwind company database records claim','link':URL};original=observation(raw,'q001',KEY,now.isoformat(),now)
        self.rows,self.events,self.contexts=enrich_results([raw],[original],'q001',KEY,self.start,{},90,tokens,LIMITS,time.monotonic()+20,'review-run',Session())
        coverage=dict(engines_queried=1,engines_answered=1,engines_empty=0,engines_failed=0,results_raw=1,results_after_dedup=1,results_kept=1,results_dropped_abuse=0)
        self.store.complete('review-run','q001',attempt,dict(status='completed',observations=self.rows,coverage=coverage,returned_count=1,cleanup_confirmed=True,page_fetch_attempts=1,page_events=self.events))
        self.store.finish('review-run')
        self.memory=ReviewMemory(KEY,lambda run,obs:next((r for r in self.store.observations(run) if r['observation_id']==obs),None))
        self.memory.accept(self.contexts)
        self.identity=self.rows[0]['observation_id']
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def payload(self,reviewer='reviewer01',**changes):
        return dict(reviewer=reviewer,decision='include',reason='explicit_organizational_exposure_claim',source_context_checked=True,privacy_checked=True,duplicate_checked=True,date_checked=True,language='en',source_type='forum_post',sector='healthcare',broad_geography='North America',claimed_exposure_type='customer_data',organization_name='Northwind',publication_date='',**changes)
    def vote(self,payload):return record_vote(self.store,self.memory,'review-run',self.identity,payload)
    def test_only_dispatched_page_reservations_are_charged_after_confirmed_cleanup(self):
        manifest=self.store.manifest('review-run')
        self.assertEqual(manifest['page_fetch_attempts'],1)
        self.assertEqual(sum(p['state']=='released' for p in manifest['pages']),4)
    def test_context_is_memory_only_and_expiry_blocks_inclusion(self):
        raw=(self.root/'data/live/collection.sqlite').read_bytes()
        self.assertNotIn(b'Northwind',raw)
        self.memory.prune(datetime.now(timezone.utc)+timedelta(days=2))
        self.assertIsNone(self.memory.get('review-run',self.identity))
        with self.assertRaises(ValueError):self.vote(self.payload())
    def test_tampered_or_uncommitted_context_is_rejected(self):
        changed={**self.contexts[0],'text':'tampered'}
        with self.assertRaises(ValueError):self.memory.accept([changed])
        unknown={**self.contexts[0],'observation_id':'f'*64}
        with self.assertRaises(ValueError):self.memory.accept([unknown])
    def test_two_consistent_distinct_reviewers_are_required(self):
        self.vote(self.payload())
        self.vote(self.payload())
        self.assertEqual(eligibility(self.store,'review-run',self.rows[0])['status'],'pending_second_review')
        self.vote(self.payload('reviewer02'))
        self.assertEqual(eligibility(self.store,'review-run',self.rows[0])['status'],'eligible')
        self.assertNotIn(b'Northwind',(self.root/'data/live/collection.sqlite').read_bytes())
    def test_disagreement_and_new_uncertainty_block_release(self):
        self.vote(self.payload())
        second=self.payload('reviewer02');second['sector']='technology';self.vote(second)
        self.assertEqual(eligibility(self.store,'review-run',self.rows[0])['status'],'review_disagreement')
        third=self.payload('reviewer03');third.update(decision='needs_review',reason='requires_source_review');self.vote(third)
        self.assertNotEqual(eligibility(self.store,'review-run',self.rows[0])['status'],'eligible')
    def test_export_is_blocked_until_reviews_then_csv_contains_no_raw_text(self):
        blocked=release_bundle(self.root,'review-run');self.assertFalse(blocked['approved_csv_created'])
        self.assertFalse((Path(blocked['output_directory'])/'findings_sanitized.csv').exists())
        self.vote(self.payload());self.vote(self.payload('reviewer02'))
        approved=release_bundle(self.root,'review-run');self.assertEqual(approved['status'],'approved')
        csv=(Path(approved['output_directory'])/'findings_sanitized.csv').read_text()
        self.assertNotIn('Northwind',csv);self.assertNotIn(URL,csv);self.assertIn('unverified_source_claim',csv)
        self.assertEqual(approved['csv_rows'],1);self.assertEqual(approved['csv_round_trip'],'passed')
    def test_partial_release_does_not_create_an_empty_approved_csv(self):
        result=release_bundle(self.root,'review-run',allow_partial=True)
        self.assertEqual(result['status'],'blocked_pending_review')
        self.assertFalse(result['approved_csv_created'])
    def test_malformed_review_decision_is_rejected(self):
        payload=self.payload();payload['decision']=[]
        with self.assertRaises(ValueError):self.vote(payload)
    def test_failed_page_cannot_smuggle_extra_unvalidated_fields(self):
        from robin_collect.observations import validate_observation
        base=observation({'title':'synthetic','link':URL},'q001',KEY,self.start,datetime.fromisoformat(self.start))
        with self.assertRaises(ValueError):validate_observation({**base,'page_status':'fetch_failed','sector':'untrusted raw text'},'q001')
        with self.assertRaises(ValueError):validate_observation({**base,'page_status':[]},'q001')
    def test_redundant_receipt_does_not_block_unrelated_context_delivery(self):
        from unittest.mock import patch
        from robin_collect.live_adapter import MCPDockerTransport
        transport=object.__new__(MCPDockerTransport);transport.root=self.root
        context=self.contexts[0]
        transport.pending_contexts=[{**context,'receipt':'f'*64},context]
        with patch('robin_collect.review.ReviewClient') as client:
            client.return_value.publish.return_value={'accepted':1}
            self.assertFalse(transport.publish_contexts())
            client.return_value.publish.assert_called_once_with([context])
        self.assertEqual(transport.pending_contexts,[])
    def test_interrupted_reservations_remain_charged_and_batch_cap_is_shared(self):
        self.store.create_run('budget-run','hash','entities',self.start,self.end,[{'id':f'q{i}','text':'synthetic'} for i in range(4)],self.limits,'image')
        for i in range(3):
            attempt=self.store.reserve('budget-run',f'q{i}',3,self.end,'robin-capture-'+str(i)*32)
            self.assertEqual(len(self.store.reserve_pages('budget-run',f'q{i}',attempt,99)),10)
            self.store.recover('budget-run',f'q{i}',attempt,True)
        attempt=self.store.reserve('budget-run','q3',3,self.end,'robin-capture-'+'e'*32)
        self.assertEqual(self.store.reserve_pages('budget-run','q3',attempt,10),[])
        self.assertEqual(self.store.manifest('budget-run')['page_fetch_attempts'],30)


if __name__=='__main__':unittest.main()
