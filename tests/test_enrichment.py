from datetime import datetime,timezone
import io,json,time
import unittest
from robin_collect.enrichment import fetch_text,eligible_url,enrich_results,RAW_RESPONSE_BYTES
from robin_collect.observations import observation,validate_outcome

KEY='synthetic-review-key-never-use-in-production-123'
URL='http://'+'a'*56+'.onion/post/1'
LIMITS={'page_characters':10000,'page_text_bytes':100000}


class Raw:
    def __init__(self,body):self.stream=io.BytesIO(body);self.bytes=0
    def read(self,count,decode_content=False):
        value=self.stream.read(count);self.bytes+=len(value);return value


class Response:
    def __init__(self,body=b'We obtained Northwind company database records. Customer data forum hospital Canada. Published by ExampleProvider.',status=200,headers=None):
        self.status_code=status;self.headers={'Content-Type':'text/plain',**(headers or {})};self.raw=Raw(body);self.closed=False
    def close(self):self.closed=True


class Session:
    def __init__(self,response=None):self.response=response or Response();self.calls=[]
    def get(self,url,**kwargs):self.calls.append((url,kwargs));return self.response


class EnrichmentTests(unittest.TestCase):
    def test_only_direct_onion_text_targets_are_eligible(self):
        self.assertTrue(eligible_url(URL))
        for value in ['http://example.invalid/',URL+'.zip',URL+'?download=1',URL.replace('/post/1','/sample/1'),'http://localhost/','http://user:password@'+'a'*56+'.onion/']:
            self.assertFalse(eligible_url(value),value)
    def test_refused_media_and_redirects_never_read_bodies(self):
        cases=[(302,{},'redirect_refused'),(200,{'Content-Type':'application/zip'},'unsupported_media'),(200,{'Content-Encoding':'gzip'},'unsupported_media'),(200,{'Content-Disposition':'attachment'},'unsupported_media'),(200,{'Content-Length':str(RAW_RESPONSE_BYTES+1)},'response_too_large')]
        for status,headers,expected in cases:
            response=Response(status=status,headers=headers);session=Session(response)
            result=fetch_text(URL,session,LIMITS,time.monotonic()+20)
            self.assertEqual(result['status'],expected)
            self.assertEqual(response.raw.bytes,0)
            self.assertTrue(response.closed)
            self.assertFalse(session.calls[0][1]['allow_redirects'])
    def test_raw_and_extracted_text_bounds_are_independent(self):
        response=Response(body=b'a'*(RAW_RESPONSE_BYTES+5000));result=fetch_text(URL,Session(response),LIMITS,time.monotonic()+20)
        self.assertEqual(response.raw.bytes,RAW_RESPONSE_BYTES)
        self.assertEqual(len(result['text']),10000)
        self.assertTrue(result['truncated'])
    def test_html_is_text_only_and_detected_sample_records_are_refused(self):
        page=b'<html><script>fetch("external")</script><p>Company database breach forum</p><time datetime="2026-11-01T00:00:00Z">Date</time><img src="http://external.invalid/"></html>'
        session=Session(Response(page,headers={'Content-Type':'text/html'}))
        result=fetch_text(URL,session,LIMITS,time.monotonic()+20)
        self.assertEqual(result['status'],'ok');self.assertNotIn('fetch',result['text']);self.assertEqual(len(session.calls),1)
        secret=fetch_text(URL,Session(Response(b'password=synthetic-secret')),LIMITS,time.monotonic()+20)
        self.assertEqual(secret['status'],'disallowed_content');self.assertEqual(secret['text'],'')
    def test_expired_deadline_dispatches_nothing(self):
        session=Session()
        with self.assertRaises(TimeoutError):fetch_text(URL,session,LIMITS,time.monotonic()-1)
        self.assertFalse(session.calls)
    def test_enrichment_is_receipt_bound_and_requires_reserved_tokens(self):
        now=datetime.now(timezone.utc);raw={'title':'We obtained Northwind company database records claim','link':URL}
        original=observation(raw,'q001',KEY,now.isoformat(),now)
        token='c'*32
        rows,events,contexts=enrich_results([raw],[original],'q001',KEY,now.isoformat(),{},90,[token],LIMITS,time.monotonic()+20,'synthetic-run',Session())
        self.assertEqual(len(events),1);self.assertEqual(len(contexts),1)
        self.assertEqual(rows[0]['metadata_parent_id'],original['observation_id'])
        self.assertNotIn('Northwind',json.dumps(rows));self.assertIn('Northwind',contexts[0]['text'])
        self.assertEqual(rows[0]['context_receipt'],contexts[0]['receipt'])
        coverage=dict(engines_queried=1,engines_answered=1,engines_empty=0,engines_failed=0,results_raw=1,results_after_dedup=1,results_kept=1,results_dropped_abuse=0)
        outcome=dict(status='completed',observations=rows,coverage=coverage,returned_count=1,cleanup_confirmed=True,page_fetch_attempts=1,page_events=events)
        validate_outcome(outcome,20,'q001',[token])
        with self.assertRaises(ValueError):validate_outcome(outcome,20,'q001',[])
        self.assertEqual(rows[0]['sector'],'healthcare')
        self.assertEqual(rows[0]['broad_geography'],'North America')


if __name__=='__main__':unittest.main()
