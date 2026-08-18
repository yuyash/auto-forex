"""Render and install OS service definitions for the server daemon."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from typing import ClassVar


class ServicePlatform(StrEnum):
    """Supported service-manager targets."""

    SYSTEMD = "systemd"
    LAUNCHD = "launchd"
    WINSW = "winsw"

    @classmethod
    def current(cls) -> ServicePlatform:
        """Detect the current host service platform."""
        system = platform.system().lower()
        if system == "linux":
            return cls.SYSTEMD
        if system == "darwin":
            return cls.LAUNCHD
        if system == "windows":
            return cls.WINSW
        raise RuntimeError(f"unsupported service platform: {system}")


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    """Inputs used to render one service-manager definition."""

    platform: ServicePlatform
    executable: Path
    configuration_file: Path
    environment_file: Path


class ServiceDefinitionRenderer:
    """Render bundled service templates with deployment paths."""

    _TEMPLATE_NAMES: ClassVar[dict[ServicePlatform, str]] = {
        ServicePlatform.SYSTEMD: "systemd.service",
        ServicePlatform.LAUNCHD: "launchd.plist",
        ServicePlatform.WINSW: "winsw.xml",
    }

    def render(self, definition: ServiceDefinition) -> str:
        """Return a rendered service definition."""
        template = (
            files("autoforex.server")
            .joinpath("service_definitions")
            .joinpath(self._TEMPLATE_NAMES[definition.platform])
            .read_text(encoding="utf-8")
        )
        return (
            template.replace("{{ executable }}", str(definition.executable))
            .replace("{{ configuration_file }}", str(definition.configuration_file))
            .replace("{{ environment_file }}", str(definition.environment_file))
        )


class ServiceDefinitionInstaller:
    """Install a rendered definition without implicit privilege escalation."""

    def __init__(self, renderer: ServiceDefinitionRenderer | None = None) -> None:
        self.renderer = renderer or ServiceDefinitionRenderer()

    def install(
        self,
        definition: ServiceDefinition,
        target: Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        """Write a service definition to an explicit target path."""
        if target.exists() and not overwrite:
            raise FileExistsError(f"service definition already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f"{target.suffix}.tmp")
        temporary.write_text(self.renderer.render(definition), encoding="utf-8")
        temporary.replace(target)
        return target

    @staticmethod
    def default_target(service_platform: ServicePlatform) -> Path:
        """Return the conventional target for a service manager."""
        if service_platform == ServicePlatform.SYSTEMD:
            return Path("/etc/systemd/system/auto-forex-server.service")
        if service_platform == ServicePlatform.LAUNCHD:
            return Path.home() / "Library/LaunchAgents/com.autoforex.server.plist"
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        return program_data / "AutoForex/auto-forex-server.xml"


class ServiceCli:
    """Command-line adapter for rendering and installing definitions."""

    def run(self, arguments: list[str] | None = None) -> int:
        """Execute the service-definition command."""
        parser = argparse.ArgumentParser(prog="auto-forex-server-service")
        parser.add_argument(
            "action",
            choices=("render", "install"),
        )
        parser.add_argument(
            "--platform",
            choices=tuple(ServicePlatform),
            default=ServicePlatform.current().value,
        )
        parser.add_argument(
            "--executable",
            type=Path,
            default=Path(shutil.which("auto-forex-server") or "auto-forex-server"),
        )
        parser.add_argument(
            "--configuration-file",
            type=Path,
            default=Path("auto-forex-server.yaml"),
        )
        parser.add_argument(
            "--environment-file",
            type=Path,
            default=Path("auto-forex-server.env"),
        )
        parser.add_argument("--target", type=Path)
        parser.add_argument("--overwrite", action="store_true")
        options = parser.parse_args(arguments)
        service_platform = ServicePlatform(options.platform)
        definition = ServiceDefinition(
            platform=service_platform,
            executable=options.executable,
            configuration_file=options.configuration_file,
            environment_file=options.environment_file,
        )
        installer = ServiceDefinitionInstaller()
        if options.action == "render":
            print(installer.renderer.render(definition), end="")
            return 0
        target = options.target or installer.default_target(service_platform)
        installer.install(definition, target, overwrite=options.overwrite)
        print(target)
        return 0


def main() -> None:
    """Run the service-definition CLI."""
    raise SystemExit(ServiceCli().run())


if __name__ == "__main__":
    main()
