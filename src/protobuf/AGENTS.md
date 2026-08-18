# Protobuf Package Guide

`protobuf` owns the gRPC contract between `api` and `server`.

## Responsibilities

- Maintain `.proto` files for gRPC services and messages.
- Version service namespaces when making breaking contract changes.
- Provide tooling dependencies for generating Python gRPC stubs.

## Boundaries

- Do not put gRPC server implementation here; use `server`.
- Do not put gRPC client orchestration here; use `api`.
- Do not put REST/OpenAPI definitions here; use `openapi`.

## Commit Policy

- Use Conventional Commits for all commits: `<type>(<scope>): <summary>`.
- Prefer the package name as the scope for package-local changes, for example
  `docs(protobuf): require conventional commits`.
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
```

Generate Python stubs with:

```bash
uv run python -m grpc_tools.protoc \
  -I proto \
  --python_out=src \
  --pyi_out=src \
  --grpc_python_out=src \
  proto/autoforex/protobuf/task/v1/task_service.proto
```
