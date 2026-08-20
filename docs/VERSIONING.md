# Versioning

LIWM follows semantic versioning. Before 1.0, minor versions may change Python
APIs or schemas, but every persisted-schema change must include an explicit,
tested migration and changelog note. Patch releases preserve public APIs and
stored-data compatibility except when a security correction makes that
impossible; such exceptions are called out prominently.

Plugin manifests, Python package, schemas, skills metadata, and release tag use
the same base version. Codex local-development cachebuster suffixes are not
release versions.
