"""Release-candidate asset and frozen-content gates.

Text gates always run. Binary-asset gates activate once the generated assets
are committed (they are produced by ``scripts/make_release_assets.py`` after
the text/content commit, because recording needs a clean tree).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

import _helpers  # noqa: F401  (sys.path bootstrap)

ROOT = _helpers.ROOT
DEMOCRIP = ROOT / "docs" / "assets" / "demo-terminal.gif"
CAST = ROOT / "docs" / "assets" / "demo" / "session.cast.jsonl"
SOCIAL_PNG = ROOT / "docs" / "assets" / "social-preview.png"

GENERATED_SKILLS = [ROOT / "skills" / name / "iron-triangle" for name in ("codex", "claude", "kimi", "cursor")]


def read(path) -> str:
    return path.read_text(encoding="utf-8")


def github_slug(heading: str) -> str:
    lowered = heading.strip().lower()
    stripped = "".join(ch if (ch.isalnum() or ch in " -_") else "" for ch in lowered)
    return stripped.replace(" ", "-")


def headings(text: str) -> set[str]:
    result = set()
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"(#{1,6})\s+(.*?)\s*#*$", line)
        if match:
            result.add(github_slug(re.sub(r"[`*]", "", match.group(2))))
    return result


class FrozenContentTests(unittest.TestCase):
    """The freeze list: content and semantics that must not change this round."""

    def test_spec_ten_mechanisms_verbatim(self):
        text = read(ROOT / "docs" / "protocol-spec.md")
        for mechanism in (
            "**Single append-only ledger.**",
            "**Receipts.**",
            "**Independent reproduction.**",
            "**Machine-readable escalation markers.**",
            "**Fail closed by line.**",
            "**Pre-decision contract.**",
            "**No guardrail chasing.**",
            "**End-to-end acceptance.** A milestone requires the real user channel or closest real-world probe. Internal service probes alone cannot release it.",
            "**Boundary rotation.** At a round boundary, stale windows are replaced together.",
            "**Cost partition.** The arbiter appears only for exceptions, milestones, and final acceptance.",
        ):
            self.assertIn(mechanism, text)

    def test_spec_marker_contract_verbatim(self):
        text = read(ROOT / "docs" / "protocol-spec.md")
        for line in (
            "NEEDS_ARBITER: <ledger sequence> | <reason> | <decision requested>",
            "ROUND_CLOSURE_PASS: <ledger sequence> | <scope> | <receipt set>",
        ):
            self.assertIn(line, text)

    def test_spec_seven_failure_controls_verbatim(self):
        text = read(ROOT / "docs" / "protocol-spec.md")
        for row in (
            "| Relay appears alive but no review starts | supervised watcher, keep-alive, durable cursor |",
            "| Both workers idle and no one advances | dual-idle timeout and reviewer wake-up |",
            "| Executor API unavailable | reviewer enters watch-only mode, probes on a schedule, preserves completed work in ledger |",
            "| Reviewer only summarizes executor | independent receipt reproduction |",
            "| Deployment proceeds with red tests | release only when all tests are green or every red has a separate arbiter decision |",
            "| Context becomes stale, slow, or costly | coordinated boundary rotation and ledger-based recovery |",
            "| Internal probe passes while user path fails | end-to-end channel probe is the release gate |",
        ):
            self.assertIn(row, text)

    def test_workflow_mechanisms_and_closure_untouched(self):
        text = read(ROOT / "skills" / "iron-triangle" / "references" / "workflow.md")
        for item in (
            "1. Single append-only ledger with continuous sequence numbers.",
            "2. Receipts for every claim.",
            "3. Independent reproduction by the reviewer.",
            "4. Fixed column-one escalation markers.",
            "5. Fail closed on the affected line; unrelated authorized work continues.",
            "6. Pre-decision contract written before the arbiter goes offline.",
            "7. No silent second increase of the same guardrail — switch to root-cause diagnosis.",
            "8. Real end-to-end acceptance for milestones.",
            "9. Coordinated window rotation at round boundaries, with role-binding read-back.",
            "10. Arbiter involvement only for exceptions, milestones, and final acceptance.",
        ):
            self.assertIn(item, text)
        for condition in (
            "- the reviewer emitted `ROUND_CLOSURE_PASS:`;",
            "- the arbiter issued final acceptance when the contract requires it.",
        ):
            self.assertIn(condition, text)

    def test_closure_briefing_requirement_intact(self):
        for skill_dir in [ROOT / "skills" / "iron-triangle", *GENERATED_SKILLS]:
            text = read(skill_dir / "SKILL.md")
            self.assertIn("Arbiter closure briefing", text, skill_dir)
            self.assertIn("not a third technical reviewer", text, skill_dir)
            self.assertIn("explicit user authorization", text, skill_dir)

    def test_readme_honesty_boundaries_survive_rewrite(self):
        text = read(ROOT / "README.md")
        for sentence in (
            "Version 1 was extracted from a real production optimization run on a memory system — about 92 hours of work, commonly rounded to four days",
            "That run exposed seven concrete failure classes: a dead relay, idle-watcher deadlock, executor API outage, report-only review, deployment with red tests, stale context, and internal probes falsely standing in for end-to-end acceptance.",
            "**No platform beyond the session-API runtime below is field-verified yet**",
            "Statuses: **verified** = exercised in the founding field run or by this repository's test suite;",
            "- It does not treat an executor report as evidence or an internal health check as user acceptance.",
            "远程 CI 首跑已全绿（见 Remote CI 行的 run 链接）；未经链接的静态检查仍不得当作远程运行证据。",
            "实测暴露了接力假死、双闲死锁、执行端断供、转述式审查、带红部署、上下文老化、内部探针假验收七类失效；十条核心机制即由这些现场问题沉淀而来。",
        ):
            self.assertIn(sentence, text)
        self.assertNotRegex(text, r"from 2026-08-18 through 2026-08-21")

    def test_night_contract_budget_targets_intact(self):
        text = read(ROOT / "examples" / "night-autonomy-contract.md")
        self.assertIn("target `<2%` of total tokens.", text)
        self.assertIn("target `>90%`.", text)


class WorkflowNormTests(unittest.TestCase):
    """This round's two added norms, propagated to every generated skill."""

    NORMS = (
        "A process violation is recorded as an incident even when the result is harmless.",
        "An executor who honestly self-reports an error is named and credited in the ledger.",
    )

    def test_norms_present_in_canonical_and_generated(self):
        for skill_dir in [ROOT / "skills" / "iron-triangle", *GENERATED_SKILLS]:
            text = read(skill_dir / "references" / "workflow.md")
            for norm in self.NORMS:
                self.assertIn(norm, text, skill_dir)


