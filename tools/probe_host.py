#!/usr/bin/env python3
"""Ask a host binary what it actually loads, instead of trusting its docs.

``docs/HOST_ACCEPTANCE.md`` is a manual protocol: it needs a person, a model
and a real session.  Most of it still does.  But one step in it -- *"the
official skills location is still valid and loaded"* -- is a claim the host can
answer itself, offline, for free, and it is the claim most likely to rot:
vendors move config directories between releases and LIWM would go on
installing into the old one.

This probe builds a throwaway host configuration, puts one real LIWM skill in
the place the registry says skills go, runs the host's own introspection
command, and reports whether the host found it.  No model runs and no
credentials are needed.

    python tools/probe_host.py opencode
    python tools/probe_host.py --all

A host with no non-interactive introspection is reported as such rather than
guessed at, because "not checkable this way" and "checked and fine" are
different states and only one of them is evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from liwm.hosts import get_host, load_registry  # noqa: E402

#: How to ask each host to enumerate the skills it can see.  ``config_env`` is
#: the variable that relocates its configuration directory, which is what makes
#: the probe safe to run against a machine someone is using.
INTROSPECTION = {
    "opencode": {
        "config_env": "OPENCODE_CONFIG_DIR",
        "argv": ["opencode", "debug", "skill"],
        "parse": "json_list_of_name",
    },
}


def _skill_source():
    skill = REPO / "skills" / "liwm" / "SKILL.md"
    if not skill.is_file():
        raise SystemExit("no skills/liwm/SKILL.md to probe with")
    return skill


def _stage(spec, root):
    """Lay a single LIWM skill out where the registry says the host reads them."""
    rel = spec.get("skills_rel")
    if not rel:
        return None
    target = root / rel / "liwm"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(_skill_source(), target / "SKILL.md")
    return target


def probe(host_id):
    spec = get_host(host_id)
    if spec is None:
        return {"host": host_id, "status": "unknown_host"}

    recipe = INTROSPECTION.get(host_id)
    if recipe is None:
        return {"host": host_id, "status": "no_introspection",
                "detail": "this host has no non-interactive way to report what it "
                          "loaded; use the manual protocol in docs/HOST_ACCEPTANCE.md"}
    if shutil.which(recipe["argv"][0]) is None:
        return {"host": host_id, "status": "not_installed",
                "detail": "%s is not on PATH" % recipe["argv"][0]}

    root = Path(tempfile.mkdtemp(prefix="liwm-probe-"))
    try:
        staged = _stage(spec, root)
        if staged is None:
            return {"host": host_id, "status": "no_skills_path",
                    "detail": "the registry claims no user-level skills directory"}
        (root / "opencode.json").write_text(
            '{"$schema": "https://opencode.ai/config.json"}\n', encoding="utf-8")

        env = dict(os.environ)
        env[recipe["config_env"]] = str(root)
        try:
            completed = subprocess.run(recipe["argv"], capture_output=True, text=True,
                                       env=env, timeout=180, cwd=str(root), check=False)
        except (OSError, subprocess.SubprocessError) as error:
            return {"host": host_id, "status": "error", "detail": str(error)}

        found, names = _parse(recipe["parse"], completed.stdout, str(staged))
        return {
            "host": host_id,
            "status": "loaded" if found else "not_loaded",
            "staged_at": str(staged),
            "skills_reported": names[:20],
            "command": " ".join(recipe["argv"]),
            "exit_code": completed.returncode,
            "detail": ("the host reported the staged LIWM skill" if found else
                       "the host did not report the staged skill; the registry's "
                       "skills path is probably wrong for this version"),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _parse(kind, stdout, staged):
    if kind != "json_list_of_name":
        raise ValueError("unknown parse mode %r" % kind)
    try:
        rows = json.loads(stdout)
    except ValueError:
        return False, []
    names = [str(row.get("name")) for row in rows if isinstance(row, dict)]
    found = any(
        isinstance(row, dict) and str(row.get("location") or "").startswith(staged)
        for row in rows
    )
    return found, names


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("host", nargs="?")
    parser.add_argument("--all", action="store_true",
                        help="probe every host in the registry")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.host and not args.all:
        parser.error("name a host, or pass --all")

    hosts = ([h["id"] for h in load_registry()] if args.all else [args.host])
    results = [probe(host_id) for host_id in hosts]

    if args.json:
        sys.stdout.write(json.dumps(results, indent=2) + "\n")
    else:
        for row in results:
            sys.stdout.write("%-16s %-16s %s\n" % (
                row["host"], row["status"], row.get("detail", "")))
    # Only a host that was actually probed and failed is a failure; "not
    # installed here" is not evidence of anything.
    return 1 if any(row["status"] == "not_loaded" for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
