#!/usr/bin/env python3
"""SubHub 1.0 — isolated coordinator, no changes to legacy installs.

Run `python3 main.py --help` for the supported commands. Runtime stdlib only.
"""
from __future__ import annotations
import argparse
import contextlib
import csv
import datetime as dt
import fcntl
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import html
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.request import Request,urlopen
import service as s

BASE=Path.home()/'bruiser-pilot'
ROOT=BASE/'subhub1-state'
PRICE=35.0


def command(argv,timeout=5):
    try:
        p=subprocess.run(argv,capture_output=True,text=True,timeout=timeout)
        return p.stdout if p.returncode==0 else ''
    except (OSError,subprocess.TimeoutExpired):return ''


def cpu_temp():
    vals=[]
    for d in Path('/sys/class/hwmon').glob('hwmon*'):
        try:
            if (d/'name').read_text().strip() not in ('coretemp','k10temp','zenpower'):continue
            for p in d.glob('temp*_input'):
                v=int(p.read_text())/1000
                if 10<v<115:vals.append(v)
        except (OSError,ValueError):continue
    return max(vals,default=None)


def gpu():
    data=command(['nvidia-smi','--query-gpu=utilization.gpu,temperature.gpu,power.draw,memory.used',
                  '--format=csv,noheader,nounits'],timeout=7)
    try:return [float(x.strip()) for x in data.splitlines()[0].split(',')[:4]]
    except (ValueError,IndexError):return [None]*4


def rapl():
    for p in Path('/sys/class/powercap').glob('intel-rapl:*'):
        if p.name.count(':')!=1:continue
        e=p/'energy_uj'
        try:return (e,int(e.read_text()),int((p/'max_energy_range_uj').read_text()))
        except (OSError,ValueError):pass
    return (None,None,None)


class Meter:
    def __init__(self,root,ctx,interval=15):
        self.root=root;self.ctx=ctx;self.interval=interval;self.stopping=threading.Event()
        self.wall=time.monotonic();self.last=None;self.last_power=None
        self.wh=0.0;self.rapl_path,self.rapl_prev,self.rapl_max=rapl();self.rapl_wh=0.0
        self.max_gpu_temp=None;self.max_cpu_temp=None;self.max_power=None;self.count=0
        self.thread=threading.Thread(target=self.loop,daemon=True)
    def start(self):self.thread.start()
    def finish(self):self.stopping.set();self.thread.join(timeout=8);self.save();return self.report()
    def report(self):
        return {'seconds':round(time.monotonic()-self.wall,1),
          'gpu_Wh_estimate':round(self.wh,3),'cpu_RAPL_Wh_if_accessible':round(self.rapl_wh,3) if self.rapl_path else None,
          'peak_gpu_C':self.max_gpu_temp,'peak_cpu_C':self.max_cpu_temp,'peak_gpu_W':self.max_power,
          'samples':self.count,'indicative_gpu_plus_cpu_yen_at_35_kWh':round((self.wh+self.rapl_wh)*PRICE/1000,3),
          'caveat':'Excludes unmeasured motherboard, drives, PSU losses, cooling and baseline electricity; not a whole-PC energy meter'}
    def save(self):
        s.atomic(self.root/'hardware-summary.json',(json.dumps(self.report(),indent=2)+'\n').encode())
    def loop(self):
        p=self.root/'hardware.csv';p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('a',newline='',encoding='utf8') as f:
            wr=csv.writer(f)
            if f.tell()==0:wr.writerow(['time_utc','elapsed_s','phase','job','gpu_util_pct','gpu_C','gpu_W','vram_MiB','cpu_C','gpu_Wh','cpu_Wh'])
            while True:
                moment=time.monotonic();g=gpu();c=cpu_temp()
                if self.last is not None and self.last_power is not None and g[2] is not None:
                    self.wh+=((self.last_power+g[2])/2)*(moment-self.last)/3600
                self.last,self.last_power=moment,g[2]
                if self.rapl_path:
                    try:
                        nxt=int(self.rapl_path.read_text());delta=nxt-self.rapl_prev
                        if delta<0 and self.rapl_max:delta+=self.rapl_max
                        if 0<=delta<self.rapl_max:self.rapl_wh+=delta/3_600_000_000
                        self.rapl_prev=nxt
                    except (OSError,ValueError):pass
                if g[1] is not None:self.max_gpu_temp=max(g[1],self.max_gpu_temp or g[1])
                if g[2] is not None:self.max_power=max(g[2],self.max_power or g[2])
                if c is not None:self.max_cpu_temp=max(c,self.max_cpu_temp or c)
                self.count+=1
                wr.writerow([s.stamp(),round(moment-self.wall,1),self.ctx.get('phase',''),self.ctx.get('job',''),*g,c,round(self.wh,5),round(self.rapl_wh,5)]);f.flush()
                self.save()
                if self.stopping.wait(self.interval):break


