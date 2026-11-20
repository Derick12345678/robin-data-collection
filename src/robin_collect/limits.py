"""Validated limits and reusable async guards; this module performs no network I/O."""
import argparse
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class PolicyError(ValueError):
    pass


class LimitReached(RuntimeError):
    pass


class TransientCollectionError(RuntimeError):
    """Adapter-classified temporary error; the only automatically retried failure."""


@dataclass(frozen=True)
class Limits:
    results_per_query: int
    pages_per_query: int
    pages_per_batch: int
    page_characters: int
    page_text_bytes: int
    concurrency: int
    timeout_seconds: int
    max_retries: int
    retry_backoff_initial_seconds: int
    retry_backoff_max_seconds: int

    def __post_init__(self):
        for name, value in asdict(self).items():
            if type(value) is not int or value < (0 if name == "max_retries" else 1):
                raise PolicyError(f"Invalid integer limit: {name}")
        if not 10 <= self.results_per_query <= 100:
            raise PolicyError("results_per_query is outside pinned Robin defaults range")
        if not 3 <= self.pages_per_query <= min(20, self.results_per_query):
            raise PolicyError("pages_per_query is outside pinned Robin defaults range")
        if self.pages_per_batch < self.pages_per_query:
            raise PolicyError("pages_per_batch must cover at least one query page budget")
        if not 1000 <= self.page_characters <= 20000 or self.concurrency > 16:
            raise PolicyError("Text/concurrency limits are outside pinned Robin ranges")
        if self.retry_backoff_initial_seconds > self.retry_backoff_max_seconds:
            raise PolicyError("Initial backoff cannot exceed maximum backoff")


@dataclass(frozen=True)
class Policy:
    limits: Limits
    query_ids: frozenset[str]
    enabled_ids: frozenset[str]
    start: datetime | None
    end: datetime | None
    config_sha256: str

    def blockers(self, now=None):
        now = now or datetime.now(timezone.utc)
        reasons = []
        if not self.enabled_ids:
            reasons.append("no_enabled_queries")
        if self.start is None or self.end is None:
            reasons.append("collection_dates_unset")
        elif not self.start <= now < self.end:
            reasons.append("outside_collection_window")
        return reasons

    def require_live(self, query_id, now=None):
        if self.blockers(now):
            raise PolicyError("Collection policy is not enabled for the current window")
        if query_id not in self.enabled_ids:
            raise PolicyError("Query is not enabled in this policy")

    def summary(self):
        return {
            "status": "valid", "config_sha256": self.config_sha256,
            "limits": asdict(self.limits), "registered_queries": len(self.query_ids),
            "enabled_queries": len(self.enabled_ids), "live_blockers": self.blockers(),
            "max_attempts_per_operation": 1 + self.limits.max_retries,
            "maximum_results_if_all_queries_enabled": len(self.query_ids) * self.limits.results_per_query,
            "page_budgets_count": "all_fetch_attempts_including_failures_and_retries",
            "timeout_scope": "dispatched_operation_including_retries_and_backoff",
            "network_activity": False,
        }

    def search_parameters(self):
        return {"max_results": self.limits.results_per_query, "threads": self.limits.concurrency}

    def scrape_parameters(self):
        return {"content_chars": self.limits.page_characters, "threads": 1, "allow_clearweb": False}


