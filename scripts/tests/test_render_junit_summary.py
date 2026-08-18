import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "render_junit_summary.py"


def render_summary(report: Path, output: Path, *, title: str) -> None:
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(report),
            "--output",
            str(output),
            "--title",
            title,
        ],
        check=True,
    )


class TestRenderJunitSummary:
    def test_includes_totals_and_test_cases(self, tmp_path: Path) -> None:
        report = tmp_path / "report.xml"
        report.write_text(
            """\
<testsuites>
  <testsuite name="pytest" tests="4" failures="1" errors="1" skipped="1" time="1.0">
    <testcase classname="tests.test_api" name="test_passes" time="0.1" />
    <testcase classname="tests.test_api" name="test_fails" time="0.2">
      <failure message="expected 200 | received 500">traceback</failure>
    </testcase>
    <testcase classname="tests.test_api" name="test_errors" time="0.3">
      <error message="connection failed">traceback</error>
    </testcase>
    <testcase classname="tests.test_api" name="test_skips" time="0.4">
      <skipped message="market closed" />
    </testcase>
  </testsuite>
</testsuites>
""",
            encoding="utf-8",
        )
        output = tmp_path / "summary.md"

        render_summary(report, output, title="oanda E2E tests")

        summary = output.read_text(encoding="utf-8")
        assert "## oanda E2E tests" in summary
        assert "| 4 | 1 | 1 | 1 | 1 | 1.000s |" in summary
        assert "tests.test_api::test_passes" in summary
        assert "expected 200 \\| received 500" in summary
        assert "market closed" in summary

    def test_reports_missing_junit_file(self, tmp_path: Path) -> None:
        output = tmp_path / "summary.md"

        render_summary(tmp_path / "missing.xml", output, title="core E2E tests")

        summary = output.read_text(encoding="utf-8")
        assert "## core E2E tests" in summary
        assert "JUnit report was not generated" in summary
