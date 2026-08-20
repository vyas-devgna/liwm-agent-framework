"""User-controlled LIWM configuration with atomic, merge-preserving updates."""

from __future__ import annotations

from pathlib import Path

from .jsonio import (
    FileLock, backup_file, lifecycle_lock_path, read_json_resilient, utc_now,
    write_json_atomic,
)

SCHEMA_VERSION = "0.2.0"

DEFAULT_CONFIG = {
    "schema_version": SCHEMA_VERSION,
    "enabled": True,
    "default_mode": "auto",
    "learning_enabled": True,
    "onboarding_offered": False,
    "privacy": {
        "telemetry": "disabled",
        "store_free_text": False,
        "redact_exports_by_default": False,
    },
    "questioning": {"max_questions_per_session": 12, "never_ask_about": []},
    "retention": {"backup_count": 60},
    "study": {"enabled": False, "retention_days": 90,
              "enabled_at": None, "start_sequence": None},
    "hosts": {},
}


def _merge_defaults(target, defaults):
    result = dict(target or {})
    for key, value in defaults.items():
        if isinstance(value, dict):
            result[key] = _merge_defaults(result.get(key), value)
        else:
            result.setdefault(key, value)
    return result


class ConfigStore:
    """Read and update ``config.json`` without dropping installer-owned fields."""

    def __init__(self, home):
        self.home = Path(home)
        self.path = self.home / "config.json"
        self.backups = self.home / "backups"
        self.logs = self.home / "logs"
        self.lock_path = self.home / "config.json.lock"

    def load(self, persist=False):
        data, _ = read_json_resilient(
            self.path, backups_dir=self.backups, logs_dir=self.logs, default=None
        )
        merged = _merge_defaults(data, DEFAULT_CONFIG)
        if persist and data != merged:
            self.save(merged)
        return merged

    def save(self, config):
        with FileLock(lifecycle_lock_path(self.home)):
            with FileLock(self.lock_path):
                return self._save_locked(config)

    def _save_locked(self, config):
        backup_file(self.path, self.backups, tag="config")
        current, _ = read_json_resilient(
            self.path, backups_dir=self.backups, logs_dir=self.logs, default={}
        )
        merged = _merge_defaults(dict(current or {}, **dict(config)), DEFAULT_CONFIG)
        merged["schema_version"] = SCHEMA_VERSION
        merged["updated_at"] = utc_now()
        write_json_atomic(self.path, merged)
        return merged

    def set(self, key, value):
        allowed = {
            "enabled", "default_mode", "learning_enabled", "onboarding_offered",
            "privacy.store_free_text", "privacy.redact_exports_by_default",
            "questioning.max_questions_per_session", "questioning.never_ask_about",
            "retention.backup_count",
            "study.enabled", "study.retention_days",
        }
        if key not in allowed:
            raise ValueError("unsupported config key %r" % key)
        if key in {"enabled", "learning_enabled", "onboarding_offered",
                   "privacy.store_free_text", "privacy.redact_exports_by_default"}:
            if not isinstance(value, bool):
                raise ValueError("%s must be true or false" % key)
        if key == "default_mode" and value not in {"auto", "low", "medium", "high", "off"}:
            raise ValueError("default_mode must be auto, low, medium, high, or off")
        if key in {"questioning.max_questions_per_session"} \
                and (not isinstance(value, int) or not 0 <= value <= 30):
            raise ValueError("%s must be an integer from 0 to 30" % key)
        if key in {"retention.backup_count"} \
                and (not isinstance(value, int) or value < 1):
            raise ValueError("%s must be a positive integer" % key)
        if key == "study.enabled" and not isinstance(value, bool):
            raise ValueError("study.enabled must be true or false")
        if key == "study.retention_days" \
                and (not isinstance(value, int) or not 1 <= value <= 3650):
            raise ValueError("study.retention_days must be an integer from 1 to 3650")
        if key == "questioning.never_ask_about" \
                and (not isinstance(value, list) or not all(isinstance(v, str) for v in value)):
            raise ValueError("questioning.never_ask_about must be a JSON array of dimensions")
        with FileLock(lifecycle_lock_path(self.home)):
            with FileLock(self.lock_path):
                data = self.load()
                target = data
                parts = key.split(".")
                for part in parts[:-1]:
                    target = target.setdefault(part, {})
                target[parts[-1]] = value
                return self._save_locked(data)

    def register_host(self, host, metadata):
        if not host or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in host):
            raise ValueError("host must be a lowercase safe identifier")
        with FileLock(lifecycle_lock_path(self.home)):
            with FileLock(self.lock_path):
                data = self.load()
                data.setdefault("hosts", {})[host] = dict(
                    metadata, installed=True, updated_at=utc_now()
                )
                return self._save_locked(data)

    def remove_host(self, host):
        with FileLock(lifecycle_lock_path(self.home)):
            with FileLock(self.lock_path):
                data = self.load()
                removed = data.setdefault("hosts", {}).pop(host, None)
                self._save_locked(data)
                return removed
