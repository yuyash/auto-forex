#!/usr/bin/env python3
"""Render a JUnit XML report as a GitHub Actions job summary."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TestResult:
    """One test case rendered in the summary table."""

    name: str
    status: str
    duration: float
    detail: str


def _duration(testcase: ET.Element) -> float:
    try:
        return float(testcase.get("time", "0"))
    except ValueError:
        return 0.0


def _problem(testcase: ET.Element) -> tuple[str, ET.Element] | None:
    for tag, status in (("failure", "FAIL"), ("error", "ERROR"), ("skipped", "SKIP")):
        problem = testcase.find(tag)
        if problem is not None:
            return status, problem
    return None


def _detail(problem: ET.Element) -> str:
    value = problem.get("message") or problem.text or ""
    line = next((item.strip() for item in value.splitlines() if item.strip()), "")
    if len(line) > 240:
        return f"{line[:237]}..."
    return line


def _test_result(testcase: ET.Element) -> TestResult:
    class_name = testcase.get("classname", "")
    test_name = testcase.get("name", "unknown test")
    name = f"{class_name}::{test_name}" if class_name else test_name
    problem = _problem(testcase)
    if problem is None:
        return TestResult(
            name=name, status="PASS", duration=_duration(testcase), detail=""
        )
    status, element = problem
    return TestResult(
        name=name,
        status=status,
        duration=_duration(testcase),
        detail=_detail(element),
    )


def _table_value(value: str) -> str:
    return value.replace("|", r"\|").replace("\r", "").replace("\n", "<br>")


def render_summary(report_path: Path, output_path: Path, *, title: str) -> None:
    """Append a human-readable JUnit report to a GitHub step summary."""
    lines = [f"## {title}", ""]
    if not report_path.exists():
        lines.append(
            "JUnit report was not generated. Check the preceding workflow steps."
        )
    else:
        root = ET.parse(report_path).getroot()
        results = [_test_result(testcase) for testcase in root.iter("testcase")]
        counts = {
            status: sum(result.status == status for result in results)
            for status in ("PASS", "FAIL", "ERROR", "SKIP")
        }
        duration = sum(result.duration for result in results)
        lines.extend(
            [
                "| Total | Passed | Failed | Errors | Skipped | Duration |",
                "| ---: | ---: | ---: | ---: | ---: | ---: |",
                (
                    f"| {len(results)} | {counts['PASS']} | {counts['FAIL']} | "
                    f"{counts['ERROR']} | {counts['SKIP']} | {duration:.3f}s |"
                ),
                "",
                "<details>",
                "<summary>Test cases</summary>",
                "",
                "| Status | Test | Duration | Detail |",
                "| :--- | :--- | ---: | :--- |",
            ]
        )
        lines.extend(
            (
                f"| {result.status} | {_table_value(result.name)} | "
                f"{result.duration:.3f}s | {_table_value(result.detail)} |"
            )
            for result in results
        )
        lines.extend(["", "</details>"])

    with output_path.open("a", encoding="utf-8") as output:
        output.write("\n".join(lines))
        output.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="E2E test report")
    args = parser.parse_args()
    render_summary(args.report, args.output, title=args.title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
