#!/usr/bin/env python3
"""One controlled follow-on search in the isolated Sunny Bazarr trial.

Use SubDL + credential-free Gestdown, and Jimaku if already configured in Sublarr.
No accounts/password entry, no downloads, no production media mounts/changes.
"""
from __future__ import annotations
import json, re, subprocess, urllib.parse, urllib.request, urllib.error
from pathlib import Path

ROOT=Path.home()/"bruiser-pilot/bazarr-trial"
BAZARR="http://100.121.156.34:16767"
SEASON_EPISODES={(3,3),(4,3),(6,7)}


def fail(message):
    raise SystemExit("TRIAL BLOCKED: "+message)


def get_key():
    p=ROOT/"config/bazarr/config/config.yaml"
    if not p.is_file():
        fail("Trial Bazarr configuration not found")
    m=re.search(r"(?m)^auth:\s*\n(?:[ \t]+[^\n]+\n)*?[ \t]+apikey:[ \t]*['\"]?([a-fA-F0-9]{32,128})",p.read_text())
    if not m: fail("Bazarr API key not found")
    return m.group(1)


def api(path,key,data=None,timeout=100):
    headers={"X-Api-Key":key}
    payload=None
    if data is not None:
        payload=urllib.parse.urlencode(data,doseq=True).encode()
        headers["Content-Type"]="application/x-www-form-urlencoded"
    try:
        req=urllib.request.Request(BAZARR+path,data=payload,headers=headers)
        with urllib.request.urlopen(req,timeout=timeout) as resp:
            raw=resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        fail(f"Bazarr API {path}: HTTP {e.code}; response suppressed")
    except (OSError, ValueError) as e:
        fail(f"Bazarr API {path}: {type(e).__name__}")


def inspect():
    d=ROOT/"media/tv/It's Always Sunny in Philadelphia"
    files=[x for x in d.rglob("*") if x.is_file() and x.suffix.lower() in (".mkv",".mp4",".avi",".m4v",".webm")] if d.is_dir() else []
    if len(files)!=5: fail("Trial video copies are missing or changed")
    for name in ("bruiser-sonarr-trial","bruiser-bazarr-trial"):
        p=subprocess.run(["docker","inspect","--format","{{json .Mounts}}",name],capture_output=True,text=True)
        if p.returncode: fail(f"Trial container missing: {name}")
        mounts=json.loads(p.stdout)
        if not mounts or any(not Path(m.get('Source','/')).resolve().is_relative_to(ROOT.resolve()) for m in mounts):
            fail(f"Unexpected media mount in {name}; do not continue")
    print("ISOLATION: only the five copied trial videos are mounted")


def sublarr_jimaku_key():
    # Sublarr config_entries are encrypted at rest. Use its own read-only
    # decryption helper inside the existing Sublarr container. No stdout logs.
    code='''import json,os,sqlite3
from config_crypto import decrypt
p=os.environ.get("SUBLARR_DB_PATH","/config/sublarr.db")
c=sqlite3.connect("file:"+p+"?mode=ro",uri=True)
r=c.execute("SELECT value FROM config_entries WHERE key='jimaku_api_key'").fetchone()
v=decrypt(r[0]) if r else None
print(json.dumps({"jimaku_api_key":v or ""}))'''
    try:
        r=subprocess.run(["docker","exec","-e","PYTHONPATH=/app","sublarr-pilot","python3","-c",code],
                         capture_output=True,text=True,timeout=25)
        if r.returncode: return ""
        value=json.loads(r.stdout).get("jimaku_api_key","")
        if not isinstance(value,str) or not value or value.startswith("enc:v1:"): return ""
        return value
    except (OSError,ValueError,subprocess.TimeoutExpired):
        return ""