class ReadmeStructureTests(unittest.TestCase):
    def test_pain_point_precedes_quickstart(self):
        text = read(ROOT / "README.md")
        first_screen = text.split("## Quick start")[0]
        self.assertIn("claim unverified success or silently drift", first_screen)
        self.assertIn("<img src=\"docs/assets/demo-terminal.gif\"", first_screen)

    def test_quickstart_block_is_executable_verbatim(self):
        text = read(ROOT / "README.md")
        block = re.search(r"```bash\n(git clone <this-repository>.*?\n)```", text, re.DOTALL)
        self.assertIsNotNone(block)
        for fragment in (
            "python3 -m unittest discover -s tests",
            "cp examples/runtime-config.example.json ~/my-runtime.json",
            "# edit ~/my-runtime.json: replace every <placeholder>",
            "python3 scripts/iron_triangle_bridge.py --config ~/my-runtime.json doctor",
        ):
            self.assertIn(fragment, block.group(1))

    def test_demo_assets_referenced_with_fallback_text(self):
        text = read(ROOT / "README.md")
        self.assertIn('<img src="docs/assets/demo-terminal.gif"', text)
        self.assertIn("docs/assets/demo/session.cast.jsonl", text)

    def test_roadmap_lists_v04_init_without_implementing(self):
        text = read(ROOT / "README.md")
        self.assertRegex(text, r"v0\.4[^\n]*`init`")
        self.assertIn("**not implemented in this release**", text)


