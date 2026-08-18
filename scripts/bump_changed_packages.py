#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

BUMPS = ("major", "minor", "patch")


@dataclass(frozen=True)
class Package:
    directory: str
    name: str
    pyproject: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bump workspace packages changed between two Git revisions."
    )
    parser.add_argument("--base", required=True, help="Base Git revision.")
    parser.add_argument("--head", default="HEAD", help="Head Git revision.")
    parser.add_argument(
        "--bump", choices=BUMPS, default="patch", help="Version component to bump."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report version updates without modifying files.",
    )
    return parser.parse_args()


def load_package(pyproject: Path) -> Package:
    with pyproject.open("rb") as file:
        project = tomllib.load(file)["project"]
    return Package(
        directory=pyproject.parent.name,
        name=project["name"],
        pyproject=pyproject,
    )


def discover_packages(root: Path) -> dict[str, Package]:
    return {
        package.directory: package
        for package in (
            load_package(pyproject)
            for pyproject in sorted((root / "src").glob("*/pyproject.toml"))
        )
    }


def changed_package_directories(root: Path, base: str, head: str) -> set[str]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--no-renames",
            base,
            head,
            "--",
            "src",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    directories: set[str] = set()
    for changed_path in result.stdout.splitlines():
        parts = PurePosixPath(changed_path).parts
        if len(parts) >= 3 and parts[0] == "src":
            directories.add(parts[1])
    return directories


def project_version(package: Package) -> str:
    with package.pyproject.open("rb") as file:
        return tomllib.load(file)["project"]["version"]


def bump_package(root: Path, package: Package, bump: str, dry_run: bool) -> None:
    command = [
        "uv",
        "version",
        "--package",
        package.name,
        "--bump",
        bump,
    ]
    if dry_run:
        command.append("--dry-run")
    else:
        command.append("--frozen")
    subprocess.run(command, cwd=root, check=True)


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    packages = discover_packages(root)
    changed_directories = changed_package_directories(root, args.base, args.head)
    changed_packages = [
        packages[directory]
        for directory in sorted(changed_directories)
        if directory in packages
    ]

    if not changed_packages:
        print("No package changes detected.")
        return

    print("Changed packages:")
    for package in changed_packages:
        previous_version = project_version(package)
        bump_package(root, package, args.bump, args.dry_run)
        next_version = previous_version if args.dry_run else project_version(package)
        suffix = " (dry run)" if args.dry_run else ""
        print(
            f"- {package.name}: {previous_version} -> "
            f"{next_version if not args.dry_run else f'next {args.bump} version'}{suffix}"
        )

    if not args.dry_run:
        subprocess.run(["uv", "lock"], cwd=root, check=True)


if __name__ == "__main__":
    main()
