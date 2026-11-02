"""Offline isolation tests: daily worker can never process unrelated queue jobs."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import service
from tools import daily_worker


def source(n=18):
    def stamp(i):
        return '%02d:%02d:%02d,000'%(i//3600,(i//60)%60,i%60)
    chunks=[]
    for i in range(n):
        chunks.append('%d\n%s --> %s\nHello, there.'%(
            i+1,stamp(i*3),stamp(i*3+2)))
    return ('\n\n'.join(chunks)+'\n').encode()


class DailyWorkerTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.state=self.root/'subhub1-state'
        self.v1=self.root/'daily-title.mkv'
        self.v2=self.root/'legacy-title.mkv'
        self.v1.write_bytes(b'daily media')
        self.v2.write_bytes(b'old media')
        store=service.Store(self.state)
        store.add('daily-episode-abcdef012345',self.v1,source(),'eng')
        store.add('old-horror-title',self.v2,source(),'eng')
        store.cn.close()

    def test_existing_service_logic_sees_only_selected_daily_job(self):
        views=[]
        def fake_run(store,base,root,args):
            seen=store.jobs()
            views.append([x['id'] for x in seen])
            self.assertEqual(len(seen),1)
            self.assertEqual(seen[0]['id'],'daily-episode-abcdef012345')
            self.assertTrue(args.publish)
            self.assertTrue(args.skip_hy)
            self.assertEqual(args.max_titles,1)
            self.assertEqual(args.mode,'translate')
            self.assertEqual(args.max_minutes,120)
            self.assertEqual(root,self.state)
            store.state('daily-episode-abcdef012345','translated')
            self.assertEqual([x['status'] for x in store.jobs()],
                             ['translated'])
        state=daily_worker.run_one(self.state,'daily-episode-abcdef012345',
                                   base=self.root,worker=fake_run)
        self.assertEqual(state,'translated')
        self.assertEqual(views,[['daily-episode-abcdef012345']])
        store=service.Store(self.state)
        try:
            old=next(x for x in store.jobs() if x['id']=='old-horror-title')
            self.assertEqual(old['status'],'queued')
            self.assertEqual(old['ja'],0)
        finally:
            store.cn.close()

    def test_published_daily_job_does_not_start_another_worker(self):
        store=service.Store(self.state)
        store.state('daily-episode-abcdef012345','published')
        store.cn.close()
        def should_not_run(*args,**kwargs):
            raise AssertionError('No worker should run on already-published job')
        self.assertEqual(daily_worker.run_one(
            self.state,'daily-episode-abcdef012345',
            worker=should_not_run),'published')

    def test_unknown_id_and_unrelated_old_jobs_are_rejected(self):
        for bad in ('old-horror-title','../video','daily-','DAILY-thing'):
            with self.assertRaises(ValueError):
                daily_worker.run_one(self.state,bad)
        with self.assertRaisesRegex(RuntimeError,'not present'):
            daily_worker.run_one(self.state,'daily-not-in-db')

    def test_no_sqlite_file_is_never_created_from_a_missing_queue(self):
        blank=self.root/'missing-state'
        with self.assertRaisesRegex(RuntimeError,'not found'):
            daily_worker.run_one(blank,'daily-episode-abcdef012345')
        self.assertFalse((blank/'jobs.sqlite3').exists())


if __name__=='__main__':
    unittest.main()