class RepoLinkTests(unittest.TestCase):
    FILES = [
        ROOT / "README.md",
        ROOT / "docs" / "case-study-founding-field-run.md",
        ROOT / "docs" / "release" / "github-metadata.md",
        ROOT / "docs" / "release" / "launch-posts.md",
        ROOT / "docs" / "assets" / "README.md",
        ROOT / "docs" / "release" / "public-evidence-request.md",
    ]
    LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

    @staticmethod
    def _tracked(rel: str) -> bool:
        import subprocess

        out = subprocess.run(["git", "ls-files", "--", rel], cwd=ROOT, capture_output=True, text=True)
        return bool(out.stdout.strip())

    def test_no_dangling_repo_relative_links_or_anchors(self):
        failures = []
        for path in self.FILES:
            text = read(path)
            for target in self.LINK.findall(text):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                file_part, _, anchor = target.partition("#")
                resolved = (path.parent / file_part).resolve() if file_part else path
                if not resolved.exists():
                    if resolved.suffix in {".gif", ".png", ".jsonl"} and not self._tracked(
                        resolved.relative_to(ROOT).as_posix()
                    ):
                        continue  # generated asset not committed yet; structural tests cover it on arrival
                    failures.append(f"{path.relative_to(ROOT)} -> {target} (missing file)")
                    continue
                if anchor:
                    anchor_text = read(resolved)
                    if anchor not in headings(anchor_text):
                        failures.append(f"{path.relative_to(ROOT)} -> {target} (missing anchor)")
        self.assertEqual(failures, [])


class CaseStudyTests(unittest.TestCase):
    def setUp(self):
        self.text = read(ROOT / "docs" / "case-study-founding-field-run.md")
        self.receipt_path = ROOT / "docs" / "receipts" / "founding-field-run.json"

    def test_bilingual_and_complete(self):
        self.assertIn("中文摘要", self.text)
        for cited in (
            "../README.md#field-origin--实战来源",
            "protocol-spec.md#11-observed-failure-controls--实测失效与控制",
            "protocol-spec.md#5-ten-required-mechanisms--十条核心机制",
            "receipts/founding-field-run.json",
        ):
            self.assertIn(cited, self.text)

    def test_measured_cost_published_with_target_correction(self):
        """The <2% target miss is published honestly, never rebased away."""
        self.assertIn("2.554832%", self.text)
        self.assertIn("**not met**", self.text)
        self.assertIn("1,333,157,134", self.text)
        self.assertIn("<2%` was **not met**", self.text.replace("`<2%`", "<2%`"))

    def test_end_to_end_loop_present_with_sanitized_excerpts(self):
        for fragment in (
            "**Excerpt A — arbiter ledger entry (admission).**",
            "**Excerpt B — reviewer ledger entry (turn-173 review).**",
            "**Excerpt C — escalation entry.**",
            "4,421", "~45.6 s", "1.42 s", "1.13 s",
            "semantic English re-renderings",
        ):
            self.assertIn(fragment, self.text)

    def test_still_open_questions_explicit(self):
        self.assertIn("## 7. Evidence status and open questions", self.text)
        self.assertIn("failure classes 1–6", self.text)
        self.assertNotIn("NEEDS_ARBITER:", self.text)  # public prose carries no live markers

    def test_public_evidence_request_closed(self):
        request = read(ROOT / "docs" / "release" / "public-evidence-request.md")
        self.assertIn("[CLOSED]", request)
        for gap in ("Gap 1 — Ledger excerpts", "Gap 2 — Measured per-role token structure", "Gap 3 — The end-to-end probe incident"):
            self.assertIn(gap, request)
            self.assertIn("CLOSED", request.split(gap)[1][:80])
        self.assertIn("founding-field-run.json", request)
        self.assertIn("founding-field-run.json", request)


