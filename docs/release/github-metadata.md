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

## Publication checklist — execution record (2026-08-22)

The public history is the orphan branch `public-main` pushed to `he62621-oss/iron-triangle-protocol` (public, default branch `main`, sanitizer-clean, no internal ancestors). The internal `main` and feature branches are **not** publishable history and must never leave this machine.

1. ✅ Repository created as public `he62621-oss/iron-triangle-protocol` (was verified absent before creation); canonical URL: `https://github.com/he62621-oss/iron-triangle-protocol`.
2. ✅ Description + topics applied exactly as above.
3. ⬜ **Social preview not uploaded yet** — maintainer UI action: Settings → Social preview → upload `docs/assets/social-preview.png`. GitHub caches previews; re-upload replaces it.
4. ✅ Public branch pushed via the explicit refspec `git push --no-tags origin public-main:main`. Forbidden forever: `--mirror`, `--all`, pushing `main`, `feature/*`, any other ref, or any refspec not exactly `public-main:main`. Tags are only ever pushed from an isolated public clone (never from this repository, whose private history must not leak through tag objects).
5. ✅ Remote release checklist executed — first all-green matrix run [32556149605](https://github.com/he62621-oss/iron-triangle-protocol/actions/runs/32556149605), tagged run [32557566761](https://github.com/he62621-oss/iron-triangle-protocol/actions/runs/32557566761), prerelease `v0.3.0-rc.1` published; see [`docs/release-gates.md`](../release-gates.md).
6. ⬜ Private-report canary drill — pending a non-owner reporter account (the official endpoint returns 403 for the owner by design); see [`docs/release-gates.md`](../release-gates.md) Gate 1.

HN/Reddit/X drafts in [`launch-posts.md`](launch-posts.md) remain **unpublished drafts**.