def lockfiles(root):
    """Take *both* exclusive locks: no 1.0 overlap or legacy inference."""
    import contextlib
    @contextlib.contextmanager
    def held():
        root.mkdir(parents=True,exist_ok=True)
        handles=[]
        try:
            for p in [root/'run.lock',s.OLD_WORKER_LOCK]:
                p.parent.mkdir(parents=True,exist_ok=True)
                h=p.open('a+b');handles.append(h)
                try:fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:raise RuntimeError(f'Another worker holds {p}; no inference started')
            yield
        finally:
            for h in handles:
                with contextlib.suppress(OSError):fcntl.flock(h,fcntl.LOCK_UN)
                h.close()
    return held()


def publish_ready(store,job,allow):
    try:
        target,status=s.publish_job(store,job,apply=allow)
        print(f'PUBLISH {job["id"]}: {status} -> {target}',flush=True)
    except Exception as e:
        store.state(job['id'],'publish_hold',str(e)[:220])
        print(f'PUBLISH HOLD {job["id"]}: {type(e).__name__}: {e}',flush=True)


def thermal_guard(gpu_limit=82,cpu_limit=85):
    data=gpu();ct=cpu_temp()
    if data[1] is not None and data[1]>=gpu_limit:
        raise s.ThermalHold(f'GPU reached {data[1]} C (limit {gpu_limit})')
    if ct is not None and ct>=cpu_limit:
        raise s.ThermalHold(f'CPU reached {ct} C (limit {cpu_limit})')


def preflight_ollama(need_gemma=True):
    # Run before touching any source/job state, so missing models cannot
    # count as thousands of cue failures or trigger a CPU-only cascade.
    try:
        with urlopen(s.OLLAMA+'/api/tags',timeout=10) as response:
            available={m.get('name') for m in json.load(response).get('models',[])}
        if need_gemma and s.GEMMA not in available:
            raise RuntimeError(f'Gemma model not installed: {s.GEMMA}')
        active=s.ollama_loaded()
        other=[m.get('name') for m in active if m.get('name') not in (s.GEMMA,s.HY)]
        if other:
            raise RuntimeError('Other Ollama models currently resident; waiting rather than forcing CPU offload: '+str(other))
        if need_gemma and any(m.get('name')==s.HY for m in active):
            # Existing HY cleanup remains scoped to this known SubHub model.
            body=json.dumps({'model':s.HY,'prompt':'','keep_alive':0}).encode()
            with urlopen(Request(s.OLLAMA+'/api/generate',data=body,headers={'Content-Type':'application/json'}),timeout=12):pass
        if need_gemma:
            try:
                import subtitle_tuned_production as tuned
            except ModuleNotFoundError:
                from tools import subtitle_tuned_production as tuned
            if s.GEMMA != tuned.MODEL:
                raise RuntimeError('Configured production model not pinned subtitle-tuned E4B')
            tuned.model_preflight()
    except Exception as exc:
        raise RuntimeError('Ollama preflight failed; jobs unchanged: '+str(exc)) from exc


