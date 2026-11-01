#!/usr/bin/env python3
"""SubHub 1.0: isolated SQLite subtitle coordinator. Standard library runtime.

The legacy Gemma and HY adapters remain in ~/bruiser-pilot. This module does
not modify old jobs or their checkpoints. Never imports/sends full movie media.
"""
from __future__ import annotations
import contextlib
import csv
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unicodedata
from urllib.request import Request, urlopen

GEMMA = 'gemma4:e4b-it-qat'
HY = 'kaelri/hy-mt2:1.8b'
OLLAMA = 'http://127.0.0.1:11434'
JP_RE = re.compile(r'[\u3040-\u30ff\u3400-\u9fff]')
SRT_TIME = r'(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{1,3}'
HEADER = re.compile(rf'(?m)^[ \t]*(\d+)[ \t]*\n[ \t]*({SRT_TIME}[ \t]*-->[ \t]*{SRT_TIME}[^\n]*)')
NEGATIONS = re.compile(r"\b(no|not|never|can't|cannot|couldn't|wouldn't|don't|doesn't|didn't|won't|isn't|aren't|without|anybody|someone|nothing)\b",re.I)
STAGE_MAX = 2_000_000
SOURCE_ROOTS = (Path('/mnt/BigDisk/Video'),Path('/mnt/2TB/Plex Expansion'))
OLD_WORKER_LOCK = Path.home()/'bruiser-pilot/subhub-household/.runner.lock'
class ThermalHold(RuntimeError):pass


