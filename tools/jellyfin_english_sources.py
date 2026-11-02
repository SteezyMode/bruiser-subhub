#!/usr/bin/env python3
"""Acquire real English subtitle SRTs through the existing native Jellyfin.

Only *explicitly selected* American Dad seasons, default S08. Uses Jellyfin
installed subtitle providers (Subbuzz/etc), not a new downloader. No subtitle
providers configured? Report the blocker. No auto-translation experiments.
Never start a full-library Jellyfin scheduled task.

First use requires one interactive Jellyfin admin login in the host terminal.
Password is never stored; a Jellyfin session token is stored 0600 under the
host owner's private configuration for subsequent runs. Never print secrets.

--apply downloads only provider results with strong episode identity, then
--start launches the already-tested separate American Dad SubHub season runner.
Default with neither --apply nor --start: read-only catalog preflight.
"""
from __future__ import annotations

import argparse
from collections import Counter
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

try:
    import american_dad_seasons as seasons
    import daily_japanese as intake
except ModuleNotFoundError:
    from tools import american_dad_seasons as seasons
    from tools import daily_japanese as intake

HOST='http://127.0.0.1:8096'
CREDENTIAL=Path.home()/'.config/bruiser/jellyfin-english-source-auth.json'
CLIENT='Bruiser Subtitle Sources'
TIMEOUT=35
ITEM_PAGE=200
MAX_PAGES=150
VALID_FORMAT={'srt','subrip'}
LANGS={'eng','en'}
SEASON_TAG=re.compile(r'(?<![a-z0-9])s(\d{1,2})[\s._-]*e(\d{1,3})(?!\d)',re.I)
ALT_TAG=re.compile(r'(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)',re.I)


def auth_header(token='',device_id='bruiser-subhub'):
    # The MediaBrowser scheme is required for newer Jellyfin builds.
    fields=[
        'Client="'+CLIENT+'"',
        'Device="OptiPlex"',
        'DeviceId="'+device_id+'"',
        'Version="1.0.0"',
    ]
    if token:
        fields.append('Token="'+token+'"')
    return 'MediaBrowser '+', '.join(fields)


class Jellyfin:
    def __init__(self, token='', device_id='bruiser-subhub',
                 root=HOST, opener=urlopen):
        if root != HOST:
            raise ValueError('Jellyfin must be the local loopback service')
        self.token=token
        self.device_id=device_id
        self.opener=opener

    def call(self,method,path,data=None):
        if not path.startswith('/') or path.startswith('//'):
            raise ValueError('Unsafe Jellyfin API route')
        blob=None if data is None else json.dumps(data).encode('utf8')
        request=Request(
            HOST+path,
            method=method,
            data=blob,
            headers={
                'Authorization':auth_header(self.token,self.device_id),
                'Accept':'application/json',
                **({'Content-Type':'application/json'} if blob is not None else {}),
            },
        )
        with self.opener(request,timeout=TIMEOUT) as response:
            raw=response.read()
        if not raw:
            return None
        return json.loads(raw)

    def get(self,path):
        return self.call('GET',path)

    def post(self,path,data=None):
        return self.call('POST',path,data)

    def login(self,username,password):
        result=self.post('/Users/AuthenticateByName',
                         {'Username':username,'Pw':password})
        if not isinstance(result,dict) or not result.get('AccessToken'):
            raise RuntimeError('Jellyfin authentication did not return a token')
        user=result.get('User') or {}
        if not (user.get('Policy') or {}).get('IsAdministrator'):
            raise RuntimeError('A Jellyfin administrator account is required')
        self.token=result['AccessToken']
        return True


def load_token(path=CREDENTIAL):
    path=Path(path)
    if not path.exists() and not path.is_symlink():
        return None
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise RuntimeError('Unsafe saved Jellyfin token permissions')
    saved=json.loads(path.read_text(encoding='utf8'))
    if saved.get('schema')!=1 or not isinstance(saved.get('token'),str):
        raise RuntimeError('Invalid saved Jellyfin token')
    if not re.fullmatch('[a-z0-9-]{8,64}',saved.get('device_id','')):
        raise RuntimeError('Invalid saved Jellyfin client ID')
    return saved


