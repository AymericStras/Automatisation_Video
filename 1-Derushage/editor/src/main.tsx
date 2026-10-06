import React,{useEffect,useMemo,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Player,PlayerRef} from '@remotion/player';
import {AbsoluteFill,Html5Video,Sequence} from 'remotion';
import {Clip,Cut,Project,Segment,Source,cutPreview,pending,segments,validate} from './model';
import './style.css';

let token='';
async function api(path:string,body?:unknown){
  const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Derushage-Token':token},body:JSON.stringify(body)});
  const d=await r.json();if(!r.ok)throw Error(d.error||'Action impossible.');return d;
}
const seconds=(frames:number,fps:number)=>(frames/fps).toLocaleString('fr-FR',{minimumFractionDigits:2,maximumFractionDigits:3});

function Montage({parts,sources}:{parts:Segment[];sources:Source[]}){
  return <AbsoluteFill style={{backgroundColor:'#101b17'}}>{parts.map(s=><Sequence key={s.id} from={s.from} durationInFrames={s.frames} premountFor={10}>
    <Html5Video src={sources[s.source].url} trimBefore={s.start} durationInFrames={s.frames} pauseWhenBuffering
      style={{width:'100%',height:'100%',objectFit:'contain'}}/>
  </Sequence>)}</AbsoluteFill>;
}
function PlaybackInfo({player,parts,sources,fps,mode,ready}:{player:React.RefObject<PlayerRef|null>;parts:Segment[];sources:Source[];fps:number;mode:'montage'|'source';ready:boolean}){
  const [frame,setFrame]=useState(0);
  useEffect(()=>{
    const p=player.current;if(!p)return;
    setFrame(p.getCurrentFrame());
    const update=({detail}:{detail:{frame:number}})=>setFrame(detail.frame);
    p.addEventListener('frameupdate',update);
    return()=>p.removeEventListener('frameupdate',update);
  },[player,parts,ready]);
  const current=parts.find(s=>s.from<=frame&&frame<s.from+s.frames);
  const sourceFrame=current?current.start+frame-current.from:0;
  const total=parts.reduce((n,s)=>n+s.frames,0);
  return <div className="playback-info"><strong>{mode==='source'?'Prise entière':'Montage'} · {seconds(frame,fps)} / {seconds(total,fps)} s</strong><span>{current?sources[current.source].name:'—'} · source {seconds(sourceFrame,fps)} s</span></div>;
}
function TimeField({label,value,fps,onChange}:{label:string;value:number;fps:number;onChange:(n:number)=>void}){
  const [text,setText]=useState(String(Number((value/fps).toFixed(6))));
  useEffect(()=>setText(String(Number((value/fps).toFixed(6)))),[value,fps]);
  function commit(){const n=text.trim()===''?NaN:Number(text.replace(',','.'));onChange(Math.round(n*fps));setText(String(Number((value/fps).toFixed(6))));}
  return <label className="time-label">{label}<span className="time-input"><input aria-label={label} type="text" inputMode="decimal" value={text} onChange={e=>setText(e.target.value)} onBlur={commit} onKeyDown={e=>{if(e.key==='Enter')e.currentTarget.blur();}}/><span>s</span></span></label>;
}

