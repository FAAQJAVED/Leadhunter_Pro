# Contributing to LeadHunter Pro

Contributions are welcome. Please read the guidelines below before opening a pull request — they keep the codebase consistent and reviews fast.

## Running the test suite

```bash
pytest
```

All tests live under `tests/`. Run the full suite before pushing; CI will also run it automatically on every PR.

## Adding a new search engine

1. Create `engines/<engine_name>.py` and subclass `engine_base.EngineBase`.
2. Implement the `search(query: str, pages: int) -> list[SearchResult]` method.
3. Register the engine in `engines/__init__.py` by adding it to `ENGINE_MAP`:

   ```python
   from engines.myengine import MyEngine
   ENGINE_MAP["myengine"] = MyEngine
   ```

4. Add `"myengine"` to `ENGINES_PRIORITY` in `config.py` if it should run by default.
5. Add at least one HTML-parsing test in `tests/test_engines.py` (see existing tests for the pattern).

## Code style

The project uses **ruff** for linting and formatting (configured in `pyproject.toml`). Line length is **100 characters**.

```bash
ruff check .
ruff format .
```

Fix all ruff warnings before submitting. Do not suppress rules without a comment explaining why.

## Pull request guidelines

- **One PR per feature or fix.** Mixed-concern PRs are hard to review and harder to revert.
- **Reference the relevant issue** in the PR description (e.g. `Closes #42`).
- Keep commit messages short and imperative: `Add Ecosia engine`, `Fix Yahoo warmup retry logic`.
- If your change touches scraping logic, include a note on which engine/site was tested and what the result looked like.
