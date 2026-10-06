const raw = $json.body ?? $json;
const bad = (message) => [{json:{ok:false,http_status:400,response:{ok:false,error:message}}}];
if (!raw || typeof raw !== 'object' || JSON.stringify(raw).length > 131072) return bad('Demande invalide ou trop volumineuse.');
if (raw.schema_version !== 1) return bad('Version du formulaire incompatible.');
if (!/^[a-f0-9-]{36}$/.test(raw.job_id ?? '')) return bad('Identifiant de projet invalide.');
if (!['plan','report'].includes(raw.action)) return bad('Action inconnue.');
let response, status, count, inputSeconds, outputSeconds = 0;
if (raw.action === 'plan') {
  if (!Array.isArray(raw.files) || raw.files.length < 1 || raw.files.length > 100) return bad('Sélectionner entre 1 et 100 vidéos.');
  const seen = new Set();
  let total = 0;
  for (const f of raw.files) {
    if (!f || typeof f.name !== 'string' || f.name.length > 240 || /[\\/:\x00]/.test(f.name) || !/\.(mp4|mov|mkv|m4v|avi|webm)$/i.test(f.name)) return bad('Nom de vidéo invalide.');
    const key = f.name.toUpperCase();
    if (seen.has(key)) return bad('Une vidéo apparaît plusieurs fois.');
    seen.add(key);
    if (typeof f.duration !== 'number' || !Number.isFinite(f.duration) || f.duration <= 0 || f.duration > 3600) return bad('Durée de vidéo invalide.');
    total += f.duration;
  }
  if (total > 3600) return bad('Cette première version accepte au plus une heure de rushs par projet.');
  const p = raw.parameters;
  if (!p || !['assemble','shorten'].includes(p.mode) || !['preview','full'].includes(p.quality)) return bad('Mode de montage ou qualité invalide.');
  const inRange = (x,a,b) => typeof x === 'number' && Number.isFinite(x) && x >= a && x <= b;
  if (!inRange(p.min_pause,0.2,5) || !inRange(p.keep_pause,0.1,1) || !inRange(p.threshold_db,-60,-10) || typeof p.trim_edges !== 'boolean') return bad('Les réglages de silence sont hors limites.');
  if (p.keep_pause >= p.min_pause) return bad('La respiration conservée doit être plus courte que la pause minimale.');
  const sorted = [...raw.files].sort((a,b) => a.name.toUpperCase() < b.name.toUpperCase() ? -1 : a.name.toUpperCase() > b.name.toUpperCase() ? 1 : 0);
  response = {ok:true,schema_version:1,job_id:raw.job_id,ordered_names:sorted.map(f => f.name),parameters:{mode:p.mode,quality:p.quality,min_pause:p.min_pause,keep_pause:p.keep_pause,threshold_db:p.threshold_db,trim_edges:p.trim_edges},input_seconds:total,requires_human_review:true};
  status = 'planned'; count = sorted.length; inputSeconds = total;
} else {
  const s = raw.summary;
  if (!s || !['completed','failed','accepted'].includes(s.status)) return bad('Bilan invalide.');
  if (![s.files_count,s.input_seconds,s.output_seconds].every(x => typeof x === 'number' && Number.isFinite(x) && x >= 0)) return bad('Mesures du bilan invalides.');
  response = {ok:true,schema_version:1,job_id:raw.job_id,recorded:true,status:s.status};
  status=s.status; count=s.files_count; inputSeconds=s.input_seconds; outputSeconds=s.output_seconds;
}
return [{json:{ok:true,http_status:200,response,entry_key:raw.job_id + ':' + raw.action,job_id:raw.job_id,event:raw.action,status,files_count:count,input_seconds:inputSeconds,output_seconds:outputSeconds,raw_request:JSON.stringify(raw),response_json:JSON.stringify(response)}}];
