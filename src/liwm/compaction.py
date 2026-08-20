"""Verified local event archives and checkpoints.

Compaction moves live event files into a gzip JSONL archive; it does not discard
history. EventStore reads archives transparently, so materialisation, rollback,
forget and explanations retain the same inputs and semantics.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from .jsonio import (
    FileLock, canonical_json, lifecycle_lock_path, sha256_of, utc_now,
    write_json_atomic,
)


def compact(store):
    events = store.events
    with FileLock(lifecycle_lock_path(store.home), timeout=60.0):
      with FileLock(events.lock_path, timeout=60.0):
        before = store.fold(_events_locked=True)
        paths = list(events._scan_paths())
        if not paths:
            return {"compacted": False, "reason": "no live events"}
        rows = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
        rows.sort(key=lambda row: int(row.get("sequence") or 0))
        first, last = rows[0]["sequence"], rows[-1]["sequence"]
        events.archive_root.mkdir(parents=True, exist_ok=True)
        archive = events.archive_root / ("events-%09d-%09d.jsonl.gz" % (first, last))
        with gzip.open(archive, "wt", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(canonical_json(row) + "\n")
        archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
        archives = list(events._archive_index().get("archives") or [])
        archives.append({
            "path": archive.name, "first_sequence": first, "last_sequence": last,
            "event_count": len(rows), "sha256": archive_hash,
        })
        checkpoint_root = Path(store.home) / "checkpoints"
        checkpoint_root.mkdir(parents=True, exist_ok=True)
        checkpoint = checkpoint_root / ("checkpoint-%09d.json" % last)
        body = {
            "schema_version": before["schema_version"], "created_at": utc_now(),
            "frontier": last, "event_count": len(rows), "archive": archive.name,
            "archive_sha256": archive_hash,
            "semantic_state_hash": sha256_of({
                "beliefs": before.get("beliefs"), "rejections": before.get("rejections"),
                "onboarding": before.get("onboarding"),
                "active_branch": before.get("materialized_from", {}).get("active_branch"),
            }),
        }
        body["integrity"] = {"algo": "sha256", "hash": sha256_of(body)}
        final_manifest = {
            "base_sequence": last, "event_count": 0, "last_sequence": last,
            "chain_head": None, "recent_event_ids": [],
        }
        events._write_transaction({
            "schema_version": before["schema_version"], "operation": "compact",
            "archive": archive.name,
            "checkpoint": str(checkpoint.relative_to(store.home)),
            "live_paths": [str(path.relative_to(events.root)) for path in paths],
            "old_archives": archives[:-1], "manifest": final_manifest,
        })
        events._write_archive_index(archives)
        write_json_atomic(checkpoint, body, fsync=True)

        for path in paths:
            path.unlink()
        for shard in events.shards():
            if not any(shard.iterdir()):
                shard.rmdir()
        events._write_manifest(final_manifest)
        events.transaction_path.unlink(missing_ok=True)

        verification = events.verify(_events_locked=True)
        if not verification["ok"]:
            raise ValueError("compaction verification failed")
        after = store.fold(_events_locked=True)
        semantic = lambda profile: {  # noqa: E731 - exact equivalence projection
            "beliefs": profile.get("beliefs"), "rejections": profile.get("rejections"),
            "onboarding": profile.get("onboarding"),
            "active_branch": profile.get("materialized_from", {}).get("active_branch"),
        }
        if semantic(before) != semantic(after):
            raise ValueError("materialisation changed during compaction")
        result = {"compacted": True, "events": len(rows), "frontier": last,
                  "archive": str(archive), "checkpoint": str(checkpoint),
                  "raw_history_retained": True}
    store.rebuild(reason="post_compaction")
    return result


def verify_checkpoints(home):
    problems = []
    checked = 0
    for path in sorted((Path(home) / "checkpoints").glob("checkpoint-*.json")):
        checked += 1
        row = json.loads(path.read_text(encoding="utf-8"))
        stored = (row.get("integrity") or {}).get("hash")
        body = {key: value for key, value in row.items() if key != "integrity"}
        if stored != sha256_of(body):
            problems.append({"path": str(path), "issue": "checkpoint_hash_mismatch"})
    return {"checked": checked, "problems": problems, "ok": not problems}