def main():
    inspect()
    key=get_key()
    settings=api("/api/system/settings",key)
    general=settings.get('general',{})
    if not general.get('use_sonarr') or general.get('use_radarr'):
        fail("Unexpected Sonarr/Radarr setup")
    if not general.get('use_postprocessing') or '/config/scripts/bazarr-subsync' not in str(general.get('postprocessing_cmd','')):
        fail("Expected alass post-processing is not enabled")
    if int(general.get('wanted_search_frequency',0))!=876000 or general.get('upgrade_subs'):
        fail("Auto-search or upgrade is enabled; refuse further changes")
    enabled=general.get('enabled_providers',[])
    if not isinstance(enabled,list) or set(enabled)-{'subdl','opensubtitlescom','gestdown','jimaku'}:
        fail("Unexpected provider configuration")
    if not settings.get('subdl',{}).get('api_key'):
        fail("Existing SubDL API key missing")
    jimaku=sublarr_jimaku_key()
    providers=['subdl','gestdown']
    fields={'settings-general-enabled_providers':providers,
            'settings-general-upgrade_subs':'false',
            'settings-general-wanted_search_frequency':'876000'}
    if jimaku:
        providers.append('jimaku')
        fields['settings-jimaku-api_key']=jimaku
        fields['settings-jimaku-enable_ai_subs']='false'
        print('JIMAKU: existing Sublarr key found (not displayed)')
    else:
        print('JIMAKU: no existing key available; skipping without creating an account')
    # During this trial OpenSubtitles remains in authentication cooldown.
    # Disable it rather than resetting or trying another login.
    api('/api/system/settings',key,fields)
    updated=api('/api/system/settings',key)
    if set(updated.get('general',{}).get('enabled_providers',[])) != set(providers):
        fail('Provider changes not confirmed')
    if int(updated.get('general',{}).get('wanted_search_frequency',0))!=876000:
        fail('Scheduled searches unexpectedly enabled')
    print('PROVIDERS: '+', '.join(providers)+'; OpenSubtitles disabled (no retry)')
    shows=api('/api/series',key)
    rows=shows.get('data',[]) if isinstance(shows,dict) else []
    sunny=[x for x in rows if x.get('tvdbId')==75805 and str(x.get('path','')).startswith('/tv/')]
    if len(rows)!=1 or len(sunny)!=1:
        fail('Trial series catalog unexpected; no searches run')
    sid=sunny[0]['sonarrSeriesId']
    episodes=api('/api/episodes?seriesid%5B%5D='+str(sid),key)
    entries=episodes.get('data',[]) if isinstance(episodes,dict) else []
    selected=[]
    for sn,epn in sorted(SEASON_EPISODES):
        hits=[e for e in entries if e.get('season')==sn and e.get('episode')==epn and e.get('path')]
        if len(hits)!=1:fail(f'S{sn:02}E{epn:02} not uniquely indexed; no searches run')
        selected.append((f'S{sn:02}E{epn:02}',hits[0]['sonarrEpisodeId']))
    print('SEARCH: controlled manual lookups of '+', '.join(t for t,_ in selected)+'; downloads OFF')
    overall=0
    for tag,eid in selected:
        # GET performs provider search. Exactly once per selected episode.
        result=api('/api/providers/episodes?episodeid='+str(eid),key,timeout=180)
        items=result.get('data',[]) if isinstance(result,dict) else []
        jp=[x for x in items if str(x.get('language','')).lower().startswith(('ja','jp','japanese'))]
        overall+=len(jp)
        print(f'{tag}: {len(jp)} Japanese candidates ({len(items)} total)')
        for item in sorted(jp,key=lambda x:x.get('score') or 0,reverse=True)[:4]:
            release=item.get('release_info') or []
            release=' | '.join(map(str,release)) if isinstance(release,list) else str(release)
            release=re.sub(r'[\x00-\x1f\x7f]',' ',release)[:85]
            print('  '+str(item.get('provider','?'))+' score='+str(item.get('score','?'))+' '+release)
    print('JAPANESE CANDIDATES TOTAL:',overall)
    state=api('/api/providers',key)
    for p in state.get('data',[]):
        if p.get('name') in providers:
            status=re.sub(r'[^a-zA-Z0-9 _.-]','',str(p.get('status','?')))[:45]
            print('PROVIDER STATUS:',p['name'],status)
    print('DONE: no subtitle files downloaded; all existing media and subtitles untouched')

if __name__=='__main__': main()
