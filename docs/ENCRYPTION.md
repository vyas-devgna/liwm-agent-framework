# Optional encryption design (not implemented in v0.1.0)

LIWM should eventually support at-rest encryption without making an agent hold a
long-lived plaintext key in prompts or configuration.

The proposed design uses one random data-encryption key per LIWM home, an AEAD
scheme (AES-256-GCM or XChaCha20-Poly1305), unique nonces, authenticated relative
paths/schema versions, and envelope wrapping through the OS credential store
(macOS Keychain, Windows Credential Manager/DPAPI, or Linux Secret Service).
Events remain separate encrypted envelopes so concurrent append is preserved.
Materialized views and backups are encrypted independently.

Requirements before implementation:

- audited cryptographic library rather than custom primitives;
- atomic key rotation and rollback;
- clear recovery-key/export workflow;
- no key in `config.json`, global instructions, logs, process arguments, or Git;
- test vectors and corruption/tamper tests on all three operating systems;
- documented behavior when the keyring is locked or unavailable.

Full-disk or encrypted-home protection is the recommendation for v0.1.0.
