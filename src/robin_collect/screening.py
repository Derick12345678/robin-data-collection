"""Conservative, finite relevance hints. These never approve a finding."""
import re
from urllib.parse import urlsplit

VERSION='retrieval-quality-1'
REASONS={'specific_exposure_claim','possible_exposure_claim','generic_directory','generic_advertising','educational_content','insufficient_claim_evidence'}
STOP={'a','an','the','new','data','database','customer','employee','corporate','company','organization','organisational','organizational','breach','leak','leaked','exposed','exposure','stolen','announcement','claim','forum','sale','for','update','business','hospital','university','retail','healthcare','financial','services','public','sector','north','america','europe','canada','unknown','what','how','this','welcome','source','vpn','security','cybersecurity','news','discussion','report','evidence','description'}

def screen(title,snippet='',url='',entities=None):
    title=' '.join(title.split())[:2000];snippet=' '.join(snippet.split())[:2000]
    text=title+' '+snippet
    claim=r'\b(?:breach(?:ed)?|leak(?:ed)?|expos(?:ed|ure)|stolen|ransomware|for sale)\b'
    data=r'\b(?:data|database|records|customer|employee|information|intellectual property)\b'
    named=any(re.search(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',text,re.I) for aliases in (entities or {}).values() for alias in aliases)
    named=named or any(word.casefold() not in STOP for word in re.findall(r'\b[A-Z][A-Za-z0-9&.-]{2,40}\b',title))
    # Evidence terms must occur in one short clause, not unrelated page sections.
    clauses=re.split(r'[.!?;\n]|\s[|]\s',text)
    paired=any(len(clause)<=300 and re.search(claim,clause,re.I) and re.search(data,clause,re.I) for clause in clauses)
    generic=bool(re.search(r'\b(?:hidden wiki|onion links|link directory|search engine|directory of|dark web directory)\b',title,re.I))
    educational=bool(re.search(r'\b(?:how to|what is|tutorial|guide to|prevent(?:ing)?|protect(?:ing)?|training|course)\b',title,re.I))
    advertising=bool(re.search(r'\b(?:advertise here|sponsored|subscription offers|buy vpn|casino|betting)\b',title,re.I))
    if generic:return {'screening_decision':'exclude','screening_reason':'generic_directory','screening_score':0}
    if educational:return {'screening_decision':'exclude','screening_reason':'educational_content','screening_score':0}
    if advertising and not paired:return {'screening_decision':'exclude','screening_reason':'generic_advertising','screening_score':0}
    if paired and named:decision,reason,score='eligible','specific_exposure_claim',90
    elif paired and re.search(r'\b(?:company|corporate|organization|hospital|university|business)\b',text,re.I):decision,reason,score='defer','possible_exposure_claim',55
    else:decision,reason,score='defer','insufficient_claim_evidence',0
    if score and urlsplit(url).path in {'','/'}:score-=15
    return {'screening_decision':decision,'screening_reason':reason,'screening_score':score}


def rank_results(rows,entities=None):
    # Stable tie-breaker removes thread-completion order as a selection signal.
    return sorted(rows,key=lambda row:(-screen(row.get('title',''),row.get('snippet',''),row.get('link',''),entities)['screening_score'],row.get('link','')))
