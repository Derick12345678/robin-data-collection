"""Direct-result Tor text retrieval with hard body bounds and ephemeral review context."""
from datetime import datetime,timedelta,timezone
from html.parser import HTMLParser
import re
import time
from urllib.parse import urlsplit,parse_qs
from .normalize import normalize_url,normalize_text
from .sanitize import sanitize
from .observations import observation,pseudonym

RAW_RESPONSE_BYTES=1_000_000
CONTEXT_TTL_SECONDS=24*60*60
PAGE_STATUSES={'ok','policy_refused','redirect_refused','unsupported_media','http_error','response_too_large','empty_text','disallowed_content','fetch_failed'}
SECTORS={'healthcare','financial_services','education','retail','manufacturing','technology','public_sector','other','unknown'}
REGIONS={'North America','South America','Europe','Asia','Africa','Oceania','Middle East','Global','unknown'}
SOURCE_TYPES={'forum_post','marketplace_listing','leak_site_announcement','related_discussion','unknown'}
EXPOSURES={'database','customer_data','employee_data','financial_records','intellectual_property','organizational_data','unknown'}


class PageText(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[];self.hidden=0;self.dates=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in {'script','style','noscript','template'}:self.hidden+=1
        if not self.hidden:
            self.parts.append(' ')
            if tag=='time' and attrs.get('datetime'):self.dates.append(attrs['datetime'])
            if tag=='meta' and (attrs.get('property') or attrs.get('name')) in {'article:published_time','datePublished'} and attrs.get('content'):self.dates.append(attrs['content'])
    def handle_endtag(self,tag):
        if tag in {'script','style','noscript','template'}:self.hidden=max(0,self.hidden-1)
        if not self.hidden:self.parts.append(' ')
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)


def eligible_url(url):
    try:
        if not isinstance(url,str) or len(url)>2048:return False
        parsed=urlsplit(normalize_url(url))
        if not re.fullmatch(r'[a-z2-7]{56}\.onion',parsed.hostname or ''):return False
        path=parsed.path.lower()
        if re.search(r'\.(?:zip|rar|7z|gz|tar|pdf|csv|xlsx?|docx?|exe|bin|sql|db|json|jpg|png|mp[34])$',path):return False
        if re.search(r'(?:download|attachment|sample|export)',path):return False
        if any(k.lower() in {'download','attachment','token','api_key','password','sample'} for k in parse_qs(parsed.query)):return False
        return True
    except (ValueError,TypeError):return False


def disallowed(text):
    return bool(re.search(r'\b(?:password|passwd|api[_ -]?key|secret|token)\s*[:=]\s*\S+|\bSSN\s*[:=]?\s*\d|\bINSERT\s+INTO\b|email\s*[,;]\s*password',text,re.I) or (text.count('@')>=3 and len(re.findall(r'(?<![A-Z0-9._%+-])[A-Z0-9._%+-]{1,64}@[A-Z0-9.-]{1,253}\.[A-Z]{2,63}',text,re.I))>=3))


def fetch_text(url,session,limits,deadline):
    result={'status':'policy_refused','wire_bytes':0,'truncated':False,'text':'','publication_date':None}
    if not eligible_url(url):return result
    remaining=deadline-time.monotonic()
    if remaining<=0:raise TimeoutError()
    response=None
    try:
        response=session.get(url,headers={'Accept':'text/html,text/plain','Accept-Encoding':'identity','User-Agent':'Mozilla/5.0'},timeout=(min(3,remaining),min(5,remaining)),allow_redirects=False,stream=True)
        if 300<=response.status_code<400:result['status']='redirect_refused';return result
        if response.status_code!=200:result['status']='http_error';return result
        media=response.headers.get('Content-Type','').split(';',1)[0].strip().lower()
        if media not in {'text/html','text/plain'} or 'attachment' in response.headers.get('Content-Disposition','').lower() or response.headers.get('Content-Encoding','identity').lower() not in {'','identity'}:
            result['status']='unsupported_media';return result
        length=response.headers.get('Content-Length')
        if length and (not length.isdigit() or int(length)>RAW_RESPONSE_BYTES):result['status']='response_too_large';return result
        chunks=[];left=RAW_RESPONSE_BYTES
        while left:
            if time.monotonic()>=deadline:raise TimeoutError()
            chunk=response.raw.read(min(4096,left),decode_content=False)
            if not chunk:break
            chunks.append(chunk);left-=len(chunk)
        body=b''.join(chunks);result['wire_bytes']=len(body)
        result['truncated']=left==0 and (not length or int(length)>len(body))
        decoded=body.decode('utf-8',errors='replace')
        dates=[]
        if media=='text/html':
            parser=PageText();parser.feed(decoded);parser.close();decoded=' '.join(parser.parts);dates=parser.dates
        text=normalize_text(decoded)
        if disallowed(text):result['status']='disallowed_content';return result
        clipped=text[:limits['page_characters']].encode('utf-8')[:limits['page_text_bytes']].decode('utf-8',errors='ignore')
        result['truncated']=result['truncated'] or clipped!=text
        if not clipped:result['status']='empty_text';return result
        normalized=[]
        for date in dates:
            try:
                parsed=datetime.fromisoformat(date.replace('Z','+00:00'))
                if parsed.tzinfo:normalized.append(parsed.astimezone(timezone.utc).isoformat())
            except (ValueError,AttributeError):pass
        if len(set(normalized))==1:result['publication_date']=normalized[0]
        result.update(status='ok',text=clipped)
        return result
    except TimeoutError:raise
    except Exception:
        result['status']='fetch_failed';return result
    finally:
        if response is not None:response.close()


