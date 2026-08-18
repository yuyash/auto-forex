from __future__ import annotations

from pathlib import Path

import pytest

from autoforex.server.configuration import (
    CONFIG_FILE_ENVIRONMENT_VARIABLE,
    ENV_FILE_ENVIRONMENT_VARIABLE,
    ConfigurationCli,
    ServerConfigurationError,
    load_server_settings,
    write_default_configuration,
)
from autoforex.server.settings import PersistenceBackend


class TestLoadServerSettings:
    def test_loads_yaml_and_expands_dotenv_and_process_environment(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        configuration = tmp_path / "server.yaml"
        configuration.write_text(
            "\n".join(
                (
                    'host: "${BIND_HOST}"',
                    'port: "${SERVER_PORT:-5100}"',
                    'database_url: "sqlite:///${DATABASE_FILE}"',
                    "csv_data_sources:",
                    "  history:",
                    "    tick_paths:",
                    '      - "${MARKET_DATA_ROOT}/USDJPY.csv"',
                )
            ),
            encoding="utf-8",
        )
        environment_file = tmp_path / "server.env"
        environment_file.write_text(
            "\n".join(
                (
                    "BIND_HOST=localhost",
                    "DATABASE_FILE=state.db",
                    "MARKET_DATA_ROOT=/var/lib/autoforex",
                    "AUTO_FOREX_SERVER_PORT=5200",
                )
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("AUTO_FOREX_SERVER_PORT", "5300")

        settings = load_server_settings(
            config_file=configuration,
            environment_file=environment_file,
        )

        assert settings.host == "localhost"
        assert settings.port == 5300
        assert settings.database_url == "sqlite:///state.db"
        assert settings.csv_data_sources["history"].tick_paths == (
            Path("/var/lib/autoforex/USDJPY.csv"),
        )

    def test_uses_environment_variables_to_select_configuration_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        configuration = tmp_path / "selected.yaml"
        configuration.write_text('host: "${BIND_HOST}"\nport: 5400\n', encoding="utf-8")
        environment_file = tmp_path / "selected.env"
        environment_file.write_text("BIND_HOST=localhost\n", encoding="utf-8")
        monkeypatch.setenv(CONFIG_FILE_ENVIRONMENT_VARIABLE, str(configuration))
        monkeypatch.setenv(ENV_FILE_ENVIRONMENT_VARIABLE, str(environment_file))

        settings = load_server_settings()

        assert settings.host == "localhost"
        assert settings.port == 5400

    def test_loads_the_packaged_default_configuration(self, tmp_path: Path) -> None:
        settings = load_server_settings(environment_file=tmp_path / "missing.env")

        assert settings.host == "127.0.0.1"
        assert settings.port == 50051
        assert settings.persistence_backend == PersistenceBackend.SQLITE

    @pytest.mark.parametrize(
        ("contents", "message"),
        [
            ("port: 5000\nport: 5001\n", "duplicate key"),
            ("- port\n- 5000\n", "root must be a mapping"),
            ("typoed_setting: true\n", "unknown server setting"),
        ],
    )
    def test_rejects_unsafe_or_mistyped_yaml(
        self,
        contents: str,
        message: str,
        tmp_path: Path,
    ) -> None:
        configuration = tmp_path / "invalid.yaml"
        configuration.write_text(contents, encoding="utf-8")

        with pytest.raises(ServerConfigurationError, match=message):
            load_server_settings(
                config_file=configuration,
                environment_file=tmp_path / "missing.env",
            )

    def test_reports_unset_environment_variable_and_setting_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        configuration = tmp_path / "server.yaml"
        configuration.write_text(
            'database_url: "sqlite:///${REQUIRED_DATABASE_FILE}"\n',
            encoding="utf-8",
        )
        monkeypatch.delenv("REQUIRED_DATABASE_FILE", raising=False)

        with pytest.raises(
            ServerConfigurationError,
            match=r"database_url.*REQUIRED_DATABASE_FILE",
        ):
            load_server_settings(
                config_file=configuration,
                environment_file=tmp_path / "missing.env",
            )

    def test_reports_cyclic_environment_references(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        configuration = tmp_path / "server.yaml"
        configuration.write_text('host: "${CYCLIC_HOST}"\n', encoding="utf-8")
        monkeypatch.setenv("CYCLIC_HOST", "${CYCLIC_HOST}")

        with pytest.raises(ServerConfigurationError, match="cyclic"):
            load_server_settings(
                config_file=configuration,
                environment_file=tmp_path / "missing.env",
            )

    def test_wraps_model_validation_errors_with_configuration_source(
        self,
        tmp_path: Path,
    ) -> None:
        configuration = tmp_path / "server.yaml"
        configuration.write_text("port: 70000\n", encoding="utf-8")

        with pytest.raises(
            ServerConfigurationError,
            match=r"invalid server configuration.*server\.yaml",
        ):
            load_server_settings(
                config_file=configuration,
                environment_file=tmp_path / "missing.env",
            )

    def test_wraps_malformed_environment_overrides(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        configuration = tmp_path / "server.yaml"
        configuration.write_text("{}\n", encoding="utf-8")
        monkeypatch.setenv("AUTO_FOREX_SERVER_CSV_DATA_SOURCES", "{not-json")

        with pytest.raises(
            ServerConfigurationError,
            match="invalid server environment overrides",
        ):
            load_server_settings(
                config_file=configuration,
                environment_file=tmp_path / "missing.env",
            )


class TestDefaultConfiguration:
    def test_writes_an_editable_copy_and_requires_explicit_overwrite(
        self,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "etc" / "server.yaml"

        result = write_default_configuration(target)

        assert result == target
        assert 'persistence_backend: "sqlite"' in target.read_text(encoding="utf-8")
        with pytest.raises(FileExistsError):
            write_default_configuration(target)
        write_default_configuration(target, overwrite=True)


class TestConfigurationCli:
    def test_initializes_and_validates_configuration(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        target = tmp_path / "server.yaml"
        cli = ConfigurationCli()

        assert cli.run(["init", "--target", str(target)]) == 0
        assert capsys.readouterr().out.strip() == str(target)
        assert cli.run(["validate", "--config", str(target)]) == 0
        assert capsys.readouterr().out.strip() == "configuration is valid"

    def test_reports_invalid_configuration_without_a_traceback(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        target = tmp_path / "invalid.yaml"
        target.write_text("unknown_setting: true\n", encoding="utf-8")

        with pytest.raises(SystemExit) as raised:
            ConfigurationCli().run(["validate", "--config", str(target)])

        assert raised.value.code == 2
        assert "unknown server setting" in capsys.readouterr().err