def run(store,base,root,args,translator=s.translation_call,hy=s.hy_call):
    status={'phase':'init','job':'','started':s.stamp()}
    with lockfiles(root):
        if translator is s.translation_call:preflight_ollama(need_gemma=args.mode!='qa')
        meter=Meter(root,status,interval=args.sample_seconds);meter.start()
        deadline=time.monotonic()+args.max_minutes*60
        completed=0
        try:
            jobs=store.jobs()
            print(f'SUBHUB 1.0: {len(jobs)} imported titles, {args.max_minutes}m budget, publish={args.publish}',flush=True)
            for job in jobs:
                if completed>=args.max_titles or time.monotonic()>deadline or (root/'PAUSE').exists():break
                if job['status']=='published':continue
                if job['status'] in ('hold','publish_hold'):continue
                status['job']=job['id'];status['phase']='translate'
                try:
                    if translator is s.translation_call and args.mode!='qa':
                        # Legacy generic-model cue checkpoints without this
                        # source+prompt+model pin MUST NOT be resumed/published.
                        tuned.assert_job_profile(root,job,int(job['ja'] or 0))
                    if args.mode!='qa' and job['ja']<job['n']:
                        began=time.monotonic();before_wh=meter.wh
                        s.translate_job(store,base,job,deadline,call=translator,
                            stop_check=lambda:(root/'PAUSE').exists(),
                            thermal_check=lambda:thermal_guard(args.max_gpu_c,args.max_cpu_c))
                        store.phase(job['id'],'gemma',time.monotonic()-began,meter.wh-before_wh)
                    now_job=next(x for x in store.jobs() if x['id']==job['id'])
                    if now_job['ja']==now_job['n'] and args.mode!='qa':
                        status['phase']='publish'
                        publish_ready(store,now_job,args.publish)
                        latest=next(x for x in store.jobs() if x['id']==job['id'])
                        if latest['status']=='published':completed+=1
                    else:
                        print(f"HELD {job['id']}: {now_job['ja']}/{now_job['n']} JA; continuing to next film",flush=True)
                except s.ThermalHold as e:
                    store.state(job['id'],'queued',f'Thermal hold: {e}')
                    print(f'THERMAL HOLD: {e}; stopping entire run',flush=True)
                    break
                except Exception as e:
                    store.state(job['id'],'hold',f'{type(e).__name__}: {str(e)[:250]}')
                    print(f'HOLD {job["id"]}: {type(e).__name__}: {e}',flush=True)
            # Separate QA phase; never blocks publishing of completed titles.
            if args.mode!='translate' and not args.skip_hy and time.monotonic()<deadline and not (root/'PAUSE').exists():
                status['phase']='hy-review'
                for job in store.jobs():
                    if time.monotonic()>=deadline or (root/'PAUSE').exists():break
                    if job['ja']!=job['n'] or job['hy']>=args.hy_sample:continue
                    status['job']=job['id']
                    try:
                        began=time.monotonic();before_wh=meter.wh
                        s.qa_job(store,base,job,deadline,hy_function=hy,count=args.hy_sample,
                                 stop_check=lambda:(root/'PAUSE').exists())
                        store.phase(job['id'],'hy',time.monotonic()-began,meter.wh-before_wh)
                    except Exception as e:
                        store.event(job['id'],'hy_deferred',f'{type(e).__name__}: {str(e)[:160]}')
                        print('HY DEFERRED '+job['id']+': '+str(e)[:150],flush=True)
        finally:
            status['phase']='finished';status['job']=''
            metrics=meter.finish()
            print('FINISHED: published this run',completed,'metrics:',json.dumps(metrics),flush=True)
    return completed


def start_detached(script,root,args):
    root.mkdir(parents=True,exist_ok=True)
    # Both old and new pid can stale; actual locks in run() are authoritative.
    log=root/'worker.log'
    argv=[sys.executable,str(script),'--root',str(root),'run','--mode',args.mode, '--max-gpu-c',str(args.max_gpu_c), '--max-cpu-c',str(args.max_cpu_c),'--max-minutes',str(args.max_minutes),
          '--max-titles',str(args.max_titles),'--hy-sample',str(args.hy_sample),
          '--sample-seconds',str(args.sample_seconds)]
    if args.publish:argv+=['--publish']
    if args.skip_hy:argv+=['--skip-hy']
    with log.open('a',encoding='utf8') as f:
        f.write('\n=== '+s.stamp()+' ===\n');f.flush()
        proc=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,
                              start_new_session=True,cwd=str(script.parent))
    print('STARTED detached PID',proc.pid,'log',log)


