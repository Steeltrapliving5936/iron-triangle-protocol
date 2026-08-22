# Public Evidence Request — Founding Field Run [CLOSED]

*Status: **closed**. All three gaps below were satisfied on 2026-08-22 by owner-approved extraction from private receipts, independently recomputed by the executor, and published as [`docs/receipts/founding-field-run.json`](../receipts/founding-field-run.json) with the completed narrative in [`docs/case-study-founding-field-run.md`](../case-study-founding-field-run.md). This file is kept as the record of what was requested and how it was closed. 状态：已闭合；本文件保留为取证请求与闭合方式的记录。*

## Gap 1 — Ledger excerpts from the run (2–3 entries): CLOSED

Delivered as semantic English re-renderings in the case study §4 (incident admission, turn-173 review entry, fail-closed escalation), sanitized per the rules this file originally specified: no paths, session ids, person/company names, or channel details; identifiers generalized; timestamps reduced to dates or relative order.

## Gap 2 — Measured per-role token structure: CLOSED

Delivered in the receipt (`roles`, `totals`, `shares_pct_of_grand_total`): raw counters per role, native totals, formulas, and cache subcounters documented as diagnostics-only. Headline correction published there and in the case study §5: the arbiter's contracted `<2%` target was missed — measured share is 2.554832%.

## Gap 3 — The end-to-end probe incident: CLOSED

Delivered as a complete loop (case study §4, receipt `end_to_end_incident`): breakage observation, arbiter admission and P0 classification, root cause (query-time full embedding of 4,421 surfaces, extrapolated ~45.6 s), fix (query-only embedding + prestored join + worker-maintained warmed index), independent reverification probes (1.42 s / 1.13 s), closure ruling.

## Still open questions

These were never part of the three gaps and remain explicitly open ([case study §7](../case-study-founding-field-run.md)):

- concrete instance receipts for failure classes 1–6;
- precise wall-clock anchors behind the ~92-hour approximation;
- per-step latency distribution across the whole run.
