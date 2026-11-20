import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from robin_collect.limits import (
    load_policy, PolicyError, LimitReached, TransientCollectionError,
    LimitedExecutor, bound_text,
)

CONFIG = Path(__file__).resolve().parents[1] / "config/queries.json"


def enabled_policy():
    policy = load_policy(CONFIG)
    now = datetime.now(timezone.utc)
    return replace(policy, enabled_ids=policy.query_ids,
                   start=now - timedelta(days=1), end=now + timedelta(days=1))


class PolicyTests(unittest.TestCase):
    def test_approved_config_reports_caps_without_enabling_collection(self):
        policy = load_policy(CONFIG)
        summary = policy.summary()
        self.assertEqual(summary["limits"]["pages_per_batch"], 30)
        self.assertEqual(summary["max_attempts_per_operation"], 3)
        self.assertEqual(summary["maximum_results_if_all_queries_enabled"], 300)
        self.assertIn("no_enabled_queries", summary["live_blockers"])
        self.assertIn("collection_dates_unset", summary["live_blockers"])
        self.assertFalse(summary["network_activity"])

    def test_invalid_limits_and_scope_are_rejected(self):
        original = json.loads(CONFIG.read_text())
        mutations = [
            lambda d: d["limits"].update(concurrency=True),
            lambda d: d["limits"].update(max_retries=-1),
            lambda d: d["limits"].update(pages_per_query=21),
            lambda d: d["limits"].update(pages_per_batch=1),
            lambda d: d["limits"].pop("timeout_seconds"),
            lambda d: d["scope"]["page_collection"].update(recursive_crawling=True),
            lambda d: d["queries"].append(d["queries"][0]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.json"
            for mutate in mutations:
                data = json.loads(json.dumps(original))
                mutate(data)
                path.write_text(json.dumps(data))
                with self.subTest(data=data["limits"]), self.assertRaises(PolicyError):
                    load_policy(path)

    def test_dates_require_timezone_and_approved_window(self):
        for start, end in [("2026-11-20", "2026-11-21"),
                           ("2026-11-20T00:00:00Z", None),
                           ("2026-11-20T00:00:00Z", "2026-12-20T00:00:00Z")]:
            data = json.loads(CONFIG.read_text())
            data["scope"]["collection_dates"].update(start_date_utc=start, end_date_utc=end)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "policy.json"
                path.write_text(json.dumps(data))
                with self.assertRaises(PolicyError):
                    load_policy(path)

    def test_text_caps_preserve_unicode_and_mark_truncation(self):
        limits = enabled_policy().limits
        output = bound_text("a" * 10001, limits)
        self.assertEqual(output.retained_characters, 10000)
        self.assertTrue(output.truncated)
        output = bound_text("\U0001f642\U0001f642X", replace(limits, page_text_bytes=7))
        self.assertEqual(output.text, "\U0001f642")
        self.assertEqual(output.retained_bytes, 4)
        self.assertTrue(output.truncated)
        self.assertFalse(bound_text("short", limits).truncated)


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.policy = enabled_policy()
        self.executor = LimitedExecutor(self.policy)

    async def results(self, remaining):
        self.assertGreater(remaining, 0)
        return [{"id": f"r{i}"} for i in range(25)]

    async def text(self, remaining):
        return "synthetic text"

    async def test_search_caps_results_and_requires_retained_direct_result(self):
        rows = await self.executor.search("q001", self.results)
        self.assertEqual(len(rows), 20)
        for result_id, reason in [("r24", "missing_research_fields"), ("r1", "crawl_link")]:
            with self.assertRaises(PolicyError):
                await self.executor.fetch_page("q001", result_id, reason, self.text)
        self.assertEqual(self.executor.page_attempts, 0)
        await self.executor.fetch_page("q001", "r1", "missing_research_fields", self.text)
        self.assertEqual(self.executor.page_attempts, 1)
        with self.assertRaises(LimitReached):
            await self.executor.search("q001", self.results)

    async def test_page_caps_across_queries_and_batch(self):
        for query in ["q001", "q002", "q003"]:
            await self.executor.search(query, self.results)
            for _ in range(10):
                await self.executor.fetch_page(query, "r1", "insufficient_relevance", self.text)
            with self.assertRaises(LimitReached):
                await self.executor.fetch_page(query, "r1", "insufficient_relevance", self.text)
        self.assertEqual(self.executor.page_attempts, 30)
        await self.executor.search("q004", self.results)
        with self.assertRaises(LimitReached):
            await self.executor.fetch_page("q004", "r1", "insufficient_relevance", self.text)
        self.assertEqual(self.executor.page_attempts, 30)

    async def test_retries_count_as_page_attempts_and_only_transient_failures_retry(self):
        await self.executor.search("q001", self.results)
        attempts = 0
        delays = []
        async def failure(remaining):
            nonlocal attempts
            attempts += 1
            raise TransientCollectionError("synthetic transient failure")
        async def no_wait(delay):
            delays.append(delay)
        with patch("robin_collect.limits.asyncio.sleep", no_wait):
            with self.assertRaises(TransientCollectionError):
                await self.executor.fetch_page("q001", "r1", "missing_research_fields", failure)
        self.assertEqual(attempts, 3)
        self.assertEqual(delays, [2, 4])
        self.assertEqual(self.executor.page_attempts, 3)
        async def permanent(remaining):
            raise ValueError("synthetic permanent failure")
        with self.assertRaises(ValueError):
            await self.executor.fetch_page("q001", "r1", "missing_research_fields", permanent)
        self.assertEqual(self.executor.page_attempts, 4)

    async def test_timeout_cancels_callback_without_retry(self):
        policy = replace(self.policy, limits=replace(self.policy.limits, timeout_seconds=1))
        executor = LimitedExecutor(policy)
        cancelled = False
        async def slow(remaining):
            nonlocal cancelled
            try:
                await asyncio.sleep(10)
            finally:
                cancelled = True
        with self.assertRaises(TimeoutError):
            await executor.search("q001", slow)
        self.assertTrue(cancelled)

    async def test_retry_backoff_shares_the_operation_deadline(self):
        policy = replace(self.policy, limits=replace(self.policy.limits, timeout_seconds=1))
        executor = LimitedExecutor(policy)
        attempts = 0
        async def temporary(remaining):
            nonlocal attempts
            attempts += 1
            raise TransientCollectionError("synthetic")
        with self.assertRaises(TimeoutError):
            await executor.search("q001", temporary)
        self.assertEqual(attempts, 1)

    async def test_collection_window_can_shorten_operation_timeout(self):
        policy = replace(self.policy, end=datetime.now(timezone.utc) + timedelta(milliseconds=50))
        executor = LimitedExecutor(policy)
        async def slow(remaining):
            self.assertLess(remaining, 1)
            await asyncio.sleep(10)
        with self.assertRaises(TimeoutError):
            await executor.search("q001", slow)

    async def test_default_policy_and_expired_window_do_not_call_adapter(self):
        for policy in [load_policy(CONFIG), replace(self.policy, end=datetime.now(timezone.utc) - timedelta(seconds=1))]:
            executor = LimitedExecutor(policy)
            called = False
            async def callback(remaining):
                nonlocal called
                called = True
                return []
            with self.assertRaises(PolicyError):
                await executor.search("q001", callback)
            self.assertFalse(called)

    async def test_calls_are_serialized_and_old_result_ids_are_invalidated(self):
        active = maximum = 0
        async def callback(remaining):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1
            return [{"id": "r1"}]
        await asyncio.gather(self.executor.search("q001", callback), self.executor.search("q002", callback))
        self.assertEqual(maximum, 1)
        with self.assertRaises(PolicyError):
            await self.executor.fetch_page("q001", "r1", "missing_research_fields", self.text)


if __name__ == "__main__":
    unittest.main()