def taxonomy(text):
    lowered=text.casefold()
    sector='unknown'
    for value,words in [('healthcare',['hospital','healthcare','patient']),('financial_services',['bank','financial services']),('education',['university','school','college']),('retail',['retail','shopping']),('manufacturing',['manufactur','factory']),('technology',['software','technology']),('public_sector',['government','municipal'])]:
        if any(word in lowered for word in words):sector=value;break
    region='unknown'
    for value,words in [('North America',['canada','united states']),('Europe',['united kingdom','germany','france','europe']),('Asia',['india','japan','china']),('Oceania',['australia','new zealand']),('Africa',['africa']),('South America',['brazil','argentina'])]:
        if any(word in lowered for word in words):region=value;break
    source='forum_post' if 'forum' in lowered or 'thread' in lowered else 'marketplace_listing' if 'for sale' in lowered else 'leak_site_announcement' if 'ransom' in lowered else 'unknown'
    exposure='employee_data' if 'employee' in lowered else 'customer_data' if 'customer' in lowered else 'financial_records' if 'financial records' in lowered else 'intellectual_property' if 'intellectual property' in lowered else 'database' if 'database' in lowered else 'unknown'
    return {'sector':sector,'broad_geography':region,'source_type':source,'claimed_exposure_type':exposure}


def context_receipt(key,context):
    fields=[context[k] for k in ['run_id','observation_id','source_pseudonym','url','title','text','fetched_at_utc','expires_at_utc','evidence_id']]
    import json
    return pseudonym(key,'review_context',json.dumps(fields,ensure_ascii=False))


def enrich_results(raw_rows,records,query_id,key,start,entities,lookback,tokens,limits,deadline,run_id,session):
    by_source={pseudonym(key,'source',normalize_url(row['link'])):row for row in raw_rows if eligible_url(row.get('link',''))}
    events=[];contexts=[];result=[];available=iter(tokens)
    for record in records:
        if record['relevance_decision']=='rejected' or record['source_pseudonym'] not in by_source or deadline-time.monotonic()<9:
            result.append(record);continue
        token=next(available,None)
        if token is None:result.append(record);continue
        raw=by_source[record['source_pseudonym']]
        reason='insufficient_relevance' if record['relevance_decision']=='needs_review' else 'missing_research_fields'
        page=fetch_text(raw['link'],session,limits,deadline)
        event={'token':token,'source_pseudonym':record['source_pseudonym'],'status':page['status'],'reason':reason,'wire_bytes':page['wire_bytes'],'truncated':page['truncated']}
        events.append(event)
        if page['status']!='ok':
            record={**record,'page_status':page['status']}
            if page['status']=='disallowed_content':record.update(relevance_decision='rejected',relevance_reason='disallowed_content',summary_sanitized='Excluded under collection criteria.')
            result.append(record);continue
        stamp=datetime.now(timezone.utc)
        enriched=observation({'title':raw.get('title',''),'snippet':page['text'],'link':raw['link'],'publication_date':page['publication_date']},query_id,key,stamp.isoformat(),datetime.fromisoformat(start),entities,lookback)
        evidence=pseudonym(key,'page_evidence',normalize_text(page['text']))
        review_text=sanitize(page['text'])[0]
        clipped_review=review_text[:limits['page_characters']].encode('utf-8')[:limits['page_text_bytes']].decode('utf-8',errors='ignore')
        page['truncated']=page['truncated'] or clipped_review!=review_text
        context={'run_id':run_id,'observation_id':enriched['observation_id'],'source_pseudonym':enriched['source_pseudonym'],
            'url':raw['link'],'title':sanitize(raw.get('title',''))[0][:1000],'text':clipped_review,
            'fetched_at_utc':stamp.isoformat(),'expires_at_utc':(stamp+timedelta(seconds=CONTEXT_TTL_SECONDS)).isoformat(),'evidence_id':evidence}
        context['receipt']=context_receipt(key,context)
        enriched.update(source_capture='direct_result_page',metadata_parent_id=record['observation_id'],evidence_id=evidence,context_receipt=context['receipt'],
            context_expires_at_utc=context['expires_at_utc'],page_status='ok',page_truncated=page['truncated'],
            raw_response_bytes=page['wire_bytes'],extracted_characters=len(page['text']),extracted_bytes=len(page['text'].encode('utf-8')),**taxonomy(page['text']))
        result.append(enriched);contexts.append(context)
    return result,events,contexts