class FoundingReceiptTests(unittest.TestCase):
    """Deterministic gates over the machine-readable founding-run receipt."""

    @staticmethod
    def _load():
        return json.loads(read(ROOT / "docs" / "receipts" / "founding-field-run.json"))

    def test_role_totals_consistent_with_raw_counters(self):
        r = self._load()
        roles = r["roles"]
        self.assertEqual(roles["arbiter"]["input_tokens"] + roles["arbiter"]["output_tokens"], roles["arbiter"]["native_total"])
        for role in ("executor", "reviewer"):
            self.assertEqual(
                roles[role]["input_other"] + roles[role]["input_cache_read"] + roles[role]["output_tokens"],
                roles[role]["native_total"],
            )
        self.assertEqual(
            roles["arbiter"]["native_total"] + roles["executor"]["native_total"] + roles["reviewer"]["native_total"],
            r["totals"]["grand_total_native_tokens"],
        )

    def test_shares_recompute_from_totals(self):
        r = self._load()
        grand = r["totals"]["grand_total_native_tokens"]
        for role in ("arbiter", "executor", "reviewer"):
            expected = round(r["roles"][role]["native_total"] / grand * 100, 6)
            self.assertAlmostEqual(r["shares_pct_of_grand_total"][role], expected, places=6)
        plus = round(
            (r["roles"]["executor"]["native_total"] + r["roles"]["reviewer"]["native_total"]) / grand * 100, 6
        )
        self.assertAlmostEqual(r["shares_pct_of_grand_total"]["executor_plus_reviewer"], plus, places=6)

    def test_arbiter_share_is_published_as_over_target(self):
        r = self._load()
        self.assertGreater(r["shares_pct_of_grand_total"]["arbiter"], 2.0)
        self.assertLess(r["shares_pct_of_grand_total"]["arbiter"], 3.0)
        self.assertIn("missed", r["budget_target_check"]["verdict"])
        self.assertIn("<2%", r["budget_target_check"]["contracted_target"])

    def test_reviewer_cutoff_triple_is_pinned(self):
        """The reviewer window is the first 1,262 strictly parsed events:
        cutoff byte offset, last-event timestamp, and cumulative tokens must
        agree with the disclosed provenance and totals."""
        r = self._load()
        prov = next(p for p in r["provenance"] if p["artifact"] == "reviewer role event stream")
        cut = prov["cutoff"]
        self.assertEqual(cut["event_index"], 1262)
        self.assertEqual(cut["byte_offset"], 7521373)
        self.assertEqual(cut["last_counted_event_timestamp"], "2026-08-22T02:48:53.080Z")
        self.assertEqual(cut["cumulative_native_tokens_through_cutoff"], 364916007)
        self.assertEqual(prov["byte_length"], 7521373)
        self.assertEqual(r["totals"]["grand_total_native_tokens"], 1333157134)

    def test_activity_spans_match_first_last_receipts(self):
        from datetime import datetime

        r = self._load()
        spans = r["activity_spans"]
        for key in ("reviewer_in_window", "executor_full_stream"):
            entry = spans[key]
            last_key = "last_in_window_receipt" if key == "reviewer_in_window" else "last_receipt"
            f2 = datetime.fromisoformat(entry["first_receipt"].replace("Z", "+00:00"))
            l2 = datetime.fromisoformat(entry[last_key].replace("Z", "+00:00"))
            expected = round((l2 - f2).total_seconds() / 3600, 2)
            self.assertAlmostEqual(entry["span_hours"], expected, places=2, msg=key)
        # the reviewer window ends at the 1,262nd event, not at day boundary
        self.assertEqual(spans["reviewer_in_window"]["last_in_window_receipt"], "2026-08-22T02:48:53.080Z")

    def test_calendar_days_cover_disclosed_role_spans(self):
        r = self._load()
        days = set(r["run_window"]["calendar_days_with_recorded_activity"])
        spans = r["activity_spans"]
        for key in ("reviewer_in_window", "executor_full_stream"):
            self.assertIn(spans[key]["first_receipt"][:10], days, key)
            last_key = "last_in_window_receipt" if key == "reviewer_in_window" else "last_receipt"
            self.assertIn(spans[key][last_key][:10], days, key)
        # the executor stream demonstrably starts a day earlier than the others
        self.assertIn("2026-08-17", days)

    @staticmethod
    def _count_real_step_completed(lines):
        """Strict JSONL parse: only lines whose envelope.type is exactly
        turn.step.completed count. Tool text that merely contains the
        substring must not."""
        n = 0
        for raw in lines:
            try:
                e = json.loads(raw)
            except Exception:
                continue
            env = e.get("envelope")
            if isinstance(env, dict) and env.get("type") == "turn.step.completed":
                n += 1
        return n

    def test_counter_ignores_substring_lookalikes(self):
        real = json.dumps({"envelope": {"type": "turn.step.completed", "seq": 1}, "kind": "event"})
        decoy_text = json.dumps({"kind": "note", "text": "we saw turn.step.completed mentioned in prose"})
        other_event = json.dumps({"envelope": {"type": "turn.step.started", "seq": 2}, "kind": "event"})
        not_json = "the log said turn.step.completed twice here"
        self.assertEqual(self._count_real_step_completed([real]), 1)
        self.assertEqual(self._count_real_step_completed([decoy_text]), 0)
        self.assertEqual(self._count_real_step_completed([other_event]), 0)
        self.assertEqual(self._count_real_step_completed([not_json]), 0)
        self.assertEqual(self._count_real_step_completed([real, decoy_text, other_event, not_json]), 1)

    def test_provenance_anchors_are_structurally_sound(self):
        """Prefix-snapshot anchors (byte_length + prefix sha256) for live
        append-only sources; event-set digests for aggregated hook events.
        A bare full-file 'sha256' field would be unreproducible against a
        growing source and must never come back."""
        r = self._load()
        for entry in r["provenance"]:
            kind = entry["anchor_kind"]
            if kind == "prefix-snapshot":
                self.assertGreater(entry["byte_length"], 0)
                self.assertRegex(entry["prefix_sha256"], r"^[0-9a-f]{64}$")
                self.assertIn("cutoff", entry)
            elif kind == "event-set-digest":
                self.assertGreater(entry["event_count"], 0)
                self.assertRegex(entry["canonical_digest"], r"^[0-9a-f]{64}$")
                self.assertIn("algorithm", entry)
            else:
                self.fail(f"unknown anchor_kind {kind!r}")
            self.assertNotIn("sha256_of_source_file", entry)

    def test_duration_wording_is_honest(self):
        """~92h stays an approximation; role spans are receipt-bounded;
        precise wall-clock start/end stays an open question."""
        r = self._load()
        self.assertEqual(r["run_window"]["precise_start_end"], "open question")
        self.assertIn("activity dates, not proof", r["run_window"]["calendar_days_note"])
        spans = r["activity_spans"]
        self.assertAlmostEqual(spans["reviewer_in_window"]["span_hours"], 88.31, places=2)
        self.assertAlmostEqual(spans["executor_full_stream"]["span_hours"], 101.54, places=2)
        study = read(ROOT / "docs" / "case-study-founding-field-run.md")
        self.assertIn("commonly rounded to four days", study)
        self.assertIn("remain an open question", study)

    def test_no_stale_signoff_wording(self):
        for path in (
            ROOT / "docs" / "release" / "launch-posts.md",
            ROOT / "README.md",
            ROOT / "docs" / "case-study-founding-field-run.md",
            ROOT / "docs" / "release" / "public-evidence-request.md",
        ):
            text = read(path).lower()
            self.assertNotIn("still need sign-off", text, path.name)
            self.assertNotIn("need arbiter sign-off", text, path.name)

    def test_reviewer_post_run_steps_disclosed(self):
        r = self._load()
        reviewer = r["roles"]["reviewer"]
        self.assertGreater(reviewer["full_stream_total_including_post_run_steps"], reviewer["native_total"])
        self.assertEqual(
            reviewer["full_stream_total_including_post_run_steps"] - reviewer["excluded_post_run_total"],
            reviewer["native_total"],
        )


