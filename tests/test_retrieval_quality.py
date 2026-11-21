from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from robin_collect.retrieval import parse_results,install,form_query_url
from robin_collect.screening import screen,rank_results
from robin_collect.enrichment import enrich_results
from robin_collect.observations import observation,validate_observation
from robin_collect.collection import prepare,collect
from robin_collect.collection_store import CollectionStore
from robin_collect.review import ReviewMemory,context_state,record_vote
from robin_collect.release import release_bundle
from robin_collect.quality import fingerprint,validation_report
from test_enrichment import KEY,URL,LIMITS,Session,Response

ROOT=Path(__file__).resolve().parents[1]
TITLE='We obtained Northwind company customer database records claim'

def html(rows=True):
    outside='<nav><a href="'+URL+'/nav">Hidden wiki directory</a></nav><aside><a href="'+URL+'/ad">VPN subscription offers</a></aside>'
    item='<li class="result"><h4><a href="/redirect/?redirect_url='+URL+'">'+TITLE+'</a></h4><p>Northwind customer data reportedly leaked</p><cite>source</cite><a href="/report">Report</a></li>'
    return outside+'<div id="ahmiaResultsPage">'+('<ol class="searchResults">'+item+'</ol>' if rows else '<p id="noResults">Nothing found</p>')+'</div>'

class ParserTests(unittest.TestCase):
    def test_only_result_heading_links_and_bounded_snippets_are_extracted(self):
        rows,status=parse_results(html())
        self.assertEqual(status,'recognized_results');self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['title'],TITLE)
        self.assertIn('reportedly leaked',rows[0]['snippet'])
        self.assertNotIn('VPN',json.dumps(rows));self.assertNotIn('Report',rows[0]['title'])
    def test_only_same_origin_public_get_search_form_is_submitted(self):
        form='<form id="searchForm" action="/search/" method="get"><input type="search" name="q"><input type="hidden" name="abcdef" value="123456"></form>'
        endpoint='http://engine.invalid/search/?q={query}'
        url=form_query_url(form,endpoint,'company+database+exposure+claim')
        self.assertIn('q=company+database+exposure+claim',url);self.assertIn('abcdef=123456',url)
        for changed in [form.replace('/search/','http://external.invalid/search/'),form.replace('method="get"','method="post"'),form.replace('abcdef','csrf'),form.replace('123456','untrusted arbitrary text')]:
            self.assertIsNone(form_query_url(changed,endpoint,'query'))
    def test_empty_is_distinct_from_changed_layout(self):
        self.assertEqual(parse_results(html(False)),([],'recognized_empty'))
        self.assertEqual(parse_results('<main><a href="'+URL+'">'+TITLE+'</a></main>'),([],'unsupported_layout'))
        self.assertEqual(parse_results('<ol class="searchResults"><li class="result"><h4><a href="'+URL+'">'+TITLE+'</a></h4></li></ol>'),([],'unsupported_layout'))
    def test_advertising_inside_result_list_is_excluded(self):
        value=html().replace('<li class="result">','<li class="result sponsored">')
        rows,status=parse_results(value);self.assertFalse(rows);self.assertEqual(status,'unsupported_layout')
    def test_unsupported_engines_make_no_network_request(self):
        from types import SimpleNamespace
        engine=SimpleNamespace(SEARCH_ENGINES=[{'name':'Ahmia','url':'http://engine.invalid/?q={query}'}],get_search_results_detailed=lambda *a,**k:None,ENGINE_FAILED='failed',_engine_record=lambda endpoint,status,**kw:dict(status=status,**kw))
        install(engine)
        result=engine.fetch_search_results_detailed('http://unsupported.invalid/','query')
        self.assertEqual(result['error'],'unsupported_parser');self.assertEqual(engine._quality_diagnostics['engines_skipped'],1)

class ScreeningTests(unittest.TestCase):
    def test_specific_claims_rank_above_generic_pages_and_educational_mentions(self):
        positive={'title':TITLE,'link':URL,'snippet':'Northwind claims customer records were exposed.'}
        negatives=[{'title':'Hidden Wiki onion links','link':URL+'/directory'}, {'title':'How to prevent company database breaches','link':URL+'/guide'}, {'title':'VPN subscription offers','link':URL+'/ads'}, {'title':'Database services','snippet':'Welcome. Leak prevention training.','link':URL+'/generic'}]
        self.assertEqual(rank_results([*negatives,positive])[0],positive)
        self.assertEqual(screen(**dict(title=TITLE,url=URL))['screening_decision'],'eligible')
        self.assertTrue(all(screen(row['title'],row.get('snippet',''),row['link'])['screening_score']==0 for row in negatives))
    def test_broad_keyword_pairs_are_insufficient(self):
        for text in ['database leak','Organizational data breach announcement','What is a database leak?']:
            self.assertNotEqual(screen(text)['screening_decision'],'eligible')
    def test_shared_source_ledger_and_within_query_duplicates_prevent_refetches(self):
        now=datetime.now(timezone.utc);raw={'title':TITLE,'link':URL};row=observation(raw,'q001',KEY,now.isoformat(),now)
        session=Session()
        rows,events,contexts=enrich_results([raw],[row,row],'q001',KEY,now.isoformat(),{},90,['a'*32,'b'*32],LIMITS,time.monotonic()+20,'synthetic',session)
        self.assertEqual(len(session.calls),1);self.assertEqual(len(events),1)
        self.assertEqual(rows[-1]['page_selection'],'already_attempted')
        session=Session()
        later,events,_=enrich_results([raw],[row],'q002',KEY,now.isoformat(),{},90,['c'*32],LIMITS,time.monotonic()+20,'synthetic',session,{row['source_pseudonym']})
        self.assertFalse(session.calls);self.assertFalse(events);self.assertEqual(later[0]['page_selection'],'already_attempted')
    def test_unrelated_discoveries_spend_no_page_budget(self):
        now=datetime.now(timezone.utc);raw={'title':'Hidden wiki onion links','link':URL};row=observation(raw,'q001',KEY,now.isoformat(),now);session=Session()
        rows,events,_=enrich_results([raw],[row],'q001',KEY,now.isoformat(),{},90,['a'*32],LIMITS,time.monotonic()+20,'synthetic',session)
        self.assertFalse(events);self.assertFalse(session.calls);self.assertEqual(rows[0]['page_selection'],'excluded')
        validate_observation(rows[0],'q001')

class QualityGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);directory=prepare(self.root)
        (directory/'hmac.key').write_text(KEY);(directory/'hmac.key').chmod(0o600)
        self.store=CollectionStore(directory/'collection.sqlite',KEY)
        now=datetime.now(timezone.utc);self.start=now.isoformat();self.end=(now+timedelta(hours=1)).isoformat()
        config=json.loads((ROOT/'config/queries.json').read_text());self.limits=config['limits']
        self.store.create_run('pilot','config','entities',self.start,self.end,[{'id':'q001','text':'synthetic'}],self.limits,'image',{'quality_validation':True,'retrieval_fingerprint':fingerprint()})
        number=self.store.reserve('pilot','q001',3,self.end,'robin-capture-'+'a'*32)
        tokens=self.store.reserve_pages('pilot','q001',number,10)
        raw=[{'title':TITLE,'link':URL+'/'+str(i)} for i in range(10)]
        base=[observation(row,'q001',KEY,self.start,now) for row in raw]
        class FreshSession:
            def get(self,*args,**kwargs):return Response()
        self.records,events,contexts=enrich_results(raw,base,'q001',KEY,self.start,{},90,tokens,LIMITS,time.monotonic()+30,'pilot',FreshSession())
        coverage=dict(engines_queried=1,engines_answered=1,engines_empty=0,engines_failed=0,results_raw=10,results_after_dedup=10,results_kept=10,results_dropped_abuse=0)
        self.store.complete('pilot','q001',number,dict(status='completed',observations=self.records,page_events=events,page_fetch_attempts=10,returned_count=10,coverage=coverage,cleanup_confirmed=True));self.store.finish('pilot')
        self.memory=ReviewMemory(KEY,lambda run,obs:next(r for r in self.store.observations(run) if r['observation_id']==obs));self.memory.accept(contexts)
    def tearDown(self):self.store.close();self.temp.cleanup()
    def vote(self,row,include=True):
        payload=dict(reviewer='synthetic_reviewer',decision='include' if include else 'reject',reason='explicit_organizational_exposure_claim' if include else 'unrelated',source_context_checked=True,privacy_checked=True,duplicate_checked=True,date_checked=True,language='en',source_type='forum_post',sector='healthcare',broad_geography='North America',claimed_exposure_type='customer_data',organization_name='Northwind',publication_date='')
        return record_vote(self.store,self.memory,'pilot',row['observation_id'],payload)
    def test_gate_requires_ten_actual_reviews_and_eighty_percent_precision(self):
        self.assertEqual(validation_report(self.store,'pilot')['status'],'blocked_quality_validation')
        for i,row in enumerate(self.records[:9]):self.vote(row,i<8)
        self.assertEqual(validation_report(self.store,'pilot')['status'],'blocked_quality_validation')
        self.vote(self.records[9],False)
        report=validation_report(self.store,'pilot');self.assertEqual(report['status'],'passed');self.assertEqual(report['relevance_precision'],.8)
        self.assertFalse(release_bundle(self.root,'pilot')['approved_csv_created']) # one reviewer cannot approve release
        with patch('robin_collect.quality.fingerprint',return_value='changed'):
            self.assertEqual(validation_report(self.store,'pilot')['status'],'blocked_quality_validation')
    def test_quarantine_blocks_votes_release_and_quality_gate_without_deleting_history(self):
        self.store.quarantine('pilot')
        with self.assertRaises(ValueError):self.vote(self.records[0])
        self.assertEqual(release_bundle(self.root,'pilot',True)['status'],'blocked_quarantined')
        self.assertEqual(len(self.store.observations('pilot')),10)
        self.assertTrue(validation_report(self.store,'pilot')['quarantined'])
    def test_context_messages_distinguish_never_collected_lost_and_expired(self):
        record=self.records[0]
        self.assertEqual(context_state(self.memory,'pilot',record),'available')
        self.memory.contexts.clear()
        self.assertEqual(context_state(self.memory,'pilot',record),'lost_session')
        self.assertEqual(context_state(self.memory,'pilot',record,datetime.now(timezone.utc)+timedelta(days=2)),'expired')
        self.assertEqual(context_state(self.memory,'pilot',{'observation_id':'f'*64}),'never_collected')

if __name__=='__main__':unittest.main()
