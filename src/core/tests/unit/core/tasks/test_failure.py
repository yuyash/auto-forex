from autoforex.core import ErrorCategory, ErrorCode, ErrorDetails, TaskFailure


class TestFailure:
    def test_task_failure_of_defaults_to_task_category(self) -> None:
        failure = TaskFailure.of("something went wrong")

        assert failure.message == "something went wrong"
        assert failure.code == ErrorCode.TASK_FAILED
        assert failure.category == ErrorCategory.TASK
        assert failure.occurred_at.tzinfo is not None

    def test_task_failure_of_accepts_context_and_details(self) -> None:
        failure = TaskFailure.of(
            "risk limit exceeded",
            code=ErrorCode.RISK_LIMIT_EXCEEDED,
            category=ErrorCategory.RISK,
            where="RiskGate.check",
            details=ErrorDetails.of(limit="2%", attempted="5%"),
        )

        assert failure.where == "RiskGate.check"
        assert failure.details.get("limit") == "2%"
        assert "RiskGate.check" in str(failure)
        assert "risk_limit_exceeded" in str(failure)

    def test_task_failure_from_exception_captures_type_and_traceback(self) -> None:
        try:
            raise RuntimeError("kaboom")
        except RuntimeError as exc:
            failure = TaskFailure.from_exception(exc, where="runner")

        assert failure.message == "kaboom"
        assert failure.cause_type == "RuntimeError"
        assert "RuntimeError" in failure.traceback
        assert failure.where == "runner"

    def test_task_failure_from_exception_falls_back_to_class_name(self) -> None:
        failure = TaskFailure.from_exception(ValueError())

        assert failure.message == "ValueError"
        assert failure.cause_type == "ValueError"
