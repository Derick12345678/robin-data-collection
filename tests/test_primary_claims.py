from datetime import datetime,timezone
import json
from pathlib import Path
import time
import unittest
from robin_collect.screening import assess,screen,primary_claim_supported
from robin_collect.observations import observation,validate_observation,pseudonym
from robin_collect.enrichment import enrich_results,context_receipt
from test_enrichment import KEY,URL,LIMITS,Session,Response
import test_review_release as review_cases

ROOT=Path(__file__).resolve().parents[1]

class ClaimRulesTests(unittest.TestCase):
    def test_primary_claim_fixture_contract(self):
        cases=json.loads((ROOT/'tests/fixtures/primary_claims.synthetic.json').read_text())['cases']
        for case in cases:
            with self.subTest(case=case['id']):
                result=assess(case['title'],case['body'])
                self.assertEqual(result['source_intent'],case['intent'])
                self.assertEqual(result['screening_decision'],case['decision'])
                self.assertEqual(result['target_names'],case.get('targets',[]))
                self.assertEqual(result['dataset_identifiers'],case.get('datasets',[]))
                self.assertEqual(primary_claim_supported(result),case['decision']=='eligible')
                if case['decision']=='eligible':
                    self.assertTrue(result['evidence_quotes'])
                    for quote in result['evidence_quotes']:self.assertIn(quote,case['title']+' '+case['body'])
                else:self.assertEqual(result['supporting_evidence_count'],0)
    def test_publisher_registry_match_is_not_a_victim(self):
        result=assess('Investigation services','Published by Northwind. We can retrieve leaked records from target company.',entities={'Northwind':['Northwind']})
        self.assertFalse(result['target_names']);self.assertFalse(primary_claim_supported(result))
    def test_raw_role_names_and_supporting_quotes_never_enter_durable_contract(self):
        now=datetime.now(timezone.utc)
        record=observation({'title':'We obtained Northwind customer records','link':URL},'q001',KEY,now.isoformat(),now)
        validate_observation(record,'q001')
        self.assertEqual(record['claim_target_pseudonyms'],[pseudonym(KEY,'organization','northwind')])
        self.assertNotIn('Northwind',json.dumps(record));self.assertNotIn('We obtained',json.dumps(record))
        self.assertEqual(record['organization_pseudonyms'],[]) # inferred target is separate from a registry match
        for change in [dict(source_intent='service_advertisement'),dict(supporting_evidence_count=0),dict(claim_target_pseudonyms=[]),dict(target_role='publisher')]:
            with self.assertRaises(ValueError):validate_observation({**record,**change},'q001')
    def test_ambiguous_discovery_spends_no_page_budget(self):
        now=datetime.now(timezone.utc);raw={'title':'Northwind company database breach announcement','link':URL}
        record=observation(raw,'q001',KEY,now.isoformat(),now);session=Session()
        rows,events,contexts=enrich_results([raw],[record],'q001',KEY,now.isoformat(),{},90,['a'*32],LIMITS,time.monotonic()+20,'synthetic',session)
        self.assertFalse(session.calls);self.assertFalse(events);self.assertFalse(contexts)
        self.assertEqual(rows[0]['page_selection'],'insufficient_evidence')
    def test_page_intent_overrides_promising_search_metadata(self):
        now=datetime.now(timezone.utc);raw={'title':'We obtained Northwind customer records','link':URL}
        record=observation(raw,'q001',KEY,now.isoformat(),now)
        body=b'News report. According to a third-party statement, we obtained Northwind customer records.'
        rows,events,contexts=enrich_results([raw],[record],'q001',KEY,now.isoformat(),{},90,['a'*32],LIMITS,time.monotonic()+20,'synthetic',Session(Response(body)))
        self.assertEqual(len(events),1);self.assertEqual(rows[0]['source_intent'],'secondary_reporting')
        self.assertEqual(rows[0]['screening_decision'],'exclude');self.assertFalse(contexts[0]['claim_evidence'])
        validate_observation(rows[0],'q001')
    def test_search_title_cannot_substitute_for_a_missing_page_claim(self):
        now=datetime.now(timezone.utc);raw={'title':'We obtained Northwind customer records','link':URL}
        base=observation(raw,'q001',KEY,now.isoformat(),now)
        rows,events,contexts=enrich_results([raw],[base],'q001',KEY,now.isoformat(),{},90,['a'*32],LIMITS,time.monotonic()+20,'synthetic',Session(Response(b'Northwind provides unrelated security services. Contact us.')))
        self.assertFalse(primary_claim_supported(rows[0],require_page=True))
        self.assertFalse(rows[0]['claim_target_pseudonyms']);self.assertFalse(contexts[0]['claim_evidence'])
        self.assertEqual(rows[0]['claim_assessment_basis'],'page_text')
    def test_reported_or_quoted_claims_do_not_become_primary_assertions(self):
        for body in ['A researcher wrote, "We obtained Northwind customer records."', '"We obtained Northwind customer records"', 'Criminals offer Northwind customer records for sale.']:
            with self.subTest(body=body):
                result=assess('Incident update',body,evidence_from_body_only=True)
                self.assertNotEqual(result['screening_decision'],'eligible')
    def test_quoted_and_boilerplate_html_are_not_claim_evidence(self):
        from robin_collect.enrichment import fetch_text
        html=b'<nav>We obtained Northwind customer records.</nav><blockquote>We obtained Northwind customer records.</blockquote><main>Background discussion.</main>'
        page=fetch_text(URL,Session(Response(html,headers={'Content-Type':'text/html'})),LIMITS,time.monotonic()+20)
        self.assertNotIn('We obtained',page['text'])
        self.assertFalse(primary_claim_supported(assess('Incident update',page['text'],evidence_from_body_only=True)))
    def test_private_supporting_quotes_are_receipt_bound(self):
        now=datetime.now(timezone.utc);raw={'title':'We obtained Northwind customer records','link':URL}
        base=observation(raw,'q001',KEY,now.isoformat(),now)
        rows,events,contexts=enrich_results([raw],[base],'q001',KEY,now.isoformat(),{},90,['a'*32],LIMITS,time.monotonic()+20,'synthetic',Session())
        context=contexts[0];self.assertTrue(context['claim_evidence'])
        self.assertEqual([pseudonym(KEY,'claim_evidence',quote) for quote in context['claim_evidence']],rows[0]['claim_evidence_pseudonyms'])
        self.assertNotEqual(context_receipt(KEY,{**context,'claim_evidence':[]}),context['receipt'])