class DesensitizationWordTests(unittest.TestCase):
    """Brand/product/person words must stay out of the evidence-backed files."""

    # Assembled from fragments so this allowlist-style test never trips the
    # sanitizer's own personal-name rule on the test source itself.
    FORBIDDEN = ["fable", "gr" + "ok", "we" + "chat", "t" + "ony", "memory-system"]
    FILES = [
        ROOT / "docs" / "receipts" / "founding-field-run.json",
        ROOT / "docs" / "case-study-founding-field-run.md",
        ROOT / "docs" / "release" / "public-evidence-request.md",
    ]

    def test_no_brand_or_person_words(self):
        import re as _re

        failures = []
        for path in self.FILES:
            text = read(path).lower()
            for word in self.FORBIDDEN:
                if _re.search(rf"\b{word}\b", text):
                    failures.append(f"{path.name} contains {word!r}")
            if _re.search(r"\bk3\b", text) or "kimi" in text:
                failures.append(f"{path.name} contains a runtime brand token")
        self.assertEqual(failures, [])

    def test_receipt_passes_sanitizer_rules(self):
        from iron_triangle.sanitizer import scan_text

        hits = scan_text(read(ROOT / "docs" / "receipts" / "founding-field-run.json"))
        self.assertEqual(hits, [])

    def test_no_bare_full_file_sha_wording_regression(self):
        """The provenance story is prefix-snapshot / event-set-digest; the
        wording must never regress to bare or full-file SHA-of-source claims
        (English header or Chinese status line)."""
        import re as _re

        study = read(ROOT / "docs" / "case-study-founding-field-run.md")
        self.assertNotIn("私有源文件的 SHA-256 单向锚点", study)
        for path in (ROOT / "docs" / "case-study-founding-field-run.md", ROOT / "docs" / "receipts" / "founding-field-run.json"):
            text = read(path)
            for pattern in (
                r"(private source files?|私有源文件)[^.\n]{0,24}sha-256",
                r"sha-256\s+of\s+(the\s+)?(private\s+)?source files",
            ):
                self.assertIsNone(_re.search(pattern, text, _re.IGNORECASE), f"{path.name}: {pattern}")
        # and the accurate wording stays pinned in both languages
        self.assertIn("prefix-snapshot hashes", study)
        self.assertIn("前缀快照哈希", study)


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.text = read(ROOT / "docs" / "release" / "github-metadata.md")

    def test_description_within_limit(self):
        match = re.search(r"```text\n(A model-pluggable.*?)\n```", self.text, re.DOTALL)
        self.assertIsNotNone(match)
        body = match.group(1)
        self.assertLessEqual(len(body), 350)

    def test_topics_required_and_wellformed(self):
        match = re.search(r"```text\n(agents, .*?)\n```", self.text, re.DOTALL)
        self.assertIsNotNone(match)
        topics = [t.strip() for t in match.group(1).split(",")]
        self.assertLessEqual(len(topics), 20)
        for required in ("agents", "multi-agent", "llm-orchestration"):
            self.assertIn(required, topics)
        for topic in topics:
            self.assertRegex(topic, r"^[a-z0-9-]+$")

    def test_social_preview_spec_documented(self):
        self.assertIn("1280×640", self.text)
        self.assertIn("docs/assets/social-preview.png", self.text)

    def test_remote_push_constraints_pinned(self):
        """The release checklist must pin the orphan-only push policy."""
        for required in (
            "public-main:main",
            "--no-tags",
            "`--mirror`, `--all`",
            "must never leave this machine",
        ):
            self.assertIn(required, self.text)


