import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

export const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
export const releaseIdOK = id => typeof id==='string' && /^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/.test(id) && !id.includes('..');
export function safeRelative(name) {
  if(typeof name!=='string'||!name||/[\x00-\x1f]/.test(name)||name.includes('\\')||name.includes(':')||name.startsWith('/')||name.split('/').some(p=>!p||p==='.'||p==='..'))throw new Error('Unsafe package path');
  return name;
}
export async function releaseFile(root,name) {
  safeRelative(name);
  const base=await fs.realpath(root),full=await fs.realpath(path.join(base,name));
  if(!full.startsWith(base+path.sep))throw new Error('Source escapes release');
  return full;
}
export async function validateRelease(root) {
  const manifest=JSON.parse(await fs.readFile(path.join(root,'manifest.json'),'utf8'));
  if(manifest.format!=='papercheck-release/v1'||!releaseIdOK(manifest.releaseId)||manifest.apiVersion!==1)throw new Error('Unsupported release format');
  const names=new Set();
  for(const item of manifest.files) {
    safeRelative(item.path);
    if(names.has(item.path)||!/^[a-f0-9]{64}$/.test(item.sha256))throw new Error('Invalid manifest entry');
    names.add(item.path);
    const file=await releaseFile(root,item.path),bytes=await fs.readFile(file);
    if(bytes.length!==item.bytes||digest(bytes)!==item.sha256)throw new Error(`Checksum mismatch: ${item.path}`);
  }
  async function walk(dir,prefix='') {
    for(const entry of await fs.readdir(dir,{withFileTypes:true})) {
      const name=prefix+entry.name;
      if(entry.isSymbolicLink())throw new Error('Symlinks are not allowed');
      if(entry.isDirectory())await walk(path.join(dir,entry.name),name+'/');
      else if(!entry.isFile()||(name!=='manifest.json'&&!names.has(name)))throw new Error(`Unlisted release file: ${name}`);
    }
  }
  await walk(root);
  for(const name of ['manuscript/paper.md','projection/data.json','projection/files.json'])if(!names.has(name))throw new Error(`Missing ${name}`);
  const paper=await fs.readFile(path.join(root,'manuscript/paper.md'));
  if(digest(paper)!==manifest.paperSha256)throw new Error('Paper SHA-256 mismatch');
  if((manifest.pdfSha256??null)!==(manifest.files.find(f=>f.path==='manuscript/paper.pdf')?.sha256??null))throw new Error('PDF SHA-256 mismatch');
  const ledger=JSON.parse(await fs.readFile(path.join(root,'audit/ledger/manifest.json'),'utf8'));
  if(ledger.input?.sha256!=='sha256:'+manifest.paperSha256||ledger.state_id!==manifest.state||ledger.snapshot_id!==manifest.snapshot)throw new Error('Immutable ledger version mismatch');
  for(const [name,hash] of Object.entries(ledger.file_hashes)) {
    if(!names.has('audit/ledger/'+safeRelative(name))||'sha256:'+digest(await fs.readFile(await releaseFile(path.join(root,'audit/ledger'),name)))!==hash)throw new Error('Immutable ledger checksum mismatch');
  }
  const data=JSON.parse(await fs.readFile(path.join(root,'projection/data.json'),'utf8'));
  const files=JSON.parse(await fs.readFile(path.join(root,'projection/files.json'),'utf8'));
  if(data.meta.sha256!=='sha256:'+manifest.paperSha256||data.meta.state!==manifest.state)throw new Error('Projection version mismatch');
  const seen=new Set(),ids=new Set(),categories={};
  for(const block of data.blocks) {
    const exact=block.ranges.map(r=>paper.subarray(r.start_byte,r.end_byte).toString('utf8')).join(data.meta.rangeJoin??'');
    if(exact!==block.raw)throw new Error(`Source byte mismatch: ${block.id}`);
    for(const key of block.claimKeys) {
      const c=data.claims[key];
      if(!c||c.blockId!==block.id||seen.has(key))throw new Error('Invalid claim placement');
      seen.add(key);ids.add(c.claimId);categories[c.category]=(categories[c.category]||0)+1;
      for(const eid of c.evidenceIds)if(!data.evidence[eid])throw new Error(`Unresolved evidence: ${eid}`);
    }
  }
  if(seen.size!==Object.keys(data.claims).length||seen.size!==data.meta.occurrences||ids.size!==data.meta.claims||data.blocks.length!==data.meta.blocks||Object.keys(data.evidence).length!==data.meta.evidence)throw new Error('Projection counts mismatch');
  for(const k of ['blocks','occurrences','claims','evidence'])if(data.meta[k]!==manifest.counts[k])throw new Error('Manifest counts mismatch');
  if(JSON.stringify(Object.entries(categories).sort())!==JSON.stringify(Object.entries(data.meta.categories).sort()))throw new Error('Category counts mismatch');
  for(const [eid,item] of Object.entries(files)) {
    if(!data.evidence[eid]||!names.has(item.path))throw new Error('Source not in manifest');
    await releaseFile(root,item.path);
    if(data.evidence[eid].localPath!==item.path)throw new Error('Evidence path mismatch');
  }
  return {root,manifest,data,files};
}
export async function loadCurrent(dataRoot) {
  const id=(await fs.readFile(path.join(dataRoot,'CURRENT'),'utf8')).trim();
  if(!releaseIdOK(id))throw new Error('Invalid CURRENT');
  const result=await validateRelease(path.join(dataRoot,'releases',id));
  if(result.manifest.releaseId!==id)throw new Error('Release directory/ID mismatch');
  result.data.meta={...result.data.meta,releaseId:id,manuscriptPdfUrl:result.manifest.pdfSha256?'/api/manuscript.pdf':undefined,manuscriptMdUrl:'/api/manuscript.md'};
  return result;
}