function App(){
  const jobId=new URLSearchParams(location.search).get('project')||'';
  const [doc,setDoc]=useState<Project|null>(null),[saved,setSaved]=useState(''),[preview,setPreview]=useState({status:'preparing',message:'Ouverture du projet…'});
  const [error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[active,setActive]=useState(''),[mode,setMode]=useState<'montage'|'source'>('montage');
  const [undo,setUndo]=useState<Clip[][]>([]),[redo,setRedo]=useState<Clip[][]>([]),[quality,setQuality]=useState('preview');
  const [exportJob,setExportJob]=useState<any>(null),[notification,setNotification]=useState('');
  const player=useRef<PlayerRef>(null),stopAt=useRef<number|null>(null);
  const pendingSeek=useRef<{frame:number;stop?:number}|null>(null),[seekRequest,setSeekRequest]=useState(0);
  const [audition,setAudition]=useState<{clips:Clip[];parts:Segment[];label:string}|null>(null);
  const currentAudition=audition?.clips===doc?.clips?audition:null;
  const dirty=!!doc&&JSON.stringify(doc.clips)!==saved;
  const parts=useMemo(()=>doc?segments(doc):[],[doc?.clips,doc?.fps]);
  const clip=doc?.clips.find(c=>c.id===active)||doc?.clips[0];
  const selectedSource=doc&&clip?doc.sources[clip.source_index]:null;
  const sourceModeParts=useMemo(()=>clip&&selectedSource?[{id:'original-'+clip.id,clipId:clip.id,source:clip.source_index,start:0,frames:selectedSource.frames,from:0}]:[],[clip?.id,selectedSource]);
  const shownParts=mode==='source'?sourceModeParts:currentAudition?.parts??parts;
  const playerKey=mode==='source'?'source-'+clip?.id:'montage';
  const inputProps=useMemo(()=>({parts:shownParts,sources:doc?.sources??[]}),[shownParts,doc?.sources]);
  const total=shownParts.reduce((n,s)=>n+s.frames,0);
  const remaining=doc?pending(doc):0;
  const approved=!!doc&&!dirty&&doc.approved_revision===doc.revision;

  useEffect(()=>{
    let live=true;let timer:ReturnType<typeof setTimeout>;
    async function open(){try{
      if(!/^[a-f0-9-]{36}$/.test(jobId))throw Error('Sélectionne un projet depuis le formulaire de dérushage.');
      const cfg=await api('/api/config');token=cfg.csrf;
      const data=await api('/api/edit/'+jobId+'/open',{});
      if(!live)return;setDoc(data.project);setSaved(JSON.stringify(data.project.clips));setActive(data.project.clips[0].id);setPreview(data.preview);
      if(data.preview.status!=='ready'&&data.preview.status!=='failed')timer=setTimeout(poll,1300);
    }catch(e){if(live)setError(String((e as Error).message));}}
    async function poll(){try{
      const d=await api('/api/edit/'+jobId);if(!live)return;setPreview(d.preview);
      if(d.preview.status==='waiting'){const next=await api('/api/edit/'+jobId+'/open',{});if(live)setPreview(next.preview);}
      if(d.preview.status!=='ready'&&d.preview.status!=='failed')timer=setTimeout(poll,1300);
    }catch(e){if(live)setError((e as Error).message);}}
    open();return()=>{live=false;clearTimeout(timer);};
  },[jobId]);
  useEffect(()=>{const guard=(e:BeforeUnloadEvent)=>{if(dirty){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',guard);return()=>window.removeEventListener('beforeunload',guard);},[dirty]);
  useEffect(()=>{
    const p=player.current;if(!p)return;
    const update=({detail}:{detail:{frame:number}})=>{if(stopAt.current!==null&&detail.frame>=stopAt.current){p.pause();stopAt.current=null;}};
    p.addEventListener('frameupdate',update);return()=>p.removeEventListener('frameupdate',update);
  },[preview.status,mode,clip?.id]);
  useEffect(()=>{const p=player.current;if(!p)return;p.pause();stopAt.current=null;
    const request=pendingSeek.current;pendingSeek.current=null;
    p.seekTo(Math.max(0,Math.min(request?.frame??p.getCurrentFrame(),total-1)));
    if(request?.stop!==undefined){stopAt.current=request.stop;p.play();}
  },[shownParts,playerKey,preview.status,seekRequest]);
  useEffect(()=>{
    if(!exportJob||['completed','accepted','failed','cancelled','interrupted'].includes(exportJob.status))return;
    const timer=setTimeout(async()=>{try{setExportJob(await api('/api/jobs/'+exportJob.id));}catch(e){setError((e as Error).message);}},1500);
    return()=>clearTimeout(timer);
  },[exportJob]);
  useEffect(()=>{
    if(!doc?.approval_sync||doc.approval_sync.n8n_synced||doc.approval_sync.n8n_error)return;
    const timer=setTimeout(async()=>{try{const d=await api('/api/edit/'+jobId);setDoc(current=>current&&current.revision===d.project.revision?{...current,approval_sync:d.project.approval_sync}:current);}catch(e){setNotification('Le bilan n8n reste à vérifier.');}},2000);
    return()=>clearTimeout(timer);
  },[doc?.approval_sync,jobId]);

  function change(fn:(draft:Project)=>void){if(!doc||busy)return;try{
    const next=structuredClone(doc);fn(next);validate(next);
    if(JSON.stringify(next.clips)===JSON.stringify(doc.clips)){setError('');return;}
    player.current?.pause();setUndo([...undo.slice(-39),structuredClone(doc.clips)]);setRedo([]);setDoc(next);setError('');setNotice('');
  }catch(e){setError((e as Error).message);}}
  function patchClip(id:string,fn:(c:Clip)=>void){change(d=>fn(d.clips.find(c=>c.id===id)!));}
  function patchCut(clipId:string,id:string,fn:(p:Cut)=>void){patchClip(clipId,c=>fn(c.cuts.find(p=>p.id===id)!));}
  function move(id:string,by:number){change(d=>{const i=d.clips.findIndex(c=>c.id===id),j=i+by;if(j<0||j>=d.clips.length)return;[d.clips[i],d.clips[j]]=[d.clips[j],d.clips[i]];});}
  function history(back:boolean){if(!doc)return;const stack=back?undo:redo;if(!stack.length)return;const next=stack[stack.length-1];if(back){setUndo(stack.slice(0,-1));setRedo([...redo,doc.clips]);}else{setRedo(stack.slice(0,-1));setUndo([...undo,doc.clips]);}setDoc({...doc,clips:structuredClone(next)});setError('');}
  async function save(){if(!doc)return;setBusy(true);setError('');try{const d=await api('/api/edit/'+jobId+'/save',{revision:doc.revision,clips:doc.clips});setDoc(d);setSaved(JSON.stringify(d.clips));setNotice('Version '+d.revision+' sauvegardée.');}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function approve(){if(!doc)return;setBusy(true);setError('');try{const d=await api('/api/edit/'+jobId+'/approve',{revision:doc.revision});setDoc(d.project);setNotice('Montage validé. Tu peux demander son export.');setNotification('La validation est enregistrée localement et son bilan est envoyé à n8n.');}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function exportVideo(){if(!doc)return;setBusy(true);setError('');try{setExportJob(await api('/api/edit/'+jobId+'/export',{revision:doc.revision,quality}));}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function syncApproval(){setBusy(true);try{const result=await api('/api/edit/'+jobId+'/sync',{});setNotification(result.n8n_synced?'Bilan enregistré dans n8n.':'Bilan conservé localement. '+result.n8n_error);const d=await api('/api/edit/'+jobId);setDoc(current=>current?{...current,approval_sync:d.project.approval_sync}:current);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  function seekAfterSwitch(frame:number){setAudition(null);pendingSeek.current={frame};setSeekRequest(n=>n+1);}
  function inspect(c:Clip){setActive(c.id);setMode('source');seekAfterSwitch(0);}
  function playClip(c:Clip){setActive(c.id);setMode('montage');const s=parts.find(x=>x.clipId===c.id);if(s)seekAfterSwitch(s.from);}
  function playJoin(c:Clip,p:Cut){
    if(!doc)return;try{
      const result=cutPreview(doc,c.id,p.id);
      setActive(c.id);setMode('montage');setError('');
      setAudition({clips:doc.clips,parts:result.parts,label:doc.sources[c.source_index].name+' · pause '+(c.cuts.indexOf(p)+1)});
      pendingSeek.current={frame:result.start,stop:result.stop};setSeekRequest(n=>n+1);
    }catch(e){setError((e as Error).message);}
  }
  async function reload(){if(dirty&&!confirm('Recharger abandonnera les corrections non sauvegardées de cette fenêtre. Continuer ?'))return;try{const d=await api('/api/edit/'+jobId);setDoc(d.project);setSaved(JSON.stringify(d.project.clips));setUndo([]);setRedo([]);setError('');setNotice('Dernière version rechargée.');}catch(e){setError((e as Error).message);}}

  return <main>
    <header><div><a href="/" className="back">← Dossiers et versions</a><p className="eyebrow">ATELIER VIDÉO · MONTAGE CORRIGIBLE</p><h1>Le bon rythme<span>.</span></h1><p className="intro">Écoute, ajuste et garde la main sur chaque coupe.</p></div><span className={'badge '+(approved?'green':'')}>{dirty?'Modifications non sauvegardées':approved?'Montage validé':doc?'Version '+doc.revision+' · À vérifier':'Ouverture…'}</span></header>
    {error&&<div className="alert" role="alert">{error} <button onClick={reload}>Recharger la version sauvegardée</button></div>}
    {notice&&<p className="notice" role="status">{notice}</p>}
    {doc&&<>
      <div className="workspace">
        <section className="viewer card"><div className="section-head"><h2>01 · Écouter le montage</h2><span>{seconds(parts.reduce((n,s)=>n+s.frames,0),doc.fps)} s</span></div>
          <div className="tabs"><button aria-pressed={mode==='montage'} onClick={()=>{setMode('montage');seekAfterSwitch(0);}}>Montage</button><button aria-pressed={mode==='source'} onClick={()=>{setMode('source');seekAfterSwitch(0);}}>Prise entière</button></div>
          {currentAudition&&<p className="notice" role="status">Écoute de la coupe proposée : {currentAudition.label}. Ta décision reste inchangée. <button onClick={()=>seekAfterSwitch(0)}>Revenir au montage</button></p>}
          {preview.status==='ready'?<div className="stage"><Player key={playerKey} ref={player} component={Montage} inputProps={inputProps}
            durationInFrames={Math.max(1,total)} fps={doc.fps} compositionWidth={doc.sources[0].width} compositionHeight={doc.sources[0].height}
            style={{width:'100%',maxHeight:520,aspectRatio:`${doc.sources[0].width}/${doc.sources[0].height}`}} controls clickToPlay doubleClickToFullscreen showVolumeControls numberOfSharedAudioTags={0}/></div>
            :<div className="loading" role="status"><strong>{preview.status==='failed'?'Copie de lecture indisponible': 'Préparation de l’aperçu'}</strong><p>{preview.message}</p><p>Cette copie est créée une seule fois. Les prochaines corrections seront immédiates.</p>{preview.status==='failed'&&<button onClick={()=>location.reload()}>Réessayer</button>}</div>}
          <PlaybackInfo player={player} parts={shownParts} sources={doc.sources} fps={doc.fps} mode={mode} ready={preview.status==='ready'}/>
          <div className="transport"><button disabled={preview.status!=='ready'} onClick={()=>{const p=player.current;if(p)p.seekTo(Math.max(0,p.getCurrentFrame()-1));}}>← 1 image</button><button disabled={preview.status!=='ready'} onClick={()=>{const p=player.current;if(p)p.seekTo(Math.min(total-1,p.getCurrentFrame()+1));}}>1 image →</button></div>
          <p className="hint">« Prise entière » permet de retrouver un mot ou une respiration retirée. Les champs indiquent les temps dans le fichier source.</p>
          <div className="ribbon" aria-label="Ordre du montage">{doc.clips.map((c,i)=><button className={active===c.id?'selected':''} key={c.id} onClick={()=>playClip(c)} disabled={!c.enabled}>{i+1}<span>{doc.sources[c.source_index].name}</span></button>)}</div>
        </section>
        <section className="decisions"><div className="section-head"><h2>02 · Corriger les prises</h2><span>{doc.clips.length} prises · {remaining} proposition{remaining>1?'s':''} à décider</span></div>
          {remaining>0&&<p className="notice">Ce projet conserve encore des pauses détectées. <button className="primary" disabled={busy} onClick={()=>change(d=>{for(const c of d.clips)if(c.enabled)for(const p of c.cuts)if(p.decision==='pending'&&p.end>c.start&&p.start<c.end)p.decision='accepted';})}>Appliquer les {remaining} coupes proposées</button></p>}
          {doc.imported_from_render&&<p className="hint">Ce projet reprend les coupes du rendu précédent. Tu peux rétablir chaque pause ou en déplacer les limites.</p>}
          <div className="history-tools"><button disabled={!undo.length||busy} onClick={()=>history(true)}>↶ Annuler</button><button disabled={!redo.length||busy} onClick={()=>history(false)}>↷ Rétablir</button><button disabled={busy} onClick={reload}>Recharger</button></div>
          {doc.clips.map((c,i)=>{const s=doc.sources[c.source_index];return <article className={'clip card '+(active===c.id?'active ':'')+(!c.enabled?'excluded':'')} key={c.id}>
            <div className="clip-head"><button className="clip-name" onClick={()=>{setActive(c.id);playClip(c);}}><span className="number">{String(i+1).padStart(2,'0')}</span>{s.name}</button><div className="ordering"><button aria-label={'Monter '+s.name} disabled={i===0||busy} onClick={()=>move(c.id,-1)}>↑</button><button aria-label={'Descendre '+s.name} disabled={i===doc.clips.length-1||busy} onClick={()=>move(c.id,1)}>↓</button></div></div>
            <div className="clip-options"><label><input type="checkbox" checked={c.enabled} disabled={busy} onChange={e=>patchClip(c.id,x=>x.enabled=e.target.checked)}/> Garder cette prise</label><button onClick={()=>inspect(c)}>Voir la prise entière</button></div>
            <div className="times"><TimeField label={'Entrée · '+s.name} value={c.start} fps={doc.fps} onChange={n=>patchClip(c.id,x=>x.start=n)}/><TimeField label={'Sortie · '+s.name} value={c.end} fps={doc.fps} onChange={n=>patchClip(c.id,x=>x.end=n)}/></div>
            {mode==='source'&&active===c.id&&<div className="at-frame"><button onClick={()=>patchClip(c.id,x=>x.start=player.current?.getCurrentFrame()??0)}>Début à l’image affichée</button><button onClick={()=>patchClip(c.id,x=>x.end=Math.min(s.frames,(player.current?.getCurrentFrame()??0)+1))}>Fin après cette image</button></div>}
            <p className="hint">Source : {seconds(s.frames,doc.fps)} s · les limites se règlent à l’image près.</p>
            {c.cuts.length===0&&<p className="hint">Aucune longue pause proposée dans cette prise.</p>}
            {c.cuts.map((p,j)=><div className={'cut '+p.decision} key={p.id}><div className="cut-title"><strong>Pause {j+1} · {seconds(p.end-p.start,doc.fps)} s</strong><span>{p.decision==='accepted'?'Retirée':p.decision==='rejected'?'Conservée':'À décider · conservée dans l’aperçu'}</span></div>
              <div className="times"><TimeField label={'Début pause '+(j+1)+' · '+s.name} value={p.start} fps={doc.fps} onChange={n=>patchCut(c.id,p.id,x=>x.start=n)}/><TimeField label={'Fin pause '+(j+1)+' · '+s.name} value={p.end} fps={doc.fps} onChange={n=>patchCut(c.id,p.id,x=>x.end=n)}/></div>
              <div className="cut-actions"><button className={p.decision==='accepted'?'chosen':''} disabled={busy||!c.enabled} onClick={()=>patchCut(c.id,p.id,x=>x.decision='accepted')}>Accepter la coupe</button><button className={p.decision==='rejected'?'chosen':''} disabled={busy||!c.enabled} onClick={()=>patchCut(c.id,p.id,x=>x.decision='rejected')}>{p.decision==='accepted'?'Rétablir la pause':'Garder la pause'}</button><button disabled={preview.status!=='ready'||!c.enabled||p.end<=c.start||p.start>=c.end} onClick={()=>playJoin(c,p)}>Écouter le raccord</button></div>
              <button className="text-button" disabled={p.start===p.original_start&&p.end===p.original_end} onClick={()=>patchCut(c.id,p.id,x=>{x.start=x.original_start;x.end=x.original_end;})}>Revenir aux limites proposées</button>
            </div>)}
          </article>;})}
        </section>
      </div>
      <section className="savebar card"><div><h2>03 · Sauvegarder et valider</h2><p>Les corrections changent l’aperçu. L’export du MP4 est une action séparée.</p></div><div className="save-actions"><button className="primary" disabled={busy||!dirty} onClick={save}>Sauvegarder les corrections</button><button disabled={busy||dirty||remaining>0||approved||preview.status!=='ready'} onClick={approve}>J’ai vérifié ce montage · Valider</button></div><small>{remaining>0?'Décide des pauses restantes avant de valider.':dirty?'Sauvegarde avant de valider.':approved?'Cette version est validée. Une nouvelle correction demandera une nouvelle validation.':'Écoute les raccords puis valide cette version.'} {approved?notification:''}</small></section>
      {approved&&doc.approval_sync&&<p className="hint" role="status">{doc.approval_sync.n8n_synced?'Validation enregistrée dans n8n.':doc.approval_sync.n8n_error?'Bilan n8n non transmis. La validation est sauvegardée sur ce PC et l’export local reste disponible.':'Enregistrement du bilan dans n8n…'} {doc.approval_sync.n8n_error&&<button disabled={busy} onClick={syncApproval}>Renvoyer le bilan</button>}</p>}
      <section className="export card"><h2>04 · Exporter la version validée</h2><div className="export-controls"><label>Qualité du MP4<select value={quality} onChange={e=>setQuality(e.target.value)}><option value="preview">Aperçu léger · 1280 px</option><option value="full">Pleine résolution</option></select></label><button className="primary" disabled={busy||!approved} onClick={exportVideo}>Exporter le MP4</button><a href={'/projects/'+jobId+'/montage.json'} download>Projet JSON sauvegardé ↓</a></div>
        {exportJob&&<div role="status"><p><strong>Export de la version {exportJob.parent_revision}</strong> · {exportJob.message}</p>{!['completed','accepted','failed','cancelled','interrupted'].includes(exportJob.status)&&<progress max={100} value={exportJob.progress}/>}{exportJob.video&&<a className="primary" href={'/projects/'+exportJob.id+'/'+exportJob.video} download>Télécharger cet export ↓</a>}{exportJob.parent_revision!==doc.revision&&<p>Cet export appartient à une version précédente. Tes nouvelles corrections sont conservées.</p>}</div>}
      </section>
      <footer>Sources intactes · copies de lecture locales · historique des versions conservé</footer>
    </>}
  </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
