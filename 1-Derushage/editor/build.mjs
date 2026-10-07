import {build} from 'esbuild';
import {fileURLToPath} from 'node:url';
import {readFileSync,existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import path from 'node:path';
const root=fileURLToPath(new URL('.',import.meta.url));
const require=createRequire(import.meta.url);
// Résolution explicite : le compilateur n'a pas besoin d'énumérer les dossiers parents du projet.
const resolver={name:'explicit-project-files',setup(b){
  b.onResolve({filter:/.*/},args=>{
    let file;
    if(path.isAbsolute(args.path))file=args.path;
    else if(args.path.startsWith('.')){
      const base=path.resolve(path.dirname(args.importer),args.path);
      file=['','.tsx','.ts','.js','.jsx','.json','.css','/index.js'].map(ext=>base+ext).find(existsSync);
    }else file=require.resolve(args.path,{paths:[args.importer?path.dirname(args.importer):root]});
    if(!file)throw Error('Import introuvable : '+args.path);
    return {path:file,namespace:'project'};
  });
  b.onLoad({filter:/.*/,namespace:'project'},args=>({contents:readFileSync(args.path,'utf8'),loader:path.extname(args.path).slice(1),resolveDir:path.dirname(args.path)}));
}};
await build({absWorkingDir:root,entryPoints:[fileURLToPath(new URL('./src/main.tsx',import.meta.url))],plugins:[resolver],tsconfigRaw:{compilerOptions:{jsx:'react-jsx'}},bundle:true,minify:true,format:'esm',jsx:'automatic',outfile:root+'../static/editor/editor.js',define:{'process.env.NODE_ENV':'"production"'},legalComments:'linked'});
