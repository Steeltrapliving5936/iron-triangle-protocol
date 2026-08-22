# Security Policy

## Scope

This repository ships orchestration tooling that dispatches prompts between agent sessions you already control. It does **not** widen any model's permissions: deployment, destructive actions, and external communication stay bound by the user's own platform rules. The protocol states this normatively (protocol-spec §3.4); the code enforces it structurally — every private binding lives outside the repository.

## Reporting a vulnerability

GitHub's **private vulnerability reporting is enabled** for this repository (Security tab → "Report a vulnerability"). Do not open a public issue for exploitable behavior.

Include: affected command path, minimal reproduction, and observed vs expected delivery state. Responses target 7 days; releases for critical issues target 14 days.

## Design invariants worth attacking

These are load-bearing fail-closed properties. If you find a way to break one, that is a security report:

1. **Send success never impersonates receive.** Only a destination acknowledgement yields `accepted`; transport timeouts yield `unknown`, which must escalate, never auto-retry (`src/iron_triangle/policy.py`).
2. **Append-only streams stop on truncation.** A shrunken event stream or ledger suspends the run fail-closed (`src/iron_triangle/store.py`).
3. **One terminal event, one dispatch.** Replays and restarts must not duplicate prompts (`tests/test_conformance.py`).
4. **Crash residue never blind-resends.** An unresolved `pending_dispatch` after restart escalates to the arbiter outbox.
5. **No secrets in the public tree.** `src/iron_triangle/sanitizer.py` scans every tracked file; CI fails on hits.

## Secrets handling

- Runtime endpoints, token files, role bindings: private config file only (see `examples/runtime-config.example.json` placeholders). Copy it **outside** the repository.
- State directories contain task content and session identifiers; treat them as sensitive, per-user data with restrictive permissions.
- Desktop notifications contain only run id + event kind, never task text.

## Supported versions

Security fixes apply to the latest tagged release only. Config schema migrations keep older files readable across one major tool version.
