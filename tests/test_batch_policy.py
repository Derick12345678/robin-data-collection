from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest
from robin_collect.collection import freeze_batch_policy,plan
from robin_collect.limits import PolicyError

ROOT=Path(__file__).resolve().parents[1]

class BatchPolicyTests(unittest.TestCase):
    def test_frozen_private_window_and_preserved_queries(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'config').mkdir()
            base=(ROOT/'config/queries.json').read_bytes()
            (root/'config/queries.json').write_bytes(base)
            now=datetime(2026,11,21,tzinfo=timezone.utc)
            result=freeze_batch_policy(root,now=now)
            path=root/'data/live/batch-policy.json'
            data=json.loads(path.read_text())
            self.assertEqual(len(result['query_ids']),15)
            self.assertEqual(path.stat().st_mode & 0o077,0)
            self.assertEqual(data['scope']['collection_dates']['end_date_utc'],'2026-11-22T00:00:00+00:00')
            self.assertTrue(all(q['enabled'] and len(q['text'].split())<=5 for q in data['queries']))
            self.assertEqual(sum(q['text']!=q['original_text'] for q in data['queries']),3)
            self.assertEqual((root/'config/queries.json').read_bytes(),base)
            with self.assertRaises(FileExistsError):freeze_batch_policy(root,now=now)
            with self.assertRaises(PolicyError):freeze_batch_policy(root,root/'public.json',now)

if __name__=='__main__':unittest.main()
