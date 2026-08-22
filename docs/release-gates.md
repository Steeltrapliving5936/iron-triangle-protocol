# Release Gates

Two gates exist: the public-release gate for the tooling, and the second-field-run gate that decides whether the normative protocol itself changes.

## Gate 1 — public release (tooling, v0.2 line → 0.3.0-rc.1 candidate)

All of the following must hold with receipts in the release ledger:

- [x] The founding bridge test suite passes unchanged (`python3 -m unittest tests.test_bridge`).
- [x] Every new suite passes on the maintainer machine and the CI matrix is defined in-tree (`.github/workflows/ci.yml`) — first remote runs completed 2026-08-22; the all-green matrix receipt is run [32556149605](https://github.com/he62621-oss/iron-triangle-protocol/actions/runs/32556149605) (the very first run [32555578161](https://github.com/he62621-oss/iron-triangle-protocol/actions/runs/32555578161) failed on Windows and surfaced two real portability defects, fixed in `956ce83`).
- [x] One tagged release built from a clean clone passes: full unittest discovery, sanitization scan zero hits, skill validator pass on all five skill directories, generator `--check` clean.
  - Done 2026-08-22: the tag was cut in a `--no-local --single-branch` clone of the published `main` (`52b7eb5`) after running the full gate set there (172 tests, bridge suite, sanitizer 0, security canary, validate 5/5, generator check).
- [x] A fresh-contributor smoke test: 60-second quick start executed verbatim on macOS plus at least one Linux.
  - Done 2026-08-22 as remote CI jobs `fresh-contributor-smoke` on ubuntu-latest and macos-latest (full quickstart path: tests, isolated-HOME config/doctor, sanitizer, five-skill validation, generator check, wall time printed) — run [32556149605](https://github.com/he62621-oss/iron-triangle-protocol/actions/runs/32556149605).
- [x] CLI lifecycle roundtrip proven in an isolated environment without touching any real system service (`tests/test_cli_lifecycle.py`).
- [x] Private-config preflight still usable against the live session API (receipt recorded in the v0.2 execution ledger).
- [x] Security policy published with a private reporting channel that has been exercised once (canary report).
  - Done 2026-08-22: the one-time canary drill was filed through GitHub private vulnerability reporting by a non-owner reporter, triaged, and closed the same day. Advisory record: `GHSA-h5p7-vmmc-mpxc`; drill receipt: `PVR-CANARY-20260822-R36` (private run ledger). The channel is exercised end to end; this box is closed.
- [x] README support matrix reviewed so no claim says "verified" without a linked receipt (reviewed 2026-08-22: **awaiting-remote** retired for remote CI after first green runs; every verified row links its evidence).

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

### Remote release execution (2026-08-22, authorized)

Executed against repository `he62621-oss/iron-triangle-protocol` (public), created empty and populated only via the explicit refspec `public-main:main --no-tags`; internal `main`/`feature/*` history never left this machine.

1. First push of the public genesis history: commit `edcb9f5` → run [32555578161](https://github.com/he62621-oss/iron-triangle-protocol/actions/runs/32555578161): ubuntu/macos × 3.9/3.12 + both smokes green; windows ×2 failed on two real portability defects (legacy-codepage JSON printing, `os.getuid()` in launchd plan rendering) — fixed in `956ce83`.
2. Run [32555851467](https://github.com/he62621-oss/iron-triangle-protocol/actions/runs/32555851467) @ `956ce83`: only remaining failure was the skill validator's POSIX-separator escape check — fixed in `440dece`.
3. Run [32556149605](https://github.com/he62621-oss/iron-triangle-protocol/actions/runs/32556149605) @ `440dece`: **all eight jobs green** (ubuntu/macos/windows × Python 3.9/3.12 + Ubuntu/macOS fresh-contributor smokes). This is the first fully green remote CI receipt.
4. Private vulnerability reporting enabled (`{"enabled": true}` read back); the one-time canary drill was completed and closed 2026-08-22 by a non-owner reporter (advisory `GHSA-h5p7-vmmc-mpxc`, receipt `PVR-CANARY-20260822-R36`), closing Gate 1's last exercised-channel requirement.
5. Tag/prerelease receipts: annotated tag `v0.3.0-rc.1` created in a `--no-local` clone of the published `main` and pushed alone; tag CI run [32557566761](https://github.com/he62621-oss/iron-triangle-protocol/actions/runs/32557566761) green @ `52b7eb5`; prerelease published at [releases/tag/v0.3.0-rc.1](https://github.com/he62621-oss/iron-triangle-protocol/releases/tag/v0.3.0-rc.1). Incident on the way: the first tag object leaked a real person name in its tagger field (the file sanitizer does not scan git objects); it was deleted and re-created with the generic maintainer identity, and a dedicated git-object metadata gate now covers this class.

The remote runs above are the receipts; local static workflow checks must still not be presented as remote CI runs.

### Git-object metadata gate

The file sanitizer only scans working-tree contents; commit author/committer identities and annotated-tag tagger identities live in git objects and leaked once through a tag. [`scripts/check_git_metadata.py`](../scripts/check_git_metadata.py) closes that blind spot: it parses every commit in the given range plus all annotated tags and applies the same desensitization rules to each identity field, exiting non-zero with a located report on any hit. It runs as the `metadata-gate` CI job (full history and tags) and locally before any push:

```bash
python3 scripts/check_git_metadata.py origin/main..public-main --tags
```

Regression canaries in `tests/test_release_assets.py` prove a generic maintainer identity passes while a personal name or `.local`-domain email fails.

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
