#!/usr/bin/env python3
"""Validate wheel/sdist contents and optionally compare clean rebuilds."""

from __future__ import annotations

import argparse
import hashlib
import re
import tarfile
from pathlib import Path
from zipfile import ZipFile


def _one(root, pattern):
    found = list(Path(root).glob(pattern))
    if len(found) != 1:
        raise SystemExit("expected one %s in %s, found %d" % (pattern, root, len(found)))
    return found[0]


def _wheel_files(path):
    with ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}


def _sdist_files(path):
    with tarfile.open(path, "r:gz") as archive:
        return {member.name.split("/", 1)[-1]: archive.extractfile(member).read()
                for member in archive.getmembers() if member.isfile()}


def _validate(dist):
    wheel, sdist = _one(dist, "*.whl"), _one(dist, "*.tar.gz")
    wheel_files = _wheel_files(wheel)
    names = set(wheel_files)
    schemas = [name for name in names if name.endswith(".schema.json")]
    skills = [name for name in names if "/share/liwm/skills/" in name and name.endswith("/SKILL.md")]
    root = Path(__file__).resolve().parents[1]
    expected_schemas = {path.name for path in (root / "schemas").glob("*.schema.json")}
    if {Path(name).name for name in schemas} != expected_schemas or len(skills) != 15:
        raise SystemExit("wheel runtime assets incomplete: %d schemas, %d skills" %
                         (len(schemas), len(skills)))
    required_wheel = ("liwm/cli.py", "share/liwm/INSTALL_PROMPT.md",
                      "share/liwm/UPDATE_PROMPT.md", "share/liwm/UNINSTALL_PROMPT.md")
    for suffix in required_wheel:
        if not any(name.endswith(suffix) for name in names):
            raise SystemExit("wheel missing %s" % suffix)
    metadata_name = next((name for name in names if name.endswith(".dist-info/METADATA")), None)
    entry_name = next((name for name in names if name.endswith(".dist-info/entry_points.txt")), None)
    metadata = wheel_files.get(metadata_name, b"").decode("utf-8")
    entries = wheel_files.get(entry_name, b"").decode("utf-8")
    for value in ("Name: liwm", "Version: 0.3.0", "Requires-Python: >=3.9"):
        if value not in metadata:
            raise SystemExit("wheel metadata missing %r" % value)
    if "liwm = liwm.cli:main" not in entries:
        raise SystemExit("wheel entry point is missing")

    source_files = _sdist_files(sdist)
    required_source = {
        "MANIFEST.in", "tests/helpers.py", "tests/run_tests.py", "tools/check_release.py",
        "INSTALL_PROMPT.md", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json",
        "THREAT_MODEL.md", "SECURITY.md", "PRIVACY.md", "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md", ".gitignore", "assets/README.md", "examples/README.md",
        "benchmarks/intentbench/README.md",
    }
    missing = sorted(required_source - set(source_files))
    if missing:
        raise SystemExit("sdist missing release inputs: %s" % ", ".join(missing))
    if len([name for name in source_files if name.startswith("skills/") and
            name.endswith("/SKILL.md")]) != 15:
        raise SystemExit("sdist does not contain all 15 skills")
    private = re.compile(r"(^|/)(user|metrics|runtime_context|personal-strategy|promoted-rules)\.json$")
    leaked = sorted(name for name in set(source_files) | names if private.search(name))
    if leaked:
        raise SystemExit("release contains private-state filenames: %s" % leaked)
    return wheel, sdist, source_files


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", default="dist")
    parser.add_argument("--compare", help="second clean build directory")
    args = parser.parse_args(argv)
    wheel, sdist, source = _validate(args.dist)
    if args.compare:
        other_wheel, _, other_source = _validate(args.compare)
        if hashlib.sha256(wheel.read_bytes()).digest() != hashlib.sha256(other_wheel.read_bytes()).digest():
            raise SystemExit("wheel rebuild is not byte reproducible")
        if source != other_source:
            raise SystemExit("sdist rebuild has different normalized file contents")
    print("release validation passed:", wheel.name, sdist.name)


if __name__ == "__main__":
    main()
