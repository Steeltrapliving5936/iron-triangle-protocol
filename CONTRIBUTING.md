# Contributing

Thanks for considering a contribution. This project treats evidence the same way its protocol does: claims need receipts.

## Ground rules

- **Python 3.9+, standard library only.** The bridge must run on a bare system Python. Do not add runtime dependencies without a written rationale in the PR.
- **Tests are stdlib `unittest`.** Every behavior change ships with tests. Run:

  ```bash
  python3 -m unittest discover -s tests -v
  ```

- **Sanitization is a hard gate.** Never commit real endpoints, tokens, absolute personal paths, session/memory identifiers, employer names, or internal hostnames. CI runs `src/iron_triangle/sanitizer.py .`; run it locally before pushing.
- **Generated files are not hand-edited.** Platform skills under `skills/<platform>/iron-triangle/` come from `scripts/build_skills.py`; edit `skills/iron-triangle/` and regenerate. CI fails on stale output (`build_skills.py --check`).
- **Honest status labels.** Anything not exercised against a real platform is *experimental*; anything without a verified mechanism is an **open question**. Keep the README support matrix and docs in that vocabulary.

## Development layout

```
src/iron_triangle/     core package (policy, store, backends, supervisors, CLI)
scripts/               stable entry shim + skill generator/validator
skills/iron-triangle/  canonical Agent Skills source
schemas/               versioned JSON Schema for runtime config
tests/                 stdlib unittest suite
docs/                  normative protocol and guides
```

## Config changes

The private runtime config is a versioned contract:

1. bump `CONFIG_SCHEMA_VERSION` in `src/iron_triangle/__init__.py`;
2. extend `migrate_config` so older files upgrade losslessly (with backup);
3. update `schemas/runtime-config.schema.json`;
4. add migration tests mirroring `tests/test_config_schema.py`.

## Adapter contributions

New controller backends implement `BridgeBackend` (see `src/iron_triangle/backend.py`) and pass the conformance checklist in `docs/platform-adapters.md` §11 via tests like `tests/test_conformance.py`. A backend that cannot acknowledge delivery must return the honest three-valued `Delivery` (`accepted` / `rejected` / `unknown`) — never fake acceptance.

## Failing closed

If your change touches dispatch, dedup, truncation, or recovery semantics, add the fail-closed test first. Silent guardrail increases are rejected by policy: the second insufficiency of any protective limit requires root-cause diagnosis, not a bigger number.

## Submitting

Small slices beat large ones. Each PR states: the falsifiable claim, the tests that prove it, and any behavior intentionally left unchanged.
