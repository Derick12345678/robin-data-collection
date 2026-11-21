"""Fail-closed engine-specific extraction; no generic all-anchor fallback."""
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit,urljoin,urlencode,unquote_plus
from .normalize import normalize_text
from .screening import rank_results

PROFILE='ahmia-results-v1'
# Verified against ahmia/ahmia-site ahmia/templates/tor_results.html:
# #ahmiaResultsPage > ol.searchResults > li.result > h4 > a, with li > p snippet.
# Other engines are deliberately skipped until their own layouts have fixtures.

class ResultsParser(HTMLParser):
    VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self):
        super().__init__(convert_charrefs=True);self.stack=[];self.rows=[];self.current=None
        self.heading=[];self.snippet=[];self.href=None;self.recognized=False;self.empty=False;self.list_seen=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);classes=set(attrs.get('class','').split())
        parent=self.stack[-1] if self.stack else None
        page=attrs.get('id')=='ahmiaResultsPage' or bool(parent and parent['page'])
        blocked=tag in {'nav','aside','header','footer','script','style','template'} or bool(parent and parent['blocked']) or bool(classes&{'ad','ads','advertisement','sponsored'})
        if page and attrs.get('id')=='noResults':self.empty=True
        results=page and tag=='ol' and 'searchResults' in classes
        if results:self.list_seen=True
        item=not blocked and tag=='li' and 'result' in classes and bool(parent and parent['results'])
        if item:
            self.current={'depth':len(self.stack),'link':'','title':'','snippet':'','source_engine':'ahmia','parser_profile':PROFILE}
            self.heading=[];self.snippet=[];self.href=None
        heading=bool(self.current and (tag=='h4' or (parent and parent['heading'])))
        description=bool(self.current and (tag=='p' or (parent and parent['description'])))
        if self.current and heading and tag=='a' and not blocked and self.href is None:self.href=attrs.get('href','')
        node=dict(tag=tag,page=page,blocked=blocked,results=results,heading=heading,description=description,item=item)
        if tag not in self.VOID:self.stack.append(node)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.VOID:self.handle_endtag(tag)
    def handle_data(self,data):
        if self.current and self.stack and not self.stack[-1]['blocked']:
            if self.stack[-1]['heading']:self.heading.append(data)
            elif self.stack[-1]['description']:self.snippet.append(data)
    def handle_endtag(self,tag):
        index=next((i for i in range(len(self.stack)-1,-1,-1) if self.stack[i]['tag']==tag),None)
        if index is None:return
        if self.current and index<=self.current['depth']:
            self.current.update(link=self.href or '',title=normalize_text(' '.join(self.heading))[:1000],snippet=normalize_text(' '.join(self.snippet))[:1000])
            self.rows.append(self.current);self.current=None
        del self.stack[index:]


def parse_results(html):
    parser=ResultsParser();parser.feed(html);parser.close()
    if parser.empty and not parser.rows:return [],'recognized_empty'
    if parser.list_seen and parser.rows:return parser.rows,'recognized_results'
    return [],'unsupported_layout'


class SearchForm(HTMLParser):
    def __init__(self):
        super().__init__();self.inside=False;self.action=None;self.fields={};self.query=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='form' and attrs.get('id')=='searchForm' and attrs.get('method','get').lower()=='get':
            self.inside=True;self.action=attrs.get('action','')
        if self.inside and tag=='input':
            name=attrs.get('name','');value=attrs.get('value','')
            if name=='q' and attrs.get('type','').lower() in {'search','text'}:self.query=True
            if attrs.get('type','').lower()=='hidden' and re.fullmatch(r'[0-9a-f]{6}',name) and re.fullmatch(r'[0-9a-f]{6}',value):self.fields[name]=value
    def handle_endtag(self,tag):
        if tag=='form':self.inside=False


