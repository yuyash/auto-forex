from autoforex.core.events import EventMessageKey, EventSeverity, EventType


class TestTypes:
    def test_event_type_defaults_model_severity_and_message_key(self) -> None:
        metadata = EventType.TASK_FAILED.metadata

        assert metadata.severity == EventSeverity.CRITICAL
        assert metadata.fatal is True
        assert EventType.TICK_RECEIVED.message_key == EventMessageKey.TICK_RECEIVED
