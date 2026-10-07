"""Formulaire et worker local. Écoute uniquement sur 127.0.0.1."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import threading
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import core
import editing

SETTINGS = core.config()
PORT = SETTINGS.get('port', 8765)
ORIGIN = f'http://127.0.0.1:{PORT}'
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
JOBS = {}
CANCEL = {}
ACTIVE = None


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def persist(job):
    job['updated_at'] = now()
    core.save_json(core.PROJECTS / job['id'] / 'etat.json',job)


def public_job(job):
    return {k:v for k,v in job.items() if k!='request'}


def worker(job_id):
    global ACTIVE
    with LOCK:
        job=JOBS[job_id]
        request=job['request']
    def progress(status,message,percent):
        with LOCK:
            job.update(status=status,message=message,progress=round(percent))
            persist(job)
    try:
        result=(editing.export_job if request.get('kind')=='edited' else core.process_job)(job_id,request,progress,CANCEL[job_id])
        with LOCK:
            job.update(result,status='prepared' if result.get('prepared') else 'completed',
                       message='Coupes prêtes à corriger' if result.get('prepared') else 'Vidéo prête à relire',progress=100,error=None)
            persist(job)
    except Exception as error:
        status='cancelled' if isinstance(error,core.Cancelled) else 'failed'
        with LOCK:
            job.update(status=status,message=str(error).split('\n')[0],error=str(error),progress=0)
            persist(job)
        # La reprise garde le même identifiant et les fichiers locaux déjà calculés.
        try:
            summary=dict(status='failed',files_count=len(request.get('files',[])),input_seconds=0,output_seconds=0,
                         error=type(error).__name__,cancelled=(status=='cancelled'))
            core.n8n_request(dict(schema_version=1,action='report',job_id=job_id,summary=summary))
        except Exception:
            pass
    finally:
        with LOCK:
            ACTIVE=None


def start_job(request, job_id=None):
    global ACTIVE
    parameters=core.validate_parameters(request.get('parameters'))
    paths=core.selected_paths(request.get('folder'),request.get('files'))
    request=dict(folder=str(paths[0].parent),files=[p.name for p in paths],parameters=parameters,
                 prepare_only=request.get('prepare_only',False) is True)
    with LOCK:
        if ACTIVE:
            raise ValueError('Un traitement est déjà en cours. Attends sa fin ou annule-le.')
        job_id=job_id or str(uuid.uuid4())
        if job_id in JOBS and JOBS[job_id]['status'] not in ('failed','cancelled','interrupted'):
            raise ValueError('Ce projet est déjà terminé ou en cours.')
        job=JOBS.get(job_id) or dict(id=job_id,created_at=now(),reviewed=False)
        job.update(status='queued',message='Préparation du projet',progress=0,request=request,
                   error=None,parameters=parameters,ordered_names=request['files'])
        JOBS[job_id]=job
        core.save_json(core.PROJECTS/job_id/'demande-locale.json',request)
        persist(job)
        ACTIVE=job_id
        CANCEL[job_id]=threading.Event()
        threading.Thread(target=worker,args=(job_id,),daemon=True).start()
        return public_job(job)


def start_edited_export(parent_id, value, resume_id=None):
    global ACTIVE
    with LOCK:
        if resume_id:
            job=JOBS[resume_id]
            if job['status'] not in ('failed','cancelled','interrupted'):
                raise ValueError('Cet export ne demande pas de reprise.')
            request=job['request']
        else:
            timeline=editing.approved_snapshot(parent_id,value.get('revision'),value.get('quality','preview'))
            for previous in JOBS.values():
                r=previous.get('request',{})
                if (r.get('kind')=='edited' and r.get('parent_id')==parent_id and
                    r['timeline']['parent_revision']==timeline['parent_revision'] and
                    r['parameters']['quality']==timeline['parameters']['quality'] and
                    previous['status'] not in ('failed','cancelled','interrupted')):
                    return public_job(previous)
            request=dict(kind='edited',parent_id=parent_id,timeline=timeline,parameters=timeline['parameters'])
            job=dict(id=str(uuid.uuid4()),created_at=now(),reviewed=False,request=request,
                     parameters=request['parameters'],parent_id=parent_id,parent_revision=timeline['parent_revision'],
                     ordered_names=[s['source'] for s in timeline['segments']])
        if ACTIVE:
            raise ValueError('Un traitement est déjà en cours. Attends sa fin ou annule-le.')
        job.update(status='queued',message='Export de la version validée',progress=0,error=None)
        JOBS[job['id']]=job
        core.save_json(core.PROJECTS/job['id']/'demande-locale.json',request)
        persist(job)
        ACTIVE=job['id']
        CANCEL[job['id']]=threading.Event()
        threading.Thread(target=worker,args=(job['id'],),daemon=True).start()
        return public_job(job)


class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args):
        pass

    def send(self,value,status=200):
        body=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        self.wfile.write(body)

    def host_ok(self):
        return self.headers.get('Host') in (f'127.0.0.1:{PORT}',f'localhost:{PORT}')

    def serve_file(self,path):
        size=path.stat().st_size
        start,end=0,size-1
        range_header=self.headers.get('Range')
        status=200
        if range_header:
            match=re.fullmatch(r'bytes=(\d+)-(\d*)',range_header)
            if not match:
                self.send({'error':'Plage invalide'},416)
                return
            start=int(match[1])
            end=min(size-1,int(match[2]) if match[2] else size-1)
            if start> end or start>=size:
                self.send({'error':'Plage invalide'},416)
                return
            status=206
        self.send_response(status)
        self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length',str(end-start+1))
        self.send_header('Accept-Ranges','bytes')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; media-src 'self' blob:; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'")
        if status==206:
            self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as stream:
            stream.seek(start)
            left=end-start+1
            while left:
                chunk=stream.read(min(left,1024*1024))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left-=len(chunk)

    def do_GET(self):
        try:
            if not self.host_ok():
                self.send({'error':'Hôte interdit.'},403)
                return
            parsed=urllib.parse.urlsplit(self.path)
            path=urllib.parse.unquote(parsed.path)
            if path=='/api/config':
                self.send(dict(app='derushage-local',version=core.VERSION,csrf=TOKEN,
                               default_folder=SETTINGS['default_folder'],default_files=SETTINGS['default_files'],
                               defaults=core.DEFAULTS,workflow_url=SETTINGS['workflow_url']))
            elif path=='/api/jobs':
                with LOCK:
                    jobs=sorted(JOBS.values(),key=lambda j:j['created_at'],reverse=True)
                    self.send(dict(jobs=[public_job(j) for j in jobs],active=ACTIVE))
            elif re.fullmatch(r'/api/edit/[a-f0-9-]{36}',path):
                job_id=path.rsplit('/',1)[1]
                if job_id not in JOBS or not editing.project_path(job_id).exists():
                    raise ValueError('Ouvre d’abord ce projet depuis le formulaire.')
                self.send(dict(project=editing.public(editing.read(job_id)),preview=editing.PREVIEWS.get(job_id,{'status':'waiting','message':'Préparer l’aperçu'})))
            elif re.fullmatch(r'/media/[a-f0-9-]{36}/\d+\.mp4',path):
                _,_,job_id,index=path.split('/')
                if job_id not in JOBS:
                    raise ValueError('Projet inconnu.')
                doc=editing.read(job_id)
                index=int(index[:-4])
                if not 0<=index<len(doc['sources']):
                    raise ValueError('Source inconnue.')
                file=editing.proxy_path(doc,index)
                if not file.is_file():
                    self.send({'error':'Copie de lecture en préparation.'},404)
                    return
                self.serve_file(file)
            elif path.startswith('/api/jobs/'):
                job_id=path.rsplit('/',1)[1]
                with LOCK:
                    if job_id not in JOBS:
                        self.send({'error':'Projet introuvable.'},404)
                    else:
                        self.send(public_job(JOBS[job_id]))
            elif path=='/edit':
                self.serve_file(core.BASE/'static'/'editor'/'index.html')
            elif path in ('/editor/editor.js','/editor/editor.css','/editor/editor.js.LEGAL.txt'):
                self.serve_file(core.BASE/'static'/path.lstrip('/'))
            elif path in ('/','/app.js','/style.css'):
                self.serve_file(core.BASE/'static'/('index.html' if path=='/' else path[1:]))
            elif path.startswith('/projects/'):
                parts=path.strip('/').split('/')
                allowed={'apercu.mp4','pleine-resolution.mp4','decoupage.json','decoupage.csv','bilan.json','montage.json'}
                if len(parts)!=3 or parts[1] not in JOBS or parts[2] not in allowed:
                    self.send({'error':'Fichier introuvable.'},404)
                    return
                file=core.PROJECTS/parts[1]/parts[2]
                if not file.is_file():
                    self.send({'error':'Fichier pas encore disponible.'},404)
                    return
                self.serve_file(file)
            else:
                self.send({'error':'Adresse inconnue.'},404)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
            pass
        except Exception as error:
            self.send({'error':str(error)},500)

    def do_POST(self):
        try:
            if (not self.host_ok() or self.headers.get('X-Derushage-Token')!=TOKEN or
                self.headers.get('Origin',ORIGIN) not in (ORIGIN,f'http://localhost:{PORT}')):
                self.send({'error':'Ouvre le formulaire local pour effectuer cette action.'},403)
                return
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=131072:
                self.send({'error':'Demande invalide.'},400)
                return
            value=json.loads(self.rfile.read(length))
            path=urllib.parse.urlsplit(self.path).path
            if path=='/api/files':
                self.send(dict(files=core.list_files(value.get('folder'))))
            elif path=='/api/jobs':
                self.send(start_job(value),202)
            elif re.fullmatch(r'/api/edit/[a-f0-9-]{36}/(open|save|approve|export|sync)',path):
                _,_,_,job_id,action=path.split('/')
                if job_id not in JOBS:
                    raise ValueError('Projet introuvable.')
                if action=='open':
                    if JOBS[job_id]['status'] not in ('prepared','completed','accepted'):
                        raise ValueError('Préparation non terminée : '+JOBS[job_id]['message'])
                    self.send(editing.open_editor(job_id))
                elif action=='save':
                    self.send(editing.save(job_id,value))
                elif action=='approve':
                    result=editing.approve(job_id,value.get('revision'))
                    self.send(dict(project=result,notification='pending'))
                    threading.Thread(target=editing.notify_approval,args=(job_id,value.get('revision')),daemon=True).start()
                elif action=='sync':
                    self.send(editing.notify_approval(job_id))
                elif action=='export':
                    self.send(start_edited_export(job_id,value),202)
            elif path=='/api/shutdown':
                with LOCK:
                    if ACTIVE or any(v['status']=='preparing' for v in editing.PREVIEWS.values()):
                        raise ValueError('Annule ou termine le traitement avant de fermer le moteur.')
                self.send({'ok':True})
                threading.Thread(target=self.server.shutdown,daemon=True).start()
            else:
                match=re.fullmatch(r'/api/jobs/([a-f0-9-]{36})/(cancel|resume|sync|review|folder)',path)
                if not match or match[1] not in JOBS:
                    self.send({'error':'Projet introuvable.'},404)
                    return
                job_id,action=match.groups()
                with LOCK:
                    job=JOBS[job_id]
                if action=='cancel':
                    if ACTIVE==job_id:
                        CANCEL[job_id].set()
                    self.send({'ok':True})
                elif action=='resume':
                    self.send(start_edited_export(job['request']['parent_id'],{},job_id) if job['request'].get('kind')=='edited' else start_job(job['request'],job_id),202)
                elif action=='folder':
                    os.startfile(core.PROJECTS/job_id)
                    self.send({'ok':True})
                elif action in ('sync','review'):
                    if job['status'] not in ('completed','accepted'):
                        raise ValueError('Le projet doit être terminé pour cette action.')
                    if action=='review':
                        with LOCK:
                            job.update(reviewed=True,status='accepted',message='Vidéo vérifiée par toi')
                            job['summary'].update(reviewed=True,status='accepted')
                            persist(job)
                            core.save_json(core.PROJECTS/job_id/'bilan.json',job['summary'])
                    try:
                        core.n8n_request(dict(schema_version=1,action='report',job_id=job_id,summary=job['summary']))
                        with LOCK:
                            job['n8n_synced']=True
                            persist(job)
                    except Exception as error:
                        with LOCK:
                            job['n8n_synced']=False
                            persist(job)
                        self.send({'error':str(error)},502)
                        return
                    self.send(public_job(job))
        except editing.Conflict as error:
            self.send({'error':str(error)},409)
        except (ValueError,FileNotFoundError,NotADirectoryError) as error:
            self.send({'error':str(error)},400)
        except Exception as error:
            self.send({'error':str(error)},500)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--open-browser',action='store_true')
    args=parser.parse_args()
    core.PROJECTS.mkdir(parents=True,exist_ok=True)
    for state in core.PROJECTS.glob('*/etat.json'):
        try:
            job=json.loads(state.read_text(encoding='utf-8'))
            if job['status'] not in ('completed','accepted','prepared','failed','cancelled','interrupted'):
                job.update(status='interrupted',message='Traitement interrompu ; tu peux le reprendre.',progress=0)
                persist(job)
            JOBS[job['id']]=job
        except (ValueError,KeyError):
            continue
    try:
        server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    except OSError:
        try:
            with urllib.request.urlopen(ORIGIN+'/api/config',timeout=3) as response:
                existing=json.load(response)
            if existing.get('app')=='derushage-local':
                if args.open_browser:
                    webbrowser.open(ORIGIN)
                return
        except Exception:
            pass
        raise RuntimeError(f'Le port {PORT} est déjà occupé. Modifie port dans config.json.')
    if args.open_browser:
        threading.Timer(.5,lambda:webbrowser.open(ORIGIN)).start()
    print(f'Dérushage local : {ORIGIN}',flush=True)
    server.serve_forever(poll_interval=.25)
    server.server_close()


if __name__=='__main__':
    main()
