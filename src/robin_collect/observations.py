"""Structured-only source observations: untrusted free text never leaves memory."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
from .normalize import normalize_text, normalize_url
from .sanitize import sanitize

POLICY_VERSION = "organizational-exposure-1-structured-only"


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


def classify(text, published, window_start, lookback_days):
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
    exposure = bool(re.search(r"\b(?:breach|leak|leaked|exposure|exposed|stolen)\b", lowered))
    subject = bool(re.search(r"\b(?:company|corporate|organization|organizational|database|customer|employee|hospital|university|retail|business)\b", lowered))
    category = "database" if "database" in lowered else "customer_data" if "customer" in lowered else "organizational_data" if subject else "unknown"
    if exposure and subject:
        return "candidate", "organizational_exposure_claim_unverified", category, "known" if published else "unknown"
    if re.search(r"\b(?:welcome|directory|advertise|advertising)\b", lowered) and not exposure:
        return "rejected", "generic_advertising", category, "known" if published else "unknown"
    return "needs_review", "insufficient_context", category, "known" if published else "unknown"


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
    organizations = []
    for canonical, aliases in entities.items():
        if any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text, re.I) for alias in aliases):
            organizations.append(pseudonym(key, "organization", normalize_text(canonical).casefold()))
    decision, reason, category, date_status = classify(text, row.get("publication_date"), window_start, lookback_days)
    # Withhold ALL original free text, not just regex matches. Unknown names,
    # addresses, secrets, source handles, and exposed records cannot leak through.
    safe_title = "Source observation [TITLE_" + pseudonym(key, "title", title) + "]"
    summary = "Possible organizational exposure claim; unverified." if decision == "candidate" else "Insufficient source context for an exposure finding." if decision == "needs_review" else "Excluded under collection criteria."
    return {
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
    if not isinstance(record,dict) or set(record)!=SAFE_KEYS or record['query_id']!=query_id:
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
        'source_type':{'unknown'},'language':{'unknown'},'relevance_decision':{'candidate','rejected','needs_review'},
        'relevance_reason':{'disallowed_content','out_of_date','publication_date_uncertain','organizational_exposure_claim_unverified','generic_advertising','insufficient_context'},
        'publication_date_status':{'known','unknown','uncertain'},'review_status':{'pending_review'},
        'privacy_mode':{'structured_only'},'policy_version':{POLICY_VERSION},'source_capture':{'before_mcp_listing_truncation'},
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
    return record


def validate_outcome(outcome, cap, query_id):
    if not isinstance(outcome,dict):raise ValueError('Invalid adapter outcome')
    status=outcome.get('status')
    if not isinstance(status,str) or status not in {'completed','no_results','engines_unreachable','timed_out','failed'}:raise ValueError('Invalid outcome status')
    code=outcome.get('code')
    if (code is not None and not isinstance(code,str)) or code not in {None,'all_locators_invalid','operation_deadline','capture_failed','transport_failed','container_deadline','cleanup_uncertain'}:raise ValueError('Unsafe outcome code')
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
    if result.get('page_fetch_attempts',0)!=0 or result.get('model_calls',0)!=0:raise ValueError('Metadata-only contract violated')
    result['result_cap_applied']=outcome.get('result_cap_applied') is True
    return result
