# Release Gates

Two gates exist: the public-release gate for the tooling, and the second-field-run gate that decides whether the normative protocol itself changes.

## Gate 1 — public release (tooling, v0.2 line → 0.3.0-rc.1 candidate)

All of the following must hold with receipts in the release ledger:

- [x] The founding bridge test suite passes unchanged (`python3 -m unittest tests.test_bridge`).
- [x] Every new suite passes on the maintainer machine and the CI matrix is defined in-tree (`.github/workflows/ci.yml`) — CI has not executed remotely yet; first remote run is a release-blocking receipt.
- [ ] One tagged release built from a clean clone passes: full unittest discovery, sanitization scan zero hits, skill validator pass on all five skill directories, generator `--check` clean.
  - Local leg done 2026-08-22 from an *untagged* local clean clone (tagging requires remote authorization) — see receipts below.
- [ ] A fresh-contributor smoke test: 60-second quick start executed verbatim on macOS plus at least one Linux.
  - macOS leg done 2026-08-22 — see receipts below; Linux leg still pending.
- [x] CLI lifecycle roundtrip proven in an isolated environment without touching any real system service (`tests/test_cli_lifecycle.py`).
- [x] Private-config preflight still usable against the live session API (receipt recorded in the v0.2 execution ledger).
- [ ] Security policy published with a private reporting channel that has been exercised once (canary report).
  - The sanitizer canary itself is now proven end to end (`tests/test_security_canary.py`: every rule trips on planted fixtures, public tree scans zero); the private reporting-channel exercise remains open.
- [x] README support matrix reviewed so no claim says "verified" without a linked receipt (reviewed 2026-08-22: **awaiting-remote** status introduced for remote CI; every verified row links its evidence).

Release is **blocked**, not merely discouraged, while any box above is open.

### Local receipts — run it-20260822-062100-6f09b4 (2026-08-22)

Recorded on the maintainer machine (macOS; Python 3.9.6 and 3.14.3), strictly before any remote execution:

- Full suite: `python3 -m unittest discover -s tests` → **120 tests, OK** on both 3.9.6 and 3.14.3 (working tree and clean clone alike); `python3 -m unittest tests.test_bridge` → the six founding tests pass unchanged.
- Sanitization: `python3 src/iron_triangle/sanitizer.py .` → `sanitization scan passed: 0 hits across all rules`; canary suite `python3 -m unittest discover -s tests -p 'test_security_canary.py'` → OK (all nine rules tripped on planted fixtures; CLI exits 1 on the canary repo, 0 on the public tree).
- Skills: `scripts/validate_skill.py` over all five skill directories → `all_ok=True`; `scripts/build_skills.py --check` → `generated skills are up to date`.
- Language policy receipts: `tests/test_language.py` (32 deterministic tests) covers Chinese titles/contracts/ledger/notification paths, task-constraint transfer, and byte-exact en compat; CLI smoke through a local fake session API read back window titles `[铁三角·执行] …` / `[铁三角·审查] …`.
- Clean clone + contributor smoke: `git clone <local-repo> <isolated-tmp>` at candidate commit `444e948`, then verbatim contributor path — unittest discovery (120 OK × two Pythons), sanitization scan (0 hits), skill validation (5/5 ok), generator `--check` (up to date), and `doctor` on a placeholder-substituted example config inside an isolated HOME (`ok: true`, launchd target) — all green. The clone's origin points at the local path only; no network remote was created.
- Live read-only: private-config `preflight` (`ok: true`, tier automatic) and `doctor --live` (`ok: true`, adapter probe pass) executed against the live session API; byte-size–mtime checks before and after show the private runtime config and the existing LaunchAgent plist untouched.
- Working tree clean; repository has no git remotes; only local commits exist (`351dea1`, `444e948`, plus this receipts commit).

### Remote release checklist (prepared, awaiting one authorization)

None of these steps has been executed. Each is a single command once the arbiter authorizes:

1. `git remote add origin <url> && git push -u origin main` — create the remote;
2. `git tag v0.3.0-rc.1 && git push origin v0.3.0-rc.1` — trigger the first CI run; a green ubuntu/macos/windows × 3.9/3.12 matrix is the release-blocking receipt;
3. cut the release from the tag with the CHANGELOG excerpt;
4. backfill the open boxes above with linked receipts.

Until then, local static workflow checks must never be presented as remote CI runs.

## Gate 2 — second field run (protocol evolution)

The founding evidence base is one four-day production run. Before the protocol text changes from `1.0-draft`, a second real run must exercise:

1. **Window rotation** — all three role windows replaced at a round boundary, with binding read-back receipts;
2. **Arbiter degradation** — the arbiter role operated by a weaker/cheaper model under pre-decision constraints, with quality deltas recorded;
3. **At least one incident class** from spec §11 recurring under the new controls, closed by receipt.

Outcomes feed three explicit open questions and nothing else until then:

- whether review independence degrades when all three roles share one vendor;
- the best default idle timeout across platforms (current default: heartbeat off);
- whether any of the ten mechanisms needs amendment.

Protocol changes outside this gate are rejected. Tooling releases (0.x) may continue independently as long as they keep the protocol text authoritative and untouched.

## Receipt conventions

Each checked box links: command, output summary (hash or count), artifact path, and who reproduced it. Reviewer reproduction per protocol §3.3 applies to every gate item before it counts.