def save_token(token,device_id,path=CREDENTIAL):
    if not token or not re.fullmatch('[a-z0-9-]{8,64}',device_id):
        raise ValueError('Invalid Jellyfin authentication metadata')
    path=Path(path)
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if path.is_symlink():
        raise RuntimeError('Refuse token destination symlink')
    data=(json.dumps({'schema':1,'token':token,
                      'device_id':device_id},sort_keys=True)+'\n').encode()
    tmp=path.parent/(path.name+'.'+secrets.token_hex(8)+'.tmp')
    fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()


def authenticate(client,token_path=CREDENTIAL,
                 username_input=input,password_input=getpass.getpass,
                 save=True):
    saved=load_token(token_path)
    if saved:
        client.token=saved['token']
        client.device_id=saved['device_id']
        try:
            user=client.get('/Users/Me')
            if isinstance(user,dict) and (user.get('Policy') or {}).get('IsAdministrator'):
                return 'cached'
        except (HTTPError,URLError,ValueError):
            pass
        client.token=''
    if not sys.stdin.isatty():
        raise RuntimeError('One-time Jellyfin admin login needs an interactive SSH terminal')
    username=username_input('Jellyfin admin username: ').strip()
    password=password_input('Jellyfin password (hidden): ')
    if not username:
        raise RuntimeError('Jellyfin username missing')
    try:
        client.device_id='bruiser-'+secrets.token_hex(12)
        client.login(username,password)
    finally:
        password=''
    if save:
        save_token(client.token,client.device_id,token_path)
    return 'interactive'


def jellyfin_episodes(client):
    """List actual library Episodes, by exact local filepath not name guessing."""
    found={}
    for page in range(MAX_PAGES):
        query=urlencode({
            'Recursive':'true','IncludeItemTypes':'Episode',
            'Fields':'Path','StartIndex':page*ITEM_PAGE,'Limit':ITEM_PAGE,
        })
        data=client.get('/Items?'+query)
        if not isinstance(data,dict) or not isinstance(data.get('Items'),list):
            raise RuntimeError('Jellyfin did not return an episode catalog')
        for item in data['Items']:
            media_path=item.get('Path')
            if not media_path or not item.get('Id'):
                continue
            # The local native-service Jellyfin sees host paths. Only match
            # EXACT real paths, not guessed episode name or fuzzy titles.
            found.setdefault(str(Path(media_path).resolve()),[]).append(item)
        if (len(data['Items'])<ITEM_PAGE or
            (isinstance(data.get('TotalRecordCount'),int)
             and (page+1)*ITEM_PAGE>=data['TotalRecordCount'])):
            return found
    raise RuntimeError('Jellyfin episode catalog exceeds safe paging bound')


def strong_match(result,season,episode,video):
    """Do not download an ambiguous or wrong-season provider release."""
    if str(result.get('Format','')).casefold() not in VALID_FORMAT:
        return False
    if str(result.get('ThreeLetterISOLanguageName','')).casefold() not in LANGS:
        return False
    if not result.get('Id') or not result.get('ProviderName'):
        return False
    name=str(result.get('Name') or '')
    tag=SEASON_TAG.search(name) or ALT_TAG.search(name)
    if tag:
        if (int(tag[1]),int(tag[2]))!=(season,episode):
            return False
        if not seasons.SHOW.search(name):
            # Provider can have shortened release names, but a filename or
            # a hash must establish that it belongs to American Dad.
            if not result.get('IsHashMatch'):
                return False
        return True
    return result.get('IsHashMatch') is True


def pick(results,season,episode,video):
    accepted=[x for x in results
              if isinstance(x,dict) and strong_match(x,season,episode,video)]
    if not accepted:
        return None
    # Strong hash match first, otherwise exact season/episode and name.
    accepted.sort(key=lambda r:(
        not bool(r.get('IsHashMatch')),
        -int(r.get('DownloadCount') or 0),
        -float(r.get('CommunityRating') or 0),
        str(r.get('ProviderName') or ''),
    ))
    return accepted[0]


