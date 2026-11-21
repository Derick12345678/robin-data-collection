"""Deterministic primary-claim screening. Hints never verify a breach or approve release."""
import re
from urllib.parse import urlsplit

VERSION='primary-claims-1'
INTENTS={'primary_announcement','specific_dataset_listing','secondary_reporting','educational_content','service_advertisement','directory','unknown'}
CLAIM_TYPES={'existing_exposure','existing_sale','capability_offer','none','uncertain'}
SPECIFICITY={'victim_identified','dataset_identified','victim_and_dataset','none'}
REASONS={'specific_exposure_claim','specific_dataset_offer','generic_directory','generic_advertising','educational_content','secondary_reporting','service_advertising','insufficient_claim_evidence','no_specific_target','ambiguous_source_intent','hypothetical_or_negated_claim'}
PUBLIC_KEYS={'screening_decision','screening_reason','screening_score','screening_version','source_intent','claim_evidence_type','claim_specificity','target_role','supporting_evidence_count','claim_assessment_basis'}
STOP=set('a an the we i our new data database dataset customer employee staff client corporate company organization organisational organizational breach leak leaked exposed exposure stolen announcement claim forum sale for update business hospital university retail healthcare financial services public sector north america europe canada unknown what how this welcome source vpn security cybersecurity news discussion report evidence description dark web onion tor all best official free hidden market marketplace leaks latest search result results records corporate pull retrieve target private investigator contact published provider service'.split())
DATA=r'\b(?:data(?:base|set)?s?|records|customer information|employee information|intellectual property)\b'
NAME=r'[A-Z][A-Za-z0-9&.-]{1,39}(?:[ \t]+[A-Z][A-Za-z0-9&.-]{1,39}){0,3}'
TARGET_DATA=re.compile(r'(?<![\w&.-])(?P<name>'+NAME+r")(?:['\u2019]s)?\s+(?:(?:company|corporate|customer|employee|staff|client|patient|student|business)\s+){0,3}"+DATA)
TARGET_LABEL=re.compile(r'\b(?:victim|affected organization|affected company|target organization|target company)\s*:\s*(?P<name>'+NAME+r')')
BREACHED_TARGET=re.compile(r'\b(?:we|i)\s+(?:have\s+)?(?:breached|compromised|hacked)\s+(?P<name>'+NAME+r')')
DATASET_LABEL=re.compile(r'\bdataset\s+(?:id|identifier|name)\s*:\s*([A-Za-z0-9][A-Za-z0-9_-]{3,79})',re.I)
FIRSTHAND=re.compile(r'\b(?:we|i)\s+(?:have\s+)?(?:obtained|exfiltrated|stole|stolen|acquired|hold|breached|compromised|hacked)\b',re.I)
FIRSTPARTY=re.compile(r'\bwe\s+(?:confirm|disclose|announce|acknowledge)\b',re.I)
EXPOSURE=re.compile(r'\b(?:breached|leaked|exposed|stolen|exfiltrated|compromised|obtained)\b',re.I)
SALE=re.compile(r'\b(?:for sale|we are selling|i am selling|available for purchase)\b',re.I)
HYPOTHETICAL=re.compile(r'\b(?:can|could|will|would|may|might|able to)\s+(?:\w+\s+){0,2}(?:obtain|retrieve|hack|breach|leak|expose|access|sell|selling)\b|\bretrieve\s+(?:leaked|stolen)\b',re.I)
NEGATED=re.compile(r'\b(?:not|never|no evidence|deny|denied|unconfirmed|rumou?r)\b',re.I)


def canonical_target(value,entities=None):
    value=' '.join(value.split()).strip(' .,;:-').casefold()
    for canonical,aliases in (entities or {}).items():
        if any(value==' '.join(alias.split()).casefold() for alias in aliases):return ' '.join(canonical.split()).casefold()
    return value


def _targets(clause,entities):
    names=[]
    for pattern in [TARGET_DATA,TARGET_LABEL,BREACHED_TARGET]:
        for match in pattern.finditer(clause):
            value=match['name'].strip(' .,;:-')
            if not any(word.casefold().strip('.') not in STOP for word in value.split()):continue
            # A byline/provider label is not a victim role.
            prefix=clause[max(0,match.start()-40):match.start()]
            if re.search(r'(?:published by|written by|provider|services by|author)\s*:?\s*$',prefix,re.I):continue
            names.append(canonical_target(value,entities))
    return sorted(set(names))


def _direct_assertion(pattern,clause):
    match=pattern.search(clause)
    if not match:return False
    prefix=clause[:match.start()].strip(' #*-')
    # Attributed/quoted speech is not a claim made by this source.
    return not prefix or bool(re.fullmatch(r'(?:claim(?: statement)?|announcement|incident notice|update):',prefix,re.I))


