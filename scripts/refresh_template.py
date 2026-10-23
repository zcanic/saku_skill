"""Refresh only a verified, unmodified generated template; never a used workspace."""
import json
from pathlib import Path
from export_template import ROOT, digest, payloads

def main():
    target=(ROOT/'template').resolve()
    previous=json.loads((target/'TEMPLATE-MANIFEST.json').read_text(encoding='utf-8'))
    old=previous['files']
    actual={p.relative_to(target).as_posix():p.read_bytes() for p in target.rglob('*') if p.is_file()}
    if set(actual)!=set(old)|{'TEMPLATE-MANIFEST.json'}:
        raise RuntimeError('Template contains missing or extra files; export to a fresh directory instead')
    for name,expected in old.items():
        if digest(actual[name])!=expected:
            raise RuntimeError(f'Template modified: {name}; will not overwrite user content')
    new=payloads()
    # Preserve the previous pristine source template as a recoverable ZIP.
    from export_template import write_archive
    backup=ROOT/'dist'/f"papercheck-template-{previous['version']}-before-refresh.zip"
    if not backup.exists():write_archive(actual,backup)
    for name,data in new.items():
        file=target/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
    for name in set(old)-set(new):
        file=(target/name).resolve()
        if target not in file.parents:raise RuntimeError('Unsafe old template path')
        file.unlink()
    print(f'Refreshed {len(new)} generated template files; previous pristine version: {backup}')

if __name__=='__main__':main()
