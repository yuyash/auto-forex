from pathlib import Path

import pytest

from autoforex.server.service import (
    ServiceCli,
    ServiceDefinition,
    ServiceDefinitionInstaller,
    ServiceDefinitionRenderer,
    ServicePlatform,
)


class TestServiceDefinitionRenderer:
    @pytest.mark.parametrize(
        "service_platform,expected",
        [
            (ServicePlatform.SYSTEMD, "ExecStart=/opt/autoforex/bin/auto-forex-server"),
            (ServicePlatform.LAUNCHD, "<string>/opt/autoforex/bin/auto-forex-server</string>"),
            (
                ServicePlatform.WINSW,
                "<executable>/opt/autoforex/bin/auto-forex-server</executable>",
            ),
        ],
    )
    def test_renders_each_supported_service_manager(
        self,
        service_platform: ServicePlatform,
        expected: str,
    ) -> None:
        rendered = ServiceDefinitionRenderer().render(
            ServiceDefinition(
                platform=service_platform,
                executable=Path("/opt/autoforex/bin/auto-forex-server"),
                configuration_file=Path("/etc/autoforex/server.yaml"),
                environment_file=Path("/etc/autoforex/server.env"),
            )
        )

        assert expected in rendered
        assert "/etc/autoforex/server.yaml" in rendered
        assert "/etc/autoforex/server.env" in rendered


class TestServiceDefinitionInstaller:
    def test_refuses_to_overwrite_without_explicit_permission(self, tmp_path: Path) -> None:
        target = tmp_path / "auto-forex-server.service"
        definition = ServiceDefinition(
            platform=ServicePlatform.SYSTEMD,
            executable=Path("/bin/auto-forex-server"),
            configuration_file=Path("/etc/autoforex/server.yaml"),
            environment_file=Path("/etc/autoforex/server.env"),
        )
        installer = ServiceDefinitionInstaller()

        installer.install(definition, target)

        with pytest.raises(FileExistsError):
            installer.install(definition, target)
        installer.install(definition, target, overwrite=True)

    @pytest.mark.parametrize(
        ("service_platform", "expected"),
        [
            (
                ServicePlatform.SYSTEMD,
                Path("/etc/systemd/system/auto-forex-server.service"),
            ),
            (
                ServicePlatform.LAUNCHD,
                Path.home() / "Library/LaunchAgents/com.autoforex.server.plist",
            ),
        ],
    )
    def test_returns_conventional_target_for_unix_service_managers(
        self,
        service_platform: ServicePlatform,
        expected: Path,
    ) -> None:
        assert ServiceDefinitionInstaller.default_target(service_platform) == expected

    def test_uses_program_data_for_windows_target(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("PROGRAMDATA", str(tmp_path))

        target = ServiceDefinitionInstaller.default_target(ServicePlatform.WINSW)

        assert target == tmp_path / "AutoForex/auto-forex-server.xml"


class TestServicePlatform:
    @pytest.mark.parametrize(
        ("system", "expected"),
        [
            ("Linux", ServicePlatform.SYSTEMD),
            ("Darwin", ServicePlatform.LAUNCHD),
            ("Windows", ServicePlatform.WINSW),
        ],
    )
    def test_detects_supported_host_platform(
        self,
        system: str,
        expected: ServicePlatform,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("autoforex.server.service.platform.system", lambda: system)

        assert ServicePlatform.current() == expected

    def test_rejects_unknown_host_platform(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("autoforex.server.service.platform.system", lambda: "Plan9")

        with pytest.raises(RuntimeError, match="unsupported"):
            ServicePlatform.current()


class TestServiceCli:
    def test_render_prints_definition_without_writing_a_file(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = ServiceCli().run(
            [
                "render",
                "--platform",
                "systemd",
                "--executable",
                "/opt/autoforex/bin/auto-forex-server",
                "--configuration-file",
                "/etc/autoforex/server.yaml",
                "--environment-file",
                "/etc/autoforex/server.env",
            ]
        )

        output = capsys.readouterr().out
        assert exit_code == 0
        assert (
            "ExecStart=/opt/autoforex/bin/auto-forex-server "
            "--config /etc/autoforex/server.yaml "
            "--env-file /etc/autoforex/server.env"
        ) in output

    def test_install_writes_the_explicit_target_and_reports_it(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        target = tmp_path / "auto-forex-server.service"

        exit_code = ServiceCli().run(
            [
                "install",
                "--platform",
                "systemd",
                "--target",
                str(target),
            ]
        )

        assert exit_code == 0
        assert target.exists()
        assert capsys.readouterr().out.strip() == str(target)
