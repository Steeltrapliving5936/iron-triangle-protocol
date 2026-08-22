"""Prompt builders for executor and reviewer dispatches.

Strings come from the language catalog in :mod:`iron_triangle.i18n`; the
``en`` entries are byte-identical to the original bridge text so existing
session behavior stays unchanged. The run record's ``language`` field
(defaulting to ``en`` for records created before the field existed) selects
the narration language; machine protocol fields inside the contracts — run
ids, paths, decision commands, and marker names — are identical everywhere.
"""

from __future__ import annotations

import pathlib
import shlex
import sys

from . import i18n
from .store import run_dir_from_record


def role_system_prompt(role: str, language: str = i18n.DEFAULT_LANGUAGE) -> str:
    key = "system_prompt_executor" if role == "executor" else "system_prompt_reviewer"
    return i18n.text(i18n.catalog_for(language), key)


def executor_prompt(run: dict) -> str:
    language = i18n.run_language(run)
    return i18n.text(
        i18n.catalog_for(language),
        "executor_contract",
        run_id=run["run_id"],
        cwd=run["cwd"],
        ledger_path=run["ledger_path"],
        task=run["task"],
        response_language_directive=i18n.response_directive(language),
    )


def reviewer_prompt(run: dict, bridge_path: pathlib.Path, config_path: pathlib.Path) -> str:
    decision_path = run_dir_from_record(run) / f"review-decision-{run['review_round']}.json"
    command_base = (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(bridge_path))} "
        f"--config {shlex.quote(str(config_path))} decide --run-id {shlex.quote(run['run_id'])} "
        f"--review-round {run['review_round']}"
    )
    # The reviewer contract must reference the round about to start.
    language = i18n.run_language(run)
    return i18n.text(
        i18n.catalog_for(language),
        "reviewer_contract",
        run_id=run["run_id"],
        review_round=run["review_round"],
        cwd=run["cwd"],
        ledger_path=run["ledger_path"],
        task=run["task"],
        command_base=command_base,
        decision_path=str(decision_path),
        response_language_directive=i18n.response_directive(language),
    )
