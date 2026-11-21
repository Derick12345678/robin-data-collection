"""Offline input and bounded, structured-only live collection adapters."""
import json
from pathlib import Path
from typing import Protocol


class Collector(Protocol):
    def collect(self, query: dict) -> list[dict]: ...


class RobinMCPCollector:
    """Search-only live adapter; context is required to prevent unbounded calls."""
    def __init__(self, root=None, transport=None):
        if transport is None:
            from .live_adapter import MCPDockerTransport
            transport=MCPDockerTransport(root or Path(__file__).resolve().parents[2])
        self.transport=transport

    def health(self):
        return self.transport.health()

    def cleanup(self, name):
        return self.transport.cleanup(name)

    def review_ready(self):return self.transport.review_ready()

    def publish_contexts(self):return self.transport.publish_contexts()

    def collect(self, query: dict, context=None):
        if context is None:
            raise ValueError("A reserved run attempt and validated policy are required")
        from .observations import validate_outcome
        return validate_outcome(self.transport.collect(query,context),context['config']['limits']['results_per_query'],query['id'],context.get('page_tokens',[]))


def load_observations(path: Path) -> list[dict]:
    if path.stat().st_size > 10_000_000:
        raise ValueError("Input exceeds the 10 MB batch limit")
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Input must be an array of observation objects; see docs/input-format.md")
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("Each observation must be an object")
        for field in ("query_id", "url", "title", "snippet"):
            if not isinstance(row.get(field), str):
                raise ValueError(f"Missing or non-text field: {field}")
        if not row["query_id"].strip() or len(row["query_id"]) > 80:
            raise ValueError("query_id must contain 1-80 characters")
        if any(len(row[field]) > 100_000 for field in ("url", "title", "snippet")):
            raise ValueError("Observation field exceeds the 100,000-character limit")
        if not (row["title"].strip() or row["snippet"].strip()):
            raise ValueError("Observation must contain a title or snippet")
    return records
