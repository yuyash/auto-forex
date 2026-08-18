# Notebooks Package Guide

`notebooks` is the JupyterLab environment for AutoForexV2 exploration,
analysis, and backtesting experiments.

## Responsibilities

- Provide an interactive environment for ad-hoc analysis and prototyping.
- Use `core` for domain logic, `server` for orchestration/task primitives, and
  `oanda` for OANDA communication.

## Boundaries

- Keep production logic out of notebooks; promote stabilized code into the
  appropriate package (`core`, `server`, `oanda`).
- This is an environment-only project (`package = false`); it is not published.

## Commit Policy

- Use Conventional Commits for all commits: `<type>(<scope>): <summary>`.
- Prefer the package name as the scope for package-local changes, for example
  `docs(notebooks): require conventional commits`.
- Use one of `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`,
  `build`, `ci`, `chore`, or `revert`.
- Keep summaries imperative, concise, and without a trailing period.
- For breaking changes, append `!` after the type/scope and include a
  `BREAKING CHANGE:` footer when more detail is needed.

## Commands

```bash
uv sync
uv run jupyter lab
uv run ruff check .
uv run ruff format .
uv run ty check
```
