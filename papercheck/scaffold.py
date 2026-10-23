"""Create a project from bundled workflow documents without overwriting files."""
from importlib.resources import files
from pathlib import Path


def scaffold(destination, paper=None):
    root = Path(destination).resolve()
    template = files("papercheck").joinpath("template")
    payloads = {}

    def walk(node, prefix=""):
        for item in node.iterdir():
            relative = prefix + item.name
            if item.is_dir():
                walk(item, relative + "/")
            else:
                payloads[relative] = item.read_bytes()

    walk(template)
    for name in ("proposal.schema.json", "records.schema.json"):
        payloads["contracts/" + name] = files("papercheck").joinpath("schemas", name).read_bytes()
    if paper:
        data = Path(paper).read_bytes()
        data.decode("utf-8")
        payloads["paper.md"] = data
    payloads.setdefault("paper.md", "# 论文标题\n\n在此放入论文正文。\n".encode("utf-8"))
    conflicts = [str(root / p) for p in payloads if (root / p).exists()]
    if conflicts:
        raise ValueError("scaffold would overwrite existing files: " + ", ".join(conflicts))
    for relative, data in payloads.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    (root / "references").mkdir(exist_ok=True)
    return root, sorted(payloads)
