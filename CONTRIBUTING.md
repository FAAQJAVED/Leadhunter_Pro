# Contributing to LeadHunter Pro

Contributions are welcome. Please read the guidelines below before opening a
pull request — they keep the codebase consistent and reviews fast.

## Getting started

```bash
git clone https://github.com/FAAQJAVED/Leadhunter_Pro.git
cd Leadhunter_Pro
pip install -r requirements.txt -r requirements-dev.txt
```

## Running the test suite

```bash
pytest tests/ --tb=short
```

All tests live under `tests/`. They require no browser and no internet
connection — the full suite completes in under 5 seconds. Run it before
pushing; CI will also run it automatically on every PR across 3 OS ×
3 Python versions.

## Code style

The project uses **ruff** for linting and formatting (configured in
`pyproject.toml`). Line length is  **100 characters** .

```bash
ruff check .
ruff format .
```

Fix all ruff warnings before submitting. Do not suppress rules without a
comment explaining why.

## Areas open for contribution

### 1 — Adding a new search engine

1. Create `engines/<engine_name>.py` and subclass `engine_base.EngineBase`.
2. Implement `search(query: str, pages: int) -> list[SearchResult]`.
3. Register the engine in `engines/__init__.py` → add it to `ENGINE_MAP`.
4. Add `"myengine"` to `ENGINES_PRIORITY` in `config.py` if it should run
   by default.
5. Add at least one HTML-parsing test in `tests/test_engines.py` (see
   existing tests for the pattern).

### 2 — Improving the data cleaning pipeline

The 10-step URL cleaning and scoring pipeline lives in
`pipeline/data_cleaner.py`. Common areas to improve:

* Expanding the `_ALWAYS_EXCLUDED` or `_DIRECTORY_DOMAINS` sets with newly
  identified junk domains.
* Tightening or loosening `SCORE_BOOST_KEYWORDS` in `config.py` for
  different industry verticals.
* Adding new flagging rules in `_assess()` for domain patterns observed
  in real runs.
* Adding regression tests in `tests/test_cleaner.py` for any new rule.

### 3 — Documentation and examples

* Improving or expanding `BLUEPRINT.md` with new architectural notes.
* Adding worked example queries and output screenshots to `Assets/`.
* Fixing typos or unclear wording in `README.md` or `CONTRIBUTING.md`.

## Pull request checklist

Before opening a PR, confirm all of the following:

* [ ] `pytest tests/ --tb=short` passes with zero failures
* [ ] `ruff check .` reports no errors
* [ ] `CHANGELOG.md` updated with a brief description of the change
* [ ] Commit message is short and imperative: `Add Ecosia engine`,
  `Fix Yahoo warmup retry logic`, `Expand directory domain blocklist`
* [ ] One PR per feature or fix — mixed-concern PRs are hard to review
  and harder to revert
* [ ] If the change touches scraping logic, include a note on which
  engine/site was tested and what the result looked like

Reference the relevant issue in the PR description (`Closes #42`).
