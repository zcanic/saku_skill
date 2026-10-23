"""Smoke test the installed wheel without importing the developer checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--target',required=True);args=parser.parse_args()
    installed=Path(args.target).resolve();sys.path.insert(0,str(installed))
    import papercheck
    from papercheck.cli import main as cli
    assert Path(papercheck.__file__).resolve().is_relative_to(installed),papercheck.__file__
    with tempfile.TemporaryDirectory(prefix='papercheck-installed-smoke-') as temporary:
        root=Path(temporary);work=root/'paper'
        assert cli(['scaffold',str(work)])==0
        assert (work/'.agents/skills/papercheck/SKILL.md').is_file()
        (work/'paper.md').write_text('Synthetic installation verification only.\n',encoding='utf-8')
        assert cli(['--root',str(work),'init'])==0
        assert cli(['--root',str(work),'inspector','init'])==0
        assert cli(['--root',str(work),'inspector','export','--release-id','install-smoke'])==0
        archive=root/'site.zip'
        assert cli(['--root',str(work),'inspector','package','--output',str(archive)])==0
        with zipfile.ZipFile(archive) as z:
            assert 'app/dist/index.html' in z.namelist()
            assert 'THIRD_PARTY_NOTICES.txt' in z.namelist()
            assert json.loads(z.read('data/releases/install-smoke/manifest.json'))['counts']['occurrences']==0
            assert z.read('data/releases/install-smoke/manuscript/paper.md')==(work/'paper.md').read_bytes()
        print(f'Installed {papercheck.__version__} smoke passed: {papercheck.__file__}; ZIP sha256={hashlib.sha256(archive.read_bytes()).hexdigest()}')

if __name__=='__main__':main()