def sha(data:bytes)->str: return hashlib.sha256(data).hexdigest()
def stamp(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def millis(s):
    m=re.match(r'(?:(\d+):)?(\d{2}):(\d{2})[,.](\d{1,3})$',s.strip())
    if not m:raise ValueError('Invalid SRT timestamp: '+s)
    return ((int(m[1] or 0)*3600+int(m[2])*60+int(m[3]))*1000 + int(m[4].ljust(3,'0')))


def parse_srt(data:bytes):
    """Match legacy numbered SRT, allow empty numbered placeholders; reject corrupt cues."""
    if len(data)>STAGE_MAX or len(data)<5:raise ValueError('Source SRT size invalid')
    text=data.decode('utf-8-sig').replace('\r\n','\n').replace('\r','\n')
    hits=list(HEADER.finditer(text))
    if not hits:raise ValueError('No SRT numbered timestamps')
    rows=[];prev=0
    for n,m in enumerate(hits):
        ident=int(m[1])
        if ident!=prev+1:raise ValueError(f'Expected cue {prev+1}, got {ident}')
        prev=ident
        end=hits[n+1].start() if n+1<len(hits) else len(text)
        body=re.sub(r'\n[ \t]*\n+','\n',text[m.end():end]).strip()
        if not body:continue
        timing=m[2].strip()
        parts=re.split(r'[ \t]*-->[ \t]*',timing, maxsplit=1)
        if len(parts)!=2:raise ValueError('Broken timing')
        # A few sources may have positional suffix after the end timestamp.
        first=parts[1].split()[0]
        a,b=millis(parts[0]),millis(first)
        if b<=a or a<0:raise ValueError(f'Cue {ident}: invalid time range')
        rows.append((ident,timing,a,b,body))
    if not rows:raise ValueError('SRT contains no dialogue')
    if len(rows)>12000:raise ValueError('Unusually many subtitle cues')
    return rows


def render_srt(rows,translations):
    if set(translations)!={str(r[0]) for r in rows}:raise ValueError('Incomplete translation')
    return ('\n\n'.join(f'{i}\n{r[1]}\n{translations[str(r[0])]}' for i,r in enumerate(rows,1))+'\n').encode('utf-8')


def render_clip(rows):
    """Render SQLite cues as valid locally numbered SRT for the legacy parser.

    SQLite rows start with job_id: positional indices silently produced
    'job ID / cue ID / end_ms' instead of SRT. Use named fields and local
    cue numbers, then restore original IDs when saving translations.
    """
    return ('\n\n'.join(f"{n}\n{r['timing']}\n{r['english']}" for n,r in enumerate(rows,1))+'\n').encode('utf-8')


def atomic(path:Path, data:bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.'+path.name+'.')
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        with contextlib.suppress(FileNotFoundError):os.unlink(temp)


class Store:
    def __init__(self,root:Path):
        self.root=root
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db=root/'jobs.sqlite3'
        self.cn=sqlite3.connect(self.db,timeout=30,isolation_level=None)
        self.cn.row_factory=sqlite3.Row
        self.cn.execute('PRAGMA busy_timeout=30000')
        self.cn.execute('PRAGMA journal_mode=WAL')
        self.cn.execute('PRAGMA foreign_keys=ON')
        self.cn.executescript('''
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, video TEXT NOT NULL, source_path TEXT NOT NULL,
          source_sha TEXT NOT NULL, source_cues INTEGER NOT NULL,
          audio_lang TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'horror',
          priority INTEGER NOT NULL DEFAULT 100, status TEXT NOT NULL DEFAULT 'queued',
          published_sha TEXT, last_error TEXT, created TEXT NOT NULL,
          updated TEXT NOT NULL, UNIQUE(video,source_sha));
        CREATE TABLE IF NOT EXISTS cues (
          job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
          cue_id INTEGER NOT NULL, timing TEXT NOT NULL,
          start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL, english TEXT NOT NULL,
          japanese TEXT, hy_back TEXT, failed INTEGER NOT NULL DEFAULT 0,
          last_error TEXT, PRIMARY KEY(job_id,cue_id));
        CREATE TABLE IF NOT EXISTS events (
          n INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
          job_id TEXT, action TEXT NOT NULL, detail TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS jobs_priority ON jobs(priority,created);
        CREATE INDEX IF NOT EXISTS events_time ON events(n);
        CREATE TABLE IF NOT EXISTS phase_stats (
          n INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
          phase TEXT NOT NULL, elapsed_s REAL NOT NULL,
          gpu_Wh_est REAL, at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS metrics (
          n INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
          phase TEXT NOT NULL, job_id TEXT,
          gpu_pct REAL, gpu_c REAL, gpu_w REAL, vram_mb REAL, cpu_c REAL);
        ''')

    def event(self,jid,action,detail):
        self.cn.execute('INSERT INTO events(at,job_id,action,detail) VALUES(?,?,?,?)', (stamp(),jid,action,str(detail)[:300]))

    def add(self,jid,video,data,audio,scope='horror',priority=100,prior=None):
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,100}',jid):raise ValueError('Invalid job ID')
        rows=parse_srt(data)
        target=self.root/'sources'/f'{jid}.en.srt'
        old=self.cn.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if old:
            if old['source_sha']!=sha(data) or old['video']!=str(video):
                raise RuntimeError('Job identity exists with a different video/source')
            return False
        if target.exists() and sha(target.read_bytes())!=sha(data):raise RuntimeError('Staged source already exists with different hash')
        if not target.exists():atomic(target,data)
        self.cn.execute('BEGIN IMMEDIATE')
        try:
            self.cn.execute('INSERT INTO jobs(id,video,source_path,source_sha,source_cues,audio_lang,scope,priority,status,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (jid,str(video),str(target),sha(data),len(rows),audio,scope,priority,'queued',stamp(),stamp()))
            self.cn.executemany('INSERT INTO cues(job_id,cue_id,timing,start_ms,end_ms,english) VALUES(?,?,?,?,?,?)',
                ((jid,r[0],r[1],r[2],r[3],r[4]) for r in rows))
            if prior:
                for i,t in prior.items():
                    if isinstance(t,str) and t.strip() and JP_RE.search(t):
                        self.cn.execute('UPDATE cues SET japanese=? WHERE job_id=? AND cue_id=?',(t,jid,int(i)))
            self.event(jid,'imported',f'{len(rows)} cues; reused {len(prior or {})} legacy translations')
            self.cn.execute('COMMIT')
        except Exception:
            self.cn.execute('ROLLBACK')
            raise
        return True

    def jobs(self):
        return self.cn.execute('''SELECT j.*,COUNT(c.cue_id) n,
          SUM(c.japanese IS NOT NULL) ja, SUM(c.hy_back IS NOT NULL) hy,
          SUM(c.japanese IS NULL AND c.failed>=5) held
          FROM jobs j JOIN cues c ON j.id=c.job_id
          GROUP BY j.id ORDER BY j.priority,j.created''').fetchall()

    def rows(self,jid):return self.cn.execute('SELECT * FROM cues WHERE job_id=? ORDER BY cue_id',(jid,)).fetchall()
    def record_japanese(self,jid,items):
        self.cn.execute('BEGIN IMMEDIATE')
        try:
            for i,t in items.items():
                self.cn.execute('UPDATE cues SET japanese=?,last_error=NULL WHERE job_id=? AND cue_id=? AND japanese IS NULL',(t,jid,int(i)))
            self.event(jid,'checkpoint',f'{len(items)} new Japanese cues')
            self.cn.execute('UPDATE jobs SET updated=? WHERE id=?',(stamp(),jid))
            self.cn.execute('COMMIT')
        except Exception:
            self.cn.execute('ROLLBACK');raise
    def fail(self,jid,ids,error,terminal=False):
        # Batch-level errors are not counted as per-cue failures. Only a
        # separately attempted singleton advances the cue's retry budget.
        self.cn.execute('BEGIN IMMEDIATE')
        try:
            if terminal:
                self.cn.executemany('UPDATE cues SET failed=failed+1,last_error=? WHERE job_id=? AND cue_id=? AND japanese IS NULL',
                                    ((str(error)[:220],jid,int(i)) for i in ids))
            self.event(jid,'gemma_retry' if not terminal else 'cue_failed',f'{ids[0]}-{ids[-1]}: {str(error)[:150]}')
            self.cn.execute('COMMIT')
        except Exception:
            self.cn.execute('ROLLBACK');raise
    def phase(self,jid,phase,elapsed,gpu_wh=None):
        self.cn.execute('INSERT INTO phase_stats(job_id,phase,elapsed_s,gpu_Wh_est,at) VALUES(?,?,?,?,?)',
                        (jid,phase,round(elapsed,3),None if gpu_wh is None else round(gpu_wh,5),stamp()))
    def state(self,jid,status,error=None):
        self.cn.execute('UPDATE jobs SET status=?,last_error=?,updated=? WHERE id=?',(status,error,stamp(),jid))
        self.event(jid,status,error or status)


def secure_video(video:Path):
    """Allow only concrete original video files in two known media roots."""
    if video.is_symlink() or not video.is_file():raise RuntimeError('Video missing or symlink')
    resolved=video.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in SOURCE_ROOTS):
        raise RuntimeError('Video outside approved media roots')


def audio_language(video:Path):
    p=subprocess.run(['ffprobe','-v','error','-select_streams','a',
       '-show_entries','stream=index:stream_tags=language:stream_disposition=default',
       '-of','json',str(video)],capture_output=True,text=True,timeout=30)
    if p.returncode: return 'unknown'
    streams=json.loads(p.stdout).get('streams',[])
    primary=next((s for s in streams if s.get('disposition',{}).get('default')==1),streams[0] if streams else {})
    lang=str(primary.get('tags',{}).get('language','')).lower().strip()
    return 'eng' if lang in ('eng','en','english') else ('unknown' if lang in ('','und','mul','unknown') else lang)


def import_legacy(store:Store,base:Path,limit:int=10,prioritize=(),include_unverified=False):
    """Copy, never edit, the existing queue and checkpoints. No model calls."""
    jpath=base/'subhub-household/jobs.json'
    cfg=json.loads(jpath.read_text(encoding='utf8'))
    jobs=[j for j in cfg['jobs'] if j.get('enabled') and j.get('learning_scope')=='horror' and j.get('host_video_path')]
    lookup={j['id']:j for j in jobs}
    preferred=[]
    for key in prioritize:
        matched=[j for j in jobs if key.lower() in j['id'].lower()]
        preferred+=matched
    jobs=list({j['id']:j for j in preferred+jobs}.values())
    added=held=skipped=0
    for j in jobs:
        if added+skipped>=limit:break
        jid=j['id'];video=Path(j['host_video_path'])
        try:
            secure_video(video)
            lang=audio_language(video)
            if lang!='eng' and not include_unverified:
                held+=1;continue
            proc=subprocess.run(['docker','exec',j['container'],'cat',j['source']],capture_output=True,timeout=40)
            if proc.returncode:raise RuntimeError('Staged English file not accessible via Sublarr container')
            data=proc.stdout
            if 'source_sha256' in j and sha(data)!=j['source_sha256']:raise RuntimeError('Legacy source hash mismatch')
            prior={}
            legacy_state=base/'subhub-household'/jid/'state.json'
            if legacy_state.exists():
                old=json.loads(legacy_state.read_text(encoding='utf8'))
                if old.get('source_sha256')!=sha(data):raise RuntimeError('Legacy checkpoint source mismatch')
                prior=old.get('translation',{})
            if store.add(jid,video,data,lang,priority=(10 if j in preferred else 100),prior=prior):
                added+=1;print(f'IMPORTED {jid} ({len(parse_srt(data))} cues; reused {len(prior)} existing)',flush=True)
            else:skipped+=1
        except Exception as ex:
            held+=1;store.event(jid,'import_hold',f'{type(ex).__name__}: {ex}')
            print(f'HOLD {jid}: {type(ex).__name__}: {str(ex)[:130]}',flush=True)
    print(f'IMPORT RESULT: {added} new, {skipped} already present, {held} held for review')
    return added


def recall_memory(base:Path,scope:str,rows):
    p=base/'subhub-household/approved-memory.jsonl'
    if not p.exists():return ''
    all_en=' '.join(r['english'] for r in rows).casefold()
    terms=set(re.findall(r'[a-z]{3,}',all_en))
    matches=[]
    for line in p.read_text(encoding='utf8').splitlines():
        try:x=json.loads(line)
        except ValueError:continue
        if x.get('approved') is not True or x.get('scope') not in (scope,'global'):continue
        en=x.get('english','')
        if not isinstance(en,str):continue
        overlap=len(set(re.findall(r'[a-z]{3,}',en.casefold()))&terms)
        if overlap>=2 or (en and en.casefold() in all_en):matches.append((overlap,x))
    matches.sort(key=lambda v:v[0],reverse=True)
    return '\n'.join('Approved EN: '+v.get('english','')+'\nApproved JA: '+v.get('japanese','') for _,v in matches[:6])


def translation_call(base,selected,memory,model=GEMMA):
    """Adapter to the proven existing bruiser_auto prompt, with no private APIs."""
    if str(base) not in sys.path:sys.path.insert(0,str(base))
    import bruiser_auto as core
    with tempfile.TemporaryDirectory(prefix='subhub10-') as td:
        path=Path(td)/'clip.srt'
        path.write_bytes(render_clip(selected))
        cues=core.parse_srt(str(path))
        local_ids=list(range(1,len(selected)+1))
        if [c.id for c in cues]!=local_ids:raise RuntimeError('Legacy prompt parser mismatch')
        system,payload=core.build_prompt(cues,0,len(cues)-1,memory)
        result=core.call_ollama(OLLAMA,model,system,payload,local_ids,240)
        # The model sees 1..N local IDs. Persist against the original cue
        # IDs, which may be 509, 510 or non-contiguous after empty sources.
        return {str(r['cue_id']):core.preserve_tags(cues[n].text,result[n+1]) for n,r in enumerate(selected)}


def acceptable_ja(text,english=None):
    """Accept Japanese script plus a narrow set of legitimate subtitle exceptions.

    Roman initials and numeral countdowns may be correct Japanese subtitles.
    Without the source text these exceptions are intentionally rejected, so
    a model cannot pass off ordinary untranslated English as localization.
    """
    if not isinstance(text,str) or not 0<len(text.strip())<800:return False
    bad=('<tool_call','<｜hy_', '[Translation note]', '訳注:',
         '翻訳の説明', '注：この', 'Explanation:', 'As an AI', 'I translated', 'Note:')
    if any(v in text for v in bad):return False
    if JP_RE.search(text):return True
    if not isinstance(english,str):return False
    en=unicodedata.normalize('NFKC',english).strip()
    ja=unicodedata.normalize('NFKC',text).strip()
    # A, B, RC etc. can be kept as initials; EMS or full English speech cannot.
    raw_en=re.sub(r'[\s.!?。！？…]+','',en)
    raw_ja=re.sub(r'[\s.!?。！？…]+','',ja)
    if re.fullmatch(r'[A-Z]{1,2}',raw_en) and raw_en==raw_ja:
        return True
    words={'zero':0,'one':1,'two':2,'three':3,'four':4,'five':5,
           'six':6,'seven':7,'eight':8,'nine':9,'ten':10}
    source_tokens=re.findall(r'[A-Za-z]+|\d+',en)
    if not source_tokens or not all(t.isdigit() or t.lower() in words for t in source_tokens):
        return False
    source_nums=[int(t) if t.isdigit() else words[t.lower()] for t in source_tokens]
    if not re.fullmatch(r'[\s\d,、.。…-]+',ja):return False
    target_nums=[int(t) for t in re.findall(r'\d+',ja)]
    return source_nums==target_nums

def single_direct(base,source,memory):
    """Independent singleton fallback when structured prompt repeatedly fails.

    No context-cue translations are requested; only a Japanese string for the
    given source cue. This preserves timecode identity and cannot shift IDs.
    """
    content=(f'Previous accepted localization examples (style only):\n{memory[:1400]}\n\n' if memory else '')
    content+='Translate ONLY the following English subtitle cue into natural, concise Japanese. '
    content+='Do not invent dialogue, notes or speaker identities. Preserve negation, numbers, and line breaks where practical. '
    content+='Return ONLY Japanese subtitle text, no code fences or explanation.\n\n'+source['english']
    body={'model':GEMMA,'stream':False,'think':False,
          'messages':[{'role':'user','content':content}],
          'options':{'temperature':0,'num_ctx':2048,'num_predict':350}}
    request=Request(OLLAMA+'/api/chat', data=json.dumps(body,ensure_ascii=False).encode('utf8'),
                    headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=180) as resp:res=json.load(resp)
    if res.get('done_reason')=='length':raise ValueError('Singleton fallback truncated')
    answer=res.get('message',{}).get('content','').strip()
    if answer.startswith('```') and answer.endswith('```'):
        answer='\n'.join(answer.splitlines()[1:-1]).strip()
    if not acceptable_ja(answer,source['english']):raise ValueError('Invalid singleton fallback result')
    return answer


def translate_window(store:Store,base:Path,job,window,call=translation_call,max_attempts=2):
    """Divide failing request to 6/3/1. Complete cues checkpointed immediately.

    Per-cue failed count bounds repeats across processes. The worker never
    invents filler text or silently publishes a partial movie.
    """
    pending=[r for r in window if r['japanese'] is None and r['failed']<5]
    if not pending:return 0
    queue=[pending];saved=0
    while queue:
        part=queue.pop(0)
        fresh={r['cue_id']:r for r in store.rows(job['id'])}
        part=[fresh[r['cue_id']] for r in part if fresh[r['cue_id']]['japanese'] is None and fresh[r['cue_id']]['failed']<5]
        if not part:continue
        result=None;error=None
        for attempt in range(max_attempts if len(part)==1 else 1):
            try:
                result=call(base,part,recall_memory(base,job['scope'],part))
                break
            except Exception as ex:
                error=f'{type(ex).__name__}: {str(ex)[:140]}'
        if len(part)==1 and (result is None or not isinstance(result,dict) or not acceptable_ja(result.get(str(part[0]['cue_id'])),part[0]['english'])) and call is translation_call:
            try:
                direct=single_direct(base,part[0],recall_memory(base,job['scope'],part))
                result={str(part[0]['cue_id']):direct}
                error=None
            except Exception as ex:
                error=f'Singleton fallback {type(ex).__name__}: {str(ex)[:140]}'
        if result is not None:
            if not isinstance(result,dict):result={}
            good={str(r['cue_id']):result[str(r['cue_id'])] for r in part if str(r['cue_id']) in result and acceptable_ja(result[str(r['cue_id'])],r['english'])}
            if good:store.record_japanese(job['id'],good);saved+=len(good)
            remain=[r for r in part if str(r['cue_id']) not in good]
            if remain:error='Unusable/missing Japanese response'
            else:continue
        else:remain=part
        store.fail(job['id'],[r['cue_id'] for r in remain],error or 'invalid',terminal=len(remain)==1)
        # Split only missing cues, not the successful ones. No exponential runaways.
        if len(remain)>1:
            mid=max(1,len(remain)//2)
            queue=[remain[:mid],remain[mid:]]+queue
    return saved


def risk_hy_ids(rows,amount=48):
    """HY is independent and advisory; deterministic risk sample plus distribution."""
    if not rows:return []
    count=max(1,min(amount,len(rows)))
    ids={rows[round((len(rows)-1)*i/max(1,min(19,count-1)))] ['cue_id'] for i in range(min(20,count))}
    scores=[]
    for r in rows:
        en=r['english'];ja=r['japanese'] or ''
        score=4*bool(NEGATIONS.search(en))+3*(len(ja)>65)+2*any(x.isdigit() for x in en)
        score+=3*(en.count('\n')>1 and ja.count('\n')<1)
        scores.append((-score,r['cue_id']))
    for _,i in sorted(scores):
        if len(ids)>=count:break
        ids.add(i)
    return sorted(ids)


def hy_call(base:Path,japanese:str):
    if str(base) not in sys.path:sys.path.insert(0,str(base))
    import bruiser_hy_backtranslate_compare as hy
    return hy.query_ollama(OLLAMA,HY,hy.clean_ja(japanese),65)


def ollama_loaded():
    with urlopen(OLLAMA+'/api/ps',timeout=5) as resp:return json.load(resp).get('models',[])


def release_gemma():
    # This is a controlled model unload, not stopping the Ollama service.
    data=json.dumps({'model':GEMMA,'keep_alive':0,'prompt':''}).encode()
    try:
        with urlopen(Request(OLLAMA+'/api/generate',data=data,headers={'Content-Type':'application/json'}),timeout=12) as r:r.read()
    except Exception:return False
    return True


def hy_gpu_ready():
    """Decline HY rather than doing an accidental full CPU-bound film pass."""
    try:
        active=ollama_loaded()
        for m in active:
            if GEMMA.split(':')[0] in m.get('name',''):
                return False,'Gemma remains resident'
        # Ollama /api/ps size_vram can be inspected once HY is resident;
        # absent HY means admission requires a fresh load, not guaranteed GPU.
        for m in active:
            if m.get('name','').startswith('kaelri/hy-mt2'):
                size=m.get('size',0);vram=m.get('size_vram',0)
                if size and vram/size < .8:return False, f'HY GPU offload only {vram/size:.0%}'
        return True,'available'
    except (OSError,ValueError):return False,'Ollama status unknown'


def translate_job(store:Store,base:Path,job,deadline,call=translation_call,batch=12,stop_check=None,thermal_check=None):
    if job['audio_lang']!='eng':store.state(job['id'],'hold','Audio language not verified English');return
    data=Path(job['source_path']).read_bytes()
    if sha(data)!=job['source_sha']:store.state(job['id'],'hold','Source changed');return
    rows=store.rows(job['id'])
    if len(rows)!=job['source_cues']:store.state(job['id'],'hold','Cue count changed');return
    store.state(job['id'],'translating')
    ids=[r['cue_id'] for r in rows]
    while time.monotonic()<deadline:
        if stop_check and stop_check():break
        if thermal_check:thermal_check()
        curr=store.rows(job['id'])
        undone=[r for r in curr if r['japanese'] is None and r['failed']<5]
        if not undone:break
        start=undone[0]['cue_id'];window=[]
        for r in curr[ids.index(start):]:
            if r['japanese'] is not None or r['failed']>=5 or (window and r['cue_id']!=window[-1]['cue_id']+1):break
            window.append(r)
            if len(window)>=batch:break
        if not window:break
        result=translate_window(store,base,job,window,call)
        done=store.cn.execute('SELECT COUNT(*) FROM cues WHERE job_id=? AND japanese IS NOT NULL',(job['id'],)).fetchone()[0]
        print(f"GEMMA {job['id']}: {done}/{len(rows)}, latest {start}-{window[-1]['cue_id']} (+{result})",flush=True)
    done=store.cn.execute('SELECT COUNT(*) FROM cues WHERE job_id=? AND japanese IS NOT NULL',(job['id'],)).fetchone()[0]
    if done==len(rows):
        store.state(job['id'],'translated');make_review_export(store,job['id'])
    else:
        blocked=store.cn.execute('SELECT COUNT(*) FROM cues WHERE job_id=? AND japanese IS NULL AND failed>=5',(job['id'],)).fetchone()[0]
        store.state(job['id'],'needs_review' if blocked else 'queued',f'{done}/{len(rows)} translated; {blocked} isolated failures')


def make_review_export(store:Store,jid):
    rows=store.rows(jid);out=store.root/'review'/f'{jid}.csv'
    buf=io.StringIO();writer=csv.writer(buf)
    writer.writerow(['cue_id','timing','english','japanese','hy_back','editor_approved_ja'])
    for r in rows:writer.writerow([r['cue_id'],r['timing'],r['english'],r['japanese'] or '',r['hy_back'] or '',''])
    atomic(out,buf.getvalue().encode('utf8'))
    return out


def qa_job(store:Store,base:Path,job,deadline,hy_function=hy_call,count=48,stop_check=None):
    rows=store.rows(job['id'])
    if not all(r['japanese'] for r in rows):return
    needed=risk_hy_ids(rows,count)
    if not needed:return
    release_gemma()
    ok,why=hy_gpu_ready()
    if not ok:
        store.event(job['id'],'hy_deferred',why)
        return
    for i in needed:
        if time.monotonic()>=deadline or (stop_check and stop_check()):break
        ok,reason=hy_gpu_ready()
        if not ok:
            store.event(job['id'],'hy_deferred',reason)
            print('HY HOLD: '+reason,flush=True)
            break
        r=next(x for x in store.rows(job['id']) if x['cue_id']==i)
        if r['hy_back']:continue
        try:
            back=hy_function(base,r['japanese'])
            if not back or not isinstance(back,str):raise ValueError('Empty back-translation')
            store.cn.execute('UPDATE cues SET hy_back=? WHERE job_id=? AND cue_id=?',(back,job['id'],i))
        except Exception as exc:
            store.event(job['id'],'hy_error',f'{i}: {str(exc)[:150]}')
        if i%12==0:print(f'HY {job["id"]}: {i} cue index inspected',flush=True)
    make_review_export(store,job['id'])
    store.event(job['id'],'hy_done',f'{sum(r["hy_back"] is not None for r in store.rows(job["id"]))}/{len(needed)} target cues done')


def validate_publish(store:Store,job):
    video=Path(job['video']);secure_video(video)
    if job['audio_lang']!='eng' or audio_language(video)!='eng':raise RuntimeError('English-primary audio no longer verified')
    source=Path(job['source_path']).read_bytes()
    if sha(source)!=job['source_sha']:raise RuntimeError('English source fingerprint changed')
    parsed=parse_srt(source)
    cues=store.rows(job['id'])
    if len(parsed)!=len(cues):raise RuntimeError('Source cue count changed')
    if any(not r['japanese'] or not acceptable_ja(r['japanese'],r['english']) for r in cues):raise RuntimeError('Incomplete or malformed Japanese')
    if any((a[0],a[1],a[2],a[3],a[4])!=(b['cue_id'],b['timing'],b['start_ms'],b['end_ms'],b['english']) for a,b in zip(parsed,cues)):
        raise RuntimeError('Source subtitle time/text mismatch')
    return video,cues


def publish_job(store:Store,job,apply=False):
    """Create-only Japanese sidecar; preserve all pre-existing subtitle files.

    An existing independent Japanese or human/editorial subtitle is a reason
    to hold *publication*, not erase, archive, overwrite, or supersede it.
    This intentionally leaves legacy Bruiser draft tracks untouched.
    """
    video,rows=validate_publish(store,job)
    result=render_srt([(r['cue_id'],r['timing'],r['start_ms'],r['end_ms'],r['english']) for r in rows],
                      {str(r['cue_id']):r['japanese'] for r in rows})
    target=video.with_name(video.stem+'.Bruiser Japanese.ja.srt')
    if target.is_symlink():
        raise RuntimeError('Existing Bruiser Japanese path is a symlink; publication refused')
    if target.exists() and (not target.is_file() or target.read_bytes()!=result):
        raise RuntimeError('Existing Bruiser Japanese differs; manual editorial promotion required')

    # Explicitly recognize older hand-edited subtitles, not just our current
    # output name. Matching is restricted to sidecars of this one film.
    # Never follow any link or touch an existing editorial/JA track.
    prefix=video.stem.casefold()+'.'
    protected=[]
    for sidecar in video.parent.iterdir():
        name=sidecar.name.casefold()
        if sidecar==target or not name.startswith(prefix) or not name.endswith('.srt'):
            continue
        suffix=name[len(prefix):]
        japanese_tag = re.search(r'(^|[._\[\] -])(?:ja|jp|jpn|japanese)(?=$|[._\[\] -])', suffix)
        if 'editorial' in suffix or japanese_tag:
            if sidecar.exists() or sidecar.is_symlink():
                protected.append(sidecar.name)
    if protected:
        raise RuntimeError('Existing Japanese/editorial sidecar(s) require review; no automatic publication: '
                           + ', '.join(sorted(protected)[:3]))
    if not apply:
        return (target,'dry-run')
    if not target.exists():
        # O_EXCL refuses an unanticipated concurrent file creation. No
        # archival or deletion of pre-existing subtitles is performed.
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
        with os.fdopen(fd,'wb') as out:
            out.write(result);out.flush();os.fsync(out.fileno())
    store.cn.execute('UPDATE jobs SET published_sha=?,status=?,updated=? WHERE id=?',
                     (sha(result),'published',stamp(),job['id']))
    store.event(job['id'],'published','Japanese-only sidecar; existing subtitle files preserved')
    return (target,'published')


def summary(store:Store):
    jobs=store.jobs();out={'jobs':[], 'completed':0, 'total':len(jobs)}
    for j in jobs:
        row={'id':j['id'],'state':j['status'],'ja':j['ja'] or 0,'hy':j['hy'] or 0,'total':j['n'],
             'isolated_failures':j['held'] or 0,'audio':j['audio_lang'],'priority':j['priority']}
        out['jobs'].append(row)
        if j['status']=='published':out['completed']+=1
    return out
