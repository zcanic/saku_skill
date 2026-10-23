import http from 'node:http';
import fs from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {loadCurrent,releaseFile,digest} from './release-store.mjs';

const ROOT=path.dirname(fileURLToPath(import.meta.url)),run=promisify(execFile);
const DATA=path.resolve(process.env.PAPERCHECK_DATA||path.join(ROOT,'../data'));
const REVIEWS=path.resolve(process.env.PAPERCHECK_REVIEWS||path.join(ROOT,'../reviews'));
const WORKSPACE=process.env.PAPERCHECK_WORKSPACE;
const PORT=Number(process.env.PORT||4178),HOST=process.env.HOST||'127.0.0.1';
const user=process.env.PAPERCHECK_USER||'reviewer',password=process.env.PAPERCHECK_PASSWORD||'';
const localInsecure=process.env.PAPERCHECK_INSECURE_LOCAL==='1'&&['127.0.0.1','::1'].includes(HOST);
if(!localInsecure&&password.length<20)throw new Error('Set PAPERCHECK_PASSWORD to at least 20 characters before starting.');
const origins=new Set([`http://127.0.0.1:${PORT}`,`http://localhost:${PORT}`]);
if(process.env.PAPERCHECK_PUBLIC_ORIGIN)origins.add(new URL(process.env.PAPERCHECK_PUBLIC_ORIGIN).origin);
const allowedHosts=new Set([...origins].map(o=>new URL(o).host));
const authHash=crypto.createHash('sha256').update(`${user}:${password}`).digest();
let active=await loadCurrent(DATA),pendingLoad=null,notes={},writeQueue=Promise.resolve(),pdfQueue=Promise.resolve();
const noteFile=path.join(REVIEWS,'personal-review.json'),pdfCache=new Map();
try{notes=JSON.parse(await fs.readFile(noteFile,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}

async function liveStatus(release) {
  const live={stale:false,actualSha256:release.data.meta.sha256,currentState:release.data.meta.state,releaseId:release.manifest.releaseId};
  if(WORKSPACE){
    try {
      live.actualSha256='sha256:'+digest(await fs.readFile(path.join(WORKSPACE,'paper.md')));
      live.currentState=(await fs.readFile(path.join(WORKSPACE,'.papercheck/CURRENT'),'utf8')).trim();
      live.stale=live.actualSha256!==release.data.meta.sha256||live.currentState!==release.data.meta.state;
    }catch{live.stale=true;}
  }
  return live;
}

async function current() {
  const id=(await fs.readFile(path.join(DATA,'CURRENT'),'utf8')).trim();
  if(id===active.manifest.releaseId){
    if(digest(await fs.readFile(path.join(active.root,'manuscript/paper.md')))!==active.manifest.paperSha256)throw new Error('Active paper modified in place');
    return active;
  }
  if(!pendingLoad)pendingLoad=loadCurrent(DATA).then(next=>{active=next;pdfCache.clear();return next;}).finally(()=>{pendingLoad=null;});
  return pendingLoad;
}
const json=(res,code,value)=>{res.writeHead(code,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(value));};
function authorized(req) {
  if(localInsecure)return true;
  if(!req.headers.authorization?.startsWith('Basic '))return false;
  const supplied=Buffer.from(req.headers.authorization.slice(6),'base64');
  return crypto.timingSafeEqual(crypto.createHash('sha256').update(supplied).digest(),authHash);
}
async function body(req) {
  let size=0;const parts=[];
  for await(const chunk of req){size+=chunk.length;if(size>100000)throw Object.assign(new Error('Request too large'),{status:413});parts.push(chunk);}
  try{return JSON.parse(Buffer.concat(parts).toString('utf8')||'{}');}catch{throw Object.assign(new Error('Invalid JSON'),{status:400});}
}
function pointer(value,ptr) {
  if(!ptr)return value;
  for(const raw of ptr.replace(/^\//,'').split('/')){const key=raw.replace(/~1/g,'/').replace(/~0/g,'~');if(value==null||!Object.hasOwn(value,key))throw new Error('Registered JSON pointer not found');value=value[key];}
  return value;
}
const types={'.html':'text/html; charset=utf-8','.js':'application/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.woff2':'font/woff2','.woff':'font/woff','.ttf':'font/ttf','.pdf':'application/pdf','.md':'text/plain; charset=utf-8','.json':'application/json; charset=utf-8'};
async function sendFile(res,file,filename) {
  const stat=await fs.stat(file);
  res.writeHead(200,{'Content-Type':types[path.extname(file)]||'application/octet-stream','Content-Length':stat.size,'Cache-Control':'private, no-cache',...(filename?{'Content-Disposition':`inline; filename="${filename}"`}:{})});
  createReadStream(file).on('error',()=>res.destroy()).pipe(res);
}
async function preview(release,eid,requested) {
  const item=release.files[eid],ev=release.data.evidence[eid];
  if(!item)return {unavailable:true,message:'此证据未包含本地全文；保留已登记引文、定位及在线入口。'};
  const file=await releaseFile(release.root,item.path),buffer=await fs.readFile(file),sha='sha256:'+digest(buffer),ext=path.extname(file);
  if(sha!=='sha256:'+release.manifest.files.find(f=>f.path===item.path)?.sha256)throw new Error('Source modified in place');
  const expected=ev.referenceRecord?.file_sha256||ev.sha256;
  const base={path:item.path,sha256:sha,expectedSha256:expected,hashMatches:expected?sha==='sha256:'+expected.replace(/^sha256:/,''):null,bytes:buffer.length,extension:ext};
  if(ev.bundleRedaction){base.hashMatches=null;base.redaction=ev.bundleRedaction;base.message='部署副本仅隐藏连接口令；原始文件SHA-256已保留，登记行号不变。包内副本按独立清单校验。';}
  if(ext==='.pdf') {
    const page=requested||Number(item.locator.pdf_page)||1;
    if(!Number.isSafeInteger(page)||page<1)throw Object.assign(new Error('Invalid PDF page'),{status:400});
    const key=`${release.manifest.releaseId}:${eid}:${page}`;
    if(pdfCache.has(key))return {...base,pdf:true,...pdfCache.get(key)};
    const result=pdfQueue.catch(()=>{}).then(async()=>{
      const output=await run(process.env.PAPERCHECK_PYTHON||'python3',[path.join(ROOT,'pdf_page.py'),file,String(page)],{encoding:'utf8',timeout:25000,maxBuffer:12*1024*1024,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
      return JSON.parse(output.stdout);
    });pdfQueue=result;
    let rendered;try{rendered=await result;}catch{throw Object.assign(new Error('PDF preview unavailable; use the registered PDF download. Check Python/PyMuPDF on the server.'),{status:503});}
    pdfCache.set(key,rendered);if(pdfCache.size>8)pdfCache.delete(pdfCache.keys().next().value);
    return {...base,pdf:true,...rendered};
  }
  if(!['.json','.jsonl','.csv','.tsv','.sql','.py','.r','.js','.ts','.md','.txt'].includes(ext))return {...base,message:'二进制来源；请核对登记引文或打开文件。'};
  const text=buffer.toString('utf8'),loc=item.locator,ptr=loc.pointer??loc.json_pointer;let excerpt;
  if(ext==='.json'&&ptr!=null)excerpt=JSON.stringify(pointer(JSON.parse(text),String(ptr)),null,2);
  else{const lines=text.split(/\r?\n/),line=Number(loc.line||loc.csv_line||1),from=Math.max(0,line-3),end=Math.min(Number(loc.end_line||line+24)+2,from+180);excerpt=lines.slice(from,end).map((l,i)=>`${from+i+1}  ${l}`).join('\n');base.previewScope='按登记行号展示局部上下文。';}
  return {...base,text:excerpt.slice(0,100000),pointer:ptr,truncated:excerpt.length>100000};
}
export const server=http.createServer(async(req,res)=>{
  res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Referrer-Policy','no-referrer');
  res.setHeader('Cross-Origin-Resource-Policy','same-origin');res.setHeader('X-Frame-Options','DENY');
  res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'");
  try {
    if(!allowedHosts.has(req.headers.host))return json(res,403,{error:'Host not allowed'});
    const url=new URL(req.url,`http://127.0.0.1:${PORT}`);
    if(url.pathname==='/healthz'&&req.method==='GET')return json(res,200,{ok:true,apiVersion:1});
    if(!authorized(req)){res.setHeader('WWW-Authenticate','Basic realm="Papercheck private", charset="UTF-8"');return json(res,401,{error:'Authentication required'});}
    if(!['GET','HEAD'].includes(req.method)&&(req.headers['sec-fetch-site']==='cross-site'||req.headers.origin&&!origins.has(req.headers.origin)))return json(res,403,{error:'Same-origin requests only'});
    const release=await current(),data=release.data;
    const live=await liveStatus(release);
    if(url.pathname==='/api/status'&&req.method==='GET')return json(res,200,{...data.meta,...live});
    if(url.pathname==='/api/data'&&req.method==='GET')return json(res,200,{...data,live});
    if(url.pathname==='/api/notes'&&req.method==='GET')return json(res,200,Object.fromEntries(Object.values(notes).filter(n=>n.releaseId===release.manifest.releaseId).map(n=>[`${n.sha256}:${n.key}`,n])));
    if(url.pathname==='/api/notes'&&req.method==='POST') {
      const row=await body(req);
      if(live.stale||row.sha256!==data.meta.sha256||row.releaseId!==release.manifest.releaseId||!data.claims[row.key])return json(res,409,{error:'论文版本已改变，请登记并导出后刷新。'});
      if(!['unreviewed','checked','question','flag'].includes(row.status))return json(res,400,{error:'Unknown review status'});
      const c=data.claims[row.key],record={key:row.key,claimId:c.claimId,blockId:c.blockId,sha256:data.meta.sha256,state:data.meta.state,releaseId:release.manifest.releaseId,status:row.status,note:String(row.note||'').slice(0,20000),updatedAt:new Date().toISOString()};
      writeQueue=writeQueue.catch(()=>{}).then(async()=>{
        const latest=await current();
        if(latest.manifest.releaseId!==row.releaseId||(await liveStatus(latest)).stale)throw Object.assign(new Error('Version changed during save'),{status:409});
        const next={...notes,[`${row.releaseId}:${row.sha256}:${row.key}`]:record};await fs.mkdir(REVIEWS,{recursive:true});
        await fs.writeFile(noteFile+'.tmp',JSON.stringify(next,null,2));await fs.rename(noteFile+'.tmp',noteFile);notes=next;
      });await writeQueue;return json(res,200,record);
    }
    if(url.pathname==='/api/refresh'&&req.method==='POST')return json(res,200,{...data.meta,...live});
    if(url.pathname==='/api/manuscript.pdf'&&['GET','HEAD'].includes(req.method))return release.manifest.pdfSha256?sendFile(res,await releaseFile(release.root,'manuscript/paper.pdf'),'paper.pdf'):json(res,404,{error:'No PDF supplied for this version'});
    if(url.pathname==='/api/manuscript.md'&&['GET','HEAD'].includes(req.method))return sendFile(res,await releaseFile(release.root,'manuscript/paper.md'),'paper.md');
    if(url.pathname.startsWith('/api/evidence/')&&req.method==='GET') {
      const eid=decodeURIComponent(url.pathname.slice('/api/evidence/'.length));if(!data.evidence[eid])return json(res,404,{error:'Unknown evidence'});
      return json(res,200,await preview(release,eid,url.searchParams.has('page')?Number(url.searchParams.get('page')):null));
    }
    if(url.pathname.startsWith('/api/file/')&&['GET','HEAD'].includes(req.method)) {
      const item=release.files[decodeURIComponent(url.pathname.slice('/api/file/'.length))];if(!item)return json(res,404,{error:'Unregistered source'});
      const file=await releaseFile(release.root,item.path);
      if(digest(await fs.readFile(file))!==release.manifest.files.find(f=>f.path===item.path)?.sha256)throw new Error('Source modified in place');
      return sendFile(res,file);
    }
    if(url.pathname.startsWith('/api/'))return json(res,404,{error:'Unknown API route'});
    if(!['GET','HEAD'].includes(req.method))return json(res,405,{error:'Method not allowed'});
    const rel=decodeURIComponent(url.pathname).replace(/^\//,'');
    if(rel.includes('\\')||rel.split('/').some(p=>p==='..'||p.startsWith('.')))return json(res,403,{error:'Forbidden'});
    const base=path.join(ROOT,'dist');let file=path.resolve(base,rel||'index.html');
    if(!file.startsWith(base+path.sep))return json(res,403,{error:'Forbidden'});
    if(!(await fs.stat(file).catch(()=>null))?.isFile())file=path.join(base,'index.html');
    return sendFile(res,file);
  }catch(e){if(!res.headersSent)json(res,e.status||503,{error:e.status?e.message:'Release or source unavailable; inspect server logs.'});else res.destroy();console.error(e.message);}
});
server.requestTimeout=30000;server.headersTimeout=15000;
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))server.listen(PORT,HOST,()=>console.log(`Papercheck portable http://${HOST}:${PORT} release=${active.manifest.releaseId}`));
