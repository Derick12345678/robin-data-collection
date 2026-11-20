"""Offline-first CLI. Does not start Tor or contact remote services."""
import argparse
import json
import os
import sqlite3
from pathlib import Path
from .pipeline import process


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=Path("data/collection.sqlite"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--run-id")
    args = parser.parse_args()
    try:
        output, report = process(args.input, args.db, args.output_dir,
                                 os.environ.get("COLLECTION_HMAC_KEY", ""), args.run_id)
    except (ValueError, OSError, RuntimeError, sqlite3.Error):
        # Do not echo input values, file contents, secrets, or exception payloads.
        parser.exit(2, "Collection failed. Check input schema, paths, unique run ID, and HMAC key; no raw error is logged.\n")
    print(json.dumps({"csv": str(output), "quality": report}, indent=2))


if __name__ == "__main__":
    main()