class RoleReviewTests(unittest.TestCase):
    setUp=review_cases.ReviewTests.setUp
    tearDown=review_cases.ReviewTests.tearDown
    payload=review_cases.ReviewTests.payload
    vote=review_cases.ReviewTests.vote
    def test_provider_name_cannot_replace_supported_victim(self):
        self.assertIn('ExampleProvider',self.memory.get('review-run',self.identity)['text'])
        payload=self.payload();payload['organization_name']='ExampleProvider'
        with self.assertRaises(ValueError):self.vote(payload)
    def test_blank_label_uses_the_single_reviewed_victim_role(self):
        payload=self.payload();payload['organization_name']=''
        self.vote(payload)
        fields=json.loads(self.store.db.execute('SELECT fields_json FROM release_review_events ORDER BY event_id DESC LIMIT 1').fetchone()[0])
        self.assertEqual(fields['organization_pseudonym'],pseudonym(KEY,'organization','northwind'))
    def test_old_or_unsupported_claim_cannot_be_promoted_by_checkboxes(self):
        from unittest.mock import patch
        rows=self.store.observations('review-run');row={**rows[0],'source_intent':'service_advertisement'}
        with patch.object(self.store,'observations',return_value=[row]):
            with self.assertRaises(ValueError):self.vote(self.payload())

if __name__=='__main__':unittest.main()