def process(roots,root,requested,client,apply=False,start=False,
            discover_fn=seasons.discover,catalog_fn=jellyfin_episodes,
            stdout=print,background=seasons.start_background):
    chosen_seasons=seasons.validate_seasons(requested)
    if start and not apply:
        raise ValueError('--start requires --apply')
    episode_paths=discover_fn(roots,chosen_seasons)
    catalog=catalog_fn(client)
    counts=Counter()
    acquisitions=0
    for (season,episode),copies in episode_paths.items():
        label=seasons.title(season,episode)
        if any(intake.already_ja(video) for video in copies):
            counts['existing_japanese']+=1
            stdout('EN_SOURCE',label,'skip_existing_japanese')
            continue
        existing=next((video for video in copies
                       if intake.english_srt(video)),None)
        if existing:
            counts['existing_english']+=1
            stdout('EN_SOURCE',label,'already_has_english_srt')
            continue
        matched=[]
        for video in copies:
            for item in catalog.get(str(video.resolve()),[]):
                # Metadata season index may differ due to ordering schemes.
                # If explicit numeric metadata disagrees, refuse the file.
                if (item.get('ParentIndexNumber') not in (None,season) or
                    item.get('IndexNumber') not in (None,episode)):
                    counts['jellyfin_numbering_conflict']+=1
                    continue
                matched.append((video,item))
        if not matched:
            counts['not_registered_or_numbering_conflict']+=1
            stdout('EN_SOURCE',label,'not_matched_in_jellyfin_library')
            continue
        video,item=matched[0]
        if not apply:
            counts['jellyfin_registered']+=1
            stdout('EN_SOURCE',label,'jellyfin_registered')
            continue
        try:
            info=intake.probe(video)
            if info['ja'] or not info['audio_en']:
                counts['not_eligible']+=1
                stdout('EN_SOURCE',label,'audio_or_japanese_blocked')
                continue
            # One bounded provider search per distinct SxxExx.
            route='/Items/'+quote(str(item['Id']),safe='')+'/RemoteSearch/Subtitles/eng'
            results=client.get(route)
            if not isinstance(results,list):
                raise RuntimeError('Invalid remote subtitle results')
            subtitle=pick(results,season,episode,video)
            if not subtitle:
                counts['no_strong_provider_match']+=1
                stdout('EN_SOURCE',label,'no_verified_provider_match',
                       'candidates',len(results))
                continue
            subtitle_id=quote(str(subtitle['Id']),safe='')
            client.post('/Items/'+quote(str(item['Id']),safe='')+
                        '/RemoteSearch/Subtitles/'+subtitle_id)
            # Jellyfin may save to its internal metadata instead of beside
            # video. Do not pretend that a new SubHub source is available.
            attached=intake.english_srt(video)
            if not attached:
                counts['not_saved_beside_video']+=1
                stdout('EN_SOURCE',label,'jellyfin_downloaded_no_media_srt')
                continue
            content,n,origin=intake.source(video,info)
            if n<15:
                raise RuntimeError('Subtitle source cue count too low')
            counts['acquired']+=1
            acquisitions+=1
            stdout('EN_SOURCE',label,'ready_for_translation',
                   'english_cues',n)
        except (HTTPError,URLError,OSError,ValueError,
                RuntimeError,TimeoutError) as exc:
            counts['provider_or_source_error']+=1
            stdout('EN_SOURCE',label,'source_error',type(exc).__name__)
    result={
        'seasons':list(chosen_seasons),
        'episodes_found':len(episode_paths),
        'categories':dict(sorted(counts.items())),
        'new_english_sources':acquisitions,
    }
    stdout('EN_SOURCE_SUMMARY',json.dumps(result,sort_keys=True))
    if start and (acquisitions or counts['existing_english']):
        run=background(root,chosen_seasons,50,480)
        stdout('SEASON_LAUNCHED',json.dumps(run,sort_keys=True))
    elif start:
        stdout('SEASON_NOT_STARTED','no_usable_english_sources')
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=intake.DEFAULT_STATE)
    p.add_argument('--media-root',type=Path,action='append',default=None)
    p.add_argument('--seasons',nargs='+',type=int,default=[8])
    p.add_argument('--apply',action='store_true')
    p.add_argument('--start',action='store_true')
    args=p.parse_args(argv)
    try:
        roots=intake.ensure_roots(args.media_root or intake.service.SOURCE_ROOTS)
        seasons.validate_seasons(args.seasons)
        client=Jellyfin()
        via=authenticate(client)
        print('JELLYFIN_AUTH',via,flush=True)
        process(roots,args.root,args.seasons,client,args.apply,args.start)
    except Exception as exc:
        # NEVER print raw HTTP errors containing tokens or URLs.
        print('EN_SOURCE_BLOCKED',type(exc).__name__,file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
