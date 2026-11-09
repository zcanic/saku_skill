"""Read-only ledger projection and reusable manuscript inspector lifecycle."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from importlib.resources import files
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlparse
import zipfile

from .state import source_text_for_ranges
from .storage import Repo, PapercheckError, ValidationError
from .util import atomic_write_text, now_iso, sha256_file, write_json

TEXT_EXTENSIONS={'.py','.sql','.json','.jsonl','.md','.txt','.csv','.tsv','.r','.js','.ts'}
SOURCE_EXTENSIONS=TEXT_EXTENSIONS|{'.pdf'}

def _assets():
    return files('papercheck').joinpath('inspector_assets')

def _asset_payloads():
    root=_assets()
    manifest=json.loads(root.joinpath('ASSET-MANIFEST.json').read_text(encoding='utf-8'))
    for name,expected in manifest['files'].items():
        data=root.joinpath(*name.split('/')).read_bytes()
        if 'sha256:'+hashlib.sha256(data).hexdigest()!=expected:
            raise PapercheckError(f'Inspector asset checksum mismatch: {name}')
        yield name,data

def inspector_path(repo:Repo,directory='inspector'):
    target=(repo.root/directory).resolve()
    if target==repo.root or target==repo.meta or repo.meta in target.parents:
        raise PapercheckError('Inspector must not overwrite the manuscript or immutable ledger')
    return target

def init_inspector(repo:Repo,directory='inspector'):
    target=inspector_path(repo,directory)
    if target.exists():raise PapercheckError(f'Refusing to overwrite existing inspector: {target}')
    payload=list(_asset_payloads())
    for name,data in payload:
        if name.startswith('runtime/'):relative=name.removeprefix('runtime/')
        elif name.startswith('frontend/'):relative=name
        else:continue
        file=target/relative;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
    write_json(target/'config.json',{'source_roots':['references'],'max_source_bytes':128*1024*1024})
    (target/'reviews').mkdir(exist_ok=True)
    return target

def _local_path(value,root):
    if not isinstance(value,str) or not value:return None
    if value.startswith('file:'):
        parsed=urlparse(value)
        if parsed.netloc not in ('','localhost'):return None
        value=unquote(parsed.path)
        if re.match(r'^/[A-Za-z]:/',value):value=value[1:]
    elif re.match(r'^https?://',value):return None
    elif '://' in value:return None
    candidate=Path(value)
    return (candidate if candidate.is_absolute() else root/candidate).resolve()

def _classification(claim,checks,assessments,tasks):
    outcomes={c['outcome'] for c in checks}
    if 'conflict' in outcomes:return 'conflict'
    if outcomes&{'fail','error'}:return 'issue'
    if any(a['status']=='partially_supported' for a in assessments):return 'partial'
    requirements=claim.get('review_requirements',['evidence'])
    if tasks or claim.get('identity_status')=='unknown' or not requirements or any(not any(c['kind']==r and c['outcome']=='pass' for c in checks) for r in requirements):return 'pending'
    return 'reviewed'

def _block_kind(raw,container_kind):
    # Parsed headings select only the heading text, so the ledger kind is authoritative.
    if container_kind=='heading' or raw.startswith('#'):return 'heading'
    if container_kind=='table' or raw.startswith('|'):return 'table'
    if container_kind=='math_block' or raw.startswith('$$'):return 'equation'
    return 'paragraph'


def project(repo:Repo,source_roots=None,max_source_bytes=128*1024*1024):
    issues=repo.verify()
    if issues:raise ValidationError(issues)
    state=repo.load_current()
    if state is None:raise PapercheckError('Commit a manuscript snapshot before exporting an inspector')
    if repo.working_copy_status(state)['changed']:
        raise PapercheckError('paper.md differs from CURRENT; register the revision before exporting')
    approved=[(repo.root/p).resolve() for p in (source_roots if source_roots is not None else ['references'])]
    snapshot=state.snapshot;paper=state.paper_bytes;claims=state.by_id('claims');variants=state.by_id('variants')
    current_checks=[c for c in state.checks if c['id'] in set(snapshot.get('check_ids',[]))]
    active_bindings=[b for b in state.bindings if b['id'] in set(snapshot.get('binding_ids',[]))]
    workflow=deepcopy(snapshot.get('workflow',{'status':'pending','tasks':[]}))
    blocks=[];by_placement={};containers=state.by_id('containers')
    for sel in snapshot['selections']:
        raw=source_text_for_ranges(paper,sel['source_ranges'])
        if raw!=variants[sel['variant_id']]['raw_text']:raise PapercheckError('Source ranges do not reproduce the current variant')
        block={'id':sel['placement_id'],'placementId':sel['placement_id'],'raw':raw,'kind':_block_kind(raw,containers.get(sel['container_id'],{}).get('kind')),'ranges':sel['source_ranges'],'claimKeys':[],'tracked':True}
        blocks.append(block);by_placement[block['id']]=block
    for row in snapshot.get('untracked_blocks',[]):
        ranges=[{'start_byte':row['start_byte'],'end_byte':row['end_byte']}]
        raw=source_text_for_ranges(paper,ranges)
        # Whitespace and bare Markdown markers (#, >, bullets) carry no text to inspect.
        if not raw or not raw.strip() or (len(raw)<=16 and re.fullmatch(r'[\s#>*+\-\d.]*',raw)):continue
        blocks.append({'id':f"untracked-{row['start_byte']}-{row['end_byte']}",'raw':raw,'kind':'table' if raw.lstrip().startswith('|') else 'paragraph','ranges':ranges,'claimKeys':[],'tracked':False,'untrackedReason':row.get('reason','untracked')})
    blocks.sort(key=lambda b:b['ranges'][0]['start_byte']);section='Front matter'
    for index,block in enumerate(blocks):
        if block['kind']=='heading':section=block['raw'].strip().lstrip('#').strip()
        block.update(index=index,section=section,line=paper[:block['ranges'][0]['start_byte']].count(b'\n')+1)
    occurrences={}
    for binding in active_bindings:
        cid=binding['claim_id'];claim=claims[cid];block=by_placement[binding['placement_id']]
        checks=[deepcopy(c) for c in current_checks if cid in c.get('claim_ids',[])]
        assessment_ids={c.get('assessment_id') for c in checks}
        assessments=[deepcopy(a) for a in state.assessments if a['id'] in assessment_ids]
        historical_checks=[deepcopy(c) for c in state.checks if cid in c.get('claim_ids',[]) and c['id'] not in set(snapshot.get('check_ids',[]))]
        historical_assessments=[deepcopy(a) for a in state.assessments if a['claim_id']==cid and a['id'] not in assessment_ids]
        eids=list(dict.fromkeys([e for c in checks for e in c.get('evidence_ids',[])]+[a['evidence_id'] for a in assessments]))
        history_eids=list(dict.fromkeys([e for c in historical_checks for e in c.get('evidence_ids',[])]+[a['evidence_id'] for a in historical_assessments]))
        pending=[deepcopy(t) for t in workflow.get('tasks',[]) if t['target'] in {cid,binding['placement_id']}]
        category=_classification(claim,checks,assessments,pending)
        key=binding['id']
        occurrences[key]={'key':key,'claimId':cid,'propositionId':binding['id'],'blockId':block['id'],'statement':claim['surface_statement'],'sentence':block['raw'],'sentenceRanges':block['ranges'],'type':claim.get('kind','assertion'),'category':category,'verdict':category,'evidenceIds':eids,'historicalEvidenceIds':history_eids,'unresolvedEvidenceIds':[],'assessments':assessments,'checks':checks,'historicalChecks':historical_checks,'historicalAssessments':historical_assessments,'pendingTasks':pending,'audit':None,'stages':{r:('completed' if any(c['kind']==r and c['outcome'] in {'pass','fail','conflict'} for c in checks) else 'pending') for r in claim.get('review_requirements',['evidence'])},'provenance':'immutable_snapshot_binding','canonical':deepcopy(claim['canonical_statement'])}
        block['claimKeys'].append(key)
    used_eids={e for c in occurrences.values() for e in c['evidenceIds']+c['historicalEvidenceIds']}
    refs=state.by_id('references');evidence={};local_sources={}
    for record in state.evidence:
        if record['id'] not in used_eids:continue
        ev=deepcopy(record);ref=deepcopy(refs[ev['reference_id']]);loc=ev.get('locator',{})
        ev.update(referenceRecord=ref,localPath=None,localExists=False)
        candidate=next((p for value in [loc.get('source_file'),loc.get('pdf_file'),loc.get('file'),ev.get('path'),ref.get('url')] if (p:=_local_path(value,repo.root)) is not None),None)
        if candidate:
            allowed=any(candidate==r or candidate.is_relative_to(r) for r in approved)
            if not allowed:ev['localAccessNote']='Source path is outside the configured source_roots; not copied.'
            elif candidate.suffix.lower() not in SOURCE_EXTENSIONS:ev['localAccessNote']='Source format is not allowlisted; not executed or copied.'
            elif candidate.is_file() and candidate.stat().st_size<=max_source_bytes:
                local_sources[ev['id']]=candidate;ev['localExists']=True
            else:ev['localAccessNote']='Local source is missing or exceeds max_source_bytes.'
        ev['doiUrl']=loc.get('doi_url') or ('https://doi.org/'+str(loc['doi']) if loc.get('doi') else (ref.get('study_id') if str(ref.get('study_id','')).startswith('https://doi.org/') else None))
        ev['sourceUrl']=next((v for v in [loc.get('url'),ref.get('url')] if isinstance(v,str) and v.startswith(('http://','https://'))),None)
        evidence[ev['id']]=ev
    # An inactive historical relation must not be reintroduced as a current edge.
    superseded={r.get('supersedes') for r in state.relations}
    active=set(snapshot.get('claim_ids',[]))
    relations=[deepcopy(r) for r in state.relations if r['id'] not in superseded and r['src'] in active and r['dst'] in active]
    meta={'state':state.state_id,'snapshot':state.snapshot_id,'sha256':state.manifest['input']['sha256'],'sourcePath':'manuscript/paper.md','inventoryPath':'audit/ledger/sources/bindings.jsonl','rangeJoin':'\n','occurrences':len(occurrences),'claims':len({c['claimId'] for c in occurrences.values()}),'blocks':len(blocks),'evidence':len(evidence),'categories':dict(Counter(c['category'] for c in occurrences.values())),'date':state.manifest['created_at'],'workflowStatus':workflow['status'],'pendingTasks':len(workflow.get('tasks',[])),'untrackedBytes':sum(r['end_byte']-r['start_byte'] for r in snapshot.get('untracked_blocks',[])),'scopeNote':'Read-only ledger projection; bound evidence and personal review do not imply fact verification.'}
    return {'meta':meta,'blocks':blocks,'claims':occurrences,'evidence':evidence,'relations':relations},local_sources,state

def _release_ops(target):
    spec=importlib.util.spec_from_file_location('papercheck_inspector_release_ops',target/'ops/release.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def export_inspector(repo:Repo,directory='inspector',pdf=None,release_id=None):
    target=inspector_path(repo,directory)
    if not (target/'app/server.mjs').is_file():raise PapercheckError('Run inspector init before export')
    config=json.loads((target/'config.json').read_text(encoding='utf-8'))
    data,local_sources,state=project(repo,config.get('source_roots',['references']),int(config.get('max_source_bytes',128*1024*1024)))
    pdf_path=Path(pdf).resolve() if pdf else None
    if pdf_path and (not pdf_path.is_file() or not pdf_path.read_bytes().startswith(b'%PDF-')):raise PapercheckError('The optional PDF must be an existing PDF; export does not generate it')
    ops=_release_ops(target)
    release_id=release_id or f"{state.state_id}-{state.manifest['input']['sha256'][7:19]}-{__import__('uuid').uuid4().hex[:8]}"
    ops.require_id(release_id)
    releases=target/'data/releases';releases.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.staging-',dir=releases)).resolve()
    try:
        (stage/'manuscript').mkdir();(stage/'manuscript/paper.md').write_bytes(state.paper_bytes)
        if pdf_path:shutil.copy2(pdf_path,stage/'manuscript/paper.pdf')
        shutil.copytree(state.path,stage/'audit/ledger')
        write_json(stage/'audit/workflow.json',state.snapshot.get('workflow',{}))
        credentials=set()
        for src in set(local_sources.values()):
            if src.suffix.lower() not in TEXT_EXTENSIONS:continue
            text=src.read_text(encoding='utf-8',errors='replace')
            for value in re.findall(r'''(?i)(?:password|api_key|secret|token)["']?\s*[:=]\s*["']([^"']{6,})["']''',text):
                if not any(c.isspace() for c in value):credentials.add(value.encode())
            for value in re.findall(r'postgres(?:ql)?://[^\s:]+:([^\s@]+)@',text):credentials.add(value.encode())
        file_map={};source_index=[];redacted=set()
        for eid,src in local_sources.items():
            raw=src.read_bytes();safe=raw
            if src.suffix.lower() in TEXT_EXTENSIONS:
                for secret in credentials:safe=safe.replace(secret,b'[REDACTED-CREDENTIAL]')
            h=hashlib.sha256(safe).hexdigest();rel='sources/'+h+src.suffix.lower();dest=stage/rel
            dest.parent.mkdir(exist_ok=True);dest.write_bytes(safe)
            ev=data['evidence'][eid];ev['localPath']=rel
            file_map[eid]={'path':rel,'locator':ev['locator'],'quote':ev['quote']}
            original=hashlib.sha256(raw).hexdigest()
            if safe!=raw:
                redacted.add(rel);ev['bundleRedaction']={'kind':'credential-only','originalSha256':original,'packageSha256':h,'lineCountUnchanged':raw.count(b'\n')==safe.count(b'\n')}
            source_index.append({'evidenceId':eid,'packagePath':rel,'originalSha256':original,'packageSha256':h})
        write_json(stage/'projection/data.json',data);write_json(stage/'projection/files.json',file_map);write_json(stage/'audit/source-index.json',source_index)
        for file in stage.rglob('*'):
            if file.is_file() and file.suffix.lower() in TEXT_EXTENSIONS and any(secret in file.read_bytes() for secret in credentials):raise PapercheckError('A credential appears in an immutable record; resolve the exposure without rewriting history before distributing it')
        entries=[{'path':f.relative_to(stage).as_posix(),'sha256':sha256_file(f)[7:],'bytes':f.stat().st_size} for f in sorted(stage.rglob('*')) if f.is_file()]
        manifest={'format':'papercheck-release/v1','apiVersion':1,'releaseId':release_id,'state':state.state_id,'snapshot':state.snapshot_id,'paperSha256':state.manifest['input']['sha256'][7:],'pdfSha256':sha256_file(pdf_path)[7:] if pdf_path else None,'createdAt':now_iso(),'counts':{k:data['meta'][k] for k in ['blocks','occurrences','claims','evidence']},'credentialRedactedFiles':len(redacted),'registeredLocalEvidence':len(file_map),'uniqueSourceFiles':len({r['path'] for r in file_map.values()}),'files':entries}
        write_json(stage/'manifest.json',manifest);ops.validate(stage)
        if repo.read_current()!=state.state_id or repo.working_copy_status(state)['changed']:raise PapercheckError('Manuscript or CURRENT changed during export; no inspector version was activated')
        published=releases/release_id
        if published.exists():raise PapercheckError('Release ID already exists; use a new ID')
        for file in stage.rglob('*'):file.chmod(0o755 if file.is_dir() else 0o644)
        stage.chmod(0o755)
        lock=target/'data/.update.lock'
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        try:
            os.close(fd)
            stage.rename(published)
            ops.activate(target/'data',release_id)
        finally:lock.unlink(missing_ok=True)
        return manifest
    finally:
        if stage.exists() and stage.parent==releases.resolve() and stage.name.startswith('.staging-'):shutil.rmtree(stage)

def package_inspector(repo:Repo,output,directory='inspector',release_only=False):
    target=inspector_path(repo,directory);ops=_release_ops(target)
    release_id=(target/'data/CURRENT').read_text().strip();ops.require_id(release_id)
    release=target/'data/releases'/release_id;manifest=ops.validate(release)
    state=repo.load_current()
    if state is None or repo.verify() or repo.working_copy_status(state)['changed'] or manifest['state']!=state.state_id or manifest['paperSha256']!=state.manifest['input']['sha256'][7:]:raise PapercheckError('Inspector is not the current registered manuscript; export again first')
    archive=Path(output).resolve()
    if archive.exists():raise PapercheckError('Refusing to overwrite an existing archive')
    if archive==repo.paper_path or repo.meta in archive.parents or target in archive.parents:raise PapercheckError('Write the ZIP outside the inspector and immutable ledger')
    archive.parent.mkdir(parents=True,exist_ok=True)
    with archive.open('xb') as stream,zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        if not release_only:
            for name,data in _asset_payloads():
                if name.startswith('runtime/'):z.writestr(name.removeprefix('runtime/'),data)
                elif name.startswith('frontend/'):z.writestr(name,data)
            z.writestr('data/CURRENT',release_id+'\n');z.writestr('reviews/.keep','')
        for file in sorted(release.rglob('*')):
            if file.is_file():z.write(file,(file.relative_to(release).as_posix() if release_only else 'data/releases/'+release_id+'/'+file.relative_to(release).as_posix()))
    atomic_write_text(Path(str(archive)+'.sha256'),sha256_file(archive)[7:]+'  '+archive.name+'\n')
    return archive

def serve_inspector(repo:Repo,directory='inspector',port=4178,node='node'):
    target=inspector_path(repo,directory)
    if not 1<=port<=65535:raise PapercheckError('Port must be between 1 and 65535')
    env={**os.environ,'HOST':'127.0.0.1','PORT':str(port),'PAPERCHECK_INSECURE_LOCAL':'1','PAPERCHECK_PYTHON':sys.executable,'PAPERCHECK_WORKSPACE':str(repo.root),'PAPERCHECK_DATA':str(target/'data'),'PAPERCHECK_REVIEWS':str(target/'reviews')}
    print(f'Local read-only inspector: http://127.0.0.1:{port}',flush=True)
    return subprocess.call([node,str(target/'app/server.mjs')],cwd=target,env=env)
