'use strict';
const $ = id => document.getElementById(id);
let cfg, available = [], selected = new Set(), jobs = [], currentId = null, activeId = null, showingVideo = null;
let timer, stopped = false, historySignature = '';
const fmt = n => Number(n).toLocaleString('fr-FR', {maximumFractionDigits: 2});
const bytes = n => n >= 1e9 ? fmt(n/1e9)+' Go' : fmt(n/1e6)+' Mo';
const finished = status => ['completed','accepted'].includes(status);
const labelStatus = status => ({prepared:'Coupes à corriger',completed:'À relire',accepted:'Vérifiée',failed:'Erreur',cancelled:'Annulé',interrupted:'À reprendre'}[status] || 'En cours');
function error(message) { $('error').textContent = message || ''; $('error').hidden = !message; }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Derushage-Token':cfg.csrf},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Une erreur est survenue.');
  return data;
}
function parameters() {
  return {mode:$('mode').value,quality:$('quality').value,min_pause:Number($('min-pause').value),keep_pause:Number($('keep-pause').value),threshold_db:Number($('threshold').value),trim_edges:$('trim-edges').checked};
}
function remember() {
  localStorage.setItem('derushage-v1',JSON.stringify({folder:$('folder').value,files:[...selected],parameters:parameters()}));
}
function displaySettings() {
  $('silence-settings').hidden = $('mode').value === 'assemble';
  $('threshold-value').textContent = $('threshold').value+' dB';
  $('launch').textContent = 'Préparer les coupes →';
  $('launch').disabled = Boolean(activeId) || !selected.size;
}
function renderFiles() {
  $('files').replaceChildren();
  available.forEach((f,index) => {
    const row = document.createElement('label'); row.className = 'file-row';
    const box = document.createElement('input');box.type='checkbox';box.checked=selected.has(f.name);box.setAttribute('aria-label',f.name);
    box.addEventListener('change',()=>{box.checked ? selected.add(f.name) : selected.delete(f.name);updateSelection();remember();});
    const num = document.createElement('span');num.className='file-num';num.textContent=String(index+1).padStart(2,'0');
    const name = document.createElement('span');name.className='file-name';name.textContent=f.name;
    const size = document.createElement('span');size.className='file-size';size.textContent=bytes(f.bytes);
    row.append(box,num,name,size);$('files').append(row);
  });
  if (!available.length) {const empty=document.createElement('p');empty.className='hint';empty.textContent='Aucune vidéo trouvée dans ce dossier.';$('files').append(empty);}
  updateSelection();
}
function updateSelection() {
  const chosen=available.filter(f=>selected.has(f.name));
  $('selection-count').textContent=chosen.length+' prise'+(chosen.length>1?'s':'')+' sélectionnée'+(chosen.length>1?'s':'')+' · '+bytes(chosen.reduce((sum,f)=>sum+f.bytes,0));
  displaySettings();
}
async function loadFiles(initial=false) {
  error('');$('load-files').disabled=true;
  try {
    const data=await api('/api/files',{folder:$('folder').value}); available=data.files;
    const names=new Set(available.map(f=>f.name));
    selected=initial?new Set([...selected].filter(n=>names.has(n))):names;
    renderFiles();remember();
  } catch(e) {error(e.message);} finally {$('load-files').disabled=false;}
}
function metrics(summary) {
  $('metrics').replaceChildren();
  for (const [value,label] of [[fmt(summary.input_seconds)+' s','Rushs au total'],[fmt(summary.output_seconds)+' s','Vidéo assemblée'],[fmt(Math.max(0,summary.removed_seconds))+' s','Temps retiré'],[String(summary.cuts_count),'Pauses raccourcies']]) {
    const item=document.createElement('div');item.className='metric';const strong=document.createElement('strong');strong.textContent=value;const span=document.createElement('span');span.textContent=label;item.append(strong,span);$('metrics').append(item);
  }
}
function showJob(job) {
  if (!job) return;
  currentId=job.id;
  const done=finished(job.status), failure=['failed','cancelled','interrupted'].includes(job.status);
  $('edit-card').hidden=!(done||job.status==='prepared');
  $('edit-link').href='/edit?project='+(job.parent_id||job.id);
  $('result').hidden=!done;$('failed-card').hidden=!failure;
  if (done) {
    const url='/projects/'+job.id+'/'+job.video;
    if (showingVideo!==url) {$('video').src=url;showingVideo=url;}
    metrics(job.summary);
    $('review-badge').textContent=job.reviewed?'Vérifiée':'À relire';
    $('result-message').textContent=job.summary.width+' × '+job.summary.height+' px · '+bytes(job.summary.bytes)+' · calcul : '+fmt(job.summary.processing_seconds)+' s · '+(job.n8n_synced?'bilan enregistré dans n8n':'bilan n8n à renvoyer');
    $('warnings').textContent=job.reviewed?'Tu as marqué cette version comme vérifiée.':(job.warnings||[]).join(' ');
    $('download-video').href=url;$('download-video').download=job.video;
    $('download-csv').href='/projects/'+job.id+'/decoupage.csv';
    $('download-json').href='/projects/'+job.id+'/decoupage.json';
    $('review').disabled=Boolean(job.reviewed);$('review').textContent=job.reviewed?'Version vérifiée':'J’ai vérifié l’image, le son et les raccords';
    $('sync').hidden=job.n8n_synced;
  } else if (failure) {
    $('failed-title').textContent=job.status==='cancelled'?'Traitement annulé':'Le traitement demande une correction';
    $('failed-message').textContent=job.message;$('resume').disabled=Boolean(activeId);
  }
}
function renderHistory() {
  const signature=JSON.stringify(jobs.map(j=>[j.id,j.status,j.updated_at]));
  if(signature===historySignature)return;
  historySignature=signature;
  $('history').replaceChildren();$('history-count').textContent=jobs.length+' projet'+(jobs.length>1?'s':'');
  for (const job of jobs) {
    const row=document.createElement('button');row.className='history-row';row.type='button';
    const left=document.createElement('div'),name=document.createElement('strong'),description=document.createElement('small'),badge=document.createElement('span');badge.className='badge';
    name.textContent=job.status==='prepared'?'Montage à corriger':(job.parent_id?'Montage corrigé · v'+job.parent_revision:job.parameters?.mode==='assemble'?'Assemblage intégral':'Pauses raccourcies')+' · '+(job.parameters?.quality==='full'?'pleine résolution':'aperçu');
    description.textContent=new Date(job.created_at).toLocaleString('fr-FR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})+' · '+(job.ordered_names?.length||0)+' prises';
    badge.textContent=labelStatus(job.status);left.append(name,description);row.append(left,badge);
    row.addEventListener('click',()=>{showJob(job);(job.status==='prepared'?$('edit-card'):finished(job.status)?$('result'):$('failed-card')).scrollIntoView({behavior:'smooth',block:'start'});});$('history').append(row);
  }
  if (!jobs.length) {const p=document.createElement('p');p.className='hint';p.textContent='Tes prochains résultats apparaîtront ici.';$('history').append(p);}
}
async function refresh() {
  try {
    const data=await api('/api/jobs'); jobs=data.jobs;activeId=data.active;
    const running=jobs.find(j=>j.id===activeId);
    $('progress-card').hidden=!running;
    if (running) {$('progress-message').textContent=running.message;$('progress').value=running.progress;}
    const current=jobs.find(j=>j.id===currentId)||jobs[0];
    if (current) showJob(current);
    renderHistory();displaySettings();
  } catch(e) {if (!stopped) error('Le moteur local ne répond plus. Relance « Lancer le derushage.vbs ».');}
  clearTimeout(timer);if(!stopped) timer=setTimeout(refresh,activeId?1200:7000);
}
async function jobAction(action) {
  if(!currentId) return;
  error('');
  try {await api('/api/jobs/'+currentId+'/'+action,{});await refresh();} catch(e) {error(e.message);}
}
async function init() {
  cfg=await api('/api/config');$('workflow').href=cfg.workflow_url;
  let saved={};try{saved=JSON.parse(localStorage.getItem('derushage-v1')||'{}');}catch(e){}
  $('folder').value=saved.folder||cfg.default_folder;selected=new Set(saved.files||cfg.default_files);
  const p={...cfg.defaults,...saved.parameters};$('mode').value=p.mode;$('quality').value=p.quality;$('min-pause').value=p.min_pause;$('keep-pause').value=p.keep_pause;$('threshold').value=p.threshold_db;$('trim-edges').checked=p.trim_edges;
  $('load-files').addEventListener('click',()=>loadFiles());
  $('select-all').addEventListener('click',()=>{selected=new Set(available.map(f=>f.name));renderFiles();remember();});
  $('select-none').addEventListener('click',()=>{selected.clear();renderFiles();remember();});
  for(const id of ['mode','quality','min-pause','keep-pause','threshold','trim-edges']) $(id).addEventListener('input',()=>{displaySettings();remember();});
  $('editor').addEventListener('submit',async event=>{
    event.preventDefault();error('');
    if(parameters().keep_pause>=parameters().min_pause){error('La respiration conservée doit être plus courte que la pause minimale.');return;}
    $('launch').disabled=true;
    try {remember();const job=await api('/api/jobs',{folder:$('folder').value,files:[...selected],parameters:parameters(),prepare_only:true});currentId=job.id;await refresh();$('progress-card').scrollIntoView({behavior:'smooth',block:'center'});}catch(e){error(e.message);displaySettings();}
  });
  $('cancel').addEventListener('click',async()=>{if(activeId){try{await api('/api/jobs/'+activeId+'/cancel',{});await refresh();}catch(e){error(e.message);}}});
  $('resume').addEventListener('click',()=>jobAction('resume'));$('review').addEventListener('click',()=>jobAction('review'));$('sync').addEventListener('click',()=>jobAction('sync'));$('open-folder').addEventListener('click',()=>jobAction('folder'));
  $('shutdown').addEventListener('click',async()=>{try{await api('/api/shutdown',{});stopped=true;clearTimeout(timer);$('shutdown').disabled=true;$('launch').disabled=true;error('Moteur fermé. Pour revenir, ouvre « Lancer le derushage.vbs ».');}catch(e){error(e.message);}});
  await loadFiles(true);await refresh();
}
init().catch(e=>error(e.message));
