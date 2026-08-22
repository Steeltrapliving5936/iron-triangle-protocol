# Changelog

All notable changes to the Iron Triangle protocol tooling are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is [SemVer](https://semver.org/).

## [0.3.1] - 2026-08-23

Patch release fixing the released-version identity inconsistency of `v0.3.0`: the stable tag was cut from a tree whose runtime `TOOL_VERSION`, README status lines, skill manifests, recorded demo, and social preview still self-identified as `0.3.0-rc.1`, with the changes below still filed under *Unreleased*. History stays honest — the published `v0.3.0` and `v0.3.0-rc.1` tags/releases are preserved unchanged. This release unifies every current-state version source to `0.3.1`, dates these entries properly, and regenerates the derived skills and assets through their generators (no manual drift). No normative protocol change.

### Added

- Canonical skill operationalizes mechanism 10 (cost partition) without changing `docs/protocol-spec.md` (Gate 2 still owns normative protocol text): the arbiter produces ruling text only; executor and reviewer attach a ≤10-line decision-summary block; incidents do not exempt the budget; two consecutive arbiter execution-layer actions are a process incident. Documented bridge commands that start a run or record a ruling remain allowed. Private instance names, local marker aliases, and host paths stay out of the public tree.
- Model-safety receipts (R-5 audit follow-up): `launch` persists per-role receipts in run state — requested and applied model, explicit-vs-adapter-default source, requested and applied thinking effort with its source (`flag` / `adapter-config` / `model-default` / `none`), whether catalog resolution fell back to a label the request never named, and the run's independence level (`separate-sessions`, enforced by construction). No adapter read-back exists yet, so every receipt records `readback: unreadback`; nothing may claim an applied value was verified on the destination. `status` surfaces the same fields.

### Fixed

- Released-version identity reconciliation: all current-state sources now read `0.3.1` — runtime `TOOL_VERSION`, README status lines (EN/中文), the five skill manifests (canonical source + generator output), the CLI-lifecycle test expectation, and the regenerated terminal demo recording and social preview.
- `resume --ack-prompt-id` now reconciles the durable review round with the contract that was actually sent. Previously, when a reviewer dispatch landed in transport-unknown, the queued round bump was dropped and the manual ack restored only delivery bookkeeping — so the reviewer's legal per-contract decision (`decide --review-round N+1`) failed round validation forever. The dispatched round is persisted in `pending_dispatch` (`contract_review_round`) and restored on ack; legacy pending records without the field gain no guessed bump. Covered by a regression test that reproduces the failure and decides the recovered run to closure.
- README no longer describes `examples/night-autonomy-contract.md` as a filled sample; the file is and declares itself a template (`Status: template`).

## [0.3.0-rc.1] - 2026-08-22

Release candidate: Chinese-first run narration plus release-gate hardening. No normative protocol change. The first remote CI runs completed green across ubuntu/macos/windows × Python 3.9/3.12 plus Ubuntu/macOS fresh-contributor smokes; published as the tagged prerelease `v0.3.0-rc.1`.

### Added

- Run narration language policy with a single source of truth (`src/iron_triangle/i18n.py`): `zh-CN` and `en` catalogs; adding a language is a data change with no call-site edits. `launch --language` (or the private config's `language` key, default `en`) resolves once, is stored on the run record, and is read back by every narration site: role window titles, role system prompts, executor/reviewer contracts, ledger narration values, desktop notification summaries, and arbiter closure/stop summaries.
- Launch window-title control: `--title` plus per-role `--executor-title` / `--reviewer-title` explicit overrides; deterministic per-language default prefixes (`[IT EXEC]` / `[IT REVIEW]`, `[铁三角·执行]` / `[铁三角·审查]`).
- Automatic response language for ordinary users (no manual switch): one `response_language` per run resolved as explicit override > configured default > dominant task script (`detect_language`: zh-CN / en / ja / ko / ru) > en, stored on the run record, and jointly inherited by executor and reviewer — they never re-judge separately. Recognized languages without a static catalog keep English machine fields and role labels while both contracts carry an explicit reply-language directive; a mid-run switch is registered by the arbiter (`arbiter --decision continue --language <code>`), recorded in the ledger, and applies to both roles together.
- Arbiter closure briefing as a hard skill requirement: after every reviewer `closure-pass` or `needs-arbiter`, the arbiter's ruling must state side by side the executor claim, reviewer findings and role divergence, ruling with rationale, residual risks/open questions, recommended next step, and the continuation-authority basis (pre-decision-covered scope or explicit wait for user authorization). The arbiter is not a third technical reviewer and must not claim to have personally re-run checks; auto-continue stays inside pre-decision-covered scope. Shipped in canonical skill §Arbiter closure briefing plus a copy-paste template in `references/templates.md`.
- Security canary suite (`tests/test_security_canary.py`): a synthetic git repository plants one fixture per sanitizer rule; the full scan path (index discovery → file read → rule match → CLI exit 1) must trip every rule while the public tree scans zero via the CLI.
- Release-path integrity suite (`tests/test_release_gate.py`): every repository path referenced by `.github/workflows/ci.yml` and `docs/release-gates.md` must exist, the five skill directories are named, and the cross-version matrix is pinned — a rename can no longer silently break the first remote run.
- Canonical skill operating rule 7: follow the user's language; protocol fields and top-level markers stay identical in every language; third-party app native UI text is an **open question**.

### Changed

- The reviewer contract now carries the arbiter's task and constraints verbatim in both languages (in v0.2 only the executor contract did).
- Ledger narration values (launch, recover ack/retry, final acceptance, continuation, stop) follow the run's language; entry headers, the six field labels, and `Result` tokens stay protocol-fixed.

### Compatibility

- The `en` path is byte-identical to v0.2 output (golden tests lock the executor contract, reviewer contract, role system prompts, title prefixes, and policy escalation text).
- Runs and configs without any `language` information behave exactly as before; the original six bridge tests are unchanged and passing; config schema stays version 2 (`language` is an optional documented key).

## [0.2.0] - 2026-08-21

Cross-platform productization of the field-proven prototype. No normative protocol change.

### Added

- Canonical Agent-Skills-compatible skill source at `skills/iron-triangle/` (lean `SKILL.md`, `references/`, `assets/`) with a generator (`scripts/build_skills.py`) producing self-contained Codex / Claude Code / Kimi / Cursor adapters, and a stdlib validator (`scripts/validate_skill.py`).
- Controller-agnostic core: pure policy state machine (`src/iron_triangle/policy.py`), adapter boundary with capability tiers (`backend.py`), durable store, runner; the Kimi session-API client moves behind the boundary wire-compatibly.
- Honest delivery states end to end: only destination acknowledgement counts as `accepted`; rejection suspends the line; unknown state escalates and never blind-retries.
- Crash resume: unresolved `pending_dispatch` fails closed after restart; `resume --ack-prompt-id` / `--retry-new` record human-verified recovery in the ledger.
- Unified CLI surface on the existing entry point: `install`, `uninstall`, `doctor`, `repair`, `upgrade`, `version` alongside the original commands; `--dry-run` and `--target {launchd,systemd,windows-task}` plans that never touch a real system.
- Supervisor abstraction: launchd apply path (as before) plus deterministic systemd unit and Windows scheduled-task generation for offline testing.
- Versioned runtime-config contract: `schema_version: 2`, JSON Schema (`schemas/runtime-config.schema.json`), lossless v1→v2 migration with timestamped backup (`upgrade`).
- Optional dual-idle heartbeat (`idle_wake_seconds`, default off).
- Test suites: policy invariants, adapter conformance (platform-adapters §11), config/migration/schema alignment, isolated-HOME CLI lifecycle roundtrip, sanitization scan as a test, skill spec validation and generator idempotency.
- Cross-platform CI matrix (ubuntu/macos/windows × Python 3.9/3.12) — workflow ships in-tree; it has not run remotely yet.
- Docs: 60-second quick start, honest support matrix (verified/experimental/open question), CONTRIBUTING.md, SECURITY.md, release gates.

### Changed

- Bridge implementation reorganized from one monolithic script into `src/iron_triangle/`; `scripts/iron_triangle_bridge.py` remains the documented entry shim with identical command behavior.
- Runtime config example now carries `schema_version: 2` and a `supervisor` object; legacy flat keys migrate automatically in memory until `upgrade` persists them.

### Removed

- Hand-maintained per-platform `skills/<platform>/SKILL.md` files (replaced by generated `skills/<platform>/iron-triangle/`).

## [0.1.0] - 2026-08-21

- Initial public draft: generalized protocol spec, platform adapter guide, sanitized night-autonomy contract, three hand-written platform skills, and the single-file Codex→Kimi Code session bridge with supervised relay (preflight/models/sessions/launch/watch-once/daemon/decide/status/resume/arbiter/install) plus six bridge tests.
