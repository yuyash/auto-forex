# auto-forex-api

## Setup

```bash
uv sync
```

## Run

```bash
uv run auto-forex-api
```

The API serves `/api/health` on `http://127.0.0.1:8001`.

## Development

```bash
uv run export-openapi
uv run ruff check .
uv run ruff format .
uv run ty check
```

`uv run export-openapi` writes the FastAPI-generated OpenAPI schema to
`../openapi/openapi.yaml`.
