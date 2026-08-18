# Core Package Guide

`core` is the AutoForexV2 domain library.

## Responsibilities

- Provide reusable domain models, calculations, backtesting logic, and trading
  task primitives.
- Keep logic deterministic and testable where possible.
- Use `pydantic` for structured domain/config data and `numpy`/`pandas` for
  market data and backtesting workflows.

## Boundaries

- Do not depend on `api`, `server`, `web`, `openapi`, `protobuf`, or `oanda`.
- Do not perform network I/O, OANDA calls, FastAPI handling, or gRPC handling.
- Keep process orchestration outside this package.

## Compatibility Policy

- Do not preserve backward compatibility in this package at this stage.
- Do not add compatibility aliases, deprecated wrappers, legacy shims, or
  duplicate old/new APIs.
- When an API changes, update all call sites and tests to the new API and remove
  the old implementation outright.

## Type Policy

- Prefer domain objects, enums, and structured models over accepting both an
  object and its serialized `str` form.
- Do not type public or internal APIs as `SomeObject | str` unless the function
  is explicitly a parser/factory at a serialization boundary, or the value is
  inherently textual such as an external ID, file path, protocol field, or log
  field.
- When removing `str` inputs, update all call sites and tests to construct the
  object before calling the API.

## Commit Policy

- Use Conventional Commits for all commits: `<type>(<scope>): <summary>`.
- Prefer the package name as the scope for package-local changes, for example
  `docs(core): require conventional commits`.
- Use one of `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`,
  `build`, `ci`, `chore`, or `revert`.
- Keep summaries imperative, concise, and without a trailing period.
- For breaking changes, append `!` after the type/scope and include a
  `BREAKING CHANGE:` footer when more detail is needed.

## Commands

```bash
uv sync
uv run ruff check .
uv run ruff format .
uv run ty check
uv run pytest
```
