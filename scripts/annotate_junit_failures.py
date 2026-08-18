#!/usr/bin/env python3
"""Emit GitHub Actions annotations for failures in a JUnit XML report."""

from __future__ import annotations

import argparse
import os
import xml.etree.ElementTree as ET
from pathlib import Path


def _escape_command(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    return _escape_command(value).replace(":", "%3A").replace(",", "%2C")


def _test_path(testcase: ET.Element, prefix: Path) -> str | None:
    path = testcase.get("file")
    if path:
        return str(prefix / path)

    parts = testcase.get("classname", "").split("::", maxsplit=1)[0].split(".")
    while parts:
        candidate = prefix / (os.sep.join(parts) + ".py")
        if candidate.exists():
            return str(candidate)
        parts.pop()
    return None


def annotate(report_path: Path, prefix: Path) -> int:
    if not report_path.exists():
        print(
            f"::error::JUnit report was not created: {_escape_command(str(report_path))}"
        )
        return 1

    root = ET.parse(report_path).getroot()
    failures = 0
    for testcase in root.iter("testcase"):
        problem = testcase.find("failure")
        if problem is None:
            problem = testcase.find("error")
        if problem is None:
            continue

        failures += 1
        test_name = testcase.get("name", "unknown test")
        message = problem.get("message") or problem.text or "Test failed"
        details = (problem.text or message).strip()
        properties = [f"title={_escape_property(test_name)}"]

        path = _test_path(testcase, prefix)
        if path:
            properties.append(f"file={_escape_property(path)}")
        line = testcase.get("line")
        if line and line.isdigit():
            properties.append(f"line={line}")

        print(f"::error {','.join(properties)}::{_escape_command(details)}")

    if failures == 0:
        print("::error::The E2E command failed without a JUnit failure or error entry.")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--prefix", type=Path, default=Path())
    args = parser.parse_args()
    return annotate(args.report, args.prefix)


if __name__ == "__main__":
    raise SystemExit(main())
