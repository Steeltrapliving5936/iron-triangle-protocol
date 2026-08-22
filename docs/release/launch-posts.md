# Launch Post Drafts (HN / Reddit / X)

*Draft copy only. Posting is the repository owner's decision and action — nothing here publishes anything. Replace `<owner>` with the real repository owner from [`github-metadata.md`](github-metadata.md) before posting; the repo-relative case-study link works on the published repository as-is. 草稿仅入库，发布动作由仓库所有者本人执行。*

## Hacker News — "Show HN"

**Title:**

```text
Show HN: Iron Triangle Protocol – an append-only paper trail that stops AI agents from claiming unverified "done"
```

**Body:**

We ran a production optimization task for four days with three model windows — one deciding, one executing, one independently verifying — held together by a single append-only ledger. Every claim needed a receipt a reviewer could reproduce; "done" without evidence was not done.

The protocol exists because of how that run broke. Seven failure classes showed up in four days, and the nastiest one wasn't a crash: internal health checks stayed green while the real user channel was broken. Internal probes falsely standing in for end-to-end acceptance is now a named failure class with a hard control — no milestone closes without the real channel probe.

The repo ships the protocol spec (v1.0-draft), a stdlib-only Python bridge with honest delivery states (accepted / rejected / unknown — a transport timeout escalates, it never blind-retries), generated agent skills for Codex / Claude Code / Kimi / Cursor, and a security canary that plants sanitizer-rule fixtures to prove the scanner actually trips.

Honest limits: one field run is the whole evidence base; remote CI hasn't had its first run yet; most platform adapters are marked experimental. The case study separates what the receipts prove from what remains explicitly open: [case study](https://github.com/<owner>/iron-triangle-protocol/blob/main/docs/case-study-founding-field-run.md).

Repo: https://github.com/<owner>/iron-triangle-protocol

## Reddit — r/LLMDevs (also fits r/LocalLLaMA with the same body minus the launch framing)

**Title:**

```text
After a 4-day unattended agent run failed in seven enumerable ways, we turned the post-mortem into a protocol: receipts or it didn't happen
```

**Body:**

The core problem: in long agentic tasks, the executing model claims success nobody verified, or drifts — and the chat transcript is the only record left. Reviews become summary-reading, incidents get buried, and an internal probe passing gets treated as "users are fine".

Iron Triangle Protocol (MIT) is what our four-day production run turned into: three pluggable model roles (arbiter with a `<2%` token budget — it actually measured 2.55%, and we published the miss; executor >90%; reviewer reproduces critical checks personally) plus an append-only ledger with two machine-readable markers (`NEEDS_ARBITER:` / `ROUND_CLOSURE_PASS:`). Pre-decided branches let work continue while the decider is offline — including the "executor API died mid-run" branch.

It's stdlib-only Python 3.9+, 60-second quick start, no account/signup:

git clone → `python3 -m unittest discover -s tests` → point a runtime config at your session API → `doctor`.

Case study with the seven observed failure classes and their controls (and an explicit list of which run details aren't public yet): docs/case-study-founding-field-run.md in the repo.

Repo: https://github.com/<owner>/iron-triangle-protocol

Not a framework or a vendor SDK — models are slots, the paper trail is the asset. Skepticism welcome: the support matrix marks everything not field-verified as experimental, and remote CI hasn't run yet.

## X (single post + optional follow-up thread)

**Post 1:**

```text
Long agent tasks fail the same boring ways: the executor claims unverified "done", the reviewer just summarizes it, internal probes stay green while the user path is broken.

We turned a real 4-day production run's post-mortem into a working protocol: append-only ledger, receipts, pre-decided branches, two escalation markers.

MIT, stdlib-only Python:
https://github.com/<owner>/iron-triangle-protocol
```

**Post 2 (thread):**

```text
The rule that cost us the most to learn: an internal service probe can never release a milestone. Only the real user-channel probe counts. That one is now mechanism #8, and closure fails without it.

Seven failure classes, ten controls, all traceable to the run:
https://github.com/<owner>/iron-triangle-protocol/blob/main/docs/case-study-founding-field-run.md
```

## Consistency notes

- All three drafts link the case study; HN/X use the expected canonical blob URL, Reddit uses the repo-relative path plus repo URL.
- No invented numbers: the figures used (four days / ~92 hours with role-level activity spans, seven failure classes, ten mechanisms, the `<2%`/`>90%` targets, and the measured 2.554832% arbiter share including the target miss) are all cited in the case study and its machine-readable receipt with public evidence.
- Remaining open questions (other failure-class instances, exact wall-clock bounds) stay framed as open questions — they are not blockers to describing the published evidence.
