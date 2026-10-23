"""Build reusable UI assets and an explicit distribution allowlist (no paper data)."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]/'papercheck/inspector_assets'

def main():
    frontend=ROOT/'frontend';runtime=ROOT/'runtime'
    npm=shutil.which('npm.cmd') or shutil.which('npm')
    if not npm:raise RuntimeError('Node.js/npm required for developer asset rebuild')
    subprocess.run([npm,'ci','--ignore-scripts'],cwd=frontend,check=True)
    subprocess.run([npm,'run','build'],cwd=frontend,check=True)
    target=runtime/'app/dist'
    # Only the explicit generated static asset directory is replaced.
    if target.exists():
        if target.resolve()!=ROOT.resolve()/'runtime/app/dist':raise RuntimeError('Unexpected build destination')
        shutil.rmtree(target)
    shutil.copytree(frontend/'dist',target)
    notices=[]
    for package in sorted((frontend/'node_modules').glob('**/package.json')):
        # npm package metadata and licenses only; never copy installed program code.
        try:metadata=json.loads(package.read_text(encoding='utf-8'))
        except (ValueError,UnicodeError):continue
        license_files=[p for p in package.parent.iterdir() if p.is_file() and p.name.lower().startswith(('license','licence','copying'))]
        if not license_files:continue
        notices.append('\n=== '+str(metadata.get('name','package'))+' '+str(metadata.get('version',''))+' ===\n')
        for p in license_files:notices.append(p.read_text(encoding='utf-8',errors='replace'))
    (runtime/'THIRD_PARTY_NOTICES.txt').write_bytes('\n'.join(notices).encode('utf-8'))
    sources=[p for p in frontend.iterdir() if p.is_file() and p.suffix in {'.json','.html','.ts'}]
    sources+=list((frontend/'src').glob('*'))
    sources+=[runtime/n for n in ['Dockerfile','compose.yaml','.env.example','.dockerignore','.gitignore','README.md','AGENTS.md','UPDATE_SOP.md','LICENSE']]
    sources.append(runtime/'THIRD_PARTY_NOTICES.txt')
    sources+=list((runtime/'app').glob('*.mjs'))+list((runtime/'app').glob('*.py'))+list((runtime/'ops').glob('*.py'))
    sources += [p for p in target.rglob('*') if p.is_file()]
    # Normalize authored text before hashing; never normalize fonts or other binary assets.
    for p in sources:
        if p.suffix in {'.json','.html','.ts','.tsx','.css','.mjs','.py','.md','.yaml','.txt'} or p.name in {'Dockerfile','.env.example','.dockerignore','.gitignore','LICENSE'}:
            raw=p.read_bytes();normal=raw.replace(b'\r\n',b'\n')
            if raw!=normal:p.write_bytes(normal)
    manifest={'format':'papercheck-inspector-assets/v1','files':{p.relative_to(ROOT).as_posix():'sha256:'+hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(sources)}}
    (ROOT/'ASSET-MANIFEST.json').write_bytes((json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode('utf-8'))
    print(f'Prepared {len(sources)} reusable inspector assets')

if __name__=='__main__':main()
