#!/usr/bin/env python3
"""WSL-native SQLite collection controller; Windows launches transparently into WSL."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    if os.name=='nt' and str(ROOT).lower().startswith('\\\\wsl.localhost\\'):
        parts=str(ROOT)[2:].split('\\')
        distro=parts[1]
        project='/'+'/'.join(parts[2:])
        return subprocess.call(['wsl.exe','-d',distro,'--cd',project,'--','python3','scripts/collect.py',*sys.argv[1:]])
    sys.path.insert(0,str(ROOT/'src'))
    from robin_collect.collection import prepare,load_key,plan,collect,write_artifacts,exclusive
    from robin_collect.collection_store import CollectionStore
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','plan','run','resume','export','review'])
    parser.add_argument('--run-id')
    parser.add_argument('--pilot',action='store_true')
    parser.add_argument('--observation-id')
    parser.add_argument('--decision',choices=['candidate','rejected','needs_review'])
    parser.add_argument('--reason')
    parser.add_argument('--reviewer')
    args=parser.parse_args()
    try:
        if args.action=='prepare':
            prepare(ROOT);result={'status':'prepared','key_printed':False}
        elif args.action=='plan':result=plan(ROOT,args.pilot)
        elif args.action in {'run','resume'}:
            if args.action=='resume' and not args.run_id:parser.error('resume requires --run-id')
            result=collect(ROOT,args.run_id,args.pilot,args.action=='resume')
        else:
            if not args.run_id:parser.error('export/review requires --run-id')
            from robin_collect.collection import _run_id
            _run_id(args.run_id)
            with exclusive(ROOT/'data/live/collection.lock'):
                store=CollectionStore(ROOT/'data/live/collection.sqlite',load_key(ROOT))
                try:
                    if args.action=='review':
                        if not all([args.observation_id,args.decision,args.reason,args.reviewer]):parser.error('review requires observation, decision, reason, and opaque reviewer ID')
                        store.review(args.observation_id,args.decision,args.reason,args.reviewer,args.run_id)
                    result=write_artifacts(ROOT,store,args.run_id)
                finally:store.close()
        print(json.dumps(result,indent=2))
        return 0 if result.get('status') not in {'needs_attention'} else 1
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError,sqlite3.Error):
        parser.exit(2,'Collection stopped. Inspect the sanitized manifest, policy, private key permissions, and Docker health; raw exception text is suppressed.\n')


if __name__=='__main__':raise SystemExit(main())
