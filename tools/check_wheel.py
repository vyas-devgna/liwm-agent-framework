#!/usr/bin/env python3
from pathlib import Path
from zipfile import ZipFile

wheels = list((Path(__file__).resolve().parents[1] / "dist").glob("*.whl"))
if len(wheels) != 1:
    raise SystemExit("expected exactly one wheel, found %d" % len(wheels))
with ZipFile(wheels[0]) as archive:
    names = archive.namelist()
    schemas = [n for n in names if n.endswith(".schema.json")]
    expected_schemas = {p.name for p in
                        (Path(__file__).resolve().parents[1] / "schemas").glob("*.schema.json")}
    if {Path(name).name for name in schemas} != expected_schemas:
        raise SystemExit("wheel schema set differs from source: %r" % schemas)
    if not any(n.endswith("liwm/cli.py") for n in names):
        raise SystemExit("wheel does not contain liwm/cli.py")
    if len([n for n in names if "/share/liwm/skills/" in n and n.endswith("/SKILL.md")]) != 15:
        raise SystemExit("wheel does not contain all 15 runtime skills")
    for prompt in ("INSTALL_PROMPT.md", "UPDATE_PROMPT.md", "UNINSTALL_PROMPT.md"):
        if not any(n.endswith("/share/liwm/" + prompt) for n in names):
            raise SystemExit("wheel does not contain %s" % prompt)
print("wheel validation passed:", wheels[0].name)
