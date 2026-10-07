"""Décisions de montage versionnées. Les horaires éditables sont des images entières."""
from __future__ import annotations
import copy
import datetime as dt
from fractions import Fraction
import hashlib
import json
import math
import threading
import time
import uuid
import core

LOCK = threading.RLock()
PREVIEWS = {}

class Conflict(ValueError):
    pass

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def project_path(job_id):
    # Toujours appelé avec un identifiant trouvé dans JOBS par le serveur.
    return core.PROJECTS / job_id / 'montage.json'

def read(job_id):
    return json.loads(project_path(job_id).read_text(encoding='utf-8'))

def source_frames(source, fps):
    return max(1, math.floor(source['duration'] * fps + .5))

def initialize(job_id, pending=False):
    with LOCK:
        if project_path(job_id).exists():
            return read(job_id)
        timeline = json.loads((core.PROJECTS / job_id / 'decoupage.json').read_text(encoding='utf-8'))
        fps = float(Fraction(timeline['fps']))
        clips, offset = [], 0.
        for i, source in enumerate(timeline['sources']):
            total = source_frames(source, fps)
            cuts = []
            for j, cut in enumerate(timeline['cuts']):
                start = max(0, math.floor((cut['start'] - offset) * fps + .5))
                end = min(total, math.floor((cut['end'] - offset) * fps + .5))
                if end > start:
                    cuts.append(dict(id=f'pause-{j}-{i}', start=start, end=end,
                                     original_start=start, original_end=end,
                                     decision='accepted'))
            clips.append(dict(id=f'prise-{i}', source_index=i, start=0, end=total, enabled=True, cuts=cuts))
            offset += source['duration']
        doc = dict(schema_version=2, job_id=job_id, revision=1, updated_at=now(),
                   fps=timeline['fps'], sources=timeline['sources'], parameters=timeline['parameters'],
                   clips=clips, approved_revision=None, approval=None,
                   imported_from_render=not pending)
        persist(doc)
        return doc

def persist(doc):
    folder = core.PROJECTS / doc['job_id'] / 'versions'
    core.save_json(folder / f"montage-v{doc['revision']:04d}.json", doc)
    core.save_json(project_path(doc['job_id']), doc)

def validate_clips(doc, clips):
    if not isinstance(clips, list) or len(clips) != len(doc['clips']):
        raise ValueError('La liste doit conserver toutes les prises du projet.')
    originals = {c['id']: c for c in doc['clips']}
    fps = float(Fraction(doc['fps']))
    result, seen = [], set()
    def integer(x):
        return isinstance(x, int) and not isinstance(x, bool)
    for c in clips:
        if not isinstance(c, dict) or c.get('id') not in originals or c['id'] in seen:
            raise ValueError('Identifiant de prise incorrect ou répété.')
        seen.add(c['id'])
        base = originals[c['id']]
        total = source_frames(doc['sources'][base['source_index']], fps)
        start, end = c.get('start'), c.get('end')
        if not integer(start) or not integer(end) or not 0 <= start < end <= total:
            raise ValueError('La fin doit suivre le début, dans les limites de la prise.')
        if not isinstance(c.get('enabled'), bool):
            raise ValueError('État de prise incorrect.')
        oldcuts = {p['id']:p for p in base['cuts']}
        if not isinstance(c.get('cuts'), list) or len(c['cuts']) != len(oldcuts):
            raise ValueError('Les propositions de pause doivent rester disponibles.')
        cuts, seen_cuts = [], set()
        for p in c['cuts']:
            if not isinstance(p, dict) or p.get('id') not in oldcuts or p['id'] in seen_cuts:
                raise ValueError('Identifiant de pause incorrect.')
            seen_cuts.add(p['id'])
            a,b = p.get('start'),p.get('end')
            if not integer(a) or not integer(b) or not 0 <= a < b <= total:
                raise ValueError('Une coupe doit rester dans sa prise, avec une durée positive.')
            if p.get('decision') not in ('pending','accepted','rejected'):
                raise ValueError('Décision de coupe incorrecte.')
            cuts.append(dict(oldcuts[p['id']], start=a, end=b, decision=p['decision']))
        ordered = sorted(cuts, key=lambda p:p['start'])
        if any(a['end'] > b['start'] for a,b in zip(ordered,ordered[1:])):
            raise ValueError('Deux propositions de coupe se chevauchent.')
        result.append(dict(base, start=start, end=end, enabled=c['enabled'], cuts=cuts))
    candidate = dict(doc, clips=result)
    build_timeline(candidate)
    return result

