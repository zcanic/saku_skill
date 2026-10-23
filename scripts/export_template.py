"""Export a clean, source-complete project using an explicit allowlist.

No developer workspace, history, credentials, fixtures, bytecode or installed
dependencies are copied. Export refuses existing destinations and archives.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def project_toml():
    original = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = {k: v for k, v in original["project"].items() if k != "optional-dependencies" and k != "scripts"}
    project["readme"] = "README.md"
    sections = [("build-system", original["build-system"]), ("project", project),
                ("project.optional-dependencies", {"postgres": original["project"]["optional-dependencies"]["postgres"]}),
                ("project.scripts", original["project"]["scripts"]),
                ("tool.setuptools.packages.find", original["tool"]["setuptools"]["packages"]["find"]),
                ("tool.setuptools.package-data", original["tool"]["setuptools"]["package-data"])]
    result = []
    for heading, fields in sections:
        result.append(f"[{heading}]")
        def value_literal(value):
            if isinstance(value, dict):
                return '{' + ', '.join(f'{key} = {value_literal(item)}' for key, item in value.items()) + '}'
            return json.dumps(value, ensure_ascii=False)
        result.extend(f"{key} = {value_literal(value)}" for key, value in fields.items())
        result.append("")
    return ("\n".join(result).rstrip() + "\n").encode("utf-8")


def payloads():
    files = {}
    package = ROOT / "papercheck"
    for path in sorted(package.glob("*.py")):
        files["papercheck/" + path.name] = path.read_bytes()
    for path in sorted((package / "schemas").glob("*.json")):
        files["papercheck/schemas/" + path.name] = path.read_bytes()
        files["contracts/" + path.name] = path.read_bytes()
    for relative in ["AGENTS.md", "PROJECT.md", ".gitignore", "LICENSE"]:
        data = (package / "template" / relative).read_bytes()
        files[relative] = data
        files["papercheck/template/" + relative] = data
    for directory, suffix in [("workflow", "*.md"), ("templates", "*.json")]:
        for path in sorted((package / "template" / directory).glob(suffix)):
            data = path.read_bytes()
            files[f"{directory}/{path.name}"] = data
            files[f"papercheck/template/{directory}/{path.name}"] = data
    files["README.md"] = (ROOT / "distribution" / "README.md").read_bytes()
    for path in sorted((package / 'template/.agents/skills/papercheck').glob('*.md')):
        relative='.agents/skills/papercheck/'+path.name
        files[relative]=path.read_bytes()
        files['papercheck/template/'+relative]=path.read_bytes()
    asset_root=package/'inspector_assets'
    asset_manifest=json.loads((asset_root/'ASSET-MANIFEST.json').read_text(encoding='utf-8'))
    for name, expected in asset_manifest['files'].items():
        data=(asset_root/name).read_bytes()
        if digest(data)!=expected:raise ValueError(f'Inspector asset mismatch: {name}')
        files['papercheck/inspector_assets/'+name]=data
    files['papercheck/inspector_assets/ASSET-MANIFEST.json']=(asset_root/'ASSET-MANIFEST.json').read_bytes()
    files["AGENTS.md"] = (
        "<!-- 此完整模板自带工具源码。首次运行前读 README.md 并执行 python -m pip install -e . -->\n\n".encode()
        + files["AGENTS.md"]
    )
    files["pyproject.toml"] = project_toml()
    files["paper.md"] = b""
    files["references/.gitkeep"] = b""
    files[".gitattributes"] = b"* text=auto eol=lf\n"
    files[".gitignore"] += b"\n.venv/\n*.pyc\n*.egg-info/\nbuild/\ndist/\n!papercheck/inspector_assets/runtime/app/dist/\n!papercheck/inspector_assets/runtime/app/dist/**\n"
    # Canonical LF makes the exported bytes identical across Windows checkouts.
    files = {name: (data if name.startswith('papercheck/inspector_assets/') else data.replace(b"\r\n", b"\n")) for name, data in files.items()}
    metadata = tomllib.loads(files["pyproject.toml"].decode())
    manifest = {"template": "papercheck", "version": metadata["project"]["version"],
                "files": {name: digest(data) for name, data in sorted(files.items())}}
    files["TEMPLATE-MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    return dict(sorted(files.items()))


def export(destination, archive=None, check=False):
    destination = Path(destination).resolve()
    archive = Path(archive).resolve() if archive else None
    if archive and destination in archive.parents:
        raise ValueError("archive must be outside the template directory")
    expected = payloads()
    if check:
        actual = {str(p.relative_to(destination)).replace("\\", "/"): p.read_bytes()
                  for p in destination.rglob("*") if p.is_file()}
        if actual != expected:
            missing = sorted(expected.keys() - actual.keys())
            extra = sorted(actual.keys() - expected.keys())
            changed = sorted(k for k in actual.keys() & expected.keys() if actual[k] != expected[k])
            raise ValueError(f"template differs: missing={missing}, extra={extra}, changed={changed}")
        if archive:
            write_archive(expected, archive)
        return expected
    if destination.exists():
        raise ValueError(f"refusing to overwrite existing template: {destination}")
    if archive and archive.exists():
        raise ValueError(f"refusing to overwrite existing archive: {archive}")
    for name, data in expected.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if archive:
        write_archive(expected, archive)
    return expected


def write_archive(expected, archive):
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("xb") as stream, zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for name, data in expected.items():
            info = zipfile.ZipInfo("papercheck-template/" + name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zipped.writestr(info, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--zip", dest="archive", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = export(args.output, args.archive, args.check)
    print(f"{'checked' if args.check else 'exported'} {len(files)} files: {args.output.resolve()}")
    if args.archive:
        print(f"archive: {args.archive.resolve()}")


if __name__ == "__main__":
    main()
