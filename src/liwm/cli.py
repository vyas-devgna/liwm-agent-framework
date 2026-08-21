"""``liwm`` command-line interface.

The primary consumer of this CLI is an *agent*, not a human, so every command
supports ``--json`` for machine parsing while defaulting to a compact
human-readable form for the terminal.

The CLI is the sanctioned way for a skill to mutate LIWM state.  Normal
framework-mediated mutations therefore pass through provenance, privacy,
atomicity and audit checks.  LIWM is not an OS security boundary: a process
with the user's filesystem authority can deliberately rewrite the framework,
events, materialised views or host configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path

from . import __version__
from .constitution import INVARIANTS, constitution_hash
from .config import ConfigStore
from .capsule import render_capsule
from .context import plan_context, write_runtime_context
from .evidence import PROVENANCE_TRUST, SOURCE_CEILINGS, SOURCE_WEIGHTS, TRUSTED_PROVENANCE
from .events import EVENT_KINDS, EventStore
from .feedback import FEEDBACK_KINDS, record_feedback
from .hosts import detect_hosts
from .jsonio import FileLock, lifecycle_lock_path, read_json_resilient, utc_now, write_json_atomic
from .metrics import MetricsStore
from .migrate import CURRENT_SCHEMA_VERSION, migrate_home
from .modes import Signals, mode_profile, resolve_auto
from .onboarding import OnboardingSession
from .paths import ensure_layout, is_inside_git_repo, liwm_home
from .profile import ProfileStore
from .projects import INTENT_SECTIONS, ProjectStore, slugify_project
from .questions import QuestionPlanner
from .report import profile_report, render_text
from .scope import resolve_for_context
from .schema import SchemaStore, validate
from .selfimprove import SelfImprovementStore
from .strategy import StrategyStore
from .traceability import recent_assumptions, why

__all__ = ["main", "build_parser"]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _emit(args, data, text=None):
    if getattr(args, "json", False) or text is None:
        sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(text.rstrip("\n") + "\n")
    return EXIT_OK


def _home(args):
    return ensure_layout(getattr(args, "home", None) or None)


def _store(args):
    return ProfileStore(_home(args))


def _learning_guard(args, operation):
    config = ConfigStore(_home(args)).load()
    if not config.get("enabled", True):
        return _emit(args, {"skipped": True, "operation": operation,
                            "reason": "LIWM is off"},
                     text="LIWM is off; %s was not recorded" % operation)
    if not config.get("learning_enabled", True):
        return _emit(args, {"skipped": True, "operation": operation,
                            "reason": "learning is disabled"},
                     text="LIWM learning is disabled; %s was not recorded" % operation)
    return None


def _signals(args):
    raw = getattr(args, "signals", None)
    data = {}
    if raw:
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise SystemExit("--signals must be JSON: %s" % exc) from exc
    for key in ("intent_uncertainty", "novelty", "consequence", "reversibility",
                "specification_completeness", "recent_correction_rate", "fatigue"):
        value = getattr(args, key, None)
        if value is not None:
            data[key] = value
    if getattr(args, "stage", None):
        data["project_stage"] = args.stage
    return data


def _validate_state_documents(home, schema_store, include_events=False):
    specs = [
        (Path(home) / "config.json", "config"),
        (Path(home) / "metrics.json", "metrics"),
        (Path(home) / "runtime_context.json", "runtime-context"),
        (Path(home) / "intent-graph.json", "intent-graph"),
        (Path(home) / "learning" / "personal-strategy.json", "personal-strategy"),
    ]
    specs.extend((p, "project-intent") for p in (Path(home) / "projects").glob("*/intent.json"))
    for directory in ("candidate-rules", "rejected-rules"):
        specs.extend((p, "candidate-rule") for p in
                     (Path(home) / "learning" / directory).glob("*.json"))
    if include_events:
        specs.extend((p, "event") for p in (Path(home) / "events").rglob("*.json"))
    errors = {}
    checked = 0
    for path, schema_name in specs:
        if not path.is_file():
            continue
        checked += 1
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            found = schema_store.validate(document, schema_name)
            if found:
                errors[str(path)] = found[:20]
        except Exception as exc:
            errors[str(path)] = [{"path": "", "message": str(exc)}]
    return {"checked": checked, "errors": errors, "ok": not errors}


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_init(args):
    target = Path(args.home).expanduser().absolute() if args.home else liwm_home()
    if is_inside_git_repo(target) and not args.allow_in_repo:
        sys.stderr.write(
            "refusing to initialise a LIWM profile inside a git repository (%s).\n"
            "Personal data must live outside version control. Use --allow-in-repo only for tests.\n"
            % target
        )
        return EXIT_ERROR
    home = ensure_layout(target)
    store = ProfileStore(home)
    created = not store.exists()
    if created:
        store.events.record(
            "session_start", "direct_user_message",
            payload={"action": "init", "liwm_version": __version__},
        )
    profile = store.rebuild(reason="init")
    MetricsStore(home).refresh(store)
    StrategyStore(home).load()
    ConfigStore(home).load(persist=True)
    data = {
        "home": str(home),
        "created": created,
        "profile_id": profile["profile_id"],
        "revision": profile["revision"],
        "schema_version": profile["schema_version"],
        "onboarding": profile["onboarding"]["status"],
        "constitution_hash": constitution_hash(),
        "inside_git_repo": is_inside_git_repo(home),
    }
    return _emit(args, data, text=(
        "LIWM home %s (%s)\nprofile %s rev %d, onboarding: %s"
        % (home, "created" if created else "already present", profile["profile_id"],
           profile["revision"], profile["onboarding"]["status"])
    ))



def _supports_symlinks(home):
    """Can this filesystem hold a symlink?

    Windows only permits them under Developer Mode or an elevated shell, and
    some network and container filesystems refuse them everywhere.  The
    installer needs the answer before it decides whether to link the skills
    directory or copy it, so LIWM tests it rather than guessing from the OS
    name.
    """
    probe = Path(home) / (".liwm-symlink-probe-%d" % os.getpid())
    try:
        probe.symlink_to(Path(home))
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False
    finally:
        try:
            if probe.is_symlink() or probe.exists():
                probe.unlink()
        except OSError:  # pragma: no cover
            pass


def _case_sensitive(home):
    """Is this filesystem case-sensitive?

    macOS and Windows are usually not, which matters because skill directory
    names are part of a host's lookup key: on a case-insensitive volume
    ``liwm-profile`` and ``LIWM-Profile`` are the same directory, and an
    installer that assumed otherwise would clobber one with the other.
    """
    lower = Path(home) / (".liwm-case-probe-%d" % os.getpid())
    upper = Path(home) / (".LIWM-CASE-PROBE-%d" % os.getpid())
    try:
        lower.write_text("probe", encoding="utf-8")
        return not upper.exists()
    except OSError:  # pragma: no cover
        return True
    finally:
        try:
            lower.unlink()
        except OSError:  # pragma: no cover
            pass


def cmd_doctor(args):
    home = _home(args)
    store = ProfileStore(home)
    schema_store = SchemaStore()
    profile = store.load()
    integrity = store.events.verify()
    state_documents = _validate_state_documents(home, schema_store)
    host_rows = detect_hosts(home)
    from .installation import inspect_installation
    interrupted = inspect_installation(home)
    errors = []

    try:
        errors = schema_store.validate(profile, "user")
    except FileNotFoundError as exc:
        errors = [{"path": "", "message": str(exc)}]

    checks = {
        "home_exists": home.is_dir(),
        "home_outside_git": not is_inside_git_repo(home),
        "profile_readable": profile is not None,
        "profile_schema_valid": not errors,
        "state_documents_valid": state_documents["ok"],
        "event_integrity_ok": integrity["ok"],
        "constitution_hash_matches": profile.get("constitution_hash") == constitution_hash(),
        "schema_version_current": profile.get("schema_version") == CURRENT_SCHEMA_VERSION,
        "config_present": (home / "config.json").is_file(),
        # A journal left behind means a plan was in flight when the process
        # stopped, so some host config may be half written.
        "no_interrupted_installation": not interrupted["interrupted"],
        "recovery_note": store.last_recovery_note,
    }
    data = {
        "liwm_version": __version__,
        "home": str(home),
        "checks": checks,
        "schema_errors": errors[:10],
        "state_document_validation": state_documents,
        "event_integrity": integrity,
        "events": store.events.stats(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "supports_symlinks": _supports_symlinks(home),
            "filesystem_case_sensitive": _case_sensitive(home),
        },
        "interrupted_installation": interrupted,
        "hosts": host_rows,
        "hosts_detected": [row["id"] for row in host_rows if row["detected"]],
        "agents_skills_dir": str(Path.home() / ".agents" / "skills"),
        "healthy": all(v for k, v in checks.items() if isinstance(v, bool)),
    }
    lines = ["LIWM %s  home=%s" % (__version__, home)]
    for key, value in checks.items():
        if isinstance(value, bool):
            lines.append("  [%s] %s" % ("ok" if value else "!!", key))
        elif value:
            lines.append("  [--] %s: %s" % (key, value))
    if errors:
        lines.append("  schema errors:")
        for err in errors[:5]:
            lines.append("    %s: %s" % (err["path"] or "/", err["message"]))
    lines.append("  [--] platform: %s %s, Python %s" % (
        data["platform"]["system"], data["platform"]["release"],
        data["platform"]["python"]))
    present = [row for row in data["hosts"] if row["detected"]]
    if present:
        for row in present:
            lines.append("  [%s] host %s%s" % (
                "ok" if row["liwm_installed"] else "--", row["id"],
                "" if row["liwm_installed"] else " (present, LIWM not installed)"))
    else:
        lines.append("  [--] no supported agent host detected (liwm hosts list)")
    return _emit(args, data, text="\n".join(lines))


def cmd_config(args):
    store = ConfigStore(_home(args))
    if args.action == "show":
        data = store.load(persist=True)
        return _emit(args, data)
    if args.action == "set":
        if not args.key:
            raise ValueError("config set requires --key")
        value = _coerce(args.value)
        data = store.set(args.key, value)
        selected = data
        for part in args.key.split("."):
            selected = selected[part]
        return _emit(args, data, text="%s = %s" % (args.key, selected))
    return EXIT_USAGE


def cmd_integration(args):
    """Manage non-personal host installation metadata atomically."""
    store = ConfigStore(_home(args))
    if args.action == "show":
        hosts = store.load(persist=True).get("hosts", {})
        return _emit(args, {"hosts": hosts})
    if not args.host:
        raise ValueError("integration %s requires --host" % args.action)
    if args.action == "remove":
        removed = store.remove_host(args.host)
        return _emit(args, {"host": args.host, "removed": removed is not None},
                     text="removed integration metadata for %s" % args.host)
    required = {
        "framework_checkout": args.framework_checkout,
        "cli_command": args.cli_command,
        "skills_path": args.skills_path,
        "install_method": args.install_method,
        "bootstrap_file": args.bootstrap_file,
        "bootstrap_version": args.bootstrap_version,
        "liwm_version": __version__,
        "installed_at": utc_now(),
    }
    missing = [key for key, value in required.items() if value is None]
    if missing:
        raise ValueError("integration register missing: %s" % ", ".join(missing))
    data = store.register_host(args.host, required)
    return _emit(args, {"host": args.host, "metadata": data["hosts"][args.host]},
                 text="registered %s integration" % args.host)


def cmd_hosts(args):
    """List, detect, or plan installation into supported agent hosts."""
    from .hosts import USER_REGISTRY_FILENAME, detect_hosts, installation_plan, load_registry

    home = _home(args)

    if args.action == "plan":
        if not args.host:
            raise ValueError("hosts plan requires --host (see: liwm hosts list)")
        block = ""
        if args.block:
            block = Path(args.block).expanduser().read_text(encoding="utf-8")
        plan = installation_plan(args.host, home=home, block_text=block)
        if plan is None:
            raise ValueError("unknown host %r (see: liwm hosts list)" % args.host)
        lines = ["installation plan for %s:" % plan["name"]]
        for step in plan["steps"]:
            lines.append("  %-14s %s" % (step["action"], step["path"] or "(no file)"))
            lines.append("                 %s" % step["detail"])
        budget = plan["budget"]
        if budget["budget_bytes"] is not None:
            lines.append("  budget         %d of %d bytes used%s" % (
                budget["total_bytes"], budget["budget_bytes"],
                "" if budget["within_budget"] else "  ** OVER BUDGET **"))
        return _emit(args, plan, text="\n".join(lines))

    rows = detect_hosts(home)
    if args.action == "detect":
        rows = [row for row in rows if row["detected"]]

    data = {
        "hosts": rows,
        "detected": [row["id"] for row in rows if row["detected"]],
        "user_registry": str(Path(home) / USER_REGISTRY_FILENAME),
        "count": len(load_registry(home)),
    }
    if not rows:
        return _emit(args, data, text="no supported agent host detected on this machine")

    lines = []
    for row in rows:
        flags = []
        if row["detected"]:
            flags.append("present")
        if row["liwm_installed"]:
            flags.append("liwm-installed")
        if row["supports_skills"]:
            flags.append("skills")
        if row["source"] != "builtin":
            flags.append(row["source"])
        lines.append("%-16s %-28s %s" % (row["id"], row["name"],
                                         ", ".join(flags) or "-"))
        target = row["global_instruction_file"] or (
            "project files: " + ", ".join(row["project_instruction_files"][:2]))
        lines.append("                 %s" % target)
    lines.append("")
    lines.append("Teach LIWM another host by adding it to %s"
                 % (Path(home) / USER_REGISTRY_FILENAME))
    return _emit(args, data, text="\n".join(lines))


def cmd_installation(args):
    """Plan and execute hash-guarded host installation lifecycle operations."""
    from .installation import (
        apply_plan, create_install_plan, create_uninstall_plan, inspect_installation,
        load_plan, repair_installation, save_plan, verify_plan,
    )

    home = _home(args)
    if args.action == "status":
        report = inspect_installation(home)
        return _emit(args, report, text=(
            "no interrupted installation" if not report["interrupted"] else
            "interrupted %s of %s: %d applied, %d pending%s" % (
                report["operation"], report["host"], report["applied"],
                report["pending"],
                "" if report["repairable"] else "; NOT repairable: %s"
                % "; ".join(report["problems"]))))
    if args.action == "repair":
        report = repair_installation(home, rollback=args.rollback)
        return _emit(args, report, text=(
            report.get("reason") or "repaired by rolling %s" % report["direction"]))
    if args.action == "plan":
        if not args.host:
            raise ValueError("%s plan requires --host" % args.command)
        if args.command == "install":
            if not args.block:
                raise ValueError("install plan requires --block")
            block = Path(args.block).expanduser().read_text(encoding="utf-8")
            plan = create_install_plan(
                args.host, home, block, skills_source=args.skills_source,
                include_skills=not args.no_skills,
            )
        else:
            plan = create_uninstall_plan(args.host, home)
        destination = (Path(args.output).expanduser() if args.output else
                       Path(home) / "install-plans" / (plan["plan_id"] + ".json"))
        save_plan(plan, destination)
        result = dict(plan)
        result["plan_file"] = str(destination.absolute())
        return _emit(args, result, text="wrote %s plan %s" % (args.command, destination))

    if not args.plan:
        raise ValueError("%s %s requires --plan" % (args.command, args.action))
    plan = load_plan(Path(args.plan).expanduser())
    if plan["operation"] != args.command:
        raise ValueError("plan operation is %s, not %s" % (plan["operation"], args.command))
    if args.action == "verify":
        report = verify_plan(plan)
        if not report["ok"]:
            raise ValueError("installation verification failed for %d target(s)" %
                             len(report["failures"]))
    else:
        report = apply_plan(plan)
    return _emit(args, report, text="%s %s complete (%d file changes)" % (
        args.command, args.action, report.get("changed", 0)))


def cmd_profile(args):
    store = _store(args)
    profile = store.load()
    if args.section:
        data = profile.get(args.section)
        if data is None:
            sys.stderr.write("no such section %r\n" % args.section)
            return EXIT_ERROR
        return _emit(args, {args.section: data})
    if args.raw:
        return _emit(args, profile)
    report = profile_report(
        store,
        metrics=MetricsStore(store.home).load(),
        strategy=StrategyStore(store.home).load(),
        promoted_rules=SelfImprovementStore(store.home).active_rules(),
    )
    return _emit(args, report, text=render_text(report))


def cmd_context(args):
    store = _store(args)
    strategy = StrategyStore(store.home)
    kwargs = dict(
        domain=args.domain,
        project_id=args.project,
        task=args.task,
        mode=args.mode,
        signals=_signals(args),
        strategy=strategy.load(),
        promoted_rules=SelfImprovementStore(store.home).active_rules(),
    )
    kwargs["gate"] = "off" if getattr(args, "no_gate", False) else "auto"
    if getattr(args, "include", None):
        kwargs["include"] = args.include
    if getattr(args, "all_beliefs", False):
        kwargs["max_beliefs"] = 10 ** 6
        kwargs["gate"] = "off"
    context, receipt = plan_context(store, **kwargs)
    if args.write:
        _, path = write_runtime_context(store, **kwargs)
        context["_written_to"] = str(path)
    if getattr(args, "receipt", False):
        # The receipt is the audit record, not model context; it is emitted on
        # its own so it can never be mistaken for something to paste into a
        # prompt.
        return _emit(args, receipt, text=None)
    if getattr(args, "capsule", False):
        # Deliberately bypasses --json: the capsule is the wire format for the
        # model, and asking for it in JSON would reinstate the overhead it
        # exists to remove.
        sys.stdout.write(render_capsule(context) + "\n")
        return EXIT_OK
    lines = [
        "mode: %s (%s, budget %s)" % (
            context["mode"]["effective"], context["mode"]["resolved_from"],
            context["mode"]["question_budget"]),
        context["mode"].get("rationale") or "",
        "profile maturity %.2f, %d applicable beliefs"
        % (context["profile_maturity"], len(context["applies"])),
    ]
    for item in context["applies"][:10]:
        lines.append("  %-44s %-18s %.2f [%s]" % (
            item["dimension"], str(item["value"])[:18], item["confidence"], item["scope"]))
    return _emit(args, context, text="\n".join(lines))


def cmd_observe(args):
    guarded = _learning_guard(args, "observation")
    if guarded is not None:
        return guarded
    store = _store(args)
    if args.provenance not in PROVENANCE_TRUST:
        sys.stderr.write("unknown provenance %r; expected one of: %s\n"
                         % (args.provenance, ", ".join(sorted(PROVENANCE_TRUST))))
        return EXIT_USAGE
    event, profile = store.observe(
        args.dimension,
        _coerce(args.value),
        source_type=args.source,
        provenance=args.provenance,
        scope=args.scope,
        scope_key=args.scope_key,
        polarity=args.polarity,
        decay_policy=args.decay,
        note=args.note,
        session_id=args.session,
        project_id=args.project,
        domain=args.domain,
    )
    belief = next(
        (b for b in profile["beliefs"]
         if b["dimension"] == args.dimension and str(b["value"]) == str(_coerce(args.value))
         and b["scope"] == args.scope),
        None,
    )
    data = {
        "event_id": event["event_id"],
        "kind": event["kind"],
        "quarantined": event.get("quarantined", False),
        "quarantine_reason": event.get("quarantine_reason"),
        "profile_revision": profile["revision"],
        "belief": belief,
    }
    if event.get("quarantined"):
        text = ("recorded but QUARANTINED (%s) - this can never influence the profile"
                % event.get("quarantine_reason"))
    elif event.get("kind") == "refusal":
        text = "REFUSED by the privacy gate (%s)" % (event.get("payload") or {}).get("category")
    elif belief:
        text = "%s = %s -> confidence %.2f (%s, %d observation(s))" % (
            belief["dimension"], belief["value"], belief["confidence"],
            belief["scope"], belief["evidence_count"])
    else:
        text = "recorded %s" % event["event_id"]
    return _emit(args, data, text=text)


def cmd_observe_intent(args):
    guarded = _learning_guard(args, "observation")
    if guarded is not None:
        return guarded
    store = _store(args)
    common = {
        "scope": args.scope, "scope_key": args.scope_key, "polarity": args.polarity,
        "decay_policy": args.decay, "note": args.note, "session_id": args.session,
        "project_id": args.project, "domain": args.domain,
        "derived_from": args.derived_from or [],
    }
    value = _coerce(args.value)
    pathway = args.command.removeprefix("observe-")
    if pathway == "user":
        event, profile = store.observe_user(args.dimension, value, args.source, **common)
    elif pathway == "edit":
        event, profile = store.observe_edit(args.dimension, value, **common)
    elif pathway == "review":
        event, profile = store.observe_review(args.dimension, value, args.source, **common)
    elif pathway == "inference":
        event, profile = store.observe_inference(args.dimension, value, args.source, **common)
    else:
        event, profile = store.observe_untrusted(
            args.dimension, value, args.provenance, args.source, **common
        )
    return _emit(args, {
        "pathway": pathway, "event_id": event["event_id"],
        "provenance": event["provenance"], "source_type": event["observation"]["source_type"],
        "quarantined": event.get("quarantined", False),
        "quarantine_reason": event.get("quarantine_reason"),
        "profile_revision": profile["revision"],
    }, text="%s observation %s%s" % (
        pathway, event["event_id"], " (quarantined)" if event.get("quarantined") else ""
    ))


def _coerce(value):
    if value is None:
        return None
    lowered = str(value).strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if str(value).lstrip().startswith(("[", "{")):
        try:
            return json.loads(value)
        except ValueError:
            return value
    try:
        if "." in value:
            return float(value)
        return int(value)
    except (TypeError, ValueError):
        return value


def cmd_feedback(args):
    guarded = _learning_guard(args, "feedback")
    if guarded is not None:
        return guarded
    store = _store(args)
    if args.kind not in FEEDBACK_KINDS:
        sys.stderr.write("unknown feedback kind %r; expected one of: %s\n"
                         % (args.kind, ", ".join(sorted(FEEDBACK_KINDS))))
        return EXIT_USAGE
    extra = []
    if args.observation:
        for raw in args.observation:
            try:
                extra.append(json.loads(raw))
            except ValueError as exc:
                sys.stderr.write("--observation must be JSON: %s\n" % exc)
                return EXIT_USAGE
    record = record_feedback(
        store, args.kind, channel=args.channel, text=args.text,
        project_id=args.project, domain=args.domain, session_id=args.session,
        artifact=args.artifact, decision_id=args.decision, prediction_id=args.prediction,
        global_intent=args.global_intent, extra_observations=extra,
        custom_acceptance=args.acceptance,
        provenance=args.provenance, derived_from=args.derived_from,
        selected_option=args.selected_option,
    )
    return _emit(args, record, text=(
        "recorded %s feedback (%s), acceptance %s, %s"
        % (record["kind"], record["channel"], record["acceptance"], record["scope_note"])
    ))


def cmd_mode(args):
    signals = _signals(args)
    config = ConfigStore(_home(args)).load()
    if not config.get("enabled", True):
        contract = mode_profile("off")
        contract["resolved_from"] = "config"
        contract["rationale"] = "LIWM is persistently disabled"
    elif args.mode and args.mode != "auto":
        contract = mode_profile(args.mode)
        contract["resolved_from"] = "explicit"
    else:
        store = _store(args)
        low, high = StrategyStore(store.home).auto_thresholds()
        profile = store.load()
        from .fatigue import profile_maturity
        signals.setdefault("profile_maturity", profile_maturity(profile))
        contract = resolve_auto(Signals(**signals), thresholds=(low, high))
    return _emit(args, contract, text=(
        "%s | budget %s | experiential %.0f%% | %s"
        % (contract["mode"].upper(), contract["max_questions"],
           100 * contract.get("experiential_ratio", 0),
           contract.get("rationale") or contract.get("summary", ""))
    ))


def cmd_plan(args):
    store = _store(args)
    profile = store.load()
    resolved = resolve_for_context(profile.get("beliefs", []), domain=args.domain,
                                   project_id=args.project, min_confidence=0.0)
    config = ConfigStore(store.home).load()
    if not config.get("enabled", True):
        contract = mode_profile("off")
    elif args.mode == "auto":
        low, high = StrategyStore(store.home).auto_thresholds()
        signals = _signals(args)
        from .fatigue import profile_maturity
        signals.setdefault("profile_maturity", profile_maturity(profile))
        contract = resolve_auto(Signals(**signals), thresholds=(low, high))
    else:
        contract = mode_profile(args.mode)
    qconfig = config.get("questioning", {})
    contract = dict(contract)
    contract["max_questions"] = min(
        int(contract.get("max_questions", 0)),
        int(qconfig.get("max_questions_per_session", 12)),
    )
    never = set(qconfig.get("never_ask_about") or [])
    from .question_bank import QUESTION_BANK
    bank = [q for q in QUESTION_BANK if not never.intersection(q.get("resolves", []))]
    from .question_outcomes import QuestionOutcomeStore
    planner = QuestionPlanner(
        contract, resolved=resolved, strategy=StrategyStore(store.home).load(), bank=bank,
        outcome_store=QuestionOutcomeStore(store), domain=args.domain,
    )
    requested_budget = args.max_questions if args.max_questions is not None \
        else contract.get("max_questions")
    plan = planner.plan(
        misunderstanding_risk=args.risk,
        fatigue=args.fatigue,
        max_questions=min(requested_budget, contract.get("max_questions")),
    )
    data = {
        "mode": contract["mode"],
        "budget": contract.get("max_questions"),
        "questions": plan,
        "stopped_because": (
            "no question cleared the %s-mode utility threshold %.2f"
            % (contract["mode"], contract.get("min_utility", 0))
            if not plan else None
        ),
    }
    if plan:
        lines = ["%s mode - %d question(s) worth asking:" % (contract["mode"].upper(), len(plan))]
        for i, q in enumerate(plan, 1):
            lines.append("  %d. [%s, u=%.2f] %s" % (i, q["style"], q["utility"], q["text"]))
            lines.append("       %s" % q["why"])
    else:
        lines = ["No question clears the bar. Make a reversible assumption, state it, "
                 "and learn from the reaction."]
    return _emit(args, data, text="\n".join(lines))


def cmd_onboarding(args):
    store = _store(args)
    session = OnboardingSession(store, session_id=args.session or "onboarding")
    if args.action == "status":
        return _emit(args, session.state())
    guarded = _learning_guard(args, "onboarding")
    if guarded is not None:
        return guarded
    if args.action == "start":
        session.start()
        return _emit(args, session.state(), text="onboarding started - ask one question at a time")
    if args.action == "next":
        q = session.next_question()
        if q is None:
            return _emit(args, {"done": True}, text="onboarding complete - run `liwm onboarding complete`")
        return _emit(args, q, text="Q%d/%d [%s/%s]  %s"
                     % (q["position"], q["of"], q["style"], q["family"], q["text"]))
    if args.action == "answer":
        observations = []
        for raw in args.observation or []:
            try:
                observations.append(json.loads(raw))
            except ValueError as exc:
                sys.stderr.write("--observation must be JSON: %s\n" % exc)
                return EXIT_USAGE
        profile = session.record_answer(args.question_id, args.text, observations=observations)
        return _emit(args, {"revision": profile["revision"], "recorded": len(observations)},
                     text="recorded %d observation(s)" % len(observations))
    if args.action == "complete":
        profile = session.complete(summary=args.text)
        state = session.state()
        return _emit(args, {"onboarding": profile["onboarding"], "state": state},
                     text="onboarding complete: %d questions, %d families covered"
                          % (state["answered"], state["families_covered"]))
    if args.action == "correct":
        profile = session.correct(args.dimension, args.value, reason=args.text)
        return _emit(args, {"revision": profile["revision"]}, text="correction recorded")
    return EXIT_USAGE


def cmd_project(args):
    store = _store(args)
    project_id = slugify_project(args.project or Path.cwd())
    ps = ProjectStore(store.home, project_id)

    if args.action == "show":
        return _emit(args, ps.load_intent() if args.raw else ps.summary())
    if args.action not in ("show", "delete"):
        guarded = _learning_guard(args, "project intent")
        if guarded is not None:
            return guarded
    if args.action == "init":
        doc = ps.load_intent(name=args.name, domain=args.domain)
        doc["domain"] = args.domain or doc.get("domain")
        doc["name"] = args.name or doc.get("name")
        ps.save_intent(doc)
        store.events.record("project_intent_update", "direct_user_message",
                            payload={"action": "init", "project_id": project_id},
                            project_id=project_id, domain=args.domain)
        return _emit(args, ps.summary(), text="project %s initialised" % project_id)
    if args.action == "add":
        if args.section not in INTENT_SECTIONS:
            sys.stderr.write("unknown section %r; expected one of: %s\n"
                             % (args.section, ", ".join(INTENT_SECTIONS)))
            return EXIT_USAGE
        project_provenance = {
            "USER_SAID": "direct_user_message",
            "AGENT_INFERRED": "agent_inference",
            "AGENT_DERIVED": "tool_output",
        }[args.origin]
        if PROVENANCE_TRUST[project_provenance] <= 0.0:
            event = store.events.record(
                "project_intent_update", project_provenance,
                payload={"action": "quarantined_add", "section": args.section,
                         "origin": args.origin}, project_id=project_id, domain=args.domain,
            )
            return _emit(args, {"quarantined": True, "event_id": event["event_id"],
                                "reason": event["quarantine_reason"]},
                         text="project intent recorded for audit but quarantined")
        item = ps.add(
            args.section, args.text, args.origin, confidence=args.confidence,
            evidence_refs=args.evidence or [], provenance=project_provenance,
        )
        store.events.record(
            "project_intent_update", project_provenance,
            payload={"action": "add", "section": args.section,
                     "item_id": item["id"], "origin": args.origin},
            project_id=project_id, domain=args.domain,
        )
        return _emit(args, item, text="%s <- [%s] %s" % (args.section, args.origin, args.text))
    if args.action == "stage":
        doc = ps.set_stage(args.text)
        return _emit(args, {"stage": doc["stage"]}, text="stage: %s" % doc["stage"])
    if args.action == "decision":
        entry = ps.record_decision(
            args.text, rationale=args.rationale, basis=args.evidence or [],
            alternatives=args.alternative or [], artifact=args.artifact,
            reversible=not args.irreversible, impact=args.impact,
        )
        store.events.record("decision", "agent_inference",
                            payload={"decision_id": entry["id"], "summary": args.text,
                                     "basis": entry["basis"], "impact": args.impact},
                            project_id=project_id, domain=args.domain)
        return _emit(args, entry, text="decision %s recorded" % entry["id"])
    if args.action == "delete":
        removed = ps.delete()
        store.forget(project_id=project_id)
        return _emit(args, {"removed": removed, "project_id": project_id},
                     text="removed project %s and tombstoned its evidence" % project_id)
    return EXIT_USAGE


def cmd_intent(args):
    """Inspect or mutate the event-derived intent state graph."""
    from .intent_graph import IntentGraphStore

    graph = IntentGraphStore(_home(args))
    if args.intent_action == "graph":
        data = graph.graph(
            scope=args.scope, scope_key=args.scope_key,
            include_quarantined=args.include_quarantined,
            include_inactive=args.include_inactive,
        )
        return _emit(args, data, text="intent graph: %d node(s), %d edge(s)" % (
            len(data["nodes"]), len(data["edges"]),
        ))
    if args.intent_action == "explain":
        data = graph.explain(args.id, history=args.history)
        element = data["element"]
        return _emit(args, data, text="%s %s (%s, effective confidence %.2f%s)\n"
                                      "%d evidence ref(s)" % (
            element["type"], element.get("label", element["id"]), element["id"],
            element.get("effective_confidence", element.get("confidence", 0.0)),
            "" if data["active"] else ", NOT ACTIVE: %s" % element.get("inactive_reason"),
            len(data["basis"]),
        ))
    if args.intent_action == "trace":
        data = graph.trace(args.id, history=args.history)
        return _emit(args, data, text="trace %s: %d node(s), %d edge(s), %d event(s)" % (
            args.id, len(data["nodes"]), len(data["edges"]),
            len(data["evidence_events"]),
        ))

    guarded = _learning_guard(args, "intent graph mutation")
    if guarded is not None:
        return guarded
    provenance = {
        "user": "direct_user_message", "edit": "direct_user_edit",
        "review": "explicit_user_review", "inference": "agent_inference",
    }[args.origin]
    common = {
        "provenance": provenance, "confidence": args.confidence,
        "scope": args.scope, "scope_key": args.scope_key,
        "evidence_refs": args.evidence or [], "status": args.status,
        "decay_policy": args.decay, "session_id": args.session,
        "project_id": args.project, "domain": args.domain,
    }
    if args.intent_action == "node":
        event, element = graph.add_node(
            args.type, args.label, value=_coerce(args.value), **common,
        )
    else:
        event, element = graph.add_edge(
            args.type, args.source, args.target, **common,
        )
    data = {
        "event_id": event["event_id"], "element": element,
        "quarantined": event.get("quarantined", False),
        "quarantine_reason": event.get("quarantine_reason"),
    }
    return _emit(args, data, text="%s %s%s" % (
        args.intent_action, element["id"],
        " (quarantined)" if event.get("quarantined") else "",
    ))


def cmd_why(args):
    store = _store(args)
    result = why(store, args.query, project_id=args.project)
    if result["result"] is None:
        return _emit(args, result, text="nothing recorded for %r" % args.query)
    return _emit(args, result, text=_render_why(result))


def _render_why(result):
    kind, payload = result["type"], result["result"]
    lines = []
    if kind == "belief":
        b = payload["belief"]
        lines.append("%s = %s  (confidence %.2f, %s scope)"
                     % (b["dimension"], b["value"], b["confidence"], b["scope"]))
        lines.append(payload["confidence_explanation"])
        if payload["supporting_evidence"]:
            lines.append("supporting:")
            for e in payload["supporting_evidence"][-5:]:
                lines.append("  %s  %-22s %s" % (e["at"][:19], e["source_type"] or e["kind"],
                                                 (e["quote"] or "")[:60]))
        if payload["opposing_evidence"]:
            lines.append("contradicting:")
            for e in payload["opposing_evidence"][-3:]:
                lines.append("  %s  %-22s %s" % (e["at"][:19], e["source_type"] or e["kind"],
                                                 (e["quote"] or "")[:60]))
        if payload.get("ignored_note"):
            lines.append(payload["ignored_note"])
    elif kind == "decision":
        d = payload["decision"]
        lines.append("decision %s: %s" % (d["id"], d["summary"]))
        lines.append("rationale: %s" % (d.get("rationale") or "(none recorded)"))
        for b in payload["basis_detail"]:
            lines.append("  based on %s %s" % (b["type"], b["ref"]))
        lines.append(payload["completeness"])
    elif kind == "dimension":
        lines.append("views on %s:" % payload["dimension"])
        for v in payload["views"]:
            lines.append("  %-8s %-16s %-18s %.2f  (%s)"
                         % (v["scope"], v.get("scope_key") or "-", str(v["value"])[:18],
                            v["confidence"], v["status"]))
        lines.append(payload["note"])
    else:
        lines.append("recent assumptions:")
        for a in payload:
            lines.append("  %s  disclosed=%s  %s"
                         % (a["at"][:19], a["disclosed"], a["assumption"]))
    return "\n".join(lines)


def cmd_stats(args):
    store = _store(args)
    ms = MetricsStore(store.home)
    metrics = ms.refresh(store) if args.refresh else (ms.load() or ms.refresh(store))
    lines = ["LIWM metrics (computed %s)" % metrics.get("computed_at")]
    for key, value in (metrics.get("rates") or {}).items():
        if value is not None:
            lines.append("  %-38s %s" % (key, value))
    cal = metrics.get("calibration") or {}
    if cal.get("samples"):
        lines.append("  %-38s %s samples, brier %s, bias %s"
                     % ("calibration", cal["samples"], cal.get("brier_score"), cal.get("bias")))
    imp = metrics.get("improvement") or {}
    lines.append("  %-38s %s (delta %s)" % ("trend", imp.get("verdict"), imp.get("delta")))
    sec = metrics.get("security") or {}
    lines.append("  %-38s %s quarantined, %s privacy refusals"
                 % ("security", sec.get("quarantined_events"), sec.get("privacy_refusals")))
    return _emit(args, metrics, text="\n".join(lines))


def cmd_predict(args):
    """Commit to an expectation *before* the user reacts to the work.

    Without this, "the framework is learning" is unfalsifiable: any outcome can
    be narrated as consistent with the profile after the fact.  With it, LIWM
    has a number on the record that later turns out right or wrong, and
    ``liwm stats`` reports the Brier score and calibration bins over them.
    """
    from .prediction import make_prediction, record_prediction

    store = _store(args)
    friction = []
    for raw in args.friction or ():
        issue, _, probability = raw.partition(":")
        if not issue.strip():
            raise ValueError("--friction takes 'issue[:probability]', got %r" % raw)
        friction.append({
            "issue": issue.strip(),
            "probability": float(probability) if probability else 0.3,
            "dimension": None,
        })

    prediction = make_prediction(
        predicted_acceptance=args.acceptance,
        confidence=args.confidence,
        predicted_friction=friction,
        uncertain_dimensions=args.uncertain or [],
        intent_assumptions=args.assumption or [],
        basis=args.basis or [],
        artifact=args.artifact,
    )
    record_prediction(store, prediction, session_id=args.session,
                      project_id=args.project, domain=args.domain)
    return _emit(args, prediction,
                 text="predicted acceptance %.2f (confidence %.2f) as %s\n"
                      "resolve it with: liwm resolve --prediction %s --acceptance <actual>"
                      % (prediction["predicted_acceptance"], prediction["confidence"],
                         prediction["id"], prediction["id"]))


def cmd_predict_preference(args):
    from .prediction import make_preference_prediction, record_prediction

    options = {}
    for raw in args.option:
        label, separator, probability = raw.partition("=")
        if not separator or not label:
            raise ValueError("--option must be LABEL=PROBABILITY")
        options[label] = float(probability)
    prediction = make_preference_prediction(
        options, args.confidence, basis=args.basis or [], artifact=args.artifact,
    )
    record_prediction(_store(args), prediction, session_id=args.session,
                      project_id=args.project, domain=args.domain)
    return _emit(args, prediction, text="predicted preference %s as %s"
                 % (prediction["predicted_option"], prediction["id"]))


def cmd_resolve(args):
    """Score an earlier prediction against what actually happened."""
    from .prediction import resolve_prediction

    store = _store(args)
    try:
        result = resolve_prediction(
            store, args.prediction, args.acceptance,
            observed_friction=args.friction or [],
            session_id=args.session, project_id=args.project, domain=args.domain,
            evaluator_type=args.evaluator, actual_option=args.actual_option,
            evidence_event_id=args.evidence_event,
        )
    except KeyError as exc:
        raise ValueError(str(exc)) from exc

    if result["target_type"] == "categorical_preference":
        lines = ["predicted %s, actual %s (%s)" % (
            result["predicted_option"], result["actual_option"],
            "correct" if result["top1_correct"] else "incorrect",
        )]
    else:
        lines = ["predicted %.2f, actual first-pass %d, error %+.2f (%s)"
                 % (result["predicted_acceptance"], result["actual_first_pass"],
                    result["error"], result["direction"])]
    if result["friction_hits"]:
        lines.append("  foreseen:  %s" % ", ".join(result["friction_hits"]))
    if result["friction_misses"]:
        lines.append("  predicted but absent: %s" % ", ".join(result["friction_misses"]))
    if result["surprises"]:
        lines.append("  did not see coming: %s" % ", ".join(result["surprises"]))
    return _emit(args, result, text="\n".join(lines))


def cmd_predictions(args):
    """List predictions and whether they were ever resolved.

    An unresolved prediction is not a neutral gap: it is a commitment LIWM made
    and never checked, and a pile of them means the calibration figures describe
    a biased sample of the work.
    """
    store = _store(args)
    predictions, outcomes = {}, {}
    for event in store.events.iter_events(kinds={"prediction", "outcome"}):
        payload = event.get("payload") or {}
        if event.get("kind") == "prediction" and payload.get("id"):
            predictions[payload["id"]] = {"at": event.get("ts"), **payload}
        elif payload.get("prediction_id"):
            outcomes[payload["prediction_id"]] = payload

    rows = []
    for pid, prediction in predictions.items():
        outcome = outcomes.get(pid)
        rows.append({
            "id": pid,
            "at": prediction.get("at"),
            "predicted_acceptance": prediction.get("predicted_acceptance"),
            "confidence": prediction.get("confidence"),
            "resolved": outcome is not None,
            "actual_acceptance": (outcome or {}).get("actual_acceptance"),
            "error": (outcome or {}).get("error"),
            "direction": (outcome or {}).get("direction"),
        })
    rows.sort(key=lambda r: r["at"] or "", reverse=True)
    unresolved = [r for r in rows if not r["resolved"]]

    if args.unresolved:
        rows = unresolved
    data = {"predictions": rows, "total": len(predictions),
            "unresolved": len(unresolved)}
    if not rows:
        return _emit(args, data, text="no predictions recorded yet")
    lines = ["%d prediction(s), %d unresolved" % (len(predictions), len(unresolved))]
    for row in rows[: args.limit]:
        lines.append("  %-18s predicted %.2f  %s" % (
            row["id"], row["predicted_acceptance"] or 0.0,
            ("actual %.2f (%s)" % (row["actual_acceptance"], row["direction"]))
            if row["resolved"] else "UNRESOLVED"))
    return _emit(args, data, text="\n".join(lines))


def cmd_calibration(args):
    metrics = MetricsStore(_home(args)).refresh(_store(args))
    calibration = metrics.get("calibration") or {}
    return _emit(args, calibration, text=(
        "%d binary sample(s): Brier %s, log loss %s, ECE %s; top-1 %s"
        % (calibration.get("samples", 0), calibration.get("brier_score"),
           calibration.get("log_loss"), calibration.get("expected_calibration_error"),
           calibration.get("top1_preference_accuracy"))
    ))


def cmd_contradictions(args):
    store = _store(args)
    profile = store.load()
    items = profile.get("contradictions", [])
    lines = ["%d contradiction(s)" % len(items)]
    for c in items:
        vals = " vs ".join("%s (%s, %.2f)" % (k["value"], k["scope"], k["confidence"])
                           for k in c["candidates"])
        lines.append("  %-42s %s" % (c["dimension"], vals))
        lines.append("      type=%s  %s" % (c["type"], c["suggested_resolution"]))
    return _emit(args, {"contradictions": items}, text="\n".join(lines))


def cmd_assumptions(args):
    store = _store(args)
    items = recent_assumptions(store, project_id=args.project, limit=args.limit)
    lines = ["%d recent assumption(s)" % len(items)]
    for a in items:
        lines.append("  %s  disclosed=%-5s impact=%-6s %s"
                     % (a["at"][:19], a["disclosed"], a["impact"], a["assumption"]))
    return _emit(args, {"assumptions": items}, text="\n".join(lines))


def cmd_assume(args):
    guarded = _learning_guard(args, "assumption")
    if guarded is not None:
        return guarded
    store = _store(args)
    event = store.events.record(
        "assumption_made", "agent_inference",
        payload={"assumption": args.text, "reversible": not args.irreversible,
                 "impact": args.impact, "disclosed": args.disclosed,
                 "basis": args.evidence or []},
        session_id=args.session, project_id=args.project, domain=args.domain,
    )
    return _emit(args, {"event_id": event["event_id"]}, text="assumption recorded")


def cmd_reject(args):
    store = _store(args)
    profile = store.reject(args.dimension, value=_coerce(args.value), reason=args.reason,
                           inference_source=args.source, session_id=args.session,
                           scope=args.scope, scope_key=args.scope_key)
    return _emit(args, {"revision": profile["revision"],
                        "rejections": profile["rejections"][-3:]},
                 text="recorded: %s is not true about you. Weak signals can no longer "
                      "relearn it; only a direct statement from you can." % args.dimension)


def cmd_forget(args):
    store = _store(args)
    if not any((args.dimension, args.belief, args.project)):
        sys.stderr.write("specify --dimension, --belief or --project\n")
        return EXIT_USAGE
    profile = store.forget(dimension=args.dimension, belief_key_=args.belief,
                           project_id=args.project, session_id=args.session)
    return _emit(args, {"revision": profile["revision"],
                        "beliefs": len(profile["beliefs"])},
                 text="forgotten; history retained for audit, effect removed")


def cmd_export(args):
    store = _store(args)
    profile = store.load()
    payload = {
        "exported_at": utc_now(),
        "liwm_version": __version__,
        "schema_version": profile.get("schema_version"),
        "profile": profile,
        "metrics": MetricsStore(store.home).load(),
        "strategy": StrategyStore(store.home).load(),
        "promoted_rules": SelfImprovementStore(store.home).promoted_rules(),
    }
    if args.include_events:
        payload["events"] = store.events.read_all(include_quarantined=True)
    anonymise = bool(
        args.anonymise
        or ConfigStore(store.home).load().get("privacy", {}).get("redact_exports_by_default")
    )
    if anonymise:
        payload = _anonymise(payload)
    out = Path(args.out).expanduser() if args.out else (
        Path(store.home) / "exports" / ("liwm-export-%s.json" % utc_now().replace(":", "")))
    write_json_atomic(out, payload)
    store.events.record("export", "direct_user_message",
                        payload={"path": str(out), "anonymised": anonymise,
                                 "included_events": bool(args.include_events)})
    return _emit(args, {"path": str(out), "bytes": out.stat().st_size,
                        "anonymised": anonymise},
                 text="exported to %s" % out)


def _anonymise(payload):
    """Build an allowlisted research export with no arbitrary free text.

    This intentionally does not recursively "scrub" the original document.
    Denylists miss new fields. Instead, each released field is selected here,
    identifiers receive unlinkable per-export pseudonyms, and unconstrained
    values become a literal redaction marker regardless of their length.
    """
    import hashlib
    import uuid
    from .taxonomy import DIMENSION_INDEX, dimension_meta

    salt = uuid.uuid4().hex

    def pseudonym(value, prefix="anon"):
        if value is None:
            return None
        digest = hashlib.sha256((salt + "\0" + str(value)).encode("utf-8")).hexdigest()[:12]
        return "%s_%s" % (prefix, digest)

    def safe_dimension(value):
        if value in DIMENSION_INDEX:
            return value
        root = str(value or "").split(".", 1)[0]
        if root in {"preferences", "anti_preferences", "goals", "anti_goals",
                    "expectations", "domain_fluency"}:
            return root + ".<redacted>"
        return "<redacted>"

    def safe_value(dimension, value):
        if value is None or isinstance(value, (bool, int, float)):
            return value
        allowed = set(dimension_meta(dimension).get("values") or ())
        if isinstance(value, str) and value in allowed:
            return value
        if isinstance(value, list) and all(
                isinstance(v, str) and v in allowed for v in value):
            return value
        return "<redacted>"

    def belief_row(row):
        dimension = row.get("dimension")
        return {
            "id": pseudonym(row.get("id"), "belief"),
            "scope": row.get("scope"),
            "scope_key": pseudonym(row.get("scope_key"), "scope"),
            "dimension": safe_dimension(dimension),
            "value": safe_value(dimension, row.get("value")),
            "confidence": row.get("confidence"),
            "evidence_count": row.get("evidence_count"),
            "contradiction_count": row.get("contradiction_count"),
            "source_types": [s for s in row.get("source_types", [])
                             if s in SOURCE_WEIGHTS or s == "promotion"],
            "provenance_types": [p for p in row.get("provenance_types", [])
                                  if p in PROVENANCE_TRUST or p == "derived"],
            "decay_policy": row.get("decay_policy"),
            "origin": row.get("origin"),
            "status": row.get("status"),
        }

    dynamic_key_containers = {
        "by_domain", "by_mode", "corrections_by_scope", "style_effectiveness",
        "parameters",
    }

    def numeric_tree(obj, pseudonymise_keys=False):
        if isinstance(obj, dict):
            out = {}
            for key, value in obj.items():
                if not (isinstance(value, (dict, list, bool, int, float)) or value is None):
                    continue
                safe_key = pseudonym(key, "key") if pseudonymise_keys else str(key)
                out[safe_key] = numeric_tree(
                    value, pseudonymise_keys=str(key) in dynamic_key_containers
                )
            return out
        if isinstance(obj, list):
            return [numeric_tree(v) for v in obj
                    if isinstance(v, (dict, list, bool, int, float)) or v is None]
        return obj if isinstance(obj, (bool, int, float)) or obj is None else None

    profile = payload.get("profile") or {}
    onboarding = profile.get("onboarding") or {}
    out = {
        "anonymised": True,
        "export_format": "liwm-research-allowlist-v1",
        "liwm_version": payload.get("liwm_version"),
        "schema_version": payload.get("schema_version"),
        "profile": {
            "profile_id": pseudonym(profile.get("profile_id"), "profile"),
            "revision": profile.get("revision"),
            "onboarding": {
                "status": onboarding.get("status"),
                "questions_asked": onboarding.get("questions_asked"),
                "dimensions_covered": [safe_dimension(d) for d in
                                       onboarding.get("dimensions_covered", [])],
            },
            "beliefs": [belief_row(row) for row in profile.get("beliefs", [])],
            "statistics_summary": numeric_tree(profile.get("statistics_summary", {})),
            "confidence_calibration": numeric_tree(profile.get("confidence_calibration", {})),
        },
        "metrics": numeric_tree(payload.get("metrics", {})),
        "strategy": numeric_tree(payload.get("strategy", {})),
        "promoted_rules": {
            "rules": [
                {
                    "id": pseudonym(rule.get("id"), "rule"),
                    "active": bool(rule.get("active")),
                    "parameters": numeric_tree(rule.get("parameters", {})),
                }
                for rule in (payload.get("promoted_rules") or {}).get("rules", [])
            ]
        },
        "anonymisation_note": (
            "Allowlisted structural and numeric research data only. Arbitrary strings, "
            "raw answers, notes, project text, paths, timestamps, and artifact content removed."
        ),
    }
    if "events" in payload:
        out["events"] = [
            {
                "event_id": pseudonym(event.get("event_id"), "event"),
                "kind": event.get("kind") if event.get("kind") in EVENT_KINDS
                        else "other",
                "provenance": event.get("provenance")
                if event.get("provenance") in PROVENANCE_TRUST else "other",
                "quarantined": bool(event.get("quarantined")),
                "observation": belief_row(event["observation"])
                if event.get("observation") else None,
            }
            for event in payload.get("events", [])
        ]
    return out


def _create_snapshot(home, prefix="manual"):
    import shutil

    root = Path(home) / "backups"
    root.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "").replace("-", "")
    destination = root / ("%s-%s" % (prefix, stamp))
    counter = 1
    while destination.exists():
        destination = root / ("%s-%s-%d" % (prefix, stamp, counter))
        counter += 1
    destination.mkdir(parents=True)
    included = []
    for name in (
        "user.json", "intent-graph.json", "metrics.json", "config.json", "runtime_context.json",
        "events-manifest.json", "events", "archives", "checkpoints", "sessions",
        "projects", "learning",
    ):
        source = Path(home) / name
        if source.is_dir():
            shutil.copytree(source, destination / name)
            included.append(name + "/")
        elif source.is_file():
            shutil.copy2(source, destination / name)
            included.append(name)
    manifest = {
        "created_at": utc_now(), "liwm_version": __version__, "source": str(home),
        "included": included,
        "restore_note": (
            "Restore only with an LIWM-aware agent. Prefer `liwm rollback` for profile state; "
            "a raw snapshot restore must preserve unrelated current data."
        ),
    }
    write_json_atomic(destination / "manifest.json", manifest)
    if not (destination / "manifest.json").is_file():  # pragma: no cover
        raise OSError("snapshot manifest was not persisted")
    return destination, included


def cmd_reset(args):
    store = _store(args)
    home = store.home
    if args.hard:
        if not args.yes:
            sys.stderr.write("refusing to hard-reset without --yes\n")
            return EXIT_USAGE
        import shutil
        with FileLock(lifecycle_lock_path(home), timeout=30.0):
            with FileLock(store.events.lock_path, timeout=30.0):
                backup, included = _create_snapshot(home, prefix="pre-reset")
                required = {"events/", "projects/", "learning/"}
                present = {name for name in included if name in required}
                for name in (
                    "events", "archives", "checkpoints", "sessions", "projects", "learning",
                ):
                    src = Path(home) / name
                    if src.is_dir():
                        shutil.rmtree(src)
                for name in (
                    "user.json", "intent-graph.json", "metrics.json", "runtime_context.json",
                    "events-manifest.json",
                ):
                    src = Path(home) / name
                    if src.is_file():
                        src.unlink()
                ensure_layout(home)
        profile = ProfileStore(home).rebuild(reason="hard_reset")
        from .intent_graph import IntentGraphStore
        IntentGraphStore(home).rebuild()
        return _emit(args, {"reset": "hard", "backup": str(backup),
                            "backup_included": included, "source_dirs_backed_up": sorted(present),
                            "revision": profile["revision"]},
                     text="hard reset complete; a snapshot is in %s" % backup)

    store.events.record("reset", "direct_user_message", payload={"type": "soft"})
    profile = store.rebuild(reason="soft_reset")
    from .intent_graph import IntentGraphStore
    IntentGraphStore(home).rebuild()
    return _emit(args, {"reset": "soft", "revision": profile["revision"]},
                 text="soft reset: prior events retained for audit but removed from active state")


def cmd_delete(args):
    """Irrecoverably remove one validated LIWM private-data root."""
    if not args.yes:
        sys.stderr.write("refusing complete private-data deletion without --yes\n")
        return EXIT_USAGE
    import shutil

    home = Path(getattr(args, "home", None) or liwm_home()).expanduser().resolve()
    forbidden = {Path("/").resolve(), Path.home().resolve(), Path.cwd().resolve()}
    if home in forbidden:
        raise ValueError("refusing unsafe deletion target %s" % home)
    marker = home / "README.txt"
    marker_text = marker.read_text(encoding="utf-8") if marker.is_file() else ""
    if "private LIWM" not in marker_text or not (home / "events").is_dir():
        raise ValueError("target does not look like an initialized LIWM home: %s" % home)
    with FileLock(lifecycle_lock_path(home), timeout=30.0):
        files = sum(1 for path in home.rglob("*") if path.is_file())
        shutil.rmtree(home)
        if home.exists():  # pragma: no cover - defensive against unusual filesystems
            raise OSError("LIWM home still exists after deletion: %s" % home)
    return _emit(args, {"deleted": str(home), "files_removed": files, "recoverable": False},
                 text="permanently deleted %s (%d files); no LIWM backup was retained"
                      % (home, files))


def _validate_cutoff(value):
    from datetime import datetime, timezone

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("--as-of must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed > datetime.now(timezone.utc):
        raise ValueError("--as-of cannot be in the future")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def cmd_rollback(args):
    if not args.yes:
        sys.stderr.write("refusing to change the active event branch without --yes\n")
        return EXIT_USAGE
    cutoff = _validate_cutoff(args.as_of)
    event, profile = _store(args).rollback(cutoff, reason=args.reason, session_id=args.session)
    from .intent_graph import IntentGraphStore
    IntentGraphStore(_home(args)).rebuild()
    branch = profile["materialized_from"].get("active_branch")
    return _emit(
        args,
        {
            "event_id": event["event_id"],
            "revision": profile["revision"],
            "beliefs": len(profile["beliefs"]),
            "active_branch": branch,
            "skipped_events": profile["materialized_from"].get("skipped_by_branch", 0),
        },
        text="rolled active state back to %s; skipped history remains auditable" % cutoff,
    )


def cmd_backup(args):
    """Create or inspect full local snapshots without interpreting their data."""
    home = _home(args)
    root = Path(home) / "backups"
    root.mkdir(parents=True, exist_ok=True)
    if args.action == "list":
        entries = []
        for path in sorted(root.iterdir(), key=lambda p: p.name, reverse=True):
            if path.is_dir():
                size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
                kind = "snapshot"
            else:
                size = path.stat().st_size
                kind = "automatic"
            entries.append({"name": path.name, "kind": kind, "bytes": size})
        return _emit(args, {"backups": entries, "directory": str(root)})

    destination, included = _create_snapshot(home)
    return _emit(args, {"path": str(destination), "included": included},
                 text="created full local snapshot %s" % destination)


def cmd_rebuild(args):
    store = _store(args)
    profile = store.rebuild(reason=args.reason or "manual", as_of=args.as_of)
    from .intent_graph import IntentGraphStore
    IntentGraphStore(store.home).rebuild()
    return _emit(args, {
        "revision": profile["revision"],
        "beliefs": len(profile["beliefs"]),
        "materialized_from": profile["materialized_from"],
    }, text="rebuilt from %d event(s) -> %d belief(s), revision %d"
            % (profile["materialized_from"]["event_count"], len(profile["beliefs"]),
               profile["revision"]))


def cmd_compact(args):
    from .compaction import compact

    result = compact(_store(args))
    return _emit(args, result, text=(
        "compacted %d event(s) through sequence %d; raw history retained in %s"
        % (result["events"], result["frontier"], result["archive"])
        if result.get("compacted") else result.get("reason", "nothing to compact")
    ))


def cmd_verify(args):
    from .compaction import verify_checkpoints

    store = _store(args)
    schema_store = SchemaStore()
    profile = store.load()
    integrity = store.events.verify(deep=getattr(args, "deep", False))
    schema_errors = schema_store.validate(profile, "user")
    state_documents = _validate_state_documents(store.home, schema_store, include_events=True)
    checkpoints = verify_checkpoints(store.home)
    folded = store.fold() if integrity["ok"] else None
    drift = bool(folded) and (
        folded["materialized_from"]["fold_hash"] != profile["materialized_from"].get("fold_hash")
    )
    data = {
        "event_integrity": integrity,
        "schema_errors": schema_errors,
        "state_document_validation": state_documents,
        "checkpoints": checkpoints,
        "constitution_hash": constitution_hash(),
        "constitution_matches": profile.get("constitution_hash") == constitution_hash(),
        "materialisation_drift": drift,
        "ok": integrity["ok"] and checkpoints["ok"] and not schema_errors
              and state_documents["ok"] and not drift,
    }
    lines = [
        "events: %d checked, %d tampered, %d unreadable"
        % (integrity["checked"], integrity["tampered"], integrity["unreadable"]),
        "schema: %d error(s)" % len(schema_errors),
        "other state: %d document(s), %d invalid"
        % (state_documents["checked"], len(state_documents["errors"])),
        "materialisation drift: %s" % ("YES - run `liwm rebuild`" if drift else "none"),
        "constitution: %s" % ("matches" if data["constitution_matches"] else "MISMATCH"),
    ]
    return _emit(args, data, text="\n".join(lines))


def cmd_migrate(args):
    store = _store(args)
    report = migrate_home(store.home, store=store)
    return _emit(args, report, text="migrated %d file(s), skipped %d, %d error(s)"
                 % (len(report["migrated"]), len(report["skipped"]), len(report["errors"])))


def cmd_rules(args):
    store = _store(args)
    si = SelfImprovementStore(store.home)
    if args.action == "list":
        candidates = si.list_candidates(state=args.state, include_rejected=args.include_rejected)
        data = {
            "active_rules": si.active_rules(),
            "candidates": [
                {"id": c["id"], "title": c["title"], "state": c["state"],
                 "surface": c["surface"],
                 "violations": c.get("constitution", {}).get("violations", []),
                 "primary_delta": (c.get("replay") or {}).get("primary_delta")}
                for c in candidates
            ],
        }
        lines = ["%d active rule(s), %d candidate(s)"
                 % (len(data["active_rules"]), len(data["candidates"]))]
        for r in data["active_rules"]:
            lines.append("  ACTIVE  %s  %s" % (r["id"][:16], r["statement"][:70]))
        for c in data["candidates"]:
            lines.append("  %-8s %s  %s" % (c["state"][:8], c["id"][:16], c["title"][:60]))
            if c["violations"]:
                lines.append("           blocked: %s" % "; ".join(c["violations"])[:100])
        return _emit(args, data, text="\n".join(lines))

    if args.action == "replay":
        from .evaluation.replay import replay_candidate
        candidate = si.read(args.id)
        if candidate is None:
            sys.stderr.write("no candidate %r\n" % args.id)
            return EXIT_ERROR
        result = replay_candidate(store.home, candidate)
        si.attach_replay(args.id, result)
        return _emit(args, result, text="replayed %d episode(s): primary %s delta %s"
                     % (result["episodes"], result["primary_metric"], result["primary_delta"]))

    if args.action == "promote":
        candidate, verdict = si.promote(args.id, store=store)
        return _emit(args, {"state": candidate["state"], "verdict": verdict},
                     text=("promoted" if verdict["passed"]
                           else "rejected: %s" % "; ".join(verdict["reasons"])))

    if args.action == "revert":
        changed = si.revert(args.id, store=store, reason=args.reason or "user requested")
        return _emit(args, {"reverted": changed},
                     text="reverted" if changed else "no active rule with that id")

    from .experiments import EXPERIMENT_MODES, ExperimentStore
    experiments = ExperimentStore(store.home)
    if args.action == "experiments":
        data = experiments.load()
        lines = ["%d experiment(s)" % len(data["experiments"])]
        for row in data["experiments"]:
            lines.append("  %-8s %-7s exposure %.2f  %s  %s"
                         % (row["state"], row["mode"], row["exposure"],
                            row["candidate_id"][:16],
                            EXPERIMENT_MODES[row["mode"]]["note"]))
        return _emit(args, data, text="\n".join(lines))

    if args.action == "enroll":
        row = experiments.enroll(args.id, args.experiment_mode, store=store,
                                 exposure=args.exposure, seed=args.seed)
        return _emit(args, row, text="enrolled %s as a %s experiment (%s)"
                     % (args.id, row["mode"], EXPERIMENT_MODES[row["mode"]]["note"]))

    if args.action == "assign":
        if not args.unit:
            raise ValueError("rules assign requires --unit")
        assignment = experiments.assign(args.id, args.unit, store=store,
                                        session_id=args.session, project_id=args.project,
                                        domain=args.domain)
        return _emit(args, assignment, text="%s -> %s (%s)"
                     % (args.unit, assignment["condition"], assignment["exposure"]))

    if args.action == "stop":
        stopped = experiments.stop(args.id, store=store,
                                   reason=args.reason or "user requested")
        return _emit(args, {"stopped": stopped},
                     text="stopped" if stopped else "no running experiment for that id")
    return EXIT_USAGE


def cmd_retro(args):
    from .retrospective import run_retrospective
    guarded = _learning_guard(args, "retrospective")
    if guarded is not None:
        return guarded
    store = _store(args)
    result = run_retrospective(store, args.session, project_id=args.project)
    lines = ["retrospective for session %s" % args.session]
    for lesson in result["lessons"]:
        lines.append("  - %s" % lesson)
    if result["strategy_changes"]:
        lines.append("  strategy: %s" % json.dumps(result["strategy_changes"]))
    for c in result["candidates"]:
        lines.append("  candidate %s [%s] %s" % (c["id"][:16], c["state"], c["title"]))
    return _emit(args, result, text="\n".join(lines))


def cmd_eval(args):
    if args.action == "retrieval":
        from .evaluation.retrieval import SPLITS, load_suite, run_retrieval
        splits = SPLITS if args.split == "all" else (args.split,)
        result = run_retrieval(load_suite(args.cases), splits=splits,
                               use_intent=not args.no_intent)
        lines = ["retrieval %s (%d/%d cases, intent %s)" % (
            result["suite_id"], result["manifest"]["cases_scored"],
            result["manifest"]["cases_total"],
            "off" if args.no_intent else "on")]
        lines.append("%-10s %6s %8s %-18s %10s %7s %8s" % (
            "split", "cases", "recall", "ci95", "precision", "mrr", "tokens"))
        for name, row in result["splits"].items():
            if not row:
                continue
            lines.append("%-10s %6d %8.3f %-18s %10.3f %7.3f %8.0f" % (
                name, row["cases"], row["recall"], str(row["recall_ci95"]),
                row["precision"], row["mrr"], row["mean_tokens"]))
        lines.append("Recall is retrieval recall, not answer accuracy. No model ran.")
        return _emit(args, result, text="\n".join(lines))
    if args.action == "contextecon":
        from .evaluation.contextecon import load_scenario, run_contextecon
        result = run_contextecon(load_scenario(args.cases, scenario=args.scenario))
        lines = ["context economics: %s (%d turns, %s token counts)" % (
            result["scenario_id"], result["manifest"]["turns"],
            result["manifest"]["token_counting"])]
        lines.append("%-22s %10s %9s %9s %7s" % (
            "arm", "tokens/turn", "sufficient", "tok/req", "poisoned"))
        for arm, row in result["arms"].items():
            lines.append("%-22s %10.1f %9s %9s %7d" % (
                arm, row["mean_tokens_per_turn"],
                "n/a" if row["evidence_sufficiency"] is None
                else "%.2f" % row["evidence_sufficiency"],
                "n/a" if row["tokens_per_satisfied_requirement"] is None
                else "%.0f" % row["tokens_per_satisfied_requirement"],
                row["poison_leak_turns"]))
        lines.append(result["caveat"])
        return _emit(args, result, text="\n".join(lines))
    if args.action == "intentbench":
        from .evaluation.intentbench import load_suite, run_intentbench
        result = run_intentbench(load_suite(args.cases, suite=args.suite),
                                 adapter=args.adapter)
        metrics = result["metrics"]
        return _emit(
            args, result,
            text=("IntentBench %s [%s]\n  adapter %s, %d cases\n"
                  "  top-1 %.3f  Brier %.3f  log loss %.3f\n  %s") % (
                      result["suite_id"], result["result_label"], result["adapter"],
                      result["cases"], metrics["top1_accuracy"],
                      metrics["mean_brier_score"], metrics["mean_log_loss"],
                      result["caveat"],
                  ),
        )
    if args.action == "converge":
        from .evaluation import run_convergence_study
        result = run_convergence_study(args.archetype, rounds=args.rounds, seed=args.seed,
                                       mode=args.mode)
        summary = result["summary"]
        lines = [
            "archetype %s, %d rounds (simulated - measures LIWM, not a person)"
            % (args.archetype, args.rounds),
            "  accuracy   %.2f -> %.2f  (gain %+.2f)"
            % (summary["accuracy_first_round"], summary["accuracy_final_round"],
               summary["accuracy_gain"]),
            "  acceptance %.2f -> %.2f  (gain %+.2f)"
            % (summary["acceptance_early"] or 0, summary["acceptance_late"] or 0,
               summary["acceptance_gain"]),
            "  questions  %.2f -> %.2f  (reduction %+.2f)"
            % (summary["questions_early"] or 0, summary["questions_late"] or 0,
               summary["questions_reduction"]),
        ]
        result.pop("temp_home", None)
        return _emit(args, result, text="\n".join(lines))

    if args.action == "modes":
        from .evaluation import run_mode_study
        result = run_mode_study()
        lines = ["mode comparison on one fixed situation:"]
        for mode, row in result["modes"].items():
            lines.append("  %-7s -> %-7s budget %-3s planned %-2s experiential %s"
                         % (mode, row["effective_mode"], row["question_budget"],
                            row["planned"], row["experiential_share"]))
        lines.append("  distinguishable: %s" % json.dumps(result["distinguishable"]))
        result.pop("temp_home", None)
        return _emit(args, result, text="\n".join(lines))
    return EXIT_USAGE


def cmd_study(args):
    from .study import (
        delete_study_key, export_study, rotate_study_key, set_study_enabled,
        study_key_status, study_status,
    )
    home = _home(args)
    if args.action == "status":
        result = dict(study_status(home), key=study_key_status(home))
        return _emit(args, result, text="study mode %s; local only; no automatic upload"
                     % ("on" if result["enabled"] else "off"))
    if args.action in {"on", "off"}:
        result = set_study_enabled(home, args.action == "on")
        return _emit(args, result, text="study mode %s" % args.action)
    if args.action == "rotate-key":
        result = rotate_study_key(home, study_id=args.study_id)
        return _emit(args, result, text="new longitudinal key for %s; exports made under "
                                        "the old key can no longer be joined to new ones"
                     % result["study_id"])
    if args.action == "forget-key":
        result = delete_study_key(home)
        return _emit(args, result, text=(
            "longitudinal key deleted; existing exports can never be linked or "
            "re-identified from this machine again" if result["deleted"]
            else "no longitudinal key to delete"))
    if args.action == "export":
        result = export_study(home, out=args.out, anonymise=args.anonymise,
                              longitudinal=args.longitudinal)
        return _emit(args, result, text="local %s study export written to %s; inspect "
                                        "before sharing"
                     % (result["mode"], result["path"]))
    return EXIT_USAGE


def cmd_schema(args):
    schema_store = SchemaStore()
    if args.action == "list":
        available = {k: str(v) for k, v in schema_store.available().items()}
        return _emit(args, available,
                     text="\n".join("  %-22s %s" % (k, v) for k, v in sorted(available.items())))
    if args.action == "validate":
        data, note = read_json_resilient(args.file)
        if data is None:
            sys.stderr.write("cannot read %s: %s\n" % (args.file, note))
            return EXIT_ERROR
        errors = validate(data, schema_store.load(args.name))
        return _emit(args, {"file": args.file, "schema": args.name, "valid": not errors,
                            "errors": errors},
                     text=("valid" if not errors else
                           "\n".join("  %s: %s" % (e["path"] or "/", e["message"])
                                     for e in errors[:20])))
    return EXIT_USAGE


def cmd_constitution(args):
    data = {
        "hash": constitution_hash(),
        "invariant_count": len(INVARIANTS),
        "invariants": [dict(i) for i in INVARIANTS],
        "provenance_trust": PROVENANCE_TRUST,
        "trusted_provenance": sorted(TRUSTED_PROVENANCE),
        "source_weights": SOURCE_WEIGHTS,
        "source_ceilings": SOURCE_CEILINGS,
    }
    lines = ["LIWM constitution (%d invariants, hash %s)"
             % (len(INVARIANTS), constitution_hash()[:16])]
    for inv in INVARIANTS:
        lines.append("  %s  %s" % (inv["id"], inv["title"]))
        if args.full:
            lines.append("        %s" % inv["rule"])
    return _emit(args, data, text="\n".join(lines))


def cmd_events(args):
    store = EventStore(_home(args))
    if args.action == "stats":
        return _emit(args, store.stats())
    if args.action == "verify":
        return _emit(args, store.verify())
    if args.action == "tail":
        events = store.latest(args.limit, include_quarantined=args.include_quarantined)
        lines = []
        for e in events:
            lines.append("%s  %-22s %-22s %s"
                         % (e["ts"][:19], e["kind"], e["provenance"],
                            "QUARANTINED" if e.get("quarantined") else ""))
        return _emit(args, {"events": events}, text="\n".join(lines))
    return EXIT_USAGE


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="liwm",
        description="LIWM - Latent Intent World Model: a local, evidence-based intent-learning "
                    "layer for coding agents.",
    )
    p.add_argument("--version", action="version", version="liwm %s" % __version__)
    p.add_argument("--home", help="LIWM data directory (default: $LIWM_HOME or ~/.liwm)")
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("init", help="create the LIWM home directory and an empty profile")
    s.add_argument("--allow-in-repo", action="store_true",
                   help="permit initialisation inside a git repository (tests only)")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("doctor", help="check installation health")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("config", help="inspect or change LIWM runtime settings")
    s.add_argument("action", choices=["show", "set"])
    s.add_argument("--key")
    s.add_argument("--value")
    s.set_defaults(func=cmd_config)

    s = sub.add_parser("integration", help="manage host installation metadata")
    s.add_argument("action", choices=["register", "show", "remove"])
    s.add_argument("--host")
    s.add_argument("--framework-checkout", dest="framework_checkout")
    s.add_argument("--cli-command", dest="cli_command")
    s.add_argument("--skills-path", dest="skills_path")
    s.add_argument("--install-method", dest="install_method")
    s.add_argument("--bootstrap-file", dest="bootstrap_file")
    s.add_argument("--bootstrap-version", dest="bootstrap_version")
    s.set_defaults(func=cmd_integration)

    s = sub.add_parser("hosts", help="list, detect, or plan installation into agent hosts")
    s.add_argument("action", nargs="?", default="list", choices=["list", "detect", "plan"])
    s.add_argument("--host", help="host id, e.g. claude-code, codex, gemini-cli")
    s.add_argument("--block", help="path to the bootstrap block, for budget checking")
    s.set_defaults(func=cmd_hosts)

    for command, actions in (("install", ["plan", "apply", "verify", "status", "repair"]),
                             ("uninstall", ["plan", "apply", "verify", "status", "repair"])):
        s = sub.add_parser(command, help="%s LIWM host integration safely" % command)
        s.add_argument("action", choices=actions)
        s.add_argument("--host", help="host id used when creating a plan")
        s.add_argument("--block", help="bootstrap block file (install plan only)")
        s.add_argument("--plan", help="serialized plan file")
        s.add_argument("--output", help="where to write a new plan")
        s.add_argument("--skills-source", help="override LIWM skills source directory")
        s.add_argument("--no-skills", action="store_true",
                       help="manage only the host instruction block")
        s.add_argument("--rollback", action="store_true",
                       help="repair by undoing the interrupted plan rather than finishing it")
        s.set_defaults(func=cmd_installation)

    s = sub.add_parser("profile", help="show the profile quality report")
    s.add_argument("--section", help="show one raw section of user.json")
    s.add_argument("--raw", action="store_true", help="dump the whole profile")
    s.set_defaults(func=cmd_profile)

    s = sub.add_parser("context", help="build the compact runtime context projection")
    s.add_argument("--domain")
    s.add_argument("--project")
    s.add_argument("--task")
    s.add_argument("--mode", default="auto", choices=["auto", "low", "medium", "high", "silent", "off"])
    s.add_argument("--signals", help="JSON object of AUTO signals")
    s.add_argument("--stage")
    s.add_argument("--write", action="store_true", help="also write runtime_context.json")
    s.add_argument("--capsule", action="store_true",
                   help="emit the compact capsule the model should read")
    s.add_argument("--receipt", action="store_true",
                   help="emit the ContextReceipt instead of the context")
    s.add_argument("--no-gate", dest="no_gate", action="store_true",
                   help="disable the zero-memory gate and always project")
    s.add_argument("--include", action="append", metavar="DIMENSION",
                   help="also project this dimension even if it was outranked; "
                        "repeatable. The sufficiency loop: ask for what is missing "
                        "rather than falling back to the whole profile")
    s.add_argument("--all", dest="all_beliefs", action="store_true",
                   help="project every applicable belief, ignoring the relevance cut")
    for key in ("intent_uncertainty", "novelty", "consequence", "reversibility",
                "specification_completeness", "recent_correction_rate", "fatigue"):
        s.add_argument("--%s" % key.replace("_", "-"), dest=key, type=float)
    s.set_defaults(func=cmd_context)

    s = sub.add_parser("observe", help="record one observation about the user")
    s.add_argument("--dimension", required=True)
    s.add_argument("--value", required=True)
    s.add_argument("--source", required=True, choices=sorted(SOURCE_WEIGHTS))
    s.add_argument("--provenance", required=True, choices=sorted(PROVENANCE_TRUST))
    s.add_argument("--scope", default="global", choices=["global", "domain", "project", "session"])
    s.add_argument("--scope-key", dest="scope_key")
    s.add_argument("--polarity", default="support", choices=["support", "oppose"])
    s.add_argument("--decay", default="standard",
                   choices=["none", "slow", "standard", "volatile", "session"])
    s.add_argument("--note")
    s.add_argument("--session")
    s.add_argument("--project")
    s.add_argument("--domain")
    s.set_defaults(func=cmd_observe)

    def add_observation_args(parser, sources, provenance=None):
        parser.add_argument("--dimension", required=True)
        parser.add_argument("--value", required=True)
        if len(sources) == 1:
            parser.set_defaults(source=next(iter(sources)))
        else:
            parser.add_argument("--source", choices=sorted(sources), default=sorted(sources)[0])
        if provenance == "untrusted":
            parser.add_argument(
                "--provenance", required=True,
                choices=sorted(k for k, v in PROVENANCE_TRUST.items() if v == 0.0),
            )
        parser.add_argument("--scope", default="global",
                            choices=["global", "domain", "project", "session"])
        parser.add_argument("--scope-key", dest="scope_key")
        parser.add_argument("--polarity", default="support", choices=["support", "oppose"])
        parser.add_argument("--decay", default="standard",
                            choices=["none", "slow", "standard", "volatile", "session"])
        parser.add_argument("--note")
        parser.add_argument("--session")
        parser.add_argument("--project")
        parser.add_argument("--domain")
        parser.add_argument("--derived-from", action="append",
                            help="upstream provenance label; repeatable and taint-propagating")
        parser.set_defaults(func=cmd_observe_intent)

    add_observation_args(
        sub.add_parser("observe-user", help="record evidence directly stated by the user"),
        {"explicit_statement", "explicit_correction", "explicit_rejection",
         "comparative_choice", "repeated_selection"},
    )
    add_observation_args(
        sub.add_parser("observe-edit", help="record a direct user edit"), {"direct_edit"}
    )
    add_observation_args(
        sub.add_parser("observe-review", help="record an explicit user review"),
        {"explicit_statement", "explicit_correction", "explicit_rejection",
         "comparative_choice", "repeated_selection"},
    )
    add_observation_args(
        sub.add_parser("observe-inference", help="record a bounded agent inference"),
        {"agent_inference", "single_behavioral", "repeated_behavioral", "outcome_signal"},
    )
    add_observation_args(
        sub.add_parser("observe-untrusted", help="record quarantined evidence for audit"),
        set(SOURCE_WEIGHTS), provenance="untrusted",
    )

    s = sub.add_parser("feedback", help="record user feedback on an artifact")
    s.add_argument("--kind", required=True, choices=sorted(FEEDBACK_KINDS))
    s.add_argument("--channel", default="explicit",
                   choices=["explicit", "corrective", "comparative", "repeated_comparative",
                            "edit", "outcome", "behavioral", "repeated_behavioral"])
    s.add_argument("--text")
    s.add_argument("--project")
    s.add_argument("--domain")
    s.add_argument("--session")
    s.add_argument("--artifact")
    s.add_argument("--decision")
    s.add_argument("--prediction",
                   help="prediction this feedback is the outcome of; required "
                        "before the prediction can be resolved as observed")
    s.add_argument("--selected-option", dest="selected_option",
                   help="option the user actually chose, for a preference prediction")
    s.add_argument("--acceptance", type=float)
    s.add_argument("--global-intent", dest="global_intent", action="store_true",
                   help="the user was speaking generally, not about this artifact")
    s.add_argument("--provenance", choices=sorted(PROVENANCE_TRUST),
                   help="true source; defaults from channel and is compatibility-checked")
    s.add_argument("--derived-from", action="append",
                   help="upstream provenance label; repeatable and taint-propagating")
    s.add_argument("--observation", action="append",
                   help="extra observation as JSON; repeatable")
    s.set_defaults(func=cmd_feedback)

    s = sub.add_parser("mode", help="resolve the operating mode")
    s.add_argument("--mode", default="auto", choices=["auto", "low", "medium", "high", "silent", "off"])
    s.add_argument("--signals")
    s.add_argument("--stage")
    for key in ("intent_uncertainty", "novelty", "consequence", "reversibility",
                "specification_completeness", "recent_correction_rate", "fatigue"):
        s.add_argument("--%s" % key.replace("_", "-"), dest=key, type=float)
    s.set_defaults(func=cmd_mode)

    s = sub.add_parser("plan", help="plan which questions are worth asking")
    s.add_argument("--mode", default="auto", choices=["auto", "low", "medium", "high", "silent", "off"])
    s.add_argument("--domain")
    s.add_argument("--project")
    s.add_argument("--risk", type=float, default=0.5, help="misunderstanding risk 0-1")
    s.add_argument("--fatigue", type=float, default=0.0)
    s.add_argument("--max-questions", dest="max_questions", type=int)
    s.add_argument("--signals")
    s.add_argument("--stage")
    for key in ("intent_uncertainty", "novelty", "consequence", "reversibility",
                "specification_completeness", "recent_correction_rate"):
        s.add_argument("--%s" % key.replace("_", "-"), dest=key, type=float)
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("onboarding", help="run the ten-question onboarding")
    s.add_argument("action", choices=["start", "next", "answer", "complete", "status", "correct"])
    s.add_argument("--question-id", dest="question_id")
    s.add_argument("--text")
    s.add_argument("--dimension")
    s.add_argument("--value")
    s.add_argument("--session")
    s.add_argument("--observation", action="append")
    s.set_defaults(func=cmd_onboarding)

    s = sub.add_parser("project", help="manage project intent")
    s.add_argument("action", choices=["init", "show", "add", "stage", "decision", "delete"])
    s.add_argument("--project", help="project id or path (default: cwd)")
    s.add_argument("--name")
    s.add_argument("--domain")
    s.add_argument("--section", choices=list(INTENT_SECTIONS))
    s.add_argument("--text")
    s.add_argument("--origin", choices=["USER_SAID", "AGENT_INFERRED", "AGENT_DERIVED"],
                   default="USER_SAID")
    s.add_argument("--confidence", type=float)
    s.add_argument("--evidence", action="append")
    s.add_argument("--alternative", action="append")
    s.add_argument("--rationale")
    s.add_argument("--artifact")
    s.add_argument("--impact", default="medium", choices=["low", "medium", "high"])
    s.add_argument("--irreversible", action="store_true")
    s.add_argument("--raw", action="store_true")
    s.set_defaults(func=cmd_project)

    s = sub.add_parser("intent", help="inspect or mutate the intent state graph")
    s.set_defaults(func=cmd_intent)
    intent_sub = s.add_subparsers(dest="intent_action", required=True)
    intent_graph = intent_sub.add_parser("graph", help="show the active graph")
    intent_graph.add_argument("--scope", choices=["global", "domain", "project", "session"])
    intent_graph.add_argument("--scope-key", dest="scope_key")
    intent_graph.add_argument("--include-quarantined", action="store_true")
    intent_graph.add_argument(
        "--include-inactive", action="store_true",
        help="also list elements a forget tombstone removed, by id and reason only")
    intent_explain = intent_sub.add_parser("explain", help="explain one node or edge")
    intent_explain.add_argument("id")
    intent_explain.add_argument(
        "--history", action="store_true",
        help="inspect the retained audit record of an element the user forgot")
    intent_trace = intent_sub.add_parser("trace", help="trace upstream evidence and intent")
    intent_trace.add_argument("id")
    intent_trace.add_argument("--history", action="store_true")

    def add_intent_mutation_args(parser, types):
        parser.add_argument("--type", required=True, choices=sorted(types))
        parser.add_argument("--origin", required=True,
                            choices=["user", "edit", "review", "inference"])
        parser.add_argument("--confidence", required=True, type=float)
        parser.add_argument("--scope", default="global",
                            choices=["global", "domain", "project", "session"])
        parser.add_argument("--scope-key", dest="scope_key")
        parser.add_argument("--evidence", action="append",
                            help="event or graph-element id; repeatable")
        parser.add_argument("--status", default="active", choices=[
            "active", "hypothesis", "validated", "falsified", "superseded", "rejected",
        ])
        parser.add_argument("--decay", default="standard",
                            choices=["none", "slow", "standard", "volatile", "session"])
        parser.add_argument("--session")
        parser.add_argument("--project")
        parser.add_argument("--domain")
        parser.set_defaults(func=cmd_intent)

    from .intent_graph import EDGE_TYPES, NODE_TYPES
    intent_node = intent_sub.add_parser("node", help="record one typed intent node")
    add_intent_mutation_args(intent_node, NODE_TYPES)
    intent_node.add_argument("--label", required=True)
    intent_node.add_argument("--value", help="JSON scalar/object, otherwise text")
    intent_edge = intent_sub.add_parser("edge", help="record one typed intent edge")
    add_intent_mutation_args(intent_edge, EDGE_TYPES)
    intent_edge.add_argument("--source", required=True)
    intent_edge.add_argument("--target", required=True)

    s = sub.add_parser("why", help="explain a belief, decision or dimension")
    s.add_argument("query", nargs="?")
    s.add_argument("--project")
    s.set_defaults(func=cmd_why)

    s = sub.add_parser("stats", help="show local performance metrics")
    s.add_argument("--refresh", action="store_true", default=True)
    s.add_argument("--no-refresh", dest="refresh", action="store_false")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("predict", help="record what LIWM expects before the user reacts")
    s.add_argument("--acceptance", type=float, required=True,
                   help="expected acceptance of the artifact, 0..1")
    s.add_argument("--confidence", type=float, required=True,
                   help="how sure LIWM is of that expectation, 0..1")
    s.add_argument("--friction", action="append",
                   help="likely friction as 'issue[:probability]'; repeatable")
    s.add_argument("--uncertain", action="append",
                   help="dimension whose uncertainty drove this; repeatable")
    s.add_argument("--assumption", action="append",
                   help="intent assumption being acted on; repeatable")
    s.add_argument("--basis", action="append", help="belief or event id relied on")
    s.add_argument("--artifact", help="short label for what is being produced")
    s.add_argument("--session")
    s.add_argument("--project")
    s.add_argument("--domain")
    s.set_defaults(func=cmd_predict)

    s = sub.add_parser("predict-preference", help="predict a preferred option before choice")
    s.add_argument("--option", action="append", required=True,
                   help="LABEL=PROBABILITY; repeat at least twice and sum to 1")
    s.add_argument("--confidence", type=float, required=True)
    s.add_argument("--basis", action="append")
    s.add_argument("--artifact")
    s.add_argument("--session")
    s.add_argument("--project")
    s.add_argument("--domain")
    s.set_defaults(func=cmd_predict_preference)

    s = sub.add_parser("resolve", help="score an earlier prediction against reality")
    s.add_argument("--prediction", required=True, help="prediction id from liwm predict")
    s.add_argument("--acceptance", type=float,
                   help="acceptance actually observed, 0..1")
    s.add_argument("--actual-option", dest="actual_option")
    s.add_argument("--evaluator", default="agent_recorded",
                   choices=["agent_recorded", "synthetic_replay", "historical_counterfactual_estimate",
                            "observed_human_outcome", "external_evaluator",
                            "benchmark_ground_truth"])
    s.add_argument("--evidence-event",
                   help="feedback event linked to this prediction; observed_human_outcome "
                        "reads the label out of it rather than taking your word")
    s.add_argument("--friction", action="append",
                   help="friction actually observed; repeatable")
    s.add_argument("--session")
    s.add_argument("--project")
    s.add_argument("--domain")
    s.set_defaults(func=cmd_resolve)

    s = sub.add_parser("predictions", help="list predictions and their outcomes")
    s.add_argument("--unresolved", action="store_true",
                   help="show only predictions that were never scored")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_predictions)

    s = sub.add_parser("calibration", help="show proper prediction scoring and reliability")
    s.set_defaults(func=cmd_calibration)

    s = sub.add_parser("contradictions", help="list contradictions in the profile")
    s.set_defaults(func=cmd_contradictions)

    s = sub.add_parser("assumptions", help="list assumptions LIWM acted on")
    s.add_argument("--project")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(func=cmd_assumptions)

    s = sub.add_parser("assume", help="record an assumption before acting on it")
    s.add_argument("text")
    s.add_argument("--impact", default="medium", choices=["low", "medium", "high"])
    s.add_argument("--irreversible", action="store_true")
    s.add_argument("--disclosed", action="store_true")
    s.add_argument("--evidence", action="append")
    s.add_argument("--session")
    s.add_argument("--project")
    s.add_argument("--domain")
    s.set_defaults(func=cmd_assume)

    s = sub.add_parser("reject", help="record that a belief is not true about you")
    s.add_argument("--dimension", required=True)
    s.add_argument("--value")
    s.add_argument("--reason")
    s.add_argument("--source", help="which inference method produced it")
    s.add_argument("--scope", default="global", choices=["global", "domain", "project"])
    s.add_argument("--scope-key", dest="scope_key")
    s.add_argument("--session")
    s.set_defaults(func=cmd_reject)

    s = sub.add_parser("forget", help="tombstone a dimension, belief or project")
    s.add_argument("--dimension")
    s.add_argument("--belief")
    s.add_argument("--project")
    s.add_argument("--session")
    s.set_defaults(func=cmd_forget)

    s = sub.add_parser("export", help="export the profile as JSON")
    s.add_argument("--out")
    s.add_argument("--include-events", action="store_true")
    s.add_argument("--anonymise", action="store_true",
                   help="strip free text and identifiers for research sharing")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("reset", help="reset the profile")
    s.add_argument("--hard", action="store_true",
                   help="reset events/projects/learning but retain a recovery snapshot")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_reset)

    s = sub.add_parser("delete", help="permanently delete the entire private LIWM home")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_delete)

    s = sub.add_parser("rebuild", help="re-fold user.json from the event log")
    s.add_argument("--reason")
    s.add_argument("--as-of", dest="as_of", help="fold only events up to this timestamp")
    s.set_defaults(func=cmd_rebuild)

    s = sub.add_parser("rollback", help="durably select an earlier event-log state")
    s.add_argument("--as-of", dest="as_of", required=True,
                   help="inclusive ISO-8601 cutoff timestamp")
    s.add_argument("--reason")
    s.add_argument("--session")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_rollback)

    s = sub.add_parser("backup", help="create or list private local snapshots")
    s.add_argument("action", choices=["create", "list"])
    s.set_defaults(func=cmd_backup)

    s = sub.add_parser("compact", help="archive live events with a verified checkpoint")
    s.set_defaults(func=cmd_compact)

    s = sub.add_parser("verify", help="verify integrity, schema and materialisation")
    s.add_argument("--deep", action="store_true",
                   help="re-hash every archived event individually rather than "
                        "trusting an archive whose recorded digest still matches. "
                        "Answers 'was this archive already corrupt when written', "
                        "which a matching digest cannot")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("migrate", help="migrate stored data to the current schema")
    s.set_defaults(func=cmd_migrate)

    s = sub.add_parser("rules", help="inspect and gate self-improvement candidates")
    s.add_argument("action", choices=["list", "replay", "promote", "revert",
                                      "experiments", "enroll", "assign", "stop"])
    s.add_argument("--id")
    s.add_argument("--state")
    s.add_argument("--reason")
    s.add_argument("--include-rejected", action="store_true")
    s.add_argument("--experiment-mode", dest="experiment_mode", default="shadow",
                   choices=["shadow", "canary", "ab"],
                   help="shadow computes without shipping; canary and ab put the "
                        "candidate in front of the user and need consent")
    s.add_argument("--exposure", type=float,
                   help="fraction of eligible interactions for a user-facing arm; "
                        "defaults to 0.10 for canary, 0.50 for ab")
    s.add_argument("--seed", help="fix the assignment seed for a registered design")
    s.add_argument("--unit", help="interaction id to assign, committed before output")
    s.add_argument("--session")
    s.add_argument("--project")
    s.add_argument("--domain")
    s.set_defaults(func=cmd_rules)

    s = sub.add_parser("retro", help="run a session retrospective")
    s.add_argument("session")
    s.add_argument("--project")
    s.set_defaults(func=cmd_retro)

    s = sub.add_parser("eval", help="run local evaluation studies")
    s.add_argument("action",
                   choices=["converge", "modes", "intentbench", "contextecon", "retrieval"])
    s.add_argument("--archetype", default="impatient_technical_expert")
    s.add_argument("--rounds", type=int, default=8)
    s.add_argument("--seed", type=int, default=1337)
    s.add_argument("--mode", default="auto")
    s.add_argument("--cases", help="IntentBench suite JSON, overriding --suite")
    s.add_argument("--suite", choices=["smoke", "mechanism"], default="smoke",
                   help="smoke tests the runner contract; mechanism runs real LIWM "
                        "against scope, poisoning, forgetting and transfer cases")
    s.add_argument("--adapter", choices=["liwm", "liwm-projection", "static-first"],
                   default="liwm-projection")
    s.add_argument("--scenario", default="longrunning-v1",
                   help="context-economics scenario id")
    s.add_argument("--split", choices=["dev", "holdout", "all"], default="dev",
                   help="retrieval split. Development reads dev; holdout is "
                        "reported once and a ranker tuned against it is no "
                        "longer evidence")
    s.add_argument("--no-intent", dest="no_intent", action="store_true",
                   help="ablate the intent cue, ranking by confidence alone")
    s.set_defaults(func=cmd_eval)

    s = sub.add_parser("study", help="manage opt-in local research exports")
    s.add_argument("action", choices=["status", "on", "off", "export",
                                      "rotate-key", "forget-key"])
    s.add_argument("--out")
    s.add_argument("--anonymise", action="store_true")
    s.add_argument("--longitudinal", action="store_true",
                   help="stable within-study pseudonyms and relative time, so "
                        "repeated measures join; implies --anonymise")
    s.add_argument("--study-id", dest="study_id",
                   help="name a rotated longitudinal key")
    s.set_defaults(func=cmd_study)

    s = sub.add_parser("schema", help="list or validate against shipped JSON schemas")
    s.add_argument("action", choices=["list", "validate"])
    s.add_argument("--file")
    s.add_argument("--name", default="user")
    s.set_defaults(func=cmd_schema)

    s = sub.add_parser("constitution", help="print the immutable invariants")
    s.add_argument("--full", action="store_true")
    s.set_defaults(func=cmd_constitution)

    s = sub.add_parser("events", help="inspect the event log")
    s.add_argument("action", choices=["stats", "verify", "tail"])
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--include-quarantined", action="store_true")
    s.set_defaults(func=cmd_events)

    return p


def _normalise_global_args(argv):
    """Allow ``--json`` and ``--home`` before or after a subcommand.

    Agents naturally write ``liwm context --json``.  Argparse otherwise accepts
    global options only before ``context``, an unnecessary integration trap.
    """
    values = list(sys.argv[1:] if argv is None else argv)
    front, rest = [], []
    i = 0
    while i < len(values):
        item = values[i]
        if item == "--json":
            front.append(item)
        elif item == "--home":
            if i + 1 >= len(values):
                rest.append(item)
            else:
                front.extend([item, values[i + 1]])
                i += 1
        elif item.startswith("--home="):
            front.append(item)
        else:
            rest.append(item)
        i += 1
    return front + rest


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(_normalise_global_args(argv))
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_USAGE
    try:
        return args.func(args) or EXIT_OK
    except KeyboardInterrupt:  # pragma: no cover
        return 130
    except SystemExit:
        raise
    except Exception as exc:
        if getattr(args, "json", False):
            sys.stdout.write(json.dumps({"error": str(exc),
                                         "type": type(exc).__name__}, indent=2) + "\n")
        else:
            sys.stderr.write("liwm: %s: %s\n" % (type(exc).__name__, exc))
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
