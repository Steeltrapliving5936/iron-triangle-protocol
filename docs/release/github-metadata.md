# GitHub Repository Metadata (Release Checklist)

*Suggested values for the public GitHub repository. Reviewing and applying them is a human/arbiter decision; nothing in this file performs a remote action. 应用本清单属于远程动作，须由仓库所有者或主控执行。*

## Description (≤350 chars)

```text
A model-pluggable operating protocol for long-running, production-facing AI work: arbiter, executor, and independent reviewer bound by an append-only ledger, receipts, red lines, and pre-decided branches — so unverified "done" cannot ship. Stdlib-only Python tooling included.
```

(278 characters.)

## Topics

Required by the release contract plus genuinely related ones (GitHub rules: lowercase letters/numbers/hyphens, ≤20 topics):

```text
agents, multi-agent, llm-orchestration, llm, ai-agents, orchestration, ai-safety, reliability, autonomous-agents, audit-trail, cli, python, developer-tools
```

Deliberately excluded: `agent-framework` (this is a protocol, not a framework), `mcp` (no MCP integration exists), anything implying benchmark results (none exist).

## Social preview

| Requirement | Value | Status |
|---|---|---|
| Recommended size | 1280×640 (2:1) | `docs/assets/social-preview.png` is exactly 1280×640 (checked by `tests/test_release_assets.py`) |
| Generated file size (bytes) | 92796 | must stay < 1 MiB; this declared value is asserted against the real file by `tests/test_release_assets.py` — regenerate the asset and update this row together, never by hand alone |
| Formats accepted | PNG or JPG | PNG |
| Content | protocol roles + budgets, real quick-start output lines; no marketing claims | source: `docs/assets/social-preview.svg` |

Upload path (remote, human-executed): repo → Settings → Social preview → upload `docs/assets/social-preview.png`. GitHub caches previews; re-upload replaces it.

## Post-creation checklist (remote, one authorization away)

The public history is the local orphan branch `public-main` (single genesis commit, sanitizer-clean, no internal ancestors). The internal `main` and feature branches are **not** publishable history and must never leave this machine.

1. Create the repository as `iron-triangle-protocol`; expected canonical URL used by launch posts: `https://github.com/<owner>/iron-triangle-protocol` (substitute the real owner at creation time).
2. Apply description + topics above.
3. Upload the social preview.
4. Push **only** the public branch, explicitly, with tags excluded:

   ```bash
   git push --no-tags <remote-url> public-main:main
   ```

   Forbidden forever: `--mirror`, `--all`, pushing `main`, `feature/*`, any other ref, or any refspec not exactly `public-main:main`. Tags must never be pushed from this repository (internal tags exist on private history).
5. Only then execute the remote release checklist in [`docs/release-gates.md`](../release-gates.md) (tagging/CI steps there apply to the public repository's own history once it exists remotely).

Until those steps are authorized and executed, this repository remains a local release candidate.
