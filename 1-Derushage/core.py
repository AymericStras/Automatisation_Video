"""Dérushage local : inspection, silences, découpage traçable et rendu synchronisé."""
from __future__ import annotations
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import urllib.parse
import subprocess
import threading
import time
import urllib.error
import urllib.request
from fractions import Fraction

BASE = Path(__file__).resolve().parent
WORK = BASE / '.work'
PROJECTS = BASE / 'projets'
def media_tool(name):
    override = os.environ.get(name.upper() + '_PATH')
    local = BASE / 'bin' / (name + ('.exe' if os.name == 'nt' else ''))
    return Path(override or (str(local) if local.is_file() else shutil.which(name) or str(local)))


FFMPEG = media_tool('ffmpeg')
FFPROBE = media_tool('ffprobe')
EXTENSIONS = {'.mp4', '.mov', '.mkv', '.m4v', '.avi', '.webm'}
VERSION = '2.0.0'
DEFAULTS = dict(mode='shorten', quality='preview', min_pause=0.8,
                keep_pause=0.3, threshold_db=-35.0, trim_edges=True)
CREATE_FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class Cancelled(Exception):
    pass


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def config():
    path = BASE / 'config.json'
    if not path.is_file():
        raise ValueError('Copie config.example.json vers config.json et renseigne ton dossier et ton webhook n8n.')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def validate_parameters(value):
    if not isinstance(value, dict):
        raise ValueError('Réglages manquants.')
    p = {k: value.get(k, v) for k, v in DEFAULTS.items()}
    if p['mode'] not in ('assemble', 'shorten') or p['quality'] not in ('preview', 'full'):
        raise ValueError('Mode ou qualité inconnus.')
    for key, lower, upper in [('min_pause', .2, 5), ('keep_pause', .1, 1), ('threshold_db', -60, -10)]:
        if isinstance(p[key], bool):
            raise ValueError(f'Valeur incorrecte pour {key}.')
        p[key] = float(p[key])
        if not math.isfinite(p[key]) or not lower <= p[key] <= upper:
            raise ValueError(f'{key} doit être compris entre {lower} et {upper}.')
    if p['keep_pause'] >= p['min_pause']:
        raise ValueError('La respiration conservée doit être plus courte que la pause minimale.')
    if not isinstance(p['trim_edges'], bool):
        raise ValueError('Le réglage des débuts et fins doit être activé ou désactivé.')
    return p


def allowed_folder(value):
    if not isinstance(value, str) or not value.strip() or value.startswith(('\\\\', '//')):
        raise ValueError('Indique un dossier local de vidéos.')
    folder = Path(value).expanduser().resolve(strict=True)
    roots = [Path(p).resolve() for p in config()['allowed_roots']]
    if not folder.is_dir() or not any(folder.is_relative_to(root) for root in roots):
        raise ValueError('Ce dossier est hors des emplacements autorisés. Voir allowed_roots dans config.json.')
    return folder


def list_files(folder):
    folder = allowed_folder(folder)
    files = []
    for p in folder.iterdir():
        if p.is_file() and not p.is_symlink() and p.suffix.lower() in EXTENSIONS:
            files.append(dict(name=p.name, bytes=p.stat().st_size))
    if len(files) > 500:
        raise ValueError('Ce dossier contient plus de 500 vidéos : choisis un sous-dossier.')
    return sorted(files, key=lambda f: f['name'].upper())


def selected_paths(folder, names):
    folder = allowed_folder(folder)
    if not isinstance(names, list) or not 1 <= len(names) <= 100:
        raise ValueError('Sélectionne entre 1 et 100 vidéos.')
    result, seen = [], set()
    for name in names:
        if not isinstance(name, str) or re.search(r'[\\/:\x00]', name) or Path(name).name != name:
            raise ValueError('Nom de fichier incorrect.')
        path = (folder / name).resolve(strict=True)
        if path.parent != folder or not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            raise ValueError(f'Vidéo inaccessible : {name}')
        if name.upper() in seen:
            raise ValueError('Une vidéo est sélectionnée deux fois.')
        seen.add(name.upper())
        result.append(path)
    return sorted(result, key=lambda p: p.name.upper())