def build_timeline(doc, quality=None):
    fps = float(Fraction(doc['fps']))
    segments, cursor, cuts = [], 0, []
    for clip in doc['clips']:
        if not clip['enabled']:
            continue
        lo, end = clip['start'], clip['end']
        source = doc['sources'][clip['source_index']]
        spans = []
        for cut in sorted(clip['cuts'], key=lambda p:p['start']):
            if cut['decision'] != 'accepted':
                continue
            a,b = max(clip['start'],cut['start']), min(end,cut['end'])
            if b <= a:
                continue
            if a > lo:
                spans.append((lo,a))
            lo = max(lo,b)
            cuts.append(dict(clip_id=clip['id'], source_index=clip['source_index'],start=a/fps,end=b/fps))
        if lo < end:
            spans.append((lo,end))
        for a,b in spans:
            frames=b-a
            segments.append(dict(source_index=clip['source_index'],source=source['name'],
                                 source_start=round(a/fps,9),source_end=round(b/fps,9),
                                 output_start=round(cursor/fps,9),output_end=round((cursor+frames)/fps,9),frames=frames))
            cursor += frames
    if not segments or len(segments)>500:
        raise ValueError('Le montage doit garder au moins une image et au plus 500 segments.')
    if cursor/fps > 3600:
        raise ValueError('Le montage dépasse une heure.')
    parameters=dict(doc['parameters'])
    if quality is not None:
        if quality not in ('preview','full'):
            raise ValueError('Qualité inconnue.')
        parameters['quality']=quality
    return dict(schema_version=2,engine_version=core.VERSION,parameters=parameters,sources=doc['sources'],
                fps=doc['fps'],segments=segments,cuts=cuts,input_seconds=sum(s['duration'] for s in doc['sources']),
                planned_output_seconds=cursor/fps, parent_job_id=doc['job_id'], parent_revision=doc['revision'])

def public(doc):
    fps=float(Fraction(doc['fps']))
    timeline=build_timeline(doc)
    return dict(schema_version=doc['schema_version'],job_id=doc['job_id'],revision=doc['revision'],fps=fps,
                updated_at=doc['updated_at'],approved_revision=doc['approved_revision'],clips=doc['clips'],
                approval_sync=doc.get('approval'),
                imported_from_render=doc['imported_from_render'],
                sources=[dict(name=s['name'],frames=source_frames(s,fps),duration=s['duration'],width=s['width'],height=s['height'],
                              url=f"/media/{doc['job_id']}/{i}.mp4") for i,s in enumerate(doc['sources'])],
                duration_frames=sum(s['frames'] for s in timeline['segments']))

def save(job_id, value):
    with LOCK:
        doc=read(job_id)
        if value.get('revision') != doc['revision']:
            raise Conflict('Une autre fenêtre a modifié ce projet. Recharge la dernière version avant de corriger.')
        clips=validate_clips(doc,value.get('clips'))
        if clips==doc['clips']:
            return public(doc)
        doc.update(clips=clips,revision=doc['revision']+1,updated_at=now(),approved_revision=None,approval=None)
        persist(doc)
        return public(doc)

def approve(job_id, revision):
    with LOCK:
        doc=read(job_id)
        if revision != doc['revision']:
            raise Conflict('La version a changé. Relis et sauvegarde le montage avant de le valider.')
        if doc['approved_revision']==revision:
            return public(doc)
        if any(p['decision']=='pending' for c in doc['clips'] if c['enabled'] for p in c['cuts']
               if p['end']>c['start'] and p['start']<c['end']):
            raise ValueError('Accepte ou refuse les propositions de pause restantes avant de valider.')
        doc.update(approved_revision=revision,approval=dict(at=now(),id=str(uuid.uuid4()),n8n_synced=False))
        persist(doc)
        core.save_json(core.PROJECTS/job_id/'versions'/f'approuve-v{revision:04d}.json',doc)
        return public(doc)

def notify_approval(job_id, revision=None):
    # La référence exacte est conservée même si une nouvelle correction arrive pendant l'appel réseau.
    with LOCK:
        latest=read(job_id)
        revision=revision if revision is not None else latest['approved_revision']
        if revision is None:
            raise ValueError('Aucune version validée à synchroniser.')
        doc=json.loads((core.PROJECTS/job_id/'versions'/f'approuve-v{revision:04d}.json').read_text(encoding='utf-8'))
        approval=copy.deepcopy(doc['approval'])
    timeline=build_timeline(doc)
    summary=dict(status='accepted',files_count=len(doc['sources']),input_seconds=timeline['input_seconds'],
                 output_seconds=timeline['planned_output_seconds'],parent_job_id=job_id,revision=doc['revision'],
                 stage='cut_edit',reviewed=True)
    try:
        core.n8n_request(dict(schema_version=1,action='report',job_id=approval['id'],summary=summary))
        outcome=dict(n8n_synced=True)
    except Exception as error:
        outcome=dict(n8n_synced=False,n8n_error=str(error))
    with LOCK:
        latest=read(job_id)
        if latest.get('approval',{} ) and latest['approval']['id']==approval['id']:
            latest['approval'].update(outcome)
            persist(latest)
    return outcome

def approved_snapshot(job_id,revision,quality):
    with LOCK:
        doc=read(job_id)
        if revision!=doc['revision'] or doc['approved_revision']!=revision:
            raise Conflict('Valide la version actuelle avant de demander un export.')
        return copy.deepcopy(build_timeline(doc,quality))