def dashboard(root):
    st=s.Store(root)
    try:
        d=s.summary(st)
        h='<html><head><meta charset="utf-8"><meta http-equiv="refresh" content="10"><style>body{background:#14171b;color:#ecf0f2;font:16px system-ui;margin:3vw;max-width:1000px}h1{font-size:28px}.muted{color:#9facb8}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #38414c;text-align:left}.bar{height:7px;background:#3b4855;border-radius:9px;overflow:hidden}.fill{height:100%;background:#60a5fa}.kpi{display:inline-block;margin-right:32px}</style></head><body>'
        h+='<h1>Bruiser · SubHub 1.0</h1><p class="muted">Auto-refresh every 10 seconds. Local-only, read-only dashboard.</p>'
        h+=f'<p class="kpi"><b>{d["completed"]}</b> published</p><p class="kpi"><b>{d["total"]}</b> imported</p>'
        metrics=root/'hardware-summary.json'
        if metrics.exists():
            m=json.loads(metrics.read_text())
            h+=f'<p>Last run: {m.get("seconds",0)} s · GPU {m.get("gpu_Wh_estimate",0)} Wh · peak {m.get("peak_gpu_C", "n/a")}°C</p>'
        h+='<table><thead><tr><th>Film</th><th>Status</th><th>Japanese</th><th>HY checked</th><th>Failures</th></tr></thead><tbody>'
        for j in d['jobs']:
            pct=100*j['ja']/max(1,j['total'])
            h+=f'<tr><td>{html.escape(j["id"])}</td><td>{html.escape(j["state"])}</td><td>{j["ja"]}/{j["total"]}<div class="bar"><div class="fill" style="width:{pct}%"></div></div></td><td>{j["hy"]}</td><td>{j["isolated_failures"]}</td></tr>'
        h+='</tbody></table><h3>Recent activity</h3><pre>'
        for x in st.cn.execute('SELECT * FROM events ORDER BY n DESC LIMIT 15'):
            h+=html.escape(f'{x["at"]} {x["job_id"] or ""} {x["action"]}: {x["detail"]}')+'\n'
        h+='</pre></body></html>'
        return h.encode('utf8')
    finally:st.cn.close()


