"""Deterministic, hash-guarded host installation lifecycle."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import sysconfig
from pathlib import Path

from .hosts import get_host, instruction_file_for, skills_dir_for
from .integration import remove_bootstrap, upsert_bootstrap
from .jsonio import FileLock, canonical_json, read_json, write_json_atomic

PLAN_SCHEMA_VERSION = "0.4.0"

#: Plan versions this build can still read.  A receipt written by an earlier
#: release is the only record of what that release changed, so refusing to read
#: it would strand the user with an installation they can no longer remove.
SUPPORTED_PLAN_VERSIONS = ("0.2.0", "0.3.0", "0.4.0")

#: One incomplete installation at a time, per home.  The journal is written and
#: fsynced *before* the first mutation and removed only after the last one, so
#: its presence is exactly the statement "a plan was in flight".
JOURNAL_NAME = "installation-journal.json"


class InstallationError(RuntimeError):
    """A plan is invalid or its filesystem preconditions no longer hold."""


def _hash(payload):
    return hashlib.sha256(payload).hexdigest()


def _state(path):
    path = Path(path)
    if path.is_symlink():
        raise InstallationError("refusing to replace symlink without an explicit migration: %s" % path)
    if path.exists() and not path.is_file():
        raise InstallationError("installation target is not a regular file: %s" % path)
    if not path.is_file():
        return {"exists": False, "sha256": None}
    return {"exists": True, "sha256": _hash(path.read_bytes())}


def _plan_id(plan):
    unsigned = dict(plan)
    unsigned.pop("plan_id", None)
    return "plan_" + _hash(canonical_json(unsigned).encode("utf-8"))[:24]


def _backup_path(home, host_id, target, state):
    target_key = _hash(str(Path(target).absolute()).encode("utf-8"))[:12]
    content_key = (state.get("sha256") or "missing")[:12]
    return str(Path(home) / "backups" / "installation" / host_id /
               ("%s-%s.bak" % (target_key, content_key)))


def _atomic_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    tmp = path.with_name("%s.%d.%s.tmp" % (path.name, os.getpid(), os.urandom(4).hex()))
    try:
        fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _text(path):
    try:
        return Path(path).read_bytes().decode("utf-8") if Path(path).is_file() else ""
    except UnicodeDecodeError as exc:
        raise InstallationError("host instruction file is not UTF-8: %s" % path) from exc


def _skills_source(explicit=None):
    if explicit:
        root = Path(explicit).expanduser().absolute()
        return root if root.is_dir() else None
    checkout = Path(__file__).resolve().parents[2] / "skills"
    if checkout.is_dir():
        return checkout
    installed = Path(sysconfig.get_path("data")) / "share" / "liwm" / "skills"
    return installed if installed.is_dir() else None


def _finish_plan(plan):
    plan["plan_id"] = _plan_id(plan)
    return plan


def create_install_plan(host_id, home, block_text, skills_source=None, include_skills=True):
    """Return a deterministic install plan without modifying the filesystem."""
    home = Path(home).absolute()
    spec = get_host(host_id, home)
    if spec is None:
        raise InstallationError("unknown host %r" % host_id)
    if re.search(r"\{\{[^{}]+\}\}", block_text):
        raise InstallationError("bootstrap block contains unresolved template variables")
    target = instruction_file_for(spec)
    if target is None:
        raise InstallationError("host %r has no writable user instruction file" % host_id)

    original = _text(target)
    desired = upsert_bootstrap(original, block_text).encode("utf-8")
    before = _state(target)
    budget = spec.get("instruction_budget_bytes")
    if budget is not None and len(desired) > budget:
        raise InstallationError("installation would use %d of %d instruction bytes" %
                                (len(desired), budget))
    steps = [{
        "kind": "bootstrap-upsert",
        "target": str(Path(target).absolute()),
        "precondition": before,
        "result": {"exists": True, "sha256": _hash(desired)},
        "block": block_text,
        "backup": _backup_path(home, host_id, target, before) if before["exists"] else None,
    }]

    skills_root = skills_dir_for(spec)
    source_root = _skills_source(skills_source)
    if include_skills and skills_root is not None and (spec.get("capabilities") or {}).get("skills"):
        if source_root is None:
            raise InstallationError("LIWM skill assets are unavailable")
        for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
            rel = source.relative_to(source_root)
            skill_target = Path(skills_root) / rel
            state = _state(skill_target)
            payload_hash = _hash(source.read_bytes())
            steps.append({
                "kind": "copy",
                "target": str(skill_target.absolute()),
                "source": str(source.absolute()),
                "source_sha256": payload_hash,
                "precondition": state,
                "result": {"exists": True, "sha256": payload_hash},
                "backup": (_backup_path(home, host_id, skill_target, state)
                           if state["exists"] else None),
            })

    prior = read_json(_receipt_path(home, host_id), default=None)
    if isinstance(prior, dict):
        _validate_plan(prior)
        prior_steps = {step["target"]: step for step in prior.get("steps", [])}
        for step in steps:
            old = prior_steps.get(step["target"])
            if old:
                step["original"] = old.get("original", old["precondition"])
                step["backup"] = old.get("backup")

    return _finish_plan({
        "schema_version": PLAN_SCHEMA_VERSION,
        "operation": "install",
        "host": host_id,
        "home": str(home),
        "skills_source": str(source_root) if source_root else None,
        "steps": steps,
    })


def _receipt_path(home, host_id):
    return Path(home) / "installations" / (host_id + ".json")


def create_uninstall_plan(host_id, home):
    """Plan removal from the current filesystem and the install receipt."""
    home = Path(home).absolute()
    receipt = read_json(_receipt_path(home, host_id), default=None)
    if not isinstance(receipt, dict) or receipt.get("operation") != "install":
        raise InstallationError("no installation receipt for host %r" % host_id)
    _validate_plan(receipt)
    steps = []
    for installed in receipt.get("steps", []):
        target = Path(installed["target"])
        original = installed.get("original", installed["precondition"])
        if installed["kind"] == "bootstrap-upsert":
            current = _state(target)
            desired = remove_bootstrap(_text(target)).encode("utf-8")
            remove_created_file = not original["exists"] and not desired
            steps.append({
                "kind": "delete" if remove_created_file else "bootstrap-remove",
                "target": str(target),
                "precondition": current,
                "result": ({"exists": False, "sha256": None} if remove_created_file else
                           {"exists": current["exists"],
                            "sha256": _hash(desired) if current["exists"] else None}),
            })
            continue
        current = _state(target)
        if current != installed["result"]:
            raise InstallationError("managed skill changed since install: %s" % target)
        if original["exists"]:
            backup = installed.get("backup")
            if not backup or _state(backup).get("sha256") != original["sha256"]:
                raise InstallationError("original backup is missing or changed: %s" % backup)
            steps.append({
                "kind": "restore", "target": str(target), "source": backup,
                "source_sha256": original["sha256"],
                "precondition": current, "result": original,
            })
        else:
            steps.append({
                "kind": "delete", "target": str(target),
                "precondition": current, "result": {"exists": False, "sha256": None},
            })
    return _finish_plan({
        "schema_version": PLAN_SCHEMA_VERSION,
        "operation": "uninstall",
        "host": host_id,
        "home": str(home),
        "steps": steps,
    })


def save_plan(plan, path):
    _validate_plan(plan)
    return write_json_atomic(path, plan)


def load_plan(path):
    plan = read_json(path)
    _validate_plan(plan)
    return plan


def _validate_plan(plan):
    if (not isinstance(plan, dict)
            or plan.get("schema_version") not in SUPPORTED_PLAN_VERSIONS):
        raise InstallationError("unsupported installation plan")
    if plan.get("plan_id") != _plan_id(plan):
        raise InstallationError("installation plan hash does not match its contents")
    if (plan.get("operation") not in {"install", "uninstall"} or
            not isinstance(plan.get("steps"), list) or not plan["steps"]):
        raise InstallationError("malformed installation plan")
    targets = [step.get("target") for step in plan["steps"] if isinstance(step, dict)]
    if len(targets) != len(plan["steps"]) or len(set(targets)) != len(targets):
        raise InstallationError("installation plan targets must be present and unique")
    if not Path(str(plan.get("home", ""))).is_absolute():
        raise InstallationError("installation plan home must be absolute")
    home = Path(plan["home"])
    spec = get_host(plan.get("host"), home)
    if spec is None:
        raise InstallationError("unknown installation host")
    instruction = instruction_file_for(spec)
    skills_root = skills_dir_for(spec)
    instruction = Path(instruction).absolute() if instruction else None
    skills_root = Path(skills_root).absolute() if skills_root else None
    backup_root = (home / "backups" / "installation" / str(plan.get("host"))).absolute()

    def within(path, root):
        if root is None:
            return False
        try:
            path.absolute().relative_to(root)
            return True
        except ValueError:
            return False
    valid_kinds = {"bootstrap-upsert", "bootstrap-remove", "copy", "restore", "delete"}
    for step in plan["steps"]:
        if step.get("kind") not in valid_kinds or not Path(str(step["target"])).is_absolute():
            raise InstallationError("malformed installation plan step")
        target = Path(step["target"]).absolute()
        if target != instruction and not within(target, skills_root):
            raise InstallationError("installation target is outside the selected host")
        backup = step.get("backup")
        if backup and not within(Path(backup), backup_root):
            raise InstallationError("installation backup is outside LIWM backup storage")
        for key in ("precondition", "result"):
            state = step.get(key)
            if not isinstance(state, dict) or set(state) != {"exists", "sha256"}:
                raise InstallationError("malformed file state in installation plan")
            digest = state["sha256"]
            if not isinstance(state["exists"], bool) or ((digest is None) != (not state["exists"])):
                raise InstallationError("inconsistent file state in installation plan")
            if digest is not None and (len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
                raise InstallationError("malformed file hash in installation plan")
        if step["kind"] == "bootstrap-upsert" and not isinstance(step.get("block"), str):
            raise InstallationError("bootstrap plan step is missing its block")
        if step["kind"] in {"copy", "restore"}:
            if not step.get("source") or not step.get("source_sha256"):
                raise InstallationError("copy plan step is missing its source")
            source = Path(step["source"]).absolute()
            if step["kind"] == "restore" and not within(source, backup_root):
                raise InstallationError("restore source is outside LIWM backup storage")
            if step["kind"] == "copy":
                source_root = plan.get("skills_source")
                if not source_root or not within(source, Path(source_root).absolute()):
                    raise InstallationError("copy source is outside the planned skills source")
        if "original" in step:
            state = step["original"]
            if not isinstance(state, dict) or set(state) != {"exists", "sha256"}:
                raise InstallationError("malformed original file state")


def _payload_for(step, current):
    kind = step["kind"]
    if kind == "bootstrap-upsert":
        return upsert_bootstrap(current.decode("utf-8"), step["block"]).encode("utf-8")
    if kind == "bootstrap-remove":
        return remove_bootstrap(current.decode("utf-8")).encode("utf-8")
    if kind in {"copy", "restore"}:
        payload = Path(step["source"]).read_bytes()
        if _hash(payload) != step["source_sha256"]:
            raise InstallationError("source hash changed: %s" % step["source"])
        return payload
    if kind == "delete":
        return None
    raise InstallationError("unknown plan step %r" % kind)


def verify_plan(plan):
    _validate_plan(plan)
    failures = []
    for step in plan["steps"]:
        actual = _state(step["target"])
        if actual != step["result"]:
            failures.append({"target": step["target"], "expected": step["result"], "actual": actual})
    return {"ok": not failures, "plan_id": plan["plan_id"], "failures": failures}



def journal_path(home):
    return Path(home) / JOURNAL_NAME


def _write_journal(home, body):
    """Persist the journal durably.  A rollback handler is not a guarantee.

    ``apply_plan`` restores what it changed when it raises, which covers a bad
    plan or a permission error.  It does nothing at all if the machine loses
    power between file three and file four, because the handler never runs.
    The journal is what survives that: it names every target, its state before
    the change and its intended state after, so a later ``liwm install repair``
    can finish the job or undo it without guessing.
    """
    path = journal_path(home)
    payload = canonical_json(body).encode("utf-8") + b"\n"
    _atomic_write(path, payload)
    return path


def read_journal(home):
    path = journal_path(home)
    if not path.is_file():
        return None
    try:
        return read_json(path)
    except (ValueError, OSError):
        return {"corrupt": True, "path": str(path)}


def _journal_body(plan, done=()):
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": plan["plan_id"],
        "operation": plan["operation"],
        "host": plan["host"],
        "home": plan["home"],
        "plan": plan,
        "completed_targets": list(done),
    }


def inspect_installation(home):
    """Classify an interrupted installation without changing anything."""
    journal = read_journal(home)
    if journal is None:
        return {"interrupted": False, "steps": [], "repairable": True, "problems": []}
    if journal.get("corrupt"):
        return {"interrupted": True, "steps": [], "repairable": False,
                "problems": ["installation journal is unreadable"], "journal": journal}
    plan = journal.get("plan") or {}
    steps, problems = [], []
    for step in plan.get("steps") or []:
        actual = _state(step["target"])
        if actual == step["result"]:
            state = "applied"
        elif actual == step["precondition"]:
            state = "pending"
        else:
            state = "unrecognised"
            problems.append("%s is in neither its original nor its planned state"
                            % step["target"])
        steps.append({"target": step["target"], "state": state,
                      "has_backup": bool(step.get("backup")
                                         and Path(step["backup"]).is_file())})
    return {
        "interrupted": True,
        "plan_id": journal.get("plan_id"),
        "operation": journal.get("operation"),
        "host": journal.get("host"),
        "steps": steps,
        "applied": sum(1 for row in steps if row["state"] == "applied"),
        "pending": sum(1 for row in steps if row["state"] == "pending"),
        # Ambiguity is not resolved by picking the likelier story.  Something
        # else edited the file, and overwriting it either way loses whatever
        # that was.
        "repairable": not problems,
        "problems": problems,
    }


def repair_installation(home, rollback=False):
    """Finish or undo an interrupted plan, converging on one of its two states."""
    report = inspect_installation(home)
    if not report["interrupted"]:
        return dict(report, repaired=False, reason="no interrupted installation")
    if not report["repairable"]:
        raise InstallationError(
            "refusing to repair: %s" % "; ".join(report["problems"] or ["unknown state"]))
    journal = read_journal(home)
    plan = journal["plan"]
    if not rollback:
        result = apply_plan(plan)
        return dict(report, repaired=True, direction="forward", verification=result)

    changed = []
    with FileLock(Path(home) / ".installation.lock", timeout=30.0):
        for step in plan["steps"]:
            target = Path(step["target"])
            if _state(target) == step["precondition"]:
                continue
            if step["precondition"]["exists"]:
                backup = step.get("backup")
                if not backup or not Path(backup).is_file():
                    raise InstallationError(
                        "cannot roll back %s: its backup is missing" % target)
                payload = Path(backup).read_bytes()
                if _hash(payload) != step["precondition"]["sha256"]:
                    raise InstallationError("backup for %s does not match the original" % target)
                _atomic_write(target, payload)
            else:
                target.unlink(missing_ok=True)
            changed.append(str(target))
        journal_path(home).unlink(missing_ok=True)
    return dict(report, repaired=True, direction="rollback", restored=changed)


def apply_plan(plan):
    """Apply a plan transactionally after checking every target and source."""
    _validate_plan(plan)
    home = Path(plan["home"])
    changed = []
    prepared = []
    with FileLock(home / ".installation.lock", timeout=30.0):
        for step in plan["steps"]:
            target = Path(step["target"])
            actual = _state(target)
            if actual == step["result"]:
                prepared.append((step, None, None))
                continue
            if actual != step["precondition"]:
                raise InstallationError("precondition changed for %s" % target)
            current = target.read_bytes() if actual["exists"] else b""
            if original_backup := step.get("backup"):
                backup_state = _state(original_backup)
                original_state = step.get("original", actual)
                if backup_state["exists"] and backup_state["sha256"] != original_state["sha256"]:
                    raise InstallationError("existing backup hash differs for %s" % target)
            try:
                payload = _payload_for(step, current)
            except UnicodeDecodeError as exc:
                raise InstallationError("host instruction file is not UTF-8: %s" % target) from exc
            result = {"exists": payload is not None,
                      "sha256": _hash(payload) if payload is not None else None}
            if result != step["result"]:
                raise InstallationError("computed output does not match plan for %s" % target)
            prepared.append((step, payload, current if actual["exists"] else None))

        receipt = _receipt_path(home, plan["host"])
        receipt_original = receipt.read_bytes() if receipt.is_file() else None
        applied = []
        _write_journal(home, _journal_body(plan))
        try:
            for step, payload, original in prepared:
                if payload is None and _state(step["target"]) == step["result"]:
                    continue
                target = Path(step["target"])
                if original is not None and step.get("backup"):
                    backup = Path(step["backup"])
                    if not backup.exists():
                        _atomic_write(backup, original)
                if payload is None:
                    target.unlink(missing_ok=True)
                else:
                    _atomic_write(target, payload)
                changed.append((target, original))
                applied.append(step["target"])
                _write_journal(home, _journal_body(plan, applied))
            if plan["operation"] == "install":
                payload = canonical_json(plan).encode("utf-8") + b"\n"
                _atomic_write(receipt, payload)
            else:
                receipt.unlink(missing_ok=True)
            changed.append((receipt, receipt_original))
            from .config import ConfigStore
            if plan["operation"] == "install":
                ConfigStore(home).register_host(
                    plan["host"], {"plan_id": plan["plan_id"], "managed_by": "installation-plan"}
                )
            else:
                ConfigStore(home).remove_host(plan["host"])
        except Exception:
            for target, original in reversed(changed):
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    _atomic_write(target, original)
            journal_path(home).unlink(missing_ok=True)
            raise
        journal_path(home).unlink(missing_ok=True)

    report = verify_plan(plan)
    report["changed"] = sum(1 for target, _ in changed if target != receipt)
    return report