def proxy_path(doc,index):
    source=doc['sources'][index]
    key=hashlib.sha256(json.dumps([source['fingerprint']['sha256'],doc['fps'],'proxy-960-v1']).encode()).hexdigest()
    return core.WORK/'proxies'/(key+'.mp4')

def check_source(source):
    path=core.selected_paths(str(core.Path(source['path']).parent),[source['name']])[0]
    stat=path.stat()
    if (stat.st_size,stat.st_mtime_ns)!=(source['fingerprint']['size'],source['fingerprint']['mtime_ns']):
        raise ValueError(f"La source {source['name']} a changé. Prépare un nouveau projet.")
    return path

def prepare_proxies(job_id):
    try:
        doc=read(job_id)
        for index,source in enumerate(doc['sources']):
            with LOCK:
                PREVIEWS[job_id]=dict(status='preparing',message=f"Copie de lecture {index+1}/{len(doc['sources'])} · {source['name']}")
            path=check_source(source)
            proxy=proxy_path(doc,index)
            if proxy.exists():
                continue
            proxy.parent.mkdir(parents=True,exist_ok=True)
            temp=proxy.with_suffix('.partial.mp4')
            ratio=min(1,960/max(source['width'],source['height']))
            w,h=max(2,round(source['width']*ratio/2)*2),max(2,round(source['height']*ratio/2)*2)
            fps=float(Fraction(doc['fps']))
            duration=source_frames(source,fps)/fps
            core.run_ffmpeg(['-y','-threads','4','-i',path,'-map','0:v:0','-map','0:a:0',
                             '-vf',f'scale={w}:{h},setsar=1,fps={doc["fps"]},tpad=stop_mode=clone:stop_duration=0.1',
                             '-af','aresample=48000,apad','-t',str(duration),'-c:v','libx264','-preset','veryfast','-crf','25',
                             '-threads','4','-pix_fmt','yuv420p','-g','25','-c:a','aac','-b:a','160k','-ac','2',
                             '-map_metadata','-1','-metadata:s:v:0','rotate=0','-movflags','+faststart',temp],proxy.with_suffix('.log'))
            check_source(source)
            info=core.probe(temp)
            if abs(info['duration']-duration)>.1:
                raise ValueError('Durée inattendue dans une copie de lecture.')
            core.os.replace(temp,proxy)
        with LOCK:
            PREVIEWS[job_id]=dict(status='ready',message='Aperçu prêt')
    except Exception as error:
        with LOCK:
            PREVIEWS[job_id]=dict(status='failed',message=str(error))

def open_editor(job_id):
    doc=initialize(job_id)
    with LOCK:
        state=PREVIEWS.get(job_id)
        if not state or state['status']=='failed':
            # Une seule conversion à la fois : évite deux écritures dans un cache commun.
            if any(v['status']=='preparing' for k,v in PREVIEWS.items() if k!=job_id):
                return dict(project=public(doc),preview=dict(status='waiting',message='Une autre copie de lecture se prépare. Réessaie dans un instant.'))
            PREVIEWS[job_id]=dict(status='preparing',message='Préparation des copies de lecture')
            threading.Thread(target=prepare_proxies,args=(job_id,),daemon=True).start()
        return dict(project=public(doc),preview=PREVIEWS[job_id])

def export_job(job_id,request,progress,cancel):
    started=time.monotonic()
    timeline=copy.deepcopy(request['timeline'])
    for source in timeline['sources']:
        check_source(source)
    folder=core.PROJECTS/job_id
    core.save_json(folder/'decoupage.json',timeline)
    core.write_cut_csv(folder/'decoupage.csv',timeline['segments'])
    final,info=core.render(timeline,job_id,progress,cancel)
    summary=dict(status='completed',files_count=len(timeline['sources']),input_seconds=timeline['input_seconds'],
                 output_seconds=info['duration'],removed_seconds=round(timeline['input_seconds']-info['duration'],6),
                 cuts_count=len(timeline['cuts']),segments_count=len(timeline['segments']),processing_seconds=round(time.monotonic()-started,2),
                 bytes=final.stat().st_size,width=info['width'],height=info['height'],fps=timeline['fps'],
                 quality=timeline['parameters']['quality'],reviewed=False,parent_job_id=timeline['parent_job_id'],
                 parent_revision=timeline['parent_revision'],technical_verification='full_decode_and_duration')
    core.save_json(folder/'bilan.json',summary)
    core.save_json(folder/'decoupage.json',timeline)
    synced=False
    try:
        core.n8n_request(dict(schema_version=1,action='report',job_id=job_id,summary=summary))
        synced=True
    except Exception:
        pass
    return dict(summary=summary,video=final.name,parameters=timeline['parameters'],n8n_synced=synced,
                warnings=['Export de la version validée. Écoute le MP4 et vérifie les raccords avant de le marquer comme vérifié.'])