def probe(path):
    result = subprocess.run([str(FFPROBE), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45,
                            creationflags=CREATE_FLAGS)
    if result.returncode:
        raise ValueError(f'Lecture impossible : {Path(path).name}. {result.stderr[-800:]}')
    data = json.loads(result.stdout)
    video = next((s for s in data['streams'] if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic')), None)
    audio = next((s for s in data['streams'] if s['codec_type'] == 'audio'), None)
    if not video or not audio:
        raise ValueError(f'{Path(path).name} doit contenir une piste vidéo et une piste audio.')
    duration = float(video.get('duration') or data['format']['duration'])
    fps = Fraction(video.get('avg_frame_rate') or video['r_frame_rate'])
    if duration <= 0 or duration > 3600 or not 1 <= float(fps) <= 120:
        raise ValueError(f'Durée ou cadence non prise en charge : {Path(path).name}.')
    rotation = next((s['rotation'] for s in video.get('side_data_list', []) if 'rotation' in s), 0)
    w, h = video['width'], video['height']
    if abs(round(rotation)) % 180 == 90:
        w, h = h, w
    if video.get('color_transfer') in ('smpte2084', 'arib-std-b67'):
        raise ValueError('Cette V1 traite les vidéos SDR ; la conversion HDR doit être définie avant cet export.')
    # Un décalage initial important doit être traité explicitement, jamais supprimé implicitement.
    if abs(float(video.get('start_time', 0)) - float(audio.get('start_time', 0))) > .05:
        raise ValueError(f'{Path(path).name} présente un décalage initial audio/vidéo supérieur à 50 ms.')
    return dict(name=Path(path).name, path=str(Path(path).resolve()), duration=duration,
                width=w, height=h, fps=str(fps), rotation=rotation, codec=video['codec_name'],
                pixel_format=video.get('pix_fmt'), bytes=Path(path).stat().st_size,
                audio_duration=float(audio.get('duration') or data['format']['duration']),
                audio_channels=audio['channels'])


def fingerprint(path):
    path = Path(path)
    before = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f'{path.name} a changé pendant la lecture. Recommence après la copie du fichier.')
    return dict(sha256=digest, size=after.st_size, mtime_ns=after.st_mtime_ns)


def run_ffmpeg(args, log, cancel=None, timeout=900):
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with log.open('w', encoding='utf-8') as errors:
        proc = subprocess.Popen([str(FFMPEG), '-hide_banner', '-nostdin', '-nostats', *map(str, args)],
                                stdout=subprocess.DEVNULL, stderr=errors, creationflags=CREATE_FLAGS)
        try:
            while True:
                if cancel and cancel.is_set():
                    raise Cancelled('Traitement annulé. Les sources et le découpage sont conservés.')
                if time.monotonic() - started > timeout:
                    raise TimeoutError('Le traitement a dépassé son délai. Le journal conserve l’étape concernée.')
                try:
                    code = proc.wait(timeout=.25)
                    break
                except subprocess.TimeoutExpired:
                    pass
        except BaseException:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            raise
    if code:
        tail = log.read_text(encoding='utf-8', errors='replace')[-1800:]
        raise RuntimeError(f'FFmpeg a échoué. Journal : {log.name}\n{tail}')


def detect_silences(source, threshold_db, cancel=None):
    key = hashlib.sha256(f"silence-v1:{source['fingerprint']['sha256']}:{threshold_db}".encode()).hexdigest()
    cache = WORK / 'cache' / (key + '.json')
    if cache.exists():
        return json.loads(cache.read_text(encoding='utf-8'))['silences']
    log = WORK / 'cache' / (key + '.log')
    run_ffmpeg(['-i', source['path'], '-map', '0:a:0', '-vn', '-af',
                f'silencedetect=noise={threshold_db}dB:d=0.05', '-f', 'null', os.devnull], log, cancel)
    text = log.read_text(encoding='utf-8', errors='replace')
    intervals, start = [], None
    for match in re.finditer(r'silence_(start|end):\s*(-?\d+(?:\.\d+)?)', text):
        kind, value = match.group(1), float(match.group(2))
        if kind == 'start':
            start = max(0., value)
        elif start is not None:
            intervals.append([start, min(source['duration'], value)])
            start = None
    if start is not None:
        intervals.append([start, source['duration']])
    intervals = [[a, b] for a, b in intervals if b > a]
    save_json(cache, dict(silences=intervals, threshold_db=threshold_db))
    return intervals


def make_timeline(sources, parameters):
    p = validate_parameters(parameters)
    total = sum(s['duration'] for s in sources)
    fps = float(Fraction(sources[0]['fps']))
    silence, offset = [], 0.
    for s in sources:
        for a, b in s.get('silences', []):
            a, b = offset + a, offset + b
            if silence and a <= silence[-1][1] + .0001:
                silence[-1][1] = max(b, silence[-1][1])
            else:
                silence.append([a, b])
        offset += s['duration']
    cuts = []
    if p['mode'] == 'shorten':
        if len(silence) == 1 and silence[0][0] < .05 and silence[0][1] >= total - .05:
            raise ValueError('Tout le son est sous le seuil choisi. Diminue la sensibilité (seuil plus négatif) ou assemble sans couper.')
        for a, b in silence:
            is_start, is_end = a < .0001, b > total - .0001
            if b - a < p['min_pause'] or ((is_start or is_end) and not p['trim_edges']):
                continue
            left = a if is_start else a + p['keep_pause'] / 2
            right = b if is_end else b - p['keep_pause'] / 2
            # Retirer moins plutôt que déborder sur la parole : arrondi des coupes vers l’intérieur.
            left = math.ceil(left * fps - 1e-7) / fps
            right = math.floor(right * fps + 1e-7) / fps
            if right - left >= 1 / fps:
                cuts.append(dict(start=left, end=right, detected_start=a, detected_end=b,
                                 removed_seconds=right-left))
    keep, cursor = [], 0.
    for cut in cuts:
        if cut['start'] > cursor:
            keep.append((cursor, cut['start']))
        cursor = cut['end']
    if cursor < total:
        keep.append((cursor, total))
    segments, offset, target = [], 0., 0.
    for source_index, s in enumerate(sources):
        for a, b in keep:
            lo, hi = max(a, offset), min(b, offset + s['duration'])
            if hi <= lo + 1e-7:
                continue
            frames = max(1, round((hi-lo) * fps))
            duration = frames / fps
            segments.append(dict(source_index=source_index, source=s['name'],
                                 source_start=round(lo-offset, 6), source_end=round(hi-offset, 6),
                                 output_start=round(target, 6), output_end=round(target+duration, 6),
                                 frames=frames))
            target += duration
        offset += s['duration']
    if len(segments) > 500:
        raise ValueError('Plus de 500 segments : augmente la durée minimale des pauses.')
    if not segments:
        raise ValueError('Aucun segment à conserver avec ces réglages.')
    return dict(schema_version=1, engine_version=VERSION, parameters=p, sources=sources,
                input_seconds=round(total, 6), planned_output_seconds=round(target, 6),
                detected_silences=silence, cuts=cuts, segments=segments, fps=sources[0]['fps'])


def write_cut_csv(path, segments):
    with Path(path).open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=['source_index','source','source_start','source_end','output_start','output_end','frames'], delimiter=';')
        writer.writeheader()
        writer.writerows(segments)


def validate_n8n_endpoint(settings):
    endpoint = settings.get('n8n_webhook', '')
    if not isinstance(endpoint, str):
        raise ValueError('Le webhook n8n doit être une adresse HTTPS de production.')
    url = urllib.parse.urlsplit(endpoint.strip())
    expected = urllib.parse.urlsplit(settings.get('workflow_url', ''))
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or not url.path.startswith('/webhook/') or not url.path[len('/webhook/'):]
            or url.query or url.fragment):
        raise ValueError('Dans config.json, utilise la Production URL du nœud Webhook : https://ton-instance/webhook/…')
    if expected.scheme != 'https' or url.netloc.lower() != expected.netloc.lower():
        raise ValueError('n8n_webhook et workflow_url doivent désigner la même instance HTTPS dans config.json.')
    return endpoint.strip()


