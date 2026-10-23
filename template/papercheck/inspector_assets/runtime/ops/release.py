"""Offline release validation, atomic activation and rollback. Python stdlib only."""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, stat, tempfile, zipfile
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
def require_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value) or '..' in value:
        raise ValueError('Invalid release ID')
    return value

def safe_path(name):
    if not isinstance(name, str) or not name or any(ord(c)<32 for c in name) or '\\' in name or ':' in name or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/')):
        raise ValueError(f'Unsafe archive path: {name!r}')
    return name

def read_json(file):
    return json.loads(Path(file).read_text(encoding='utf-8'))

def sha(file):
    h=hashlib.sha256()
    with Path(file).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def validate(root):
    root=Path(root).resolve()
    manifest=read_json(root/'manifest.json')
    if manifest.get('format')!='papercheck-release/v1' or manifest.get('apiVersion')!=1: raise ValueError('Unsupported format')
    require_id(manifest['releaseId'])
    expected={}
    for entry in manifest['files']:
        name=safe_path(entry['path'])
        if name in expected or not re.fullmatch('[a-f0-9]{64}',entry['sha256']): raise ValueError('Duplicate/invalid manifest entry')
        expected[name]=entry
    actual=set()
    for file in root.rglob('*'):
        if file.is_symlink(): raise ValueError('Symlink rejected')
        if file.is_file(): actual.add(file.relative_to(root).as_posix())
    if actual!=set(expected)|{'manifest.json'}: raise ValueError('Missing or unlisted release files')
    for name,entry in expected.items():
        file=root/name
        if not file.resolve().is_relative_to(root) or file.stat().st_size!=entry['bytes'] or sha(file)!=entry['sha256']: raise ValueError(f'Checksum mismatch: {name}')
    for name in ['manuscript/paper.md','projection/data.json','projection/files.json']:
        if name not in expected: raise ValueError(f'Missing {name}')
    paper=(root/'manuscript/paper.md').read_bytes()
    if hashlib.sha256(paper).hexdigest()!=manifest['paperSha256']: raise ValueError('Paper SHA mismatch')
    if manifest.get('pdfSha256')!=expected.get('manuscript/paper.pdf',{}).get('sha256'): raise ValueError('PDF SHA mismatch')
    ledger=read_json(root/'audit/ledger/manifest.json')
    if ledger['input']['sha256']!='sha256:'+manifest['paperSha256'] or ledger['state_id']!=manifest['state'] or ledger['snapshot_id']!=manifest['snapshot']: raise ValueError('Immutable ledger version mismatch')
    for name,h in ledger['file_hashes'].items():
        if 'audit/ledger/'+safe_path(name) not in expected or 'sha256:'+sha(root/'audit/ledger'/name)!=h: raise ValueError('Immutable ledger checksum mismatch')
    data=read_json(root/'projection/data.json'); files=read_json(root/'projection/files.json')
    if data['meta']['sha256']!='sha256:'+manifest['paperSha256'] or data['meta']['state']!=manifest['state']: raise ValueError('Projection version mismatch')
    seen=set();claims=set();categories={}
    for block in data['blocks']:
        raw=data['meta'].get('rangeJoin','').join(paper[r['start_byte']:r['end_byte']].decode('utf-8') for r in block['ranges'])
        if raw!=block['raw']: raise ValueError(f'Original byte mismatch: {block["id"]}')
        for key in block['claimKeys']:
            c=data['claims'][key]
            if key in seen or c['blockId']!=block['id']: raise ValueError('Invalid claim placement')
            seen.add(key); claims.add(c['claimId']);categories[c['category']]=categories.get(c['category'],0)+1
            if any(e not in data['evidence'] for e in c['evidenceIds']): raise ValueError('Evidence ID unresolved')
    counts=(len(data['blocks']),len(seen),len(claims),len(data['evidence']))
    if counts!=tuple(data['meta'][k] for k in ['blocks','occurrences','claims','evidence']) or len(seen)!=len(data['claims']) or categories!=data['meta']['categories']: raise ValueError('Projection counts mismatch')
    if any(data['meta'][k]!=manifest['counts'][k] for k in ['blocks','occurrences','claims','evidence']): raise ValueError('Manifest counts mismatch')
    for eid,entry in files.items():
        if eid not in data['evidence'] or safe_path(entry['path']) not in expected or data['evidence'][eid]['localPath']!=entry['path']: raise ValueError('Unregistered source')
    return manifest

