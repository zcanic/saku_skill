"""Synthetic manuscripts only: reusable UI projection and independent release lifecycle."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile

import pytest

from papercheck.cli import main
from papercheck.inspector import init_inspector, project, export_inspector, package_inspector, _release_ops
from papercheck.storage import Repo, PapercheckError
from test_semantic import proposal, canonical


def registered(root, source='references/measurement.json', content='{"value": 7}', status='supported'):
    repo=Repo(root)
    path=root/source;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf-8')
    p=proposal(repo, 'Synthetic X causes Y.')
    p['semantic'].update(references=[{'ref':'r','title':'Synthetic source','source_access':'full_text'}],
        evidence=[{'ref':'e','reference':'r','quote':'Synthetic measurement','locator':{'source_file':source,'pointer':'/value'}}],
        assessments=[{'claim':'c','evidence':'e','status':status,'reason':'Synthetic source read by test fixture'}])
    repo.commit(proposal=p)
    return repo


def test_projection_uses_real_binding_ids_current_checks_and_source_roots(tmp_path):
    repo=registered(tmp_path)
    data,sources,state=project(repo)
    occurrence=next(iter(data['claims'].values()))
    assert occurrence['key']==state.bindings[0]['id']
    assert occurrence['category']=='reviewed' and occurrence['checks']
    assert data['meta']['pendingTasks']==0
    assert len(sources)==1 and data['blocks'][0]['raw']==repo.paper_path.read_text()
    denied,files,_=project(repo,source_roots=[])
    assert not files
    assert 'outside' in next(iter(denied['evidence'].values()))['localAccessNote']


@pytest.mark.parametrize('status,category',[('partially_supported','partial'),('unsupported','issue'),('counterevidence','conflict')])
def test_assessment_categories_remain_distinct(tmp_path,status,category):
    data,_,_=project(registered(tmp_path,status=status))
    assert next(iter(data['claims'].values()))['category']==category


def test_dirty_manuscript_cannot_export_or_package(tmp_path):
    repo=registered(tmp_path);init_inspector(repo);export_inspector(repo)
    repo.paper_path.write_text('Unregistered revision.',encoding='utf-8')
    with pytest.raises(PapercheckError,match='differs'):export_inspector(repo)
    with pytest.raises(PapercheckError,match='not the current'):package_inspector(repo,tmp_path/'bad.zip')
    assert not (tmp_path/'bad.zip').exists()


def test_text_only_snapshot_and_untracked_bytes_are_not_hidden(tmp_path):
    repo=Repo(tmp_path);repo.paper_path.write_text('# Synthetic\n\nA claim not extracted.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n',encoding='utf-8');repo.commit(auto=True)
    data,_,_=project(repo)
    assert not data['claims'] and data['meta']['workflowStatus']=='pending'
    assert any('not extracted' in b['raw'] for b in data['blocks'])
    # Parser may track a table or preserve it untracked; both must be rendered.
    assert any('| 1 | 2 |' in b['raw'] for b in data['blocks'])
    init_inspector(repo);manifest=export_inspector(repo)
    assert manifest['counts']['occurrences']==0


def test_invalidated_check_is_history_only(tmp_path):
    repo=Repo(tmp_path);p=proposal(repo)
    p['semantic']['claims'].append({'ref':'conclusion','surface_statement':'Conclusion','canonical_statement':canonical('conclusion')})
    p['semantic']['bindings'].append({'claim':'conclusion','segment':'s','reason':'Synthetic second claim'})
    p['semantic']['relations']=[{'src':'conclusion','dst':'c','type':'DEPENDS_ON','status':'confirmed','reason':'Synthetic dependency'}]
    p['semantic']['checks']=[{'claim_ids':['conclusion'],'kind':'logic','outcome':'pass','method':'fixture','reason':'Synthetic check'}]
    repo.commit(proposal=p)
    p=proposal(repo,'Revised synthetic premise.',canonical('new_predicate'))
    p['semantic']['bindings'].append({'claim':'C000002','segment':'s','reason':'Conclusion remains'})
    repo.commit(proposal=p)
    data,_,_=project(repo)
    conclusion=next(c for c in data['claims'].values() if c['claimId']=='C000002')
    assert conclusion['category']=='pending'
    assert not conclusion['checks'] and conclusion['historicalChecks'][0]['outcome']=='pass'


def test_full_and_version_zip_exclude_notes_credentials_and_other_versions(tmp_path):
    repo=registered(tmp_path);root=init_inspector(repo)
    first=export_inspector(repo,release_id='synthetic-one')
    second=export_inspector(repo,release_id='synthetic-two')
    (root/'.env').write_text('PRIVATE=do-not-distribute');(root/'reviews/note.json').write_text('private note')
    full=package_inspector(repo,tmp_path/'site.zip');version=package_inspector(repo,tmp_path/'version.zip',release_only=True)
    with zipfile.ZipFile(full) as z:
        assert z.read('data/CURRENT')==b'synthetic-two\n'
        assert 'app/dist/index.html' in z.namelist()
        assert 'LICENSE' in z.namelist() and 'MIT License' in z.read('LICENSE').decode()
        assert not any('synthetic-one' in n or n=='.env' or n=='reviews/note.json' for n in z.namelist())
    with zipfile.ZipFile(version) as z:
        assert 'manifest.json' in z.namelist() and not any(n.startswith('app/') for n in z.namelist())
    assert Path(str(full)+'.sha256').read_text().startswith(hashlib.sha256(full.read_bytes()).hexdigest())
    ops=_release_ops(root);server_data=tmp_path/'server/data'
    assert ops.import_zip(server_data,version)['releaseId']==second['releaseId']
    assert ops.validate(server_data/'releases/synthetic-two')['pdfSha256'] is None
    with pytest.raises(PapercheckError,match='overwrite'):package_inspector(repo,full)
    with pytest.raises(PapercheckError,match='Release ID'):export_inspector(repo,release_id=first['releaseId'])
    assert (root/'data/CURRENT').read_text().strip()=='synthetic-two'


def test_credential_redaction_preserves_original_and_discloses_copy_hash(tmp_path):
    secret='fixture-secret-not-a-real-password'
    repo=registered(tmp_path,source='references/setup.py',content=f'password = "{secret}"\nvalue = 7\n')
    root=init_inspector(repo);manifest=export_inspector(repo)
    release=root/'data/releases'/manifest['releaseId'];data=json.loads((release/'projection/data.json').read_text())
    ev=next(iter(data['evidence'].values()))
    assert secret not in (release/ev['localPath']).read_text()
    assert ev['bundleRedaction']['lineCountUnchanged']
    assert secret in (tmp_path/'references/setup.py').read_text()
    assert ev['bundleRedaction']['originalSha256']!=ev['bundleRedaction']['packageSha256']


def test_multi_range_utf8_projection_reconstructs_exact_join(tmp_path):
    repo=Repo(tmp_path);paper='甲\n乙'.encode();repo.paper_path.write_bytes(paper)
    p={'schema_version':'1.1.0','base_state_id':None,'base_sha256':None,'paper_sha256':'sha256:'+hashlib.sha256(paper).hexdigest(),
       'segments':[{'ref':'s','block_ref':'p','kind':'paragraph','source_ranges':[{'start_byte':0,'end_byte':3},{'start_byte':4,'end_byte':7}]}],
       'untracked':[{'start_byte':3,'end_byte':4,'reason':'newline'}]}
    repo.commit(proposal=p);data,_,_=project(repo)
    assert data['blocks'][0]['raw']=='甲\n乙'
    root=init_inspector(repo);manifest=export_inspector(repo)
    assert _release_ops(root).validate(root/'data/releases'/manifest['releaseId'])


def test_scaffold_has_project_skill_and_inspector_cli(tmp_path):
    work=tmp_path/'work'
    assert main(['scaffold',str(work)])==0
    assert (work/'.agents/skills/papercheck/SKILL.md').is_file()
    (work/'paper.md').write_text('Synthetic unexamined text.',encoding='utf-8')
    assert main(['--root',str(work),'init'])==0
    assert main(['--root',str(work),'inspector','init'])==0
    assert main(['--root',str(work),'inspector','export'])==0
    assert main(['--root',str(work),'inspector','package','--output',str(tmp_path/'site.zip')])==0


def test_independent_node_runtime_stale_notes_switch_and_rollback(tmp_path):
    node=shutil.which('node') or ('D:/tools/node24/node.exe' if Path('D:/tools/node24/node.exe').exists() else None)
    if not node:pytest.skip('Node runtime unavailable')
    repo=registered(tmp_path);root=init_inspector(repo);first=export_inspector(repo,release_id='runtime-one')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={**os.environ,'PORT':str(port),'HOST':'127.0.0.1','PAPERCHECK_INSECURE_LOCAL':'1','PAPERCHECK_WORKSPACE':str(tmp_path)}
    process=subprocess.Popen([node,str(root/'app/server.mjs')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    def request(route,body=None):
        req=Request(f'http://127.0.0.1:{port}'+route,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=5) as response:return json.load(response)
    try:
        for _ in range(100):
            try:data=request('/api/data');break
            except URLError:time.sleep(.05)
        else:pytest.fail('Inspector failed to start')
        assert not data['live']['stale'] and not data['meta'].get('manuscriptPdfUrl')
        key=next(iter(data['claims']));eid=next(iter(data['evidence']))
        assert '7' in request('/api/evidence/'+eid)['text']
        row={'key':key,'sha256':data['meta']['sha256'],'releaseId':'runtime-one','status':'checked','note':'Synthetic note'}
        assert request('/api/notes',row)['status']=='checked'
        repo.paper_path.write_text('Unregistered synthetic edit.',encoding='utf-8')
        assert request('/api/status')['stale']
        with pytest.raises(HTTPError) as exc:request('/api/notes',row)
        assert exc.value.code==409
        repo.paper_path.write_bytes(repo.load_current().paper_bytes)
        export_inspector(repo,release_id='runtime-two')
        assert request('/api/data')['meta']['releaseId']=='runtime-two'
        assert not request('/api/notes')
        ops=_release_ops(root);ops.activate(root/'data','runtime-one')
        assert len(request('/api/notes'))==1
        with pytest.raises(HTTPError) as exc:request('/api/manuscript.pdf')
        assert exc.value.code==404
        release=root/'data/releases/runtime-one'
        source=json.loads((release/'projection/files.json').read_text())[eid]['path']
        (release/source).write_text('tampered synthetic source',encoding='utf-8')
        with pytest.raises(HTTPError) as exc:request('/api/file/'+eid)
        assert exc.value.code==503
    finally:
        process.terminate();process.wait(timeout=10)