def n8n_request(payload):
    endpoint = validate_n8n_endpoint(config())
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
    for attempt in range(2):
        try:
            req = urllib.request.Request(endpoint, data=encoded, headers={'Content-Type':'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=25) as response:
                result = json.load(response)
            if not result.get('ok'):
                raise ValueError(result.get('error', 'n8n a refusé la demande.'))
            return result
        except urllib.error.HTTPError as error:
            try:
                body = json.loads(error.read())
            except Exception:
                body = {}
            if error.code < 500:
                raise ValueError(body.get('error', f'n8n répond HTTP {error.code}. Vérifie que Dérushage est publié.')) from error
            if attempt:
                raise ConnectionError(f'n8n indisponible (HTTP {error.code}). Reprends le même projet.') from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            if attempt:
                raise ConnectionError('Connexion à n8n impossible. Vérifie Internet et reprends le même projet.') from error
        time.sleep(.5)


def render(timeline, job_id, progress, cancel):
    scratch = WORK / 'jobs' / job_id
    scratch.mkdir(parents=True, exist_ok=True)
    p, sources = timeline['parameters'], timeline['sources']
    w, h = sources[0]['width'], sources[0]['height']
    if p['quality'] == 'preview':
        ratio = min(1., 1280 / max(w, h))
        w, h = max(2, round(w*ratio/2)*2), max(2, round(h*ratio/2)*2)
    else:
        w, h = w//2*2, h//2*2
    timeline['export'] = dict(width=w, height=h, codec='H.264', pixel_format='yuv420p', fps=timeline['fps'])
    fps = str(Fraction(timeline['fps']))
    pieces = []
    # Conserver l'ordre édité, y compris A → B → A. Ne jamais regrouper par fichier.
    groups = []
    for seg in timeline['segments']:
        source = sources[seg['source_index']]
        if groups and groups[-1][1] is source:
            groups[-1][2].append(seg)
        else:
            groups.append((len(groups), source, [seg]))
    for i, source, segments in groups:
        if not segments:
            continue
        if cancel.is_set():
            raise Cancelled('Traitement annulé.')
        progress('rendering', f"Assemblage {i+1}/{len(groups)} · {source['name']}", 30+55*i/len(groups))
        signature = hashlib.sha256(json.dumps([VERSION,source['fingerprint'],segments,w,h,fps,p['quality']], sort_keys=True).encode()).hexdigest()
        piece = scratch / f'{i:04d}-{signature[:12]}.mkv'
        if not piece.exists():
            graph, labels = [], []
            for j, seg in enumerate(segments):
                start, end = seg['source_start'], seg['source_end']
                duration = seg['frames'] / float(Fraction(fps))
                graph.append(f'[0:v:0]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,'
                             f'scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                             f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},'
                             f'tpad=stop_mode=clone:stop_duration=0.1,trim=end_frame={seg["frames"]},'
                             f'setpts=PTS-STARTPTS,format=yuv420p[v{j}]')
                graph.append(f'[0:a:0]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,'
                             f'aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,apad,'
                             f'atrim=duration={duration:.6f},afade=t=in:d=0.003,'
                             f'afade=t=out:st={max(0,duration-.003):.6f}:d=0.003[a{j}]')
                labels.append(f'[v{j}][a{j}]')
            graph.append(''.join(labels)+f'concat=n={len(segments)}:v=1:a=1[v][a]')
            script = scratch / f'filters-{i:04d}.txt'
            script.write_text(';\n'.join(graph), encoding='utf-8')
            temp = piece.with_suffix('.partial.mkv')
            run_ffmpeg(['-y','-threads','4','-i',source['path'],'-filter_complex_threads','2',
                        '-/filter_complex',str(script),'-map','[v]','-map','[a]',
                        '-map_metadata','-1','-c:v','libx264','-preset','veryfast','-crf',
                        '23' if p['quality']=='preview' else '17','-threads','4','-pix_fmt','yuv420p',
                        '-c:a','pcm_s16le','-metadata:s:v:0','rotate=0',str(temp)],
                       scratch / f'render-{i:04d}.log',cancel,timeout=1800)
            info = probe(temp)
            expected = sum(seg['frames'] for seg in segments) / float(Fraction(fps))
            if abs(info['duration']-expected) > .06 or (info['width'],info['height']) != (w,h):
                raise RuntimeError(f'Durée ou dimensions inattendues après le rendu de {source["name"]}.')
            os.replace(temp,piece)
        pieces.append(piece)
    listing = scratch / 'concat.txt'
    listing.write_text('\n'.join(f"file '{x.name}'" for x in pieces),encoding='utf-8')
    final = PROJECTS / job_id / ('apercu.mp4' if p['quality']=='preview' else 'pleine-resolution.mp4')
    temp = final.with_suffix('.partial.mp4')
    progress('rendering','Assemblage final et encodage audio',88)
    run_ffmpeg(['-y','-f','concat','-safe','1','-i',str(listing),'-map','0:v:0','-map','0:a:0',
                '-map_metadata','-1','-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',str(temp)],
               scratch/'concat.log',cancel)
    progress('verifying','Vérification du fichier vidéo et de sa durée',94)
    info = probe(temp)
    if abs(info['duration']-timeline['planned_output_seconds']) > .1 or abs(info['audio_duration']-info['duration']) > .1:
        raise RuntimeError('La durée ou la synchronisation du fichier final dépasse la tolérance de 100 ms.')
    run_ffmpeg(['-v','error','-xerror','-threads','4','-i',str(temp),'-map','0:v:0','-map','0:a:0','-f','null',os.devnull],
               scratch/'verification.log',cancel,timeout=900)
    for source in sources:
        stat = Path(source['path']).stat()
        if (stat.st_size,stat.st_mtime_ns) != (source['fingerprint']['size'],source['fingerprint']['mtime_ns']):
            raise RuntimeError(f"Le rush {source['name']} a été modifié pendant le traitement.")
    os.replace(temp,final)
    return final, info


def process_job(job_id, request, progress, cancel):
    started = time.monotonic()
    folder = PROJECTS / job_id
    folder.mkdir(parents=True,exist_ok=True)
    p = validate_parameters(request['parameters'])
    paths = selected_paths(request['folder'],request['files'])
    sources = []
    for index,path in enumerate(paths):
        if cancel.is_set():
            raise Cancelled('Traitement annulé.')
        progress('inspecting',f'Lecture de {path.name}',2+8*index/len(paths))
        source=probe(path)
        source['fingerprint']=fingerprint(path)
        sources.append(source)
    if sum(s['duration'] for s in sources)>3600:
        raise ValueError('Cette V1 accepte au plus une heure de rushs par projet.')
    remote_request=dict(schema_version=1,action='plan',job_id=job_id,
                        files=[{k:s[k] for k in ('name','duration','width','height','fps')} for s in sources],parameters=p)
    save_json(folder/'demande-n8n.json',remote_request)
    progress('planning','n8n valide les paramètres et ordonne les vidéos',12)
    plan=n8n_request(remote_request)
    if plan.get('job_id')!=job_id or plan.get('schema_version')!=1 or plan.get('ordered_names')!=[s['name'] for s in sources] or plan.get('parameters')!=p:
        raise RuntimeError('Le plan retourné par n8n ne correspond pas à la sélection et aux réglages demandés.')
    save_json(folder/'plan-n8n.json',plan)
    for index,source in enumerate(sources):
        progress('analyzing',f"Analyse des pauses · {source['name']}",15+15*index/len(sources))
        source['silences']=detect_silences(source,p['threshold_db'],cancel) if p['mode']=='shorten' else []
    timeline=make_timeline(sources,p)
    save_json(folder/'decoupage.json',timeline)
    write_cut_csv(folder/'decoupage.csv',timeline['segments'])
    if request.get('prepare_only'):
        import editing
        editing.initialize(job_id,pending=True)
        return dict(prepared=True,parameters=p,ordered_names=[s['name'] for s in sources],
                    warnings=[],n8n_synced=True)
    final,info=render(timeline,job_id,progress,cancel)
    timeline['output_seconds']=info['duration']
    save_json(folder/'decoupage.json',timeline)
    summary=dict(status='completed',files_count=len(sources),input_seconds=timeline['input_seconds'],
                 output_seconds=info['duration'],removed_seconds=round(timeline['input_seconds']-info['duration'],3),
                 cuts_count=len(timeline['cuts']),segments_count=len(timeline['segments']),
                 processing_seconds=round(time.monotonic()-started,2),bytes=final.stat().st_size,
                 width=info['width'],height=info['height'],fps=info['fps'],quality=p['quality'],
                 reviewed=False,technical_verification='full_decode_and_duration')
    save_json(folder/'bilan.json',summary)
    result=dict(summary=summary,video=final.name,parameters=p,ordered_names=[s['name'] for s in sources],
                n8n_synced=False,warnings=[])
    if summary['removed_seconds']>summary['input_seconds']*.5:
        result['warnings'].append('Plus de la moitié de la durée a été retirée : vérifie les coupes et diminue la sensibilité si nécessaire.')
    result['warnings'].append('Le fichier a passé les contrôles techniques. Écoute les raccords avant de le marquer comme vérifié.')
    try:
        n8n_request(dict(schema_version=1,action='report',job_id=job_id,summary=summary))
        result['n8n_synced']=True
    except Exception as error:
        result['warnings'].append('Vidéo prête ; bilan n8n en attente. '+str(error))
    return result