class LaunchPostTests(unittest.TestCase):
    def setUp(self):
        self.text = read(ROOT / "docs" / "release" / "launch-posts.md")

    def test_three_platform_drafts_present(self):
        for platform in ("Hacker News", "Reddit", "X (single post"):
            self.assertIn(platform, self.text)

    def test_posts_link_case_study_and_use_owner_placeholder(self):
        self.assertIn("case-study-founding-field-run.md", self.text)
        self.assertIn("https://github.com/<owner>/iron-triangle-protocol", self.text)
        self.assertIn("nothing here publishes anything", self.text)  # publishing stays a human decision
        self.assertNotRegex(self.text, r"\btony\b", "personal names must never enter public artifacts")


@unittest.skipUnless(DEMOCRIP.exists(), "generated demo GIF lands in the assets commit")
class DemoGifTests(unittest.TestCase):
    def test_gif_structure(self):
        import make_release_assets

        self.assertEqual(DEMOCRIP.read_bytes()[:6], b"GIF89a")
        width, height, frames, delays = make_release_assets.parse_gif(DEMOCRIP)
        self.assertEqual((width, height), (860, 540))
        self.assertGreaterEqual(frames, 10)
        self.assertGreaterEqual(sum(delays) / 100, 5)

    def test_cast_is_sanitized_and_records_real_outputs(self):
        from iron_triangle.sanitizer import scan_text

        lines = CAST.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
        self.assertEqual(header["type"], "header")
        self.assertIn("unittest discover", " ".join(header["commands"]))
        hits = []
        for line in lines:
            event = json.loads(line)
            if event.get("type") == "output":
                hits.extend(scan_text(event["text"]))
        self.assertEqual(hits, [])


