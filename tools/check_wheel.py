#!/usr/bin/env python3
from pathlib import Path
from zipfile import ZipFile

wheels = list((Path(__file__).resolve().parents[1] / "dist").glob("*.whl"))
if len(wheels) != 1:
    raise SystemExit("expected exactly one wheel, found %d" % len(wheels))
with ZipFile(wheels[0]) as archive:
    names = archive.namelist()
    schemas = [n for n in names if n.endswith(".schema.json")]
    if len(schemas) != 8:
        raise SystemExit("wheel contains %d schemas, expected 8: %r" % (len(schemas), schemas))
    if not any(n.endswith("liwm/cli.py") for n in names):
        raise SystemExit("wheel does not contain liwm/cli.py")
print("wheel validation passed:", wheels[0].name)