def atomic_text(file, text):
    file=Path(file);file.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+file.name+'-',dir=file.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,file)
    finally:
        if Path(tmp).exists(): Path(tmp).unlink()

def activate(data, release_id):
    release_id=require_id(release_id)
    manifest=validate(data/'releases'/release_id)
    if manifest['releaseId']!=release_id: raise ValueError('Directory/ID mismatch')
    old=(data/'CURRENT').read_text().strip() if (data/'CURRENT').exists() else None
    if old==release_id: return {'releaseId':release_id,'previous':old,'changed':False}
    if old: atomic_text(data/'PREVIOUS',require_id(old)+'\n')
    atomic_text(data/'CURRENT',release_id+'\n')
    with (data/'release-events.jsonl').open('a',encoding='utf-8') as stream:
        stream.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'from':old,'to':release_id,'manifestSha256':sha(data/'releases'/release_id/'manifest.json')})+'\n')
    return {'releaseId':release_id,'previous':old,'changed':True}

def import_zip(data, archive, expected_sha=None, activate_now=True):
    archive=Path(archive).resolve()
    if expected_sha and sha(archive)!=expected_sha.lower(): raise ValueError('ZIP SHA-256 does not match the supplied value')
    releases=data/'releases';releases.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.staging-',dir=releases)).resolve()
    try:
        with zipfile.ZipFile(archive) as z:
            infos=z.infolist()
            if len(infos)>20000 or sum(i.file_size for i in infos)>2*1024**3: raise ValueError('ZIP limits exceeded')
            names=set()
            for entry in infos:
                original=entry.orig_filename
                name=safe_path(original.rstrip('/') if entry.is_dir() else original)
                if stat.S_ISLNK(entry.external_attr>>16): raise ValueError('Symlink in ZIP')
                if entry.is_dir(): continue
                if name in names: raise ValueError('Duplicate path in ZIP')
                names.add(name);target=stage/name
                if not target.resolve().is_relative_to(stage): raise ValueError('ZIP escape rejected')
                target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(entry) as src,target.open('xb') as dst: shutil.copyfileobj(src,dst)
        manifest=validate(stage);release_id=manifest['releaseId'];target=releases/release_id
        if target.exists():
            validate(target)
            if sha(target/'manifest.json')!=sha(stage/'manifest.json'): raise ValueError('Release ID exists with different contents; use a new ID')
        else:
            for file in stage.rglob('*'):file.chmod(0o755 if file.is_dir() else 0o644)
            stage.chmod(0o755);stage.rename(target)
        return activate(data,release_id) if activate_now else {'releaseId':release_id,'activated':False}
    finally:
        if stage.exists():
            if stage.parent!=releases.resolve() or not stage.name.startswith('.staging-'): raise RuntimeError('Unsafe temporary cleanup target')
            shutil.rmtree(stage)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',default=str(Path(__file__).resolve().parent.parent/'data'))
    subs=parser.add_subparsers(dest='command',required=True)
    check=subs.add_parser('validate');check.add_argument('directory')
    imp=subs.add_parser('import');imp.add_argument('zip');imp.add_argument('--sha256');imp.add_argument('--stage-only',action='store_true')
    act=subs.add_parser('activate');act.add_argument('release_id')
    back=subs.add_parser('rollback');back.add_argument('release_id',nargs='?')
    subs.add_parser('status')
    args=parser.parse_args();data=Path(args.data).resolve();data.mkdir(parents=True,exist_ok=True)
    if args.command=='validate': print(json.dumps(validate(args.directory),ensure_ascii=False,indent=2));return
    if args.command=='status':
        print(json.dumps({'current':(data/'CURRENT').read_text().strip() if (data/'CURRENT').exists() else None,'previous':(data/'PREVIOUS').read_text().strip() if (data/'PREVIOUS').exists() else None,'installed':sorted(p.name for p in (data/'releases').iterdir() if p.is_dir() and not p.name.startswith('.'))},indent=2));return
    lock=data/'.update.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        os.write(fd,str(os.getpid()).encode());os.close(fd)
        if args.command=='import':result=import_zip(data,args.zip,args.sha256,not args.stage_only)
        elif args.command=='activate':result=activate(data,args.release_id)
        else:result=activate(data,args.release_id or (data/'PREVIOUS').read_text().strip())
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally: lock.unlink(missing_ok=True)

if __name__=='__main__': main()
