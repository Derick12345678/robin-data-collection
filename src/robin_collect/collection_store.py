"""Durable collection state. Only allowlisted structured observations are stored."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from .observations import pseudonym, POLICY_VERSION, validate_outcome

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS collection_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS collection_runs (
 run_id TEXT PRIMARY KEY, config_hash TEXT NOT NULL, entities_hash TEXT NOT NULL,
 started TEXT NOT NULL, finished TEXT, status TEXT NOT NULL, window_start TEXT NOT NULL,
 window_end TEXT NOT NULL, query_ids TEXT NOT NULL, limits_json TEXT NOT NULL,
 image TEXT NOT NULL, collector_version TEXT NOT NULL, policy_version TEXT NOT NULL, options_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS collection_queries (
 run_id TEXT NOT NULL REFERENCES collection_runs, query_id TEXT NOT NULL,
 state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, operation_deadline TEXT,
 original_query_pseudonym TEXT NOT NULL, refined_query_pseudonym TEXT NOT NULL,
 report_json TEXT, error_code TEXT, PRIMARY KEY(run_id,query_id)
);
CREATE TABLE IF NOT EXISTS collection_attempts (
 run_id TEXT NOT NULL, query_id TEXT NOT NULL, attempt INTEGER NOT NULL,
 container_name TEXT NOT NULL UNIQUE, state TEXT NOT NULL, charged_at TEXT NOT NULL,
 finished_at TEXT, cleanup_confirmed INTEGER NOT NULL DEFAULT 0, report_json TEXT,
 PRIMARY KEY(run_id,query_id,attempt),
 FOREIGN KEY(run_id,query_id) REFERENCES collection_queries(run_id,query_id)
);
CREATE TABLE IF NOT EXISTS collection_page_attempts (
 token TEXT PRIMARY KEY,run_id TEXT NOT NULL,query_id TEXT NOT NULL,query_attempt INTEGER NOT NULL,
 state TEXT NOT NULL,source_id TEXT,status TEXT,reason TEXT,wire_bytes INTEGER NOT NULL DEFAULT 0,
 truncated INTEGER NOT NULL DEFAULT 0,reserved_at TEXT NOT NULL,finished_at TEXT,
 FOREIGN KEY(run_id,query_id,query_attempt) REFERENCES collection_attempts(run_id,query_id,attempt)
);
CREATE TABLE IF NOT EXISTS run_quarantine_events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL REFERENCES collection_runs,
 reason TEXT NOT NULL,created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_observations (
 observation_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, content_id TEXT NOT NULL,
 safe_json TEXT NOT NULL, first_collected TEXT NOT NULL,last_collected TEXT NOT NULL,
 change_review TEXT NOT NULL DEFAULT 'none'
);
CREATE TABLE IF NOT EXISTS observation_matches (
 run_id TEXT NOT NULL, query_id TEXT NOT NULL, observation_id TEXT NOT NULL REFERENCES source_observations,
 collected_at TEXT NOT NULL, safe_json TEXT NOT NULL, PRIMARY KEY(run_id,query_id,observation_id),
 FOREIGN KEY(run_id,query_id) REFERENCES collection_queries(run_id,query_id)
);
CREATE TABLE IF NOT EXISTS collection_reviews (
 run_id TEXT NOT NULL REFERENCES collection_runs,
 observation_id TEXT NOT NULL REFERENCES source_observations,
 decision TEXT NOT NULL,reason TEXT NOT NULL,reviewer TEXT NOT NULL,reviewed_at TEXT NOT NULL,
 PRIMARY KEY(run_id,observation_id)
);
CREATE TABLE IF NOT EXISTS collection_review_events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 run_id TEXT NOT NULL REFERENCES collection_runs,
 observation_id TEXT NOT NULL REFERENCES source_observations,
 decision TEXT NOT NULL,reason TEXT NOT NULL,reviewer TEXT NOT NULL,reviewed_at TEXT NOT NULL
);
"""


def utc():
    return datetime.now(timezone.utc).isoformat()


