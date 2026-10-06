export type Cut = {id:string;start:number;end:number;original_start:number;original_end:number;decision:'pending'|'accepted'|'rejected'};
export type Clip = {id:string;source_index:number;start:number;end:number;enabled:boolean;cuts:Cut[]};
export type Source = {name:string;frames:number;duration:number;width:number;height:number;url:string};
export type Project = {job_id:string;revision:number;fps:number;approved_revision:number|null;approval_sync?:{n8n_synced:boolean;n8n_error?:string}|null;updated_at:string;clips:Clip[];sources:Source[];duration_frames:number;imported_from_render:boolean};
export type Segment = {id:string;clipId:string;source:number;start:number;frames:number;from:number};
export function segments(project:Project):Segment[]{
  let from=0;const output:Segment[]=[];
  for(const c of project.clips){
    if(!c.enabled)continue;
    let at=c.start;const spans:number[][]=[];
    for(const p of [...c.cuts].sort((a,b)=>a.start-b.start)){
      if(p.decision!=='accepted')continue;
      const a=Math.max(c.start,p.start),b=Math.min(c.end,p.end);
      if(b<=a)continue;
      if(a>at)spans.push([at,a]);at=Math.max(at,b);
    }
    if(at<c.end)spans.push([at,c.end]);
    spans.forEach(([a,b],i)=>{output.push({id:c.id+'-'+i,clipId:c.id,source:c.source_index,start:a,frames:b-a,from});from+=b-a;});
  }
  return output;
}
export function validate(project:Project){
  for(const c of project.clips){
    const total=project.sources[c.source_index].frames;
    if(!Number.isInteger(c.start)||!Number.isInteger(c.end)||c.start<0||c.end>total||c.start>=c.end)throw Error('La fin doit suivre le début, dans les limites de la prise.');
    const cuts=[...c.cuts].sort((a,b)=>a.start-b.start);
    for(let i=0;i<cuts.length;i++){
      const p=cuts[i];
      if(!Number.isInteger(p.start)||!Number.isInteger(p.end)||p.start<0||p.end>total||p.start>=p.end)throw Error('La coupe doit avoir une durée positive et rester dans la prise.');
      if(i&&cuts[i-1].end>p.start)throw Error('Deux propositions de coupe se chevauchent.');
    }
  }
  const s=segments(project);
  if(!s.length||s.length>500)throw Error('Conserve au moins une image et au plus 500 segments.');
}
export const pending=(p:Project)=>p.clips.reduce((n,c)=>n+(c.enabled?c.cuts.filter(x=>x.decision==='pending'&&x.end>c.start&&x.start<c.end).length:0),0);

// Audition a proposal without changing the saved or unsaved decisions.
export function cutPreview(project:Project,clipId:string,cutId:string){
  const index=project.clips.findIndex(c=>c.id===clipId),clip=project.clips[index];
  const cut=clip?.cuts.find(p=>p.id===cutId);
  if(!clip?.enabled||!cut||cut.end<=clip.start||cut.start>=clip.end)throw Error('Cette coupe est hors de la portion conservée.');
  const candidate={...project,clips:project.clips.map(c=>c.id===clipId?{...c,cuts:c.cuts.map(p=>p.id===cutId?{...p,decision:'accepted' as const}:p)}:c)};
  const parts=segments(candidate),total=parts.reduce((n,s)=>n+s.frames,0);
  if(!total)throw Error('Cette coupe retirerait toutes les images du montage.');
  const preceding=new Set(project.clips.slice(0,index).map(c=>c.id));
  const point=parts.reduce((n,s)=>n+(preceding.has(s.clipId)||(s.clipId===clipId&&s.start<cut.end)?s.frames:0),0);
  const margin=Math.max(1,Math.round(project.fps*.7));
  return {parts,start:Math.max(0,point-margin),stop:Math.min(total-1,point+margin)};
}