def _date(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise PolicyError("Collection dates must be timezone-aware ISO timestamps")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PolicyError("Invalid collection timestamp") from None
    if parsed.tzinfo is None:
        raise PolicyError("Collection dates require an explicit timezone")
    return parsed.astimezone(timezone.utc)


def load_policy(path: Path):
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
        values = data["limits"]
        if data["status"] != "approved":
            raise PolicyError("Collection scope must be approved")
        limits = Limits(**{name: values[name] for name in Limits.__dataclass_fields__})
        if (values.get("page_budget_counts") != "attempts_including_failures_and_retries"
                or values.get("timeout_scope") != "operation_including_retries_and_backoff"):
            raise PolicyError("Unsupported page-budget or timeout semantics")
        scope = data["scope"]
        pages = scope["page_collection"]
        if (pages["strategy"] != "titles_and_snippets_first" or pages["recursive_crawling"] is not False
                or pages["direct_result_page_only"] is not True):
            raise PolicyError("Only conditional, direct-result text collection is supported")
        dates = scope["collection_dates"]
        start, end = _date(dates["start_date_utc"]), _date(dates["end_date_utc"])
        if (start is None) != (end is None):
            raise PolicyError("Set both collection dates or leave both unset")
        days = dates["window_days"]
        if type(days) is not int or days < 1:
            raise PolicyError("Invalid collection window length")
        if start and not timedelta(0) < end - start <= timedelta(days=days):
            raise PolicyError("Collection window exceeds approved duration or is reversed")
        queries = data["queries"]
        ids, enabled = set(), set()
        for query in queries:
            qid = query["id"]
            if not isinstance(qid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", qid) or qid in ids:
                raise PolicyError("Query IDs must be unique opaque identifiers")
            if type(query["enabled"]) is not bool:
                raise PolicyError("Query enabled flags must be booleans")
            if not isinstance(query["text"], str) or not query["text"].strip():
                raise PolicyError("Query text is required")
            ids.add(qid)
            if query["enabled"]:
                enabled.add(qid)
        if not ids:
            raise PolicyError("Query registry cannot be empty")
        return Policy(limits, frozenset(ids), frozenset(enabled), start, end, hashlib.sha256(raw).hexdigest())
    except (KeyError, TypeError, json.JSONDecodeError):
        raise PolicyError("Invalid collection policy structure") from None


@dataclass(frozen=True)
class BoundedText:
    text: str
    truncated: bool
    retained_characters: int
    retained_bytes: int


def bound_text(text: str, limits: Limits):
    if not isinstance(text, str):
        raise PolicyError("Page result must be extracted text")
    clipped = text[:limits.page_characters].encode("utf-8")[:limits.page_text_bytes].decode("utf-8", errors="ignore")
    return BoundedText(clipped, clipped != text, len(clipped), len(clipped.encode("utf-8")))


class LimitedExecutor:
    """In-memory single-batch guard. Async callbacks must honor cancellation.

    Serializes MCP calls because each search can internally use multiple workers.
    The future adapter must persist counters/checkpoints and terminate remote work
    on timeout before resuming; cancelling a client does not guarantee server stop.
    """
    def __init__(self, policy: Policy):
        self.policy = policy
        self._lock = asyncio.Lock()
        self.page_attempts = 0
        self.query_page_attempts = {}
        self._results = {}
        self._active_query_id = None

    def _reserve_page_attempt(self, query_id):
        limits = self.policy.limits
        count = self.query_page_attempts.get(query_id, 0)
        if count >= limits.pages_per_query or self.page_attempts >= limits.pages_per_batch:
            raise LimitReached("Page-fetch attempt budget exhausted")
        self.query_page_attempts[query_id] = count + 1
        self.page_attempts += 1

    async def _execute(self, query_id, callback: Callable[[float], Awaitable[T]], *, page=False):
        limits = self.policy.limits
        self.policy.require_live(query_id)
        duration = min(limits.timeout_seconds, (self.policy.end - datetime.now(timezone.utc)).total_seconds())
        deadline = time.monotonic() + duration
        async with asyncio.timeout(duration):
            for attempt in range(limits.max_retries + 1):
                self.policy.require_live(query_id)
                if page:
                    self._reserve_page_attempt(query_id)
                try:
                    value = await callback(max(0.0, deadline - time.monotonic()))
                    self.policy.require_live(query_id)
                    return value
                except TransientCollectionError:
                    if attempt == limits.max_retries:
                        raise
                    delay = min(limits.retry_backoff_initial_seconds * (2 ** attempt), limits.retry_backoff_max_seconds)
                    await asyncio.sleep(delay)
        raise TimeoutError("Collection operation timed out")

    async def search(self, query_id, callback):
        async with self._lock:
            self.policy.require_live(query_id)
            if query_id in self._results:
                raise LimitReached("Query search already completed in this batch")
            self._active_query_id = None
            rows = await self._execute(query_id, callback)
            if not isinstance(rows, list):
                raise PolicyError("Search adapter must return a list")
            kept = rows[:self.policy.limits.results_per_query]
            if any(not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] for row in kept):
                raise PolicyError("Search results require opaque result IDs")
            self._results[query_id] = {row["id"] for row in kept}
            self._active_query_id = query_id
            return kept

    async def fetch_page(self, query_id, result_id, reason, callback):
        async with self._lock:
            self.policy.require_live(query_id)
            if query_id != self._active_query_id or result_id not in self._results.get(query_id, set()):
                raise PolicyError("Only results retained from this query may be fetched")
            if reason not in {"insufficient_relevance", "missing_research_fields"}:
                raise PolicyError("A supported metadata-insufficiency reason is required")
            text = await self._execute(query_id, callback, page=True)
            return bound_text(text, self.policy.limits)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/queries.json"))
    args = parser.parse_args()
    try:
        print(json.dumps(load_policy(args.config).summary(), indent=2))
    except (OSError, PolicyError):
        parser.exit(2, "Collection policy invalid; check required fields, numeric limits, dates, and query IDs.\n")


if __name__ == "__main__":
    main()
