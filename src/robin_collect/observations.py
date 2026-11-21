"""Structured-only source observations: untrusted free text never leaves memory."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
from .normalize import normalize_text, normalize_url
from .sanitize import sanitize

POLICY_VERSION = "organizational-exposure-2-primary-claims-structured-only"


def pseudonym(key, kind, value):
    return hmac.new(key.encode(), (kind + "\0" + value).encode(), hashlib.sha256).hexdigest()


def plain(value):
    # Normalize source identity before redaction, preserving separate source items.
    from .sanitize import PlainText
    parser = PlainText()
    parser.feed(value)
    parser.close()
    return normalize_text(" ".join(parser.parts))


def validate_entities(entities):
    if not isinstance(entities, dict) or len(entities) > 1000:
        raise ValueError("Invalid entity registry")
    for canonical, aliases in entities.items():
        if not isinstance(canonical, str) or not canonical.strip() or not isinstance(aliases, list):
            raise ValueError("Invalid entity registry")
        if not aliases or any(not isinstance(alias, str) or not alias.strip() or len(alias) > 200 for alias in aliases):
            raise ValueError("Invalid entity aliases")
    return entities


def classify(text, published, window_start, lookback_days, hint=None):
    lowered = text.casefold()
    # Only finite, pre-defined outputs can persist. Hints are not authenticity findings.
    if re.search(r"\b(?:password|passwd|api[_ -]?key|token)\s*[:=]\s*\S+", text, re.I):
        return "rejected", "disallowed_content", "unknown", "unknown"
    if published:
        try:
            date = datetime.fromisoformat(published.replace("Z", "+00:00"))
            if date.tzinfo is None:
                raise ValueError()
            if date < window_start - timedelta(days=lookback_days):
                return "rejected", "out_of_date", "unknown", "known"
            if date > datetime.now(timezone.utc):
                return "needs_review", "publication_date_uncertain", "unknown", "uncertain"
        except (ValueError, AttributeError):
            return "needs_review", "publication_date_uncertain", "unknown", "uncertain"
    from .screening import screen
    hint=hint or screen(text)
    category='database' if 'database' in lowered else 'customer_data' if 'customer' in lowered else 'unknown'
    if hint['screening_decision']=='eligible':
        return 'candidate','organizational_exposure_claim_unverified',category,'known' if published else 'unknown'
    if hint['screening_decision']=='exclude':
        return 'rejected',hint['screening_reason'],category,'known' if published else 'unknown'
    return 'needs_review',hint['screening_reason'],category,'known' if published else 'unknown'



def observation(row, query_id, key, collected_at, window_start, entities=None, lookback_days=90):
    if len(key) < 32:
        raise ValueError("A stable HMAC key is required")
    entities = validate_entities(entities or {})
    title, snippet = row.get("title", ""), row.get("snippet", "")
    if not isinstance(title, str) or not isinstance(snippet, str) or max(len(title), len(snippet)) > 100_000:
        raise ValueError("Invalid source text")
    url = normalize_url(row.get("link") or row.get("url") or "")
    title, snippet = plain(title), plain(snippet)
    source = pseudonym(key, "source", url)
    content = json.dumps([title, snippet], ensure_ascii=False)
    content_id = pseudonym(key, "content", content)
    identity = pseudonym(key, "observation", source + "\0" + content_id)
    text = title + " " + snippet
    _, categories = sanitize(text)
    from .screening import assess,PUBLIC_KEYS
    assessment=assess(title,snippet,url,entities,evidence_from_body_only=row.get('_assessment_stage')=='page')
    hint={name:assessment[name] for name in PUBLIC_KEYS}
    targets=[pseudonym(key,'organization',value) for value in assessment['target_names']]
    registry_names={' '.join(name.split()).casefold() for name in entities}
    organizations=[pseudonym(key,'organization',value) for value in assessment['target_names'] if value in registry_names]
    dataset_ids=[pseudonym(key,'dataset',value) for value in assessment['dataset_identifiers']]
    quotes=[sanitize(quote)[0] for quote in assessment['evidence_quotes']]
    evidence_ids=[pseudonym(key,'claim_evidence',quote) for quote in quotes]
    decision, reason, category, date_status = classify(text, row.get("publication_date"), window_start, lookback_days,hint)
    # Withhold ALL original free text, not just regex matches. Unknown names,
    # addresses, secrets, source handles, and exposed records cannot leak through.
    safe_title = "Source observation [TITLE_" + pseudonym(key, "title", title) + "]"
    summary = "Possible organizational exposure claim; unverified." if decision == "candidate" else "Insufficient source context for an exposure finding." if decision == "needs_review" else "Excluded under collection criteria."
    return {
        **hint,"claim_target_pseudonyms":targets,"claim_dataset_pseudonyms":dataset_ids,"claim_evidence_pseudonyms":evidence_ids,"page_selection":"not_selected",
        "source_engine":row.get("source_engine","unknown"),"parser_profile":row.get("parser_profile","unknown"),
        "similarity_tokens": sorted({pseudonym(key,"similarity_token",token.casefold()) for token in re.findall(r"\w+",text)})[:64],
        "observation_id": identity, "source_pseudonym": source, "content_pseudonym": content_id,
        "query_id": query_id, "collected_at_utc": collected_at,
        "title_sanitized": safe_title, "summary_sanitized": summary,
        "organization_pseudonyms": sorted(set(organizations)),
        "organization_detection": "registry_match" if organizations else "unknown",
        "research_category": category, "source_type": "unknown", "language": "unknown",
        "relevance_decision": decision, "relevance_reason": reason,
        "publication_date_status": date_status, "source_claimed_publication_date": datetime.fromisoformat(row["publication_date"].replace("Z", "+00:00")).isoformat() if date_status == "known" else None,
        "snippet_available": bool(snippet), "snippet_sanitized": "[TEXT_WITHHELD]" if snippet else "",
        "listing_title_truncated": len(title) > 200, "listing_url_truncated": len(url) > 500,
        "source_capture": "before_mcp_listing_truncation", "raw_url_persisted": False,
        "redaction_categories": sorted(set(categories + ["unstructured_text_withheld"] + (["organization_pseudonymized"] if organizations else []))),
        "review_status": "pending_review", "privacy_mode": "structured_only", "policy_version": POLICY_VERSION,
    }


def capture_observations(rows, query_id, key, window_start, entities, lookback_days):
    from urllib.parse import urlsplit
    start = datetime.fromisoformat(window_start)
    collected = datetime.now(timezone.utc).isoformat()
    records, invalid = [], 0
    for row in rows:
        try:
            if not (urlsplit(row.get('link','')).hostname or '').lower().endswith('.onion'):
                raise ValueError('Not an onion source')
            records.append(observation(row, query_id, key, collected, start, entities, lookback_days))
        except (ValueError,TypeError,AttributeError):
            invalid += 1
    return records, invalid


SAFE_KEYS = {
    'collected_at_utc',
    'content_pseudonym',
    'language',
    'listing_title_truncated',
    'listing_url_truncated',
    'observation_id',
    'organization_detection',
    'organization_pseudonyms',
    'policy_version',
    'privacy_mode',
    'publication_date_status',
    'query_id',
    'raw_url_persisted',
    'redaction_categories',
    'relevance_decision',
    'relevance_reason',
    'research_category',
    'review_status',
    'similarity_tokens',
    'snippet_available',
    'snippet_sanitized',
    'source_capture',
    'source_claimed_publication_date',
    'source_pseudonym',
    'source_type',
    'summary_sanitized',
    'title_sanitized',
}


def validate_observation(record, query_id):
    quality={'screening_decision','screening_reason','screening_score','page_selection','source_engine','parser_profile'}
    claims={'screening_version','source_intent','claim_evidence_type','claim_specificity','target_role','supporting_evidence_count','claim_target_pseudonyms','claim_dataset_pseudonyms','claim_evidence_pseudonyms','claim_assessment_basis'}
    optional={'metadata_parent_id','evidence_id','context_receipt','context_expires_at_utc','page_status','page_truncated','raw_response_bytes','extracted_characters','extracted_bytes','sector','broad_geography','claimed_exposure_type'}
    if not isinstance(record,dict) or not SAFE_KEYS<=set(record) or not set(record)<=SAFE_KEYS|optional|quality|claims or record['query_id']!=query_id:
        raise ValueError('Invalid observation contract')
    for name in ['observation_id','source_pseudonym','content_pseudonym']:
        if not isinstance(record[name],str) or not re.fullmatch(r'[0-9a-f]{64}',record[name]):raise ValueError('Invalid pseudonym')
    if not isinstance(record['title_sanitized'],str) or not re.fullmatch(r'Source observation \[TITLE_[0-9a-f]{64}\]',record['title_sanitized']):raise ValueError('Unsafe title')
    if not isinstance(record['summary_sanitized'],str) or record['summary_sanitized'] not in {'Possible organizational exposure claim; unverified.','Insufficient source context for an exposure finding.','Excluded under collection criteria.'}:raise ValueError('Unsafe summary')
    if not isinstance(record['snippet_sanitized'],str) or record['snippet_sanitized'] not in {'','[TEXT_WITHHELD]'}:raise ValueError('Unsafe excerpt')
    tokens=record['similarity_tokens']
    if not isinstance(tokens,list) or len(tokens)>64 or any(not isinstance(x,str) or not re.fullmatch(r'[0-9a-f]{64}',x) for x in tokens):raise ValueError('Unsafe similarity tokens')
    organizations=record['organization_pseudonyms']
    if not isinstance(organizations,list) or any(not isinstance(x,str) or not re.fullmatch(r'[0-9a-f]{64}',x) for x in organizations):raise ValueError('Unsafe organization field')
    allowed={
        'organization_detection':{'registry_match','unknown'},'research_category':{'database','customer_data','organizational_data','unknown'},
        'source_type':{'unknown','forum_post','marketplace_listing','leak_site_announcement','related_discussion'},'language':{'unknown'},'relevance_decision':{'candidate','rejected','needs_review'},
        'relevance_reason':{'disallowed_content','out_of_date','publication_date_uncertain','organizational_exposure_claim_unverified','generic_advertising','insufficient_context','generic_directory','educational_content','secondary_reporting','service_advertising','insufficient_claim_evidence','no_specific_target','ambiguous_source_intent','hypothetical_or_negated_claim','specific_dataset_offer'},
        'publication_date_status':{'known','unknown','uncertain'},'review_status':{'pending_review'},
        'privacy_mode':{'structured_only'},'policy_version':{POLICY_VERSION},'source_capture':{'before_mcp_listing_truncation','direct_result_page'},
    }
    for name,values in allowed.items():
        if not isinstance(record[name],str) or record[name] not in values:raise ValueError('Invalid structured field')
    for name in ['snippet_available','listing_title_truncated','listing_url_truncated','raw_url_persisted']:
        if type(record[name]) is not bool:raise ValueError('Invalid flag')
    if record['raw_url_persisted']:raise ValueError('Raw URL persistence forbidden')
    if not isinstance(record['redaction_categories'],list) or any(not isinstance(value,str) for value in record['redaction_categories']) or not set(record['redaction_categories']) <= {'email','credential','phone','ipv4','unstructured_text_withheld','organization_pseudonymized'}:raise ValueError('Unsafe redaction category')
    if 'unstructured_text_withheld' not in record['redaction_categories']:raise ValueError('Missing privacy marker')
    for name in ['collected_at_utc','source_claimed_publication_date']:
        value=record[name]
        if value is None and name=='source_claimed_publication_date':continue
        if not isinstance(value,str) or datetime.fromisoformat(value).tzinfo is None:raise ValueError('Invalid timestamp')
    if 'page_status' in record:
        from .enrichment import PAGE_STATUSES,SECTORS,REGIONS,EXPOSURES,RAW_RESPONSE_BYTES
        if not isinstance(record['page_status'],str) or record['page_status'] not in PAGE_STATUSES:raise ValueError('Invalid page status')
        if record['page_status']=='ok':
            needed=optional-{'page_status'}
            if not needed<=set(record):raise ValueError('Incomplete page evidence')
            for name in ['metadata_parent_id','evidence_id','context_receipt']:
                if not isinstance(record[name],str) or not re.fullmatch(r'[0-9a-f]{64}',record[name]):raise ValueError('Invalid evidence pseudonym')
            if not isinstance(record['context_expires_at_utc'],str) or datetime.fromisoformat(record['context_expires_at_utc']).tzinfo is None:raise ValueError('Invalid context expiry')
            for name,high in [('raw_response_bytes',RAW_RESPONSE_BYTES),('extracted_characters',10000),('extracted_bytes',100000)]:
                if type(record[name]) is not int or not 0<=record[name]<=high:raise ValueError('Page bound exceeded')
            if type(record['page_truncated']) is not bool:raise ValueError('Unsafe truncation flag')
            for name,values in [('sector',SECTORS),('broad_geography',REGIONS),('claimed_exposure_type',EXPOSURES)]:
                if not isinstance(record[name],str) or record[name] not in values:raise ValueError('Unsafe taxonomy')
        elif not set(record)<=SAFE_KEYS|quality|claims|{'page_status'}:raise ValueError('Unbound failed-page evidence')
    elif set(record)&optional:raise ValueError('Unbound page evidence')
    if set(record)&quality:
        from .screening import REASONS
        if not quality<=set(record):raise ValueError('Incomplete screening provenance')
        for name,values in [('screening_decision',{'eligible','defer','exclude'}),('screening_reason',REASONS),('source_engine',{'unknown','ahmia'}),('parser_profile',{'unknown','ahmia-results-v1'}),('page_selection',{'not_selected','selected','excluded','insufficient_evidence','already_attempted','budget_exhausted','deadline','captured','fetch_failed'})]:
            if not isinstance(record[name],str) or record[name] not in values:raise ValueError('Unsafe screening provenance')
        if type(record['screening_score']) is not int or not 0<=record['screening_score']<=100:raise ValueError('Unsafe screening score')
    if set(record)&claims:
        from .screening import VERSION,INTENTS,CLAIM_TYPES,SPECIFICITY,primary_claim_supported
        if not claims<=set(record) or not quality<=set(record):raise ValueError('Incomplete claim-role contract')
        for name,values in [('screening_version',{VERSION}),('source_intent',INTENTS),('claim_evidence_type',CLAIM_TYPES),('claim_specificity',SPECIFICITY),('target_role',{'victim','unspecified'}),('claim_assessment_basis',{'search_metadata','page_text'})]:
            if not isinstance(record[name],str) or record[name] not in values:raise ValueError('Unsafe claim-role label')
        for name in ['claim_target_pseudonyms','claim_dataset_pseudonyms','claim_evidence_pseudonyms']:
            values=record[name]
            if not isinstance(values,list) or len(values)>3 or any(not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{64}',value) for value in values):raise ValueError('Unsafe role/evidence pseudonym')
        if (record['claim_assessment_basis']=='page_text')!=('page_status' in record and record['page_status']=='ok'):raise ValueError('Inconsistent page evidence basis')
        count=record['supporting_evidence_count']
        if type(count) is not int or not 0<=count<=3 or count!=len(record['claim_evidence_pseudonyms']):raise ValueError('Invalid evidence count')
        if record['screening_decision']=='eligible' and (not primary_claim_supported(record) or not (record['claim_target_pseudonyms'] or record['claim_dataset_pseudonyms'])):raise ValueError('Unsupported primary claim')
        if record['screening_decision']!='eligible' and (count or record['claim_target_pseudonyms'] or record['claim_dataset_pseudonyms']):raise ValueError('Unbound target/evidence assertions')
        specificity='victim_and_dataset' if record['claim_target_pseudonyms'] and record['claim_dataset_pseudonyms'] else 'victim_identified' if record['claim_target_pseudonyms'] else 'dataset_identified' if record['claim_dataset_pseudonyms'] else 'none'
        if record['claim_specificity']!=specificity or (record['target_role']=='victim')!=bool(record['claim_target_pseudonyms']):raise ValueError('Inconsistent target role')
    return record


def validate_outcome(outcome, cap, query_id, page_tokens=None):
    if not isinstance(outcome,dict):raise ValueError('Invalid adapter outcome')
    status=outcome.get('status')
    if not isinstance(status,str) or status not in {'completed','no_results','engines_unreachable','timed_out','failed'}:raise ValueError('Invalid outcome status')
    code=outcome.get('code')
    if (code is not None and not isinstance(code,str)) or code not in {None,'all_locators_invalid','operation_deadline','capture_failed','transport_failed','container_deadline','cleanup_uncertain','unsupported_layout'}:raise ValueError('Unsafe outcome code')
    records=outcome.get('observations',[])
    if not isinstance(records,list) or len(records)>cap:raise ValueError('Observation cap exceeded')
    records=[validate_observation(row,query_id) for row in records]
    count=outcome.get('returned_count')
    if count is not None and (type(count) is not int or not 0<=count<=cap):raise ValueError('Invalid returned count')
    if status in {'completed','no_results'} and (count is None or len(records)>count):raise ValueError('Incomplete successful outcome')
    if status=='no_results' and (count!=0 or records):raise ValueError('Invalid empty result')
    result={'status':status,'code':code,'observations':records,'returned_count':count,'cleanup_confirmed':outcome.get('cleanup_confirmed') is True}
    coverage=outcome.get('coverage')
    if coverage is not None:
        names={'engines_queried','engines_answered','engines_empty','engines_failed','results_raw','results_after_dedup','results_kept','results_dropped_abuse'}
        if not isinstance(coverage,dict) or set(coverage)!=names or any(type(v) is not int or v<0 for v in coverage.values()):raise ValueError('Invalid coverage')
        if coverage['engines_queried']!=sum(coverage[k] for k in ['engines_answered','engines_empty','engines_failed']):raise ValueError('Inconsistent coverage')
        if status=='no_results' and coverage['engines_answered']+coverage['engines_empty']==0:raise ValueError('Outage is not an empty result')
        result['coverage']=coverage
    elif status in {'completed','no_results','engines_unreachable'}:raise ValueError('Missing coverage evidence')
    for name in ['invalid_locator_count','page_fetch_attempts','model_calls','title_available_count','url_available_count','snippet_available_count','titles_exceeding_robin_character_cap','urls_exceeding_robin_character_cap']:
        if name in outcome:
            if type(outcome[name]) is not int or outcome[name]<0:raise ValueError('Invalid count')
            result[name]=outcome[name]
    tokens=set(page_tokens or [])
    events=outcome.get('page_events',[])
    if not isinstance(events,list) or len(events)>len(tokens):raise ValueError('Unreserved page attempts')
    used=set()
    for event in events:
        from .enrichment import PAGE_STATUSES,RAW_RESPONSE_BYTES
        if not isinstance(event,dict) or set(event)!={'token','source_pseudonym','status','reason','wire_bytes','truncated'}:raise ValueError('Unsafe page event')
        if not isinstance(event['token'],str) or event['token'] not in tokens or event['token'] in used:raise ValueError('Invalid page token')
        used.add(event['token'])
        if not isinstance(event['source_pseudonym'],str) or not re.fullmatch(r'[0-9a-f]{64}',event['source_pseudonym']) or event['source_pseudonym'] not in {r['source_pseudonym'] for r in records}:raise ValueError('Unbound page source')
        if not isinstance(event['status'],str) or event['status'] not in PAGE_STATUSES or not isinstance(event['reason'],str) or event['reason'] not in {'insufficient_relevance','missing_research_fields'} or type(event['wire_bytes']) is not int or not 0<=event['wire_bytes']<=RAW_RESPONSE_BYTES or type(event['truncated']) is not bool:raise ValueError('Invalid page event')
    if result.get('page_fetch_attempts',0)!=len(events) or result.get('model_calls',0)!=0:raise ValueError('Capture contract violated')
    if any('page_status' in r and r['source_pseudonym'] not in {e['source_pseudonym'] for e in events} for r in records):raise ValueError('Missing page provenance')
    diagnostics=outcome.get('retrieval_diagnostics')
    if diagnostics is not None:
        names={'engines_skipped','recognized_results','recognized_empty','unsupported_layout','fetch_failed','engine_http_requests'}
        if not isinstance(diagnostics,dict) or set(diagnostics)!=names or any(type(v) is not int or not 0<=v<=32 for v in diagnostics.values()):raise ValueError('Unsafe parser diagnostics')
        result['retrieval_diagnostics']=diagnostics
    if code=='unsupported_layout' and (status!='failed' or records or count!=0 or events or not diagnostics or not diagnostics['unsupported_layout']):raise ValueError('Invalid layout-failure evidence')
    result['page_events']=events
    result['result_cap_applied']=outcome.get('result_cap_applied') is True
    return result