def serve(root,port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ('/','/status'):self.send_error(404);return
            data=dashboard(root);self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
        def log_message(self,format,*args):pass
    print(f'Dashboard on http://127.0.0.1:{port}/ (SSH tunnel required from Mac mini)',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()


def activate_timer(root,script):
    """Retire legacy timers only after one proven SubHub 1.0 publication."""
    db=s.Store(root)
    try:
        if s.summary(db)['completed']<1:
            raise RuntimeError('At least one live SubHub 1.0 film must publish before timer takeover')
    finally: db.cn.close()
    legacy=('subhub-household.timer','subhub-bulk-publisher.timer')
    user=Path.home()/'.config/systemd/user'
    user.mkdir(parents=True,exist_ok=True)
    service=user/'subhub1.service';timer=user/'subhub1.timer'
    if service.exists() or timer.exists():
        raise RuntimeError('SubHub 1.0 units already exist; refusing to overwrite')
    body='\n'.join((
        '[Unit]','Description=SubHub 1.0 bounded subtitle coordinator','',
        '[Service]','Type=oneshot',
        f'ExecStart=/usr/bin/python3 {script} --root {root} run --mode all --publish --max-minutes 105 --max-titles 10 --hy-sample 48',
        'Nice=15','IOSchedulingClass=idle','CPUQuota=300%','TimeoutStartSec=2h',''))
    schedule='\n'.join((
        '[Unit]','Description=SubHub 1.0 quiet-hours translation','',
        '[Timer]','OnCalendar=*-*-* 02:00:00 Asia/Tokyo',
        'Persistent=false','AccuracySec=1min','Unit=subhub1.service','',
        '[Install]','WantedBy=timers.target',''))
    def ctl(*cmd):
        r=subprocess.run(['systemctl','--user',*cmd],capture_output=True,text=True,timeout=20)
        if r.returncode:raise RuntimeError(f'systemctl {cmd}: {r.stderr.strip()[:300]}')
    previously=[]
    for u in legacy:
        q=subprocess.run(['systemctl','--user','is-enabled',u],capture_output=True,text=True)
        if q.returncode==0 and q.stdout.strip()=='enabled':previously.append(u)
    try:
        s.atomic(service,body.encode());s.atomic(timer,schedule.encode())
        ctl('daemon-reload')
        for u in previously:ctl('disable','--now',u)
        ctl('enable','--now','subhub1.timer')
        print('TIMER CUTOVER COMPLETE: SubHub 1.0 nightly 02:00 JST; legacy timers disabled',flush=True)
    except Exception:
        subprocess.run(['systemctl','--user','disable','--now','subhub1.timer'],capture_output=True)
        for u in previously:
            subprocess.run(['systemctl','--user','enable','--now',u],capture_output=True)
        with contextlib.suppress(FileNotFoundError):service.unlink()
        with contextlib.suppress(FileNotFoundError):timer.unlink()
        subprocess.run(['systemctl','--user','daemon-reload'],capture_output=True)
        raise

def cli(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=ROOT)
    sub=ap.add_subparsers(dest='action',required=True)
    imp=sub.add_parser('import-legacy',help='snapshot specific legacy queued Horror titles; read-only to legacy')
    imp.add_argument('--limit',type=int,default=10)
    imp.add_argument('--prioritize',default='heretic,primate')
    add=sub.add_parser('add-srt',help='register a chosen existing video and source English SRT')
    for k in ('id','video','source'):add.add_argument('--'+k,required=True)
    for name in ('run','start'):
        x=sub.add_parser(name)
        x.add_argument('--max-minutes',type=int,default=90)
        x.add_argument('--mode',choices=['all','translate','qa'],default='all')
        x.add_argument('--max-gpu-c',type=int,default=82)
        x.add_argument('--max-cpu-c',type=int,default=85)
        x.add_argument('--max-titles',type=int,default=10)
        x.add_argument('--hy-sample',type=int,default=48)
        x.add_argument('--sample-seconds',type=int,default=15)
        x.add_argument('--publish',action='store_true',help='publish Japanese for verified English-audio films')
        x.add_argument('--skip-hy',action='store_true',help='translation and publication only; HY may run later')
    sub.add_parser('status')
    sub.add_parser('pause')
    sub.add_parser('resume')
    exp=sub.add_parser('export-review');exp.add_argument('--id',required=True)
    q=sub.add_parser('serve');q.add_argument('--port',type=int,default=8686)
    sub.add_parser('self-test')
    sub.add_parser('activate-timer',help='after a real 1.0 publication, replace legacy timers safely')
    a=ap.parse_args(argv)
    if a.action=='self-test':
        import unittest
        import test_subhub1
        suite=unittest.defaultTestLoader.loadTestsFromModule(test_subhub1)
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 2
    store=s.Store(a.root)
    try:
        if a.action=='import-legacy':
            if not 1<=a.limit<=50:raise ValueError('limit must be 1 to 50')
            s.import_legacy(store,BASE,limit=a.limit,prioritize=[p.strip() for p in a.prioritize.split(',') if p.strip()])
        elif a.action=='add-srt':
            video=Path(a.video);s.secure_video(video);lang=s.audio_language(video)
            store.add(a.id,video,Path(a.source).read_bytes(),lang)
            print('ADDED',a.id,'audio',lang)
        elif a.action=='run':
            if not 1<=a.max_minutes<=480 or not 1<=a.max_titles<=50 or not 10<=a.sample_seconds<=120:raise ValueError('Unsafe run limits')
            run(store,BASE,a.root,a)
        elif a.action=='start':
            if not 1<=a.max_minutes<=480 or not 1<=a.max_titles<=50:raise ValueError('Unsafe run limits')
            start_detached(Path(__file__).resolve(),a.root,a)
        elif a.action=='status':
            info=s.summary(store)
            print('SUBHUB 1.0 | published',info['completed'],'/',info['total'])
            for j in info['jobs']:
                print(f"{j['id']}: {j['state']}, JA {j['ja']}/{j['total']}, HY {j['hy']}/{j['total']}, isolated failures {j['isolated_failures']}")
            h=a.root/'hardware-summary.json'
            if h.exists():print('HARDWARE',h.read_text()[:1100])
            print('LATEST EVENTS')
            for x in store.cn.execute('SELECT job_id,phase,ROUND(SUM(elapsed_s),1) elapsed,ROUND(SUM(gpu_Wh_est),3) wh FROM phase_stats GROUP BY job_id,phase ORDER BY job_id,phase'):
                print('TIMING',x['job_id'],x['phase'],str(x['elapsed'])+'s',str(x['wh'])+' GPU Wh estimate')
            for e in store.cn.execute('SELECT * FROM events ORDER BY n DESC LIMIT 8'):
                print(e['at'],e['job_id'] or '-',e['action'],e['detail'])
        elif a.action=='pause':s.atomic(a.root/'PAUSE',b'paused\n');print('Pause requested; current inference call may finish before stopping')
        elif a.action=='resume':(a.root/'PAUSE').unlink(missing_ok=True);print('Pause lifted')
        elif a.action=='export-review':print('REVIEW CSV',s.make_review_export(store,a.id))
        elif a.action=='serve':serve(a.root,a.port)
        elif a.action=='activate-timer':activate_timer(a.root,Path(__file__).resolve())
        return 0
    finally:store.cn.close()

if __name__=='__main__':sys.exit(cli())
