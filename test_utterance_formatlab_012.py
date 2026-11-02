"""Offline regressions for private 24-group, two-format pinned-E4B pilot."""
from pathlib import Path
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import service
from tools import american_dad_utterance_011 as old
from tools import american_dad_core_009 as core
from tools import semantic_groups_011 as sem
from tools import utterance_formatlab_012 as lab


def srt():
    blocks=[]
    for i in range(23):
        base=i*6
        pieces=((i*2+1,base,base+1,'I think we should consider'),
                (i*2+2,base+1.2,base+2.2,'the new plan carefully.'))
        for cid,start,end,english in pieces:
            def stamp(x):
                whole=int(x)
                return '%02d:%02d:%02d,%03d'%(whole//3600,
                       (whole//60)%60,whole%60,round((x-whole)*1000))
            blocks.append('%d\n%s --> %s\n%s'%(
                cid,stamp(start),stamp(end),english))
    return ('\n\n'.join(blocks)+'\n').encode('utf8')


class Lab012(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.state=self.root/'private-new-lab'
        self.original_state=self.root/'original-frozen-v011'
        self.recovery_state=self.root/'old-recovered'
        self.profile=self.root/'profile.json'
        self.profile.write_text('{"recurring_people":[]}',encoding='utf8')
        self.lock_root=self.root/'locks'
        self.entries={}
        for episode in lab.EPISODES:
            folder=self.original_state/'episodes'/episode
            folder.mkdir(parents=True)
            source=folder/'source.en.srt'
            source.write_bytes(srt())
            rows=service.parse_srt(srt())
            groups=sem.plan(rows)
            self.assertEqual(len(groups),23)
            for group in groups[:6]:
                key='%05d-%05d'%(group[0][0],group[-1][0])
                for n in (1,2,3):
                    path=folder/'attempts'/(key+'-'+str(n)+'.json')
                    core.save(path,{'ids':[x[0] for x in group],
                                    'error':'RuntimeError: Output length cap'})
            for group in groups[6:8]:
                path=old.unit_file(folder,group)
                core.save(path,{
                    'schema':old.SCHEMA,'source_sha':lab.sha(srt()),
                    'model_id':core.MODEL_ID,'pipeline_sha':old.pipeline_sha(),
                    'unit_sha':sem.unit_sha(group),'ids':[x[0] for x in group],
                    'translations':{str(x[0]):'日本語の文章です。' for x in group},
                    'attempt':1,
                })
            self.entries[episode]={
                'episode':episode,'source_path':str(source),
                'source_sha':lab.sha(srt()),'count':len(rows)}
            baseline_folder=self.recovery_state/'episodes'/episode
            baseline_folder.mkdir(parents=True)
            baseline=service.render_srt(rows,{
                str(x[0]):'元の日本語の字幕です。' for x in rows})
            (baseline_folder/'pilot-recovered.ja.srt').write_bytes(baseline)
        core.save(self.original_state/'manifest.json',{
            'schema':old.SCHEMA,'pipeline_sha':old.pipeline_sha(),
            'model':core.MODEL,'model_id':core.MODEL_ID,
            'profile_sha':lab.sha(self.profile.read_bytes()),
            'episodes':[self.entries[x] for x in lab.EPISODES],
        })
        self.before={str(p):p.read_bytes() for p in
                     self.original_state.rglob('*') if p.is_file()}
        self.calls=[]

    def fake(self,msg,mode):
        body=msg[1]['content'].split('[SOURCE_CUES]\n',1)[1].split(
            '\n[/SOURCE_CUES]',1)[0]
        numbers=[line.split('|',1)[0].strip() for line in body.splitlines()]
        self.calls.append((mode,tuple(numbers)))
        val='短い日本語の言葉です。'
        content=json.dumps({cid:val for cid in numbers},ensure_ascii=False) if mode=='json' else (
            '\n'.join(cid+' | '+val for cid in numbers))
        return {'content':content,'done_reason':'stop','eval_count':len(content),
                'prompt_eval_count':120,'total_duration_ns':25000000}

    def sample(self):
        return lab.freeze(self.state,self.original_state,self.profile)

    def experiment(self,ask=None):
        return lab.run(1,state=self.state,original_state=self.original_state,
                       profile=self.profile,ask=ask or self.fake,base=self.lock_root)

    def test_deterministic_balanced_24_utterances_and_no_source_writes(self):
        identity,source_rows=self.sample()
        self.assertEqual(len(identity['selected']),24)
        self.assertEqual({x['episode'] for x in identity['selected']},set(lab.EPISODES))
        for ep in lab.EPISODES:
            for typ in ('formerly_failed','never_attempted'):
                items=[x for x in identity['selected'] if
                       x['episode']==ep and x['stratum']==typ]
                self.assertEqual(len(items),4)
                for item in items:
                    self.assertEqual(len(lab.group_for(item,source_rows[ep])),2)
        before=(self.state/'selection.json').read_bytes()
        again,_=self.sample()
        self.assertEqual(identity,again)
        self.assertEqual(before,(self.state/'selection.json').read_bytes())
        self.assertEqual(self.before,{str(p):p.read_bytes() for p in
                          self.original_state.rglob('*') if p.is_file()})

    def test_both_formats_same_model_valid_parse_and_summary(self):
        result=self.experiment()
        self.assertEqual(result['completed_calls'],48)
        self.assertEqual(result['expected_calls'],48)
        self.assertEqual(len(self.calls),48)
        for stratum in ('formerly_failed','never_attempted'):
            for mode in lab.VARIANTS:
                x=result['by_stratum_and_format'][stratum][mode]
                self.assertEqual(x['attempted'],12)
                self.assertEqual(x['valid'],12)
                self.assertEqual(x['failed'],0)
        self.assertEqual(self.before,{str(p):p.read_bytes() for p in
                          self.original_state.rglob('*') if p.is_file()})
        self.assertEqual(list(self.state.rglob('*.srt')),[])
        count=len(self.calls)
        again=self.experiment()
        self.assertEqual(again,result)
        self.assertEqual(len(self.calls),count)
        self.assertEqual(self.calls[0][0],'json')
        self.assertEqual(self.calls[2][0],'lines')

    def test_malformed_numbered_lines_and_cue_mapping_are_blocked(self):
        group=sem.plan(service.parse_srt(srt()))[0]
        expected='%d | 日本語です。\n%d | こちらも日本語です。'%(group[0][0],group[1][0])
        self.assertEqual(len(lab.validate(expected,group,'lines')),2)
        for x in ('%d | 日本語です。'%group[0][0],
                  '%d | 日本語です。\n%d | 日本語です。'%(group[1][0],group[0][0]),
                  '~~~plaintext\n'+expected+'\n~~~',
                  expected+'\n999 | 余計な文章です。'):
            with self.assertRaises(ValueError):
                lab.validate(x,group,'lines')
        with self.assertRaises(Exception):
            lab.validate('{"1":"日本語です。"}',group,'json')

    def test_length_cap_json_vs_valid_lines_is_recorded_privately(self):
        identity,rows=self.sample()
        item=identity['selected'][0]
        group=lab.group_for(item,rows[item['episode']])
        def fake_caps(msg,mode):
            x=self.fake(msg,mode)
            if mode=='json':
                x['done_reason']='length'
            return x
        json_out=lab.run_one(self.state,item,group,'json','{}',fake_caps)
        lines_out=lab.run_one(self.state,item,group,'lines','{}',fake_caps)
        self.assertEqual(json_out['failure_category'],'length_cap')
        self.assertEqual(lines_out['status'],'valid')
        self.assertEqual(json_out['status'],'failed')
        prior=len(self.calls)
        self.assertEqual(lab.run_one(self.state,item,group,'json','{}',fake_caps),
                         json_out)
        self.assertEqual(len(self.calls),prior)
        self.assertIn('raw_private',json_out)
        self.assertNotIn('日本語',str(lab.report(self.state,identity)))

    def test_saved_state_fails_closed_after_changed_source_or_code(self):
        self.sample()
        with patch.object(lab,'file_code_sha',return_value='new-revision'):
            with self.assertRaisesRegex(RuntimeError,'differs'):
                self.sample()
        entry=self.entries['S19E10']
        source=Path(entry['source_path'])
        source.write_bytes(source.read_bytes().replace(b'the new plan',b'an old plan'))
        with self.assertRaisesRegex(RuntimeError,'source hash mismatch'):
            self.sample()

    def test_export_private_balanced_pairs_and_recovered_baseline(self):
        self.experiment()
        out=io.BytesIO()
        stats=lab.private_export(self.state,self.original_state,
                                 self.recovery_state,self.profile,out)
        self.assertEqual(stats['completed_calls'],48)
        with tarfile.open(fileobj=io.BytesIO(out.getvalue()),mode='r:gz') as archive:
            names=archive.getnames()
            self.assertEqual(names,['private_24_group_bilingual_review.json'])
            payload=json.load(archive.extractfile(names[0]))
        self.assertEqual(len(payload['groups']),24)
        for item in payload['groups']:
            self.assertEqual(set(item['outputs']),set(lab.VARIANTS))
            self.assertTrue(all(c['baseline_ja']=='元の日本語の字幕です。'
                                for c in item['cues']))
            self.assertTrue(all(v['status']=='valid'
                                for v in item['outputs'].values()))
        self.assertNotIn(str(self.original_state),str(payload))

    def test_reject_private_export_if_missing_calls_or_bad_baseline(self):
        self.sample()
        with self.assertRaisesRegex(RuntimeError,'comparison incomplete'):
            lab.private_export(self.state,self.original_state,
                               self.recovery_state,self.profile,io.BytesIO())
        self.experiment()
        baseline=self.recovery_state/'episodes'/'S19E10'/'pilot-recovered.ja.srt'
        baseline.write_bytes(baseline.read_bytes().replace(
            b'00:00:00,000',b'00:00:01,000'))
        with self.assertRaisesRegex(RuntimeError,'timing differs'):
            lab.private_export(self.state,self.original_state,
                               self.recovery_state,self.profile,io.BytesIO())

    def test_same_generation_budget_and_json_only_structural_constraint(self):
        payloads=[]
        def opener(request,timeout=240):
            payloads.append(json.loads(request.data.decode('utf8')))
            return io.BytesIO(json.dumps({
                'message':{'content':'日本語です。'},
                'done_reason':'stop','eval_count':14,'prompt_eval_count':38,
                'total_duration':1000}).encode())
        for mode in lab.VARIANTS:
            response=lab.model_call([{'role':'user','content':'Synthetic'}],
                                    mode,opener)
            self.assertEqual(response['eval_count'],14)
        self.assertEqual(payloads[0]['model'],core.MODEL)
        self.assertEqual(payloads[1]['model'],core.MODEL)
        self.assertEqual(payloads[0]['options'],payloads[1]['options'])
        self.assertEqual(payloads[0]['options']['num_predict'],450)
        self.assertEqual(payloads[0]['format'],'json')
        self.assertNotIn('format',payloads[1])

    def test_wrappers_no_production_mutations(self):
        base=Path(__file__).resolve().parent/'tools'
        for script in ('run_utterance_formatlab_012.sh',
                       'collect_utterance_formatlab_012.sh'):
            path=base/script
            result=subprocess.run(['bash','-n',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            contents=path.read_text(encoding='utf8')
            self.assertNotIn('docker restart',contents)
            self.assertNotIn('systemctl',contents)
            self.assertNotIn('scp -q service.py',contents)
        self.assertIn('tools/utterance_formatlab_012.py',
                      (base/'run_utterance_formatlab_012.sh').read_text())


if __name__=='__main__':
    unittest.main()