def assess(title,body='',url='',entities=None,evidence_from_body_only=False):
    """Return finite labels plus ephemeral role/evidence strings for trusted callers.

    A proper noun alone is never sufficient: it must occupy a supported victim/data
    relationship in the same bounded clause as a first-party/possession/sale assertion.
    Unsupported language patterns defer rather than guessing a victim from a byline.
    """
    title=' '.join(title.split())[:1000]
    body=body[:10000]
    text=title+'\n'+body
    front=title+' '+body[:1200]
    directory=bool(re.search(r'\b(?:hidden wiki|onion links|link directory|search engine|directory of|dark web directory)\b',title,re.I))
    news=bool(re.search(r'\b(?:warns? that|says? that|reports? that|reported that|news article|news report|according to|told reporters|journalist|by reuters)\b',front,re.I))
    service=bool(re.search(r'\b(?:hire a hacker|hire certified|our investigation services|forensics services|private investigator services|retrieve leaked (?:staff|client|customer)|corporate leak pull)\b',front,re.I))
    education=bool(re.search(r'\b(?:how to|what is|tutorial|guide to|complete.{0,15}guide|prevent(?:ing)?|protect(?:ing)?|training|course)\b',title,re.I))
    advertising=bool(re.search(r'\b(?:advertise here|sponsored|subscription offers|buy vpn|casino|betting)\b',title,re.I))
    intent='unknown';reason='insufficient_claim_evidence';decision='defer';score=0
    if directory:intent,reason,decision='directory','generic_directory','exclude'
    elif news:intent,reason,decision='secondary_reporting','secondary_reporting','exclude'
    elif service:intent,reason,decision='service_advertisement','service_advertising','exclude'
    elif education:intent,reason,decision='educational_content','educational_content','exclude'
    elif advertising:intent,reason,decision='service_advertisement','generic_advertising','exclude'
    targets=[];datasets=[];quotes=[];kinds=[];saw_claim=False;saw_hypothetical=False
    # Keep sentence boundaries. Never combine a provider byline with another sentence's claim.
    clauses=re.split(r'(?<!\d)[.!?;\n]|\s[|]\s',body if evidence_from_body_only else text)
    for part in clauses[:120]:
        clause=' '.join(part.split())
        if not clause or len(clause)>450 or not re.search(DATA,clause,re.I):continue
        firsthand=_direct_assertion(FIRSTHAND,clause)
        firstparty=bool(_direct_assertion(FIRSTPARTY,clause) and re.search(r'\bour\b',clause,re.I) and EXPOSURE.search(clause))
        sale=bool(SALE.search(clause) and (re.match(r'^(?:for sale|we are selling|i am selling|available for purchase)\b',clause,re.I) or TARGET_DATA.match(clause)))
        if not(firsthand or firstparty or sale):
            saw_hypothetical=saw_hypothetical or bool(HYPOTHETICAL.search(clause));continue
        saw_claim=True
        if NEGATED.search(clause) or HYPOTHETICAL.search(clause):saw_hypothetical=True;continue
        victims=_targets(clause,entities)
        organizational=bool(re.search(r'\b(?:company|corporate|organization|business|customer|employee|staff|client|patient|student|financial|intellectual property)\b',clause,re.I))
        registry_targets={canonical_target(name,entities) for name in (entities or {})}
        if not organizational and not (set(victims)&registry_targets):continue
        identifiers=[m.group(1).casefold() for m in DATASET_LABEL.finditer(clause) if m.group(1).casefold() not in STOP]
        if not victims and not identifiers:continue
        targets.extend(victims);datasets.extend(identifiers);quotes.append(clause);kinds.append('existing_sale' if sale else 'existing_exposure')
    if decision!='exclude':
        if quotes:
            if len(set(kinds))>1:intent,reason='unknown','ambiguous_source_intent'
            else:
                intent='specific_dataset_listing' if kinds[0]=='existing_sale' else 'primary_announcement'
                reason='specific_dataset_offer' if kinds[0]=='existing_sale' else 'specific_exposure_claim'
                decision='eligible';score=90
        elif saw_hypothetical:reason='hypothetical_or_negated_claim'
        elif saw_claim:reason='no_specific_target'
        elif EXPOSURE.search(text):reason='ambiguous_source_intent'
    # Excluded/ambiguous material cannot retain an affirmative claim/target assertion.
    supported=decision=='eligible'
    targets=sorted(set(targets))[:3] if supported else []
    datasets=sorted(set(datasets))[:3] if supported else []
    quotes=list(dict.fromkeys(quotes))[:3] if supported else []
    specificity='victim_and_dataset' if targets and datasets else 'victim_identified' if targets else 'dataset_identified' if datasets else 'none'
    evidence_type=kinds[0] if supported else 'capability_offer' if intent=='service_advertisement' or saw_hypothetical else 'uncertain' if saw_claim else 'none'
    if score and urlsplit(url).path in {'','/'}:score-=10
    return dict(screening_decision=decision,screening_reason=reason,screening_score=score,
        screening_version=VERSION,source_intent=intent,claim_evidence_type=evidence_type,
        claim_specificity=specificity,target_role='victim' if targets else 'unspecified',
        supporting_evidence_count=len(quotes),claim_assessment_basis='page_text' if evidence_from_body_only else 'search_metadata',target_names=targets,dataset_identifiers=datasets,evidence_quotes=quotes)


def screen(title,snippet='',url='',entities=None):
    result=assess(title,snippet,url,entities)
    return {key:result[key] for key in PUBLIC_KEYS}


def primary_claim_supported(record,require_page=False):
    if require_page and (record.get('claim_assessment_basis')!='page_text' or record.get('page_status')!='ok'):return False
    return (record.get('screening_version')==VERSION and record.get('screening_decision')=='eligible'
        and record.get('source_intent') in {'primary_announcement','specific_dataset_listing'}
        and record.get('claim_evidence_type') in {'existing_exposure','existing_sale'}
        and record.get('claim_specificity') in SPECIFICITY-{'none'}
        and type(record.get('supporting_evidence_count')) is int and 1<=record['supporting_evidence_count']<=3)


def rank_results(rows,entities=None):
    return sorted(rows,key=lambda row:(-screen(row.get('title',''),row.get('snippet',''),row.get('link',''),entities)['screening_score'],row.get('link','')))
