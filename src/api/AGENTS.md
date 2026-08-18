# API Package Guide

`api` is the server-side Web API process for AutoForexV2.

## Responsibilities

- Expose HTTP endpoints for `web`.
- Treat FastAPI route metadata in this package as the source of truth for the
  frontend-facing REST contract.
- Export the generated OpenAPI schema to `openapi/openapi.yaml` after route
  changes.
- Communicate with `server` over gRPC.
- Treat `protobuf` as the source of truth for gRPC messages and services.

## Boundaries

- Do not put trading task execution or OANDA access here; that belongs in
  `server`, `core`, or `oanda`.
- Do not define `.proto` files here.
- Do not manually edit `openapi/openapi.yaml` for API behavior changes; update
  FastAPI routes here and run `uv run export-openapi`.

## Commit Policy

- Use Conventional Commits for all commits: `<type>(<scope>): <summary>`.
- Prefer the package name as the scope for package-local changes, for example
  `docs(api): require conventional commits`.
- Use one of `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`,
  `build`, `ci`, `chore`, or `revert`.
- Keep summaries imperative, concise, and without a trailing period.
- For breaking changes, append `!` after the type/scope and include a
  `BREAKING CHANGE:` footer when more detail is needed.

## Commands

```bash
uv sync
uv run auto-forex-api
uv run export-openapi
uv run ruff check .
uv run ruff format .
uv run ty check
```