class CollectionStore:
    def __init__(self, path: Path, key):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        # Upgrade the initial milestone development database without losing matches.
        if 'safe_json' not in {row[1] for row in self.db.execute('PRAGMA table_info(observation_matches)')}:
            with self.db:
                self.db.execute('ALTER TABLE observation_matches ADD COLUMN safe_json TEXT')
                self.db.execute('UPDATE observation_matches SET safe_json=(SELECT safe_json FROM source_observations WHERE observation_id=observation_matches.observation_id)')
        if 'options_json' not in {row[1] for row in self.db.execute('PRAGMA table_info(collection_runs)')}:
            with self.db:self.db.execute("ALTER TABLE collection_runs ADD COLUMN options_json TEXT NOT NULL DEFAULT '{}' ")
        fingerprint = pseudonym(key, "key-check", "collection-store")
        try:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute("SELECT value FROM collection_meta WHERE key='key_fingerprint'").fetchone()
            if old and old[0] != fingerprint:
                raise ValueError("Database HMAC key mismatch")
            self.db.execute("INSERT OR IGNORE INTO collection_meta VALUES('key_fingerprint',?)", (fingerprint,))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            self.db.close()
            raise
        self.key = key

    def close(self):
        self.db.close()

    def create_run(self, run_id, config_hash, entities_hash, start, end, queries, limits, image, options=None):
        with self.db:
            self.db.execute("INSERT INTO collection_runs(run_id,config_hash,entities_hash,started,finished,status,window_start,window_end,query_ids,limits_json,image,collector_version,policy_version,options_json) VALUES(?,?,?,?,NULL,'running',?,?,?,?,?,?,?,?)",
                (run_id, config_hash, entities_hash, utc(), start, end, json.dumps([q['id'] for q in queries]), json.dumps(limits), image, '0.5.0', POLICY_VERSION, json.dumps(options or {})))
            for query in queries:
                qhash = pseudonym(self.key, 'query', query['text'])
                original = pseudonym(self.key, 'query', query.get('original_text',query['text']))
                self.db.execute("INSERT INTO collection_queries(run_id,query_id,state,original_query_pseudonym,refined_query_pseudonym) VALUES(?,?,'pending',?,?)", (run_id, query['id'], original, qhash))

    def run(self, run_id):
        value = self.db.execute("SELECT * FROM collection_runs WHERE run_id=?", (run_id,)).fetchone()
        if value is None:
            raise ValueError("Unknown run")
        return dict(value)

    def query(self, run_id, query_id):
        return dict(self.db.execute("SELECT * FROM collection_queries WHERE run_id=? AND query_id=?", (run_id, query_id)).fetchone())

    def reserve(self, run_id, query_id, max_attempts, deadline, container_name):
        # A second process cannot reserve the same query or refund an uncertain attempt.
        try:
            self.db.execute("BEGIN IMMEDIATE")
            query = self.query(run_id, query_id)
            if query['state'] not in {'pending', 'retryable'} or query['attempts'] >= max_attempts:
                raise RuntimeError("Query cannot be dispatched")
            attempt = query['attempts'] + 1
            self.db.execute("INSERT INTO collection_attempts(run_id,query_id,attempt,container_name,state,charged_at,finished_at,cleanup_confirmed) VALUES(?,?,?,?,'in_flight',?,NULL,0)", (run_id, query_id, attempt, container_name, utc()))
            self.db.execute("UPDATE collection_queries SET state='in_flight',attempts=?,operation_deadline=COALESCE(operation_deadline,?) WHERE run_id=? AND query_id=?", (attempt, deadline, run_id, query_id))
            self.db.commit()
            return attempt
        except BaseException:
            self.db.rollback()
            raise

    def reserve_pages(self,run_id,query_id,attempt,requested):
        import uuid
        limits=json.loads(self.run(run_id)['limits_json'])
        try:
            self.db.execute('BEGIN IMMEDIATE')
            query=self.query(run_id,query_id)
            if query['state']!='in_flight' or query['attempts']!=attempt:raise RuntimeError('No active query reservation')
            batch=self.db.execute("SELECT COUNT(*) FROM collection_page_attempts WHERE run_id=? AND state<>'released'",(run_id,)).fetchone()[0]
            used=self.db.execute("SELECT COUNT(*) FROM collection_page_attempts WHERE run_id=? AND query_id=? AND state<>'released'",(run_id,query_id)).fetchone()[0]
            count=max(0,min(requested,limits['pages_per_batch']-batch,limits['pages_per_query']-used))
            tokens=[]
            for _ in range(count):
                token=uuid.uuid4().hex
                self.db.execute("INSERT INTO collection_page_attempts(token,run_id,query_id,query_attempt,state,reserved_at) VALUES(?,?,?,?,'reserved',?)",(token,run_id,query_id,attempt,utc()))
                tokens.append(token)
            self.db.commit();return tokens
        except BaseException:self.db.rollback();raise

    def inflight(self, run_id):
        return [dict(row) for row in self.db.execute("SELECT * FROM collection_attempts WHERE run_id=? AND (state='in_flight' OR cleanup_confirmed=0)", (run_id,))]

    def recover(self, run_id, query_id, attempt, cleanup):
        with self.db:
            self.db.execute("UPDATE collection_attempts SET state='uncertain',finished_at=?,cleanup_confirmed=? WHERE run_id=? AND query_id=? AND attempt=?", (utc(), int(cleanup), run_id, query_id, attempt))
            self.db.execute("UPDATE collection_page_attempts SET state='uncertain',finished_at=? WHERE run_id=? AND query_id=? AND query_attempt=? AND state='reserved'",(utc(),run_id,query_id,attempt))
            self.db.execute("UPDATE collection_queries SET state='uncertain',error_code='interrupted_attempt_not_refunded' WHERE run_id=? AND query_id=?", (run_id, query_id))

    def complete(self, run_id, query_id, attempt, outcome):
        cap=json.loads(self.run(run_id)['limits_json'])['results_per_query']
        tokens=[r[0] for r in self.db.execute('SELECT token FROM collection_page_attempts WHERE run_id=? AND query_id=? AND query_attempt=?',(run_id,query_id,attempt))]
        outcome=validate_outcome(outcome,cap,query_id,tokens)
        with self.db:
            query = self.query(run_id, query_id)
            if query['state'] != 'in_flight' or query['attempts'] != attempt:
                raise RuntimeError("Stale completion")
            cleanup = bool(outcome['cleanup_confirmed'])
            status = outcome['status'] if cleanup else 'uncertain'
            events={event['token']:event for event in outcome.get('page_events',[])}
            known=cleanup and (status in {'completed','no_results','engines_unreachable'} or outcome.get('code')=='unsupported_layout')
            for token in tokens:
                event=events.get(token)
                if known and event:
                    self.db.execute("UPDATE collection_page_attempts SET state='charged',source_id=?,status=?,reason=?,wire_bytes=?,truncated=?,finished_at=? WHERE token=?",(event['source_pseudonym'],event['status'],event['reason'],event['wire_bytes'],int(event['truncated']),utc(),token))
                else:
                    self.db.execute("UPDATE collection_page_attempts SET state=?,finished_at=? WHERE token=?",('released' if known else 'uncertain',utc(),token))
            if status in {'completed', 'no_results'}:
                for item in outcome['observations']:
                    if item.get('page_selection')=='already_attempted':
                        existing=self.db.execute("SELECT safe_json FROM observation_matches WHERE run_id=? AND json_extract(safe_json,'$.metadata_parent_id')=? ORDER BY collected_at,query_id LIMIT 1",(run_id,item['observation_id'])).fetchone()
                        if existing:
                            canonical=json.loads(existing['safe_json'])
                            canonical.update(query_id=query_id,collected_at_utc=item['collected_at_utc'],page_selection='already_attempted')
                            item=canonical
                    prior = self.db.execute("SELECT 1 FROM source_observations WHERE source_id=? AND observation_id<>? AND observation_id<>?", (item['source_pseudonym'], item['observation_id'],item.get('metadata_parent_id',''))).fetchone()
                    if prior:
                        self.db.execute("UPDATE source_observations SET change_review='requires_review' WHERE source_id=?", (item['source_pseudonym'],))
                    safe = json.dumps(item, sort_keys=True)
                    self.db.execute("INSERT INTO source_observations VALUES(?,?,?,?,?,?,?) ON CONFLICT(observation_id) DO UPDATE SET first_collected=MIN(source_observations.first_collected,excluded.first_collected),last_collected=MAX(source_observations.last_collected,excluded.last_collected)", (item['observation_id'], item['source_pseudonym'], item['content_pseudonym'], safe, item['collected_at_utc'], item['collected_at_utc'], 'requires_review' if prior else 'none'))
                    self.db.execute("INSERT OR IGNORE INTO observation_matches(run_id,query_id,observation_id,collected_at,safe_json) VALUES(?,?,?,?,?)", (run_id, query_id, item['observation_id'], item['collected_at_utc'], safe))
            summary = {k:v for k,v in outcome.items() if k != 'observations'}
            self.db.execute("UPDATE collection_attempts SET state=?,finished_at=?,cleanup_confirmed=?,report_json=? WHERE run_id=? AND query_id=? AND attempt=?", (status, utc(), int(cleanup), json.dumps(summary), run_id, query_id, attempt))
            self.db.execute("UPDATE collection_queries SET state=?,report_json=?,error_code=? WHERE run_id=? AND query_id=?", (status, json.dumps(summary), outcome.get('code'), run_id, query_id))

    def allow_retry(self, run_id, query_id):
        with self.db:
            self.db.execute("UPDATE collection_queries SET state='retryable' WHERE run_id=? AND query_id=? AND state='engines_unreachable'", (run_id, query_id))

    def finish(self, run_id):
        states = [row[0] for row in self.db.execute("SELECT state FROM collection_queries WHERE run_id=?", (run_id,))]
        status = 'completed' if all(s in {'completed','no_results'} for s in states) else 'needs_attention'
        with self.db:
            self.db.execute("UPDATE collection_runs SET status=?,finished=? WHERE run_id=?", (status, utc(), run_id))
        return status

    def quarantine_events(self,run_id):
        return [dict(row) for row in self.db.execute('SELECT * FROM run_quarantine_events WHERE run_id=? ORDER BY event_id',(run_id,))]

    def quarantine(self,run_id,reason='failed_relevance_pilot'):
        self.run(run_id)
        if reason not in {'failed_relevance_pilot','operator_reported_irrelevant'}:raise ValueError('Invalid quarantine reason')
        with self.db:self.db.execute('INSERT INTO run_quarantine_events(run_id,reason,created_at) VALUES(?,?,?)',(run_id,reason,utc()))

    def attempted_sources(self,run_id):
        return sorted({row[0] for row in self.db.execute("SELECT source_id FROM collection_page_attempts WHERE run_id=? AND source_id IS NOT NULL AND state<>'released'",(run_id,))})

    def observations(self, run_id):
        result=[]
        for row in self.db.execute("SELECT o.*,(SELECT safe_json FROM observation_matches m WHERE m.run_id=? AND m.observation_id=o.observation_id ORDER BY collected_at,query_id LIMIT 1) AS run_json FROM source_observations o WHERE EXISTS(SELECT 1 FROM observation_matches m WHERE m.run_id=? AND m.observation_id=o.observation_id) ORDER BY o.observation_id", (run_id,run_id)):
            item=json.loads(row['run_json'])
            item['collected_at_utc']=self.db.execute('SELECT MIN(collected_at) FROM observation_matches WHERE run_id=? AND observation_id=?',(run_id,item['observation_id'])).fetchone()[0]
            item.update(first_collected_at_utc=row['first_collected'],last_collected_at_utc=row['last_collected'],change_review=row['change_review'])
            item['query_ids']=[x[0] for x in self.db.execute("SELECT DISTINCT query_id FROM observation_matches WHERE run_id=? AND observation_id=? ORDER BY query_id",(run_id,item['observation_id']))]
            item.pop('query_id',None)
            # Equal text across sources is a review grouping, never a merge.
            count=self.db.execute("SELECT COUNT(*) FROM source_observations WHERE content_id=?",(row['content_id'],)).fetchone()[0]
            item['cross_source_duplicate_candidate']=count>1
            tokens=set(item['similarity_tokens'])
            near=[]
            for other in self.db.execute('SELECT observation_id,safe_json FROM source_observations WHERE observation_id<>?',(item['observation_id'],)):
                candidate=set(json.loads(other['safe_json'])['similarity_tokens'])
                union=tokens|candidate
                if union and len(tokens&candidate)/len(union)>=0.8:near.append(other['observation_id'])
            item['near_duplicate_candidates']=sorted(near)
            item.pop('similarity_tokens')
            review=self.db.execute("SELECT * FROM collection_reviews WHERE run_id=? AND observation_id=?",(run_id,item['observation_id'])).fetchone()
            if review:
                item['human_review']=dict(review)
                item['review_status']='reviewed_pending_release'
            item['review_history']=[dict(event) for event in self.db.execute('SELECT * FROM collection_review_events WHERE run_id=? AND observation_id=? ORDER BY event_id',(run_id,item['observation_id']))]
            result.append(item)
        return result

    def manifest(self, run_id):
        result=self.run(run_id)
        result['query_ids']=json.loads(result['query_ids'])
        result['limits']=json.loads(result.pop('limits_json'))
        result['queries']=[dict(row) for row in self.db.execute("SELECT * FROM collection_queries WHERE run_id=? ORDER BY query_id",(run_id,))]
        for query in result['queries']:
            query['report']=json.loads(query.pop('report_json') or '{}')
        result['attempts']=[dict(row) for row in self.db.execute("SELECT * FROM collection_attempts WHERE run_id=? ORDER BY query_id,attempt",(run_id,))]
        for attempt in result['attempts']:attempt['report']=json.loads(attempt.pop('report_json') or '{}')
        result['options']=json.loads(result.pop('options_json'))
        result['pages']=[dict(row) for row in self.db.execute('SELECT * FROM collection_page_attempts WHERE run_id=? ORDER BY reserved_at,token',(run_id,))]
        result['page_fetch_attempts']=sum(page['state'] in {'charged','uncertain','reserved'} for page in result['pages'])
        result['page_attempts_confirmed']=sum(page['state']=='charged' for page in result['pages'])
        result['page_budget_held_or_uncertain']=sum(page['state'] in {'reserved','uncertain'} for page in result['pages'])
        result['raw_content_persisted']=False
        result['record_count']=len(self.observations(run_id))
        result['quarantine_events']=self.quarantine_events(run_id)
        result['research_suitability']='quarantined' if result['quarantine_events'] else 'unvalidated'
        result['dataset_approval']='not_approved'
        return result

    def review(self, observation_id, decision, reason, reviewer, run_id):
        if decision not in {'candidate','rejected','needs_review'} or reason not in {'insufficient_context','unrelated','generic_advertising','out_of_date','disallowed_content','requires_source_review','consistent_with_scope'}:
            raise ValueError("Unsupported review decision/reason")
        if not reviewer.isascii() or not reviewer.replace('-','').replace('_','').isalnum() or len(reviewer)>40:
            raise ValueError("Use an opaque reviewer ID")
        if not self.db.execute('SELECT 1 FROM observation_matches WHERE run_id=? AND observation_id=?',(run_id,observation_id)).fetchone():
            raise ValueError('Observation is not part of this run')
        with self.db:
            stamp=utc()
            self.db.execute("INSERT INTO collection_review_events(run_id,observation_id,decision,reason,reviewer,reviewed_at) VALUES(?,?,?,?,?,?)",(run_id,observation_id,decision,reason,reviewer,stamp))
            self.db.execute("INSERT OR REPLACE INTO collection_reviews VALUES(?,?,?,?,?,?)",(run_id,observation_id,decision,reason,reviewer,stamp))
