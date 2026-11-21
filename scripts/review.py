#!/usr/bin/env python3
"""Start the private review service, or print the owner's temporary access URL."""
import argparse,json,os
from pathlib import Path
import subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
if os.name=='nt' and str(ROOT).lower().startswith('\\\\wsl.localhost\\'):
    parts=str(ROOT)[2:].split('\\');raise SystemExit(subprocess.call(['wsl.exe','-d',parts[1],'--cd','/'+'/'.join(parts[2:]),'--','python3','scripts/review.py',*sys.argv[1:]]))
sys.path.insert(0,str(ROOT/'src'))
from robin_collect.review_server import serve
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['serve','access']);parser.add_argument('--port',type=int,default=18601);args=parser.parse_args()
if args.action=='serve':serve(ROOT,args.port)
else:
    path=ROOT/'data/live/review-session.json'
    if path.is_symlink() or path.stat().st_mode & 0o077:raise SystemExit('Private session required')
    data=json.loads(path.read_text());print(data['url']+'#'+data['token'])
