from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import autoforex.server.main as main_module
from autoforex.server.configuration import ServerConfigurationError


class TestServerEntrypoint:
    def test_builds_runs_and_stops_the_process_from_yaml_and_environment(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        events: list[Any] = []
        settings = object()
        application = object()

        def settings_factory(**kwargs: Any) -> object:
            events.append(("settings", kwargs))
            return settings

        process = SimpleNamespace(
            run=lambda: events.append("run"),
            stop=lambda: events.append("stop"),
        )
        monkeypatch.setattr(main_module, "load_server_settings", settings_factory)
        monkeypatch.setattr(
            main_module.ServerApplication,
            "build",
            lambda value: application if value is settings else None,
        )
        monkeypatch.setattr(
            main_module.ServerProcess,
            "create",
            lambda value: process if value is application else None,
        )

        main_module.main(
            [
                "--config",
                "/etc/autoforex/server.yaml",
                "--env-file",
                "/etc/autoforex/server.env",
            ]
        )

        assert events == [
            (
                "settings",
                {
                    "config_file": Path("/etc/autoforex/server.yaml"),
                    "environment_file": Path("/etc/autoforex/server.env"),
                },
            ),
            "run",
            "stop",
        ]

    def test_stops_the_process_when_run_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        events: list[str] = []
        process = SimpleNamespace(
            run=lambda: (_ for _ in ()).throw(RuntimeError("listener failed")),
            stop=lambda: events.append("stop"),
        )
        monkeypatch.setattr(main_module, "load_server_settings", lambda **kwargs: object())
        monkeypatch.setattr(main_module.ServerApplication, "build", lambda settings: object())
        monkeypatch.setattr(main_module.ServerProcess, "create", lambda application: process)

        with pytest.raises(RuntimeError, match="listener failed"):
            main_module.main([])

        assert events == ["stop"]

    def test_reports_configuration_errors_without_building_the_server(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def fail(**kwargs: Any) -> None:
            raise ServerConfigurationError("invalid test configuration")

        monkeypatch.setattr(main_module, "load_server_settings", fail)

        with pytest.raises(SystemExit) as raised:
            main_module.main([])

        assert raised.value.code == 2
        assert "invalid test configuration" in capsys.readouterr().err
