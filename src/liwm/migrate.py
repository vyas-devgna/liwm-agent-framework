"""Schema migration and version compatibility.

Because ``user.json`` is folded from events, most migrations reduce to "upgrade
the event log if needed, then re-fold".  That keeps migrations small and makes
them verifiable: the post-migration profile must be exactly what folding
produces, and if it is not, something is wrong with the migration rather than
quietly wrong with the user's data.

Rules:

* migrations are ordered and idempotent;
* a backup is always taken first;
* an unknown *newer* schema version is refused rather than guessed at, so an
  older LIWM cannot corrupt a profile written by a newer one;
* unknown *fields* are preserved, not dropped.
"""

from __future__ import annotations

from pathlib import Path

from .jsonio import backup_file, read_json_resilient, utc_now, write_json_atomic

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "SUPPORTED_VERSIONS",
    "MigrationError",
    "needs_migration",
    "migrate_home",
    "version_tuple",
]

CURRENT_SCHEMA_VERSION = "0.4.0"

#: Every version this build knows how to read.
SUPPORTED_VERSIONS = ("0.1.0", "0.2.0", "0.3.0", "0.4.0")


class MigrationError(RuntimeError):
    """Raised when data cannot be safely migrated."""


def version_tuple(version):
    parts = str(version or "0.0.0").split(".")
    out = []
    for part in parts[:3]:
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def needs_migration(version):
    return version_tuple(version) < version_tuple(CURRENT_SCHEMA_VERSION)


def is_newer(version):
    return version_tuple(version) > version_tuple(CURRENT_SCHEMA_VERSION)


# ---------------------------------------------------------------------------
# Migration steps.  Each takes and returns a profile dict.  Register future
# versions here; the runner applies them in order.
# ---------------------------------------------------------------------------

def _noop(profile):
    return profile


MIGRATIONS = (
    # (from_version, to_version, function)
    ("0.1.0", "0.2.0", _noop),
    # 0.2 -> 0.3 is additive everywhere a profile is concerned. The new fields
    # live in the intent graph projection, in outcome and question-outcome
    # payloads, and in config, all of which are rebuilt or merged from
    # defaults. Nothing in user.json needs rewriting, and rewriting it anyway
    # would mean touching evidence in order to change a version string.
    ("0.2.0", "0.3.0", _noop),
    # 0.3 -> 0.4 changes nothing that is persisted. The release adds the
    # zero-memory gate, the capsule and the receipt, all of which act on
    # runtime_context.json -- a projection rebuilt from the log on demand,
    # never a store of record. user.json, the event log and the intent graph
    # are untouched.
    ("0.3.0", "0.4.0", _noop),
)


def migrate_profile(profile):
    """Apply every applicable migration step to a profile dict."""
    version = profile.get("schema_version", "0.0.0")
    if is_newer(version):
        raise MigrationError(
            "profile schema %s is newer than this LIWM build (%s); upgrade LIWM instead of "
            "downgrading the profile" % (version, CURRENT_SCHEMA_VERSION)
        )
    applied = []
    for from_v, to_v, func in MIGRATIONS:
        if version_tuple(version) == version_tuple(from_v):
            profile = func(profile)
            profile["schema_version"] = to_v
            version = to_v
            applied.append("%s->%s" % (from_v, to_v))
    if needs_migration(version):
        # No step exists but we are behind: safe because the fold is
        # authoritative, so just stamp and let a rebuild regenerate the shape.
        profile["schema_version"] = CURRENT_SCHEMA_VERSION
        applied.append("%s->%s (stamped; rebuild regenerates the shape)"
                       % (version, CURRENT_SCHEMA_VERSION))
    return profile, applied


def migrate_home(home, store=None):
    """Migrate every versioned document in a LIWM home directory."""
    home = Path(home)
    report = {"at": utc_now(), "home": str(home), "migrated": [], "skipped": [], "errors": []}

    if store is not None and not store.events.manifest_path.is_file() \
            and any(store.events._scan_paths()):
        # v0.1 had no deletion-detecting manifest. Create its v0.2 chain once,
        # under the append lock, before any new event is admitted.
        from .jsonio import FileLock
        with FileLock(store.events.lock_path, timeout=30.0):
            store.events._write_manifest(store.events._index_existing())
        report["migrated"].append({"file": "events-manifest.json", "steps": ["indexed v0.1 log"]})

    profile_path = home / "user.json"
    if profile_path.is_file():
        data, note = read_json_resilient(
            profile_path, backups_dir=home / "backups", logs_dir=home / "logs"
        )
        if data is None:
            report["errors"].append({"file": "user.json", "error": note})
        else:
            try:
                migrated, applied = migrate_profile(data)
            except MigrationError as exc:
                report["errors"].append({"file": "user.json", "error": str(exc)})
            else:
                if applied:
                    backup_file(profile_path, home / "backups", tag="pre-migration")
                    write_json_atomic(profile_path, migrated)
                    report["migrated"].append({"file": "user.json", "steps": applied})
                else:
                    report["skipped"].append("user.json (already %s)" % CURRENT_SCHEMA_VERSION)

    for name in ("metrics.json", "config.json", "runtime_context.json"):
        path = home / name
        if not path.is_file():
            continue
        data, _ = read_json_resilient(path, backups_dir=home / "backups", logs_dir=home / "logs")
        if not isinstance(data, dict):
            continue
        version = data.get("schema_version")
        if version and is_newer(version):
            report["errors"].append(
                {"file": name, "error": "written by a newer LIWM (%s)" % version}
            )
        elif version != CURRENT_SCHEMA_VERSION:
            backup_file(path, home / "backups", tag="pre-migration")
            data["schema_version"] = CURRENT_SCHEMA_VERSION
            write_json_atomic(path, data)
            report["migrated"].append({"file": name, "steps": ["stamped"]})
        else:
            report["skipped"].append("%s (already %s)" % (name, CURRENT_SCHEMA_VERSION))

    # The 0.3 intent graph carries effective confidence, effective ceiling and
    # recorded status, none of which a 0.2 file has. It is a projection, so the
    # migration is to rebuild it from the log rather than to patch fields into
    # it -- and rebuilding also applies the forget semantics the 0.2 graph did
    # not have, which is the point of the release.
    if (home / "intent-graph.json").is_file():
        try:
            from .intent_graph import IntentGraphStore
            backup_file(home / "intent-graph.json", home / "backups", tag="pre-migration")
            IntentGraphStore(home).rebuild()
            report["migrated"].append({"file": "intent-graph.json", "steps": ["rebuilt"]})
        except (OSError, ValueError) as exc:
            report["errors"].append({"file": "intent-graph.json", "error": str(exc)})

    if report["migrated"] and store is not None:
        store.events.record(
            "migration", "agent_inference",
            payload={"report": report, "to_version": CURRENT_SCHEMA_VERSION},
        )
        store.rebuild(reason="post_migration")
        report["rebuilt"] = True

    return report
