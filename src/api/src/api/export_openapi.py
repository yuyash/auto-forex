from argparse import ArgumentParser
from pathlib import Path
from typing import Any

import yaml

from api.main import app


def default_output_path() -> Path:
    workspace_root = Path(__file__).resolve().parents[3]
    return workspace_root / "openapi" / "openapi.yaml"


def write_openapi_yaml(output_path: Path) -> None:
    schema: dict[str, Any] = app.openapi()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(schema, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def main() -> None:
    parser = ArgumentParser(description="Export FastAPI OpenAPI schema to YAML.")
    parser.add_argument(
        "--output",
        default=default_output_path(),
        type=Path,
        help="Path to write openapi.yaml.",
    )
    args = parser.parse_args()
    write_openapi_yaml(args.output)