def form_query_url(html,endpoint,query):
    """Submit only fields publicly supplied by the normal same-origin GET form."""
    form=SearchForm();form.feed(html);form.close()
    origin=urlsplit(endpoint)
    target=urlsplit(urljoin(endpoint,form.action or ''))
    if not form.query or len(form.fields)!=1 or (target.scheme,target.netloc,target.path)!=(origin.scheme,origin.netloc,origin.path) or target.query or target.fragment:
        return None
    return target._replace(query=urlencode({'q':unquote_plus(query),**form.fields})).geturl()


def install(search,entities=None):
    """Replace the pinned generic parser inside the disposable capture process."""
    endpoint=next(e['url'] for e in search.SEARCH_ENGINES if e['name']=='Ahmia')
    search._quality_diagnostics={'engines_skipped':0,'recognized_results':0,'recognized_empty':0,'unsupported_layout':0,'fetch_failed':0,'engine_http_requests':0}
    def fetch(engine,query):
        if engine!=endpoint:
            search._quality_diagnostics['engines_skipped']+=1
            return search._engine_record(engine,search.ENGINE_FAILED,error='unsupported_parser')
        response=None
        try:
            session=search.get_tor_session()
            origin=urlsplit(engine)
            homepage=origin._replace(path='/',query='',fragment='').geturl()
            search._quality_diagnostics['engine_http_requests']+=1
            response,_=search.get_over_tor(session,homepage,allow_clearweb=False,headers={'User-Agent':search.USER_AGENTS[0]},timeout=search.ENGINE_TIMEOUT)
            if response.status_code!=200:raise ValueError('engine_http_error')
            form_html=search.decode_capped(response,search.read_capped(response,search.SEARCH_PAGE_MAX_BYTES))
            response.close();response=None
            target=form_query_url(form_html,engine,query)
            if target is None:
                search._quality_diagnostics['unsupported_layout']+=1
                return search._engine_record(engine,search.ENGINE_FAILED,error='unsupported_search_form')
            search._quality_diagnostics['engine_http_requests']+=1
            response,_=search.get_over_tor(session,target,allow_clearweb=False,headers={'User-Agent':search.USER_AGENTS[0]},timeout=search.ENGINE_TIMEOUT)
            if response.status_code!=200:raise ValueError('engine_http_error')
            html=search.decode_capped(response,search.read_capped(response,search.SEARCH_PAGE_MAX_BYTES))
            rows,status=parse_results(html);search._quality_diagnostics[status]+=1
            if status=='unsupported_layout':return search._engine_record(engine,search.ENGINE_FAILED,error='unsupported_layout')
            links=[];host=urlsplit(engine).hostname
            for row in rows:
                target=search._extract_target_onion(row['link'],host)
                if not target or urlsplit(target).hostname in search._ENGINE_HOSTS:continue
                row=dict(row,link=target,title=search.scrub_untrusted_text(row['title']),snippet=search.scrub_untrusted_text(row['snippet']))
                if search._is_useful_title(row['title']) and not search.is_abuse_material(row):links.append(row)
            return search._engine_record(engine,search.ENGINE_OK if links else search.ENGINE_EMPTY,links,http_status=200)
        except Exception:
            search._quality_diagnostics['fetch_failed']+=1
            return search._engine_record(engine,search.ENGINE_FAILED,error='engine_fetch_failed')
        finally:
            if response is not None:response.close()
    search.fetch_search_results_detailed=fetch
    original=search.get_search_results_detailed
    def detailed(query,max_workers=2,per_host_limit=None):
        outcome=original(query,max_workers=max_workers,per_host_limit=per_host_limit)
        # Unsupported engines are skips, not failed network queries.
        skipped=search._quality_diagnostics['engines_skipped']
        outcome['stats']['engines_queried']-=skipped
        outcome['stats']['engines_failed']-=skipped
        outcome['results']=rank_results(outcome['results'],entities)
        return outcome
    search.get_search_results_detailed=detailed
