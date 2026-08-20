#!/usr/bin/env python3
"""Dependency-free release structure, docs, schema, adapter, and skill checks."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from liwm.schema import SchemaStore  # noqa: E402

REQUIRED = {
    "README.md", "LICENSE", "CONTRIBUTING.md", "SECURITY.md",
    "CODE_OF_CONDUCT.md", "CHANGELOG.md", "ROADMAP.md", "ARCHITECTURE.md",
    "PRIVACY.md", "THREAT_MODEL.md", "INSTALL_PROMPT.md", "UPDATE_PROMPT.md",
    "UNINSTALL_PROMPT.md", "RELEASE_CHECKLIST.md", "MANIFEST.in",
    ".gitignore", "pyproject.toml",
    ".github/workflows/ci.yml", ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
}

REQUIRED_SKILLS = {
    "liwm", "liwm-onboarding", "liwm-profile", "liwm-intent-discovery",
    "liwm-question-planner", "liwm-project-intent", "liwm-counterfactual",
    "liwm-feedback", "liwm-learning", "liwm-retrospective",
    "liwm-profile-maintenance", "liwm-traceability", "liwm-evaluation",
    "liwm-privacy", "liwm-self-improvement",
}


def fail(errors, message):
    errors.append(message)


def check_markdown_links(errors):
    link_re = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
    for path in ROOT.rglob("*.md"):
        if any(part in {".git", ".venv"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        for raw in link_re.findall(text):
            target = raw.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            candidate = (path.parent / target).resolve()
            if not candidate.exists():
                fail(errors, "%s: broken local link %s" % (path.relative_to(ROOT), raw))


def main():
    errors = []
    for rel in sorted(REQUIRED):
        if not (ROOT / rel).is_file():
            fail(errors, "missing required file %s" % rel)

    installers = list(ROOT.glob("install.*")) + list(ROOT.glob("uninstall.*"))
    forbidden = [p for p in installers if p.suffix.lower() in {".sh", ".ps1", ".exe", ".bat"}]
    if forbidden:
        fail(errors, "forbidden installer scripts: %s" % forbidden)

    skills = {p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md")}
    if skills != REQUIRED_SKILLS:
        fail(errors, "skill set mismatch: missing=%s extra=%s"
             % (sorted(REQUIRED_SKILLS - skills), sorted(skills - REQUIRED_SKILLS)))
    for skill_file in (ROOT / "skills").glob("*/SKILL.md"):
        text = skill_file.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if not match or not re.search(r"^name:\s*\S+", match.group(1), re.M) \
                or not re.search(r"^description:\s*\S+", match.group(1), re.M):
            fail(errors, "%s: missing valid name/description frontmatter" % skill_file)

    # Every shipped block must be a single well-formed unit that the installer
    # can upsert, and must fit the tightest budget it is offered for.
    blocks = sorted((ROOT / "adapters").rglob("*.md"))
    block_files = [b for b in blocks if b.name == "bootstrap.md"
                   or b.parent.name == "blocks"]
    if len(block_files) < 5:
        fail(errors, "expected at least 5 bootstrap blocks, found %d" % len(block_files))
    for block_file in block_files:
        block = block_file.read_text(encoding="utf-8")
        rel = block_file.relative_to(ROOT)
        if block.count("<!-- LIWM:BEGIN") != 1 or block.count("<!-- LIWM:END -->") != 1:
            fail(errors, "%s markers invalid" % rel)
        if len(block.encode("utf-8")) > 1536:
            fail(errors, "%s exceeds 1.5 KiB" % rel)
        if "{{LIWM_COMMAND}}" not in block:
            fail(errors, "%s does not use the {{LIWM_COMMAND}} placeholder" % rel)
        # The compact block exists for hosts with a hard cap; the tightest
        # documented one is Windsurf's 6,000 characters, and LIWM must leave
        # most of that for the user's own rules.
        if block_file.name == "compact.md" and len(block.encode("utf-8")) > 768:
            fail(errors, "%s must stay under 768 bytes to fit tight host budgets" % rel)

    # Every host in the registry must be reachable from the adapter index, so a
    # newly supported host cannot ship undocumented.
    from liwm.hosts import BUILTIN_HOSTS

    index = (ROOT / "adapters" / "README.md").read_text(encoding="utf-8")
    for host in BUILTIN_HOSTS:
        if host["name"] not in index:
            fail(errors, "adapters/README.md does not document host %r" % host["id"])

    for path in list((ROOT / "schemas").glob("*.json")) + [
        ROOT / ".claude-plugin" / "plugin.json", ROOT / ".codex-plugin" / "plugin.json"
    ]:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            fail(errors, "%s: invalid JSON: %s" % (path.relative_to(ROOT), exc))

    schemas = SchemaStore()
    expected_schemas = {"user", "event", "project-intent", "runtime-context",
                        "metrics", "candidate-rule", "personal-strategy", "config",
                        "intentbench-case", "install-plan", "intent-graph"}
    if set(schemas.available()) != expected_schemas:
        fail(errors, "schema set mismatch: %s" % sorted(schemas.available()))

    from liwm import __version__
    from liwm.migrate import CURRENT_SCHEMA_VERSION

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.M)
    versions = {"python package": __version__, "schema": CURRENT_SCHEMA_VERSION,
                "pyproject": match.group(1) if match else None}
    for manifest in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        versions[manifest] = json.loads((ROOT / manifest).read_text(encoding="utf-8"))["version"]
    for skill_file in (ROOT / "skills").glob("*/SKILL.md"):
        match = re.search(r"^  version:\s*(\S+)", skill_file.read_text(encoding="utf-8"), re.M)
        versions[str(skill_file.relative_to(ROOT))] = match.group(1) if match else None
    for block_file in block_files:
        marker = re.search(r"<!-- LIWM:BEGIN v([^\s>]+)",
                           block_file.read_text(encoding="utf-8"))
        versions[str(block_file.relative_to(ROOT))] = marker.group(1) if marker else None
    for module in (ROOT / "src" / "liwm").glob("*.py"):
        match = re.search(r'^SCHEMA_VERSION = "([^"]+)"$',
                          module.read_text(encoding="utf-8"), re.M)
        if match:
            versions[str(module.relative_to(ROOT))] = match.group(1)
    mismatched = {name: version for name, version in versions.items() if version != __version__}
    if mismatched:
        fail(errors, "release version mismatch (expected %s): %s" % (__version__, mismatched))

    for prompt in ("INSTALL_PROMPT.md", "UPDATE_PROMPT.md", "UNINSTALL_PROMPT.md"):
        text = (ROOT / prompt).read_text(encoding="utf-8")
        if text.count("```text") != 1 or text.count("```") != 2:
            fail(errors, "%s must contain exactly one copy-paste prompt" % prompt)

    tracked_private = ["user.json", "metrics.json", "runtime_context.json"]
    for name in tracked_private:
        for path in ROOT.rglob(name):
            if "examples" not in path.parts and "fixtures" not in path.parts:
                fail(errors, "private-state filename present: %s" % path.relative_to(ROOT))

    # Docs reference brand assets by exact name. A missing one renders as a
    # broken image on the front page of the project, so it fails the build
    # rather than waiting for somebody to notice.
    expected_assets = {
        "logo.png", "logo-dark.png", "favicon.png", "social-preview.png",
    }
    present = {p.name for p in (ROOT / "assets").glob("*.png")}
    missing = sorted(expected_assets - present)
    if missing:
        if os.environ.get("LIWM_ALLOW_MISSING_ASSETS"):
            print("WARNING: brand assets not yet added: %s" % ", ".join(missing))
        else:
            fail(errors, "missing brand assets (see assets/README.md): %s"
                 % ", ".join(missing))

    check_markdown_links(errors)
    if errors:
        for error in errors:
            print("ERROR:", error)
        return 1
    print("repository validation passed: %d skills, %d schemas" %
          (len(skills), len(schemas.available())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
