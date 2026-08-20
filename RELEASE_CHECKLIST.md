# Release checklist

Release publishing remains a deliberate maintainer action. CI builds and checks
artifacts but never uploads to a package index.

- [ ] Working tree is clean and the release commit is reviewed.
- [ ] Package, schema, plugin, skill, adapter, changelog, and tag versions agree.
- [ ] `python tests/run_tests.py -v` passes on the supported Python/OS matrix.
- [ ] `python tools/validate_repo.py` passes, including provenance and private-state checks.
- [ ] Install/update/verify/repair/uninstall round trips pass in disposable host directories.
- [ ] Wheel and sdist are built twice with `SOURCE_DATE_EPOCH` set; wheel bytes
  match and normalized sdist file contents match (setuptools sdist gzip/tar
  metadata is not byte-reproducible).
- [ ] `python tools/check_release.py --dist dist --compare dist-repeat` passes.
- [ ] The built wheel installs on Python 3.9 and 3.14 from outside the checkout.
- [ ] The installed CLI passes `--version`, `schema list`, `init`, `doctor`, and `verify` smoke tests.
- [ ] The extracted sdist runs the test suite and contains no personal state.
- [ ] Concurrency/recovery, compaction equivalence, and 100k-event release benchmarks pass.
- [ ] Synthetic evaluation results are labelled synthetic; no human-study claim is implied.
- [ ] Release notes describe migrations, compatibility, known limitations, and artifact hashes.
- [ ] A draft release is inspected before the signed `v0.2.0` tag and artifacts are published.