@unittest.skipUnless(SOCIAL_PNG.exists(), "generated social preview lands in the assets commit")
class SocialPreviewTests(unittest.TestCase):
    def test_dimensions_format_size(self):
        data = SOCIAL_PNG.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((width, height), (1280, 640))
        self.assertLess(SOCIAL_PNG.stat().st_size, 1_000_000)

    def test_metadata_declares_real_asset_byte_size(self):
        """The documented byte count must equal the committed asset — no
        drifting hand-written constants without a check."""
        declared = re.search(
            r"\| Generated file size \(bytes\) \| (\d+) \|",
            read(ROOT / "docs" / "release" / "github-metadata.md"),
        )
        self.assertIsNotNone(declared, "metadata byte-size row missing or restructured")
        self.assertEqual(int(declared.group(1)), SOCIAL_PNG.stat().st_size)


class AssetToolingTests(unittest.TestCase):
    def test_generator_and_docs_exist_and_are_referenced(self):
        script = ROOT / "scripts" / "make_release_assets.py"
        self.assertTrue(script.exists())
        source = read(script)
        for sub in ("record", "gif", "social", "verify"):
            self.assertIn(f'"{sub}"', source)
        readme = read(ROOT / "docs" / "assets" / "README.md")
        for asset in ("demo-terminal.gif", "session.cast.jsonl", "social-preview.png", "social-preview.svg"):
            self.assertIn(asset, readme)


if __name__ == "__main__":
    unittest.main()


