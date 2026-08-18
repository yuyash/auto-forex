#!/usr/bin/env python3
"""Verify built AutoForex wheels in isolated virtual environments."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WHEEL_NAMES = {
    "aws": "auto_forex_aws",
    "core": "auto_forex_core",
    "oanda": "auto_forex_oanda",
    "protobuf": "auto_forex_protobuf",
    "server": "auto_forex_server",
    "snowball": "auto_forex_snowball",
}

BASE_ASSERTIONS = """
from importlib.metadata import PackageNotFoundError, distribution, version
from importlib.util import find_spec
from importlib.resources import files

import autoforex.core
import autoforex.protobuf
import autoforex.server
import autoforex.snowball
from autoforex.protobuf.task.v1 import task_service_pb2
from autoforex.server.configuration import load_server_settings
from autoforex.server.discovery import ServiceInstance, ServiceInstanceStatus
from autoforex.server.optional import OptionalDependencyError, require_optional_dependency

for distribution_name in (
    "auto-forex-core",
    "auto-forex-protobuf",
    "auto-forex-server",
    "auto-forex-snowball",
):
    version(distribution_name)

for distribution_name, module in (
    ("auto-forex-aws", "autoforex.aws"),
    ("auto-forex-oanda", "autoforex.oanda"),
):
    try:
        version(distribution_name)
    except PackageNotFoundError:
        pass
    else:
        raise AssertionError(
            f"{distribution_name} must not be installed by the base server"
        )
    assert find_spec(module) is None

default_configuration = (
    files("autoforex.server").joinpath("default-config.yaml").read_text(encoding="utf-8")
)
assert 'persistence_backend: "sqlite"' in default_configuration
assert "service_discovery_enabled: false" in default_configuration
assert load_server_settings().port == 50051
assert ServiceInstanceStatus.SERVING.value == "serving"
assert ServiceInstance.__module__ == "autoforex.server.discovery"
assert (
    "ListServerInstances"
    in task_service_pb2.DESCRIPTOR.services_by_name["TaskService"].methods_by_name
)
server_scripts = {
    entry.name
    for entry in distribution("auto-forex-server").entry_points
    if entry.group == "console_scripts"
}
assert {
    "auto-forex-server",
    "auto-forex-server-config",
    "auto-forex-server-service",
} <= server_scripts

try:
    require_optional_dependency(
        "autoforex.oanda",
        extra="oanda",
        feature="OANDA provider support",
    )
except OptionalDependencyError as error:
    assert 'pip install "auto-forex-server[oanda]"' in str(error)
else:
    raise AssertionError("missing OANDA extra did not raise OptionalDependencyError")
"""

ALL_ASSERTIONS = """
from importlib.metadata import version

import psycopg
import autoforex.aws
import autoforex.core
import autoforex.oanda
import autoforex.protobuf
import autoforex.server
import autoforex.snowball

for distribution in (
    "auto-forex-aws",
    "auto-forex-core",
    "auto-forex-oanda",
    "auto-forex-protobuf",
    "auto-forex-server",
    "auto-forex-snowball",
):
    version(distribution)
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install built AutoForex wheels and verify package boundaries."
    )
    parser.add_argument(
        "dist_dir", type=Path, help="Directory containing built wheels."
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter or version passed to `uv venv`.",
    )
    return parser.parse_args()


def find_wheels(dist_dir: Path) -> dict[str, Path]:
    wheels: dict[str, Path] = {}
    for package, normalized_name in WHEEL_NAMES.items():
        matches = sorted(dist_dir.glob(f"{normalized_name}-*.whl"))
        if len(matches) != 1:
            raise RuntimeError(
                f"expected one wheel for {package}, found {len(matches)} in {dist_dir}"
            )
        wheels[package] = matches[0].resolve()
    return wheels


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def create_environment(path: Path, *, python: str) -> Path:
    run(["uv", "venv", str(path), "--python", python])
    return venv_python(path)


def install_base(python: Path, wheels: dict[str, Path]) -> None:
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            str(wheels["core"]),
            str(wheels["protobuf"]),
            str(wheels["snowball"]),
            str(wheels["server"]),
        ]
    )


def install_all(python: Path, wheels: dict[str, Path]) -> None:
    server_requirement = f"auto-forex-server[all] @ {wheels['server'].as_uri()}"
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            str(wheels["aws"]),
            str(wheels["core"]),
            str(wheels["oanda"]),
            str(wheels["protobuf"]),
            str(wheels["snowball"]),
            server_requirement,
        ]
    )


def verify(python: Path, assertions: str) -> None:
    run([str(python), "-I", "-c", assertions])


def main() -> None:
    args = parse_args()
    dist_dir = args.dist_dir.resolve()
    wheels = find_wheels(dist_dir)

    with tempfile.TemporaryDirectory(prefix="autoforex-wheels-") as temporary:
        root = Path(temporary)
        base_python = create_environment(root / "base", python=args.python)
        install_base(base_python, wheels)
        verify(base_python, BASE_ASSERTIONS)

        all_python = create_environment(root / "all", python=args.python)
        install_all(all_python, wheels)
        verify(all_python, ALL_ASSERTIONS)

    print("Built distributions passed isolated installation checks.")


if __name__ == "__main__":
    main()