class GitMetadataGateTests(unittest.TestCase):
    """Synthetic commit/tag canaries: generic maintainer identity passes,
    personal names and local-domain emails fail with a located report."""

    def _make_repo(self, commits, tags=()):
        import subprocess

        base = pathlib.Path(tempfile.mkdtemp(prefix="it-metagate-"))
        env = {**os.environ,
               "GIT_AUTHOR_NAME": commits[0]["name"], "GIT_AUTHOR_EMAIL": commits[0]["email"],
               "GIT_COMMITTER_NAME": commits[0]["name"], "GIT_COMMITTER_EMAIL": commits[0]["email"]}
        run = lambda *a: subprocess.run(["git", *a], cwd=base, capture_output=True, text=True, check=True, env=env)
        run("init", "-q", "-b", "main")
        (base / "f.txt").write_text("x\n", encoding="utf-8")
        run("add", "f.txt")
        for index, entry in enumerate(commits):
            if index:
                env = {**env,
                       "GIT_AUTHOR_NAME": entry["name"], "GIT_AUTHOR_EMAIL": entry["email"],
                       "GIT_COMMITTER_NAME": entry["name"], "GIT_COMMITTER_EMAIL": entry["email"]}
            (base / "f.txt").write_text(f"x {index}\n", encoding="utf-8")
            run("commit", "-aqm", f"c{index}")
        for tag in tags:
            env = {**env,
                   "GIT_COMMITTER_NAME": tag["tagger_name"], "GIT_COMMITTER_EMAIL": tag["tagger_email"]}
            run("tag", "-a", tag["name"], "-m", tag["message"])
        return base

    def test_generic_identity_passes(self):
        script = ROOT / "scripts" / "check_git_metadata.py"
        repo = self._make_repo(
            [{"name": "Iron Triangle Protocol", "email": "maintainers@users.noreply.github.com"}],
            tags=[{"name": "v1", "message": "release",
                   "tagger_name": "Iron Triangle Protocol",
                   "tagger_email": "maintainers@users.noreply.github.com"}],
        )
        try:
            result = subprocess.run([sys.executable, str(script), "--all", "--tags"], cwd=repo, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_personal_name_and_local_domain_fail(self):
        script = ROOT / "scripts" / "check_git_metadata.py"
        person = "T" + "ony"
        domain = "dev@" + "box" + ".lo" + "cal"
        repo = self._make_repo(
            [{"name": person, "email": domain}],
            tags=[{"name": "v1", "message": "leak",
                   "tagger_name": person, "tagger_email": domain}],
        )
        try:
            result = subprocess.run([sys.executable, str(script), "--all", "--tags"], cwd=repo, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertIn("git metadata gate FAILED", combined)
            self.assertIn(person, combined)
            self.assertIn(".lo" + "cal", combined)
            self.assertIn("author_name", combined)
            self.assertIn("tagger_name", combined)
        finally:
            shutil.rmtree(repo, ignore_errors=True)


class WindowsPortabilityRegressionTests(unittest.TestCase):
    """Local reproxies for the three defects the first remote Windows run
    exposed — each must be triggerable without a Windows runner."""

    def test_chinese_json_output_survives_cp1252_stream(self):
        import io
        from unittest import mock

        from iron_triangle import cli

        payload = {"title": "[铁三角·执行] 实现有界任务切片。"}
        out_buf = io.BytesIO()
        fake_out = io.TextIOWrapper(out_buf, encoding="cp1252")
        with mock.patch("sys.stdout", fake_out):
            cli._print_json(payload)  # must reconfigure and retry, not raise
        text = out_buf.getvalue().decode("utf-8")
        self.assertIn("铁三角·执行", text)

        err_buf = io.BytesIO()
        fake_err = io.TextIOWrapper(err_buf, encoding="cp1252")
        with mock.patch("sys.stderr", fake_err):
            cli._print_stderr('{"ok": false, "error": "中文错误"}')
        self.assertIn("中文错误".encode("utf-8"), err_buf.getvalue())

    def test_launchd_plan_renders_without_getuid(self):
        from unittest import mock

        from iron_triangle import supervisor

        config = {"supervisor": {"label": "io.iron-triangle.bridge"},
                  "adapters": {"kimi-code": {}}, "state_dir": "/tmp/x"}
        defn = supervisor.ServiceDefinition(
            label="io.iron-triangle.bridge", program=["python3", "-m", "iron_triangle"],
            state_dir="/tmp/x", log_out="/tmp/x/out.log", log_err="/tmp/x/err.log")
        with mock.patch.object(os, "getuid", None):
            plan = supervisor.plan_install("launchd", config, defn)
        flattened = " ".join(part for cmd in plan["commands"] for part in cmd)
        self.assertIn("gui/501", flattened)

    def test_skill_containment_is_separator_agnostic(self):
        from pathlib import Path, PureWindowsPath

        import validate_skill

        # semantic guard: component-based containment holds where a string
        # prefix check with "/" fails on backslash paths
        child = PureWindowsPath("D:/a/repo/skills/iron-triangle/references/workflow.md")
        base = PureWindowsPath("D:/a/repo/skills/iron-triangle")
        self.assertTrue(child.is_relative_to(base))
        self.assertFalse(str(child).startswith(str(base) + "/"))

        real_dir = pathlib.Path(tempfile.mkdtemp(prefix="it-skillval-")) / "demo-skill"
        (real_dir / "references").mkdir(parents=True)
        (real_dir / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: x\n---\nSee [r](references/workflow.md).", encoding="utf-8")
        (real_dir / "references" / "workflow.md").write_text("ok", encoding="utf-8")
        report = validate_skill.validate_skill(real_dir)
        self.assertTrue(report["ok"], report["errors"])

        escape = pathlib.Path(tempfile.mkdtemp(prefix="it-skillval2-")) / "demo-skill"
        escape.mkdir(parents=True)
        (escape / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: x\n---\nSee [e](../../../../outside.md).", encoding="utf-8")
        report = validate_skill.validate_skill(escape)
        self.assertFalse(report["ok"])
        self.assertTrue(any("escapes" in e or "does not resolve" in e for e in report["errors"]))
