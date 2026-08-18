"""Load, validate, and materialize server YAML configuration."""

from __future__ import annotations

import argparse
import os
import re
from collections.abc import Mapping, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any, Final

import yaml
from dotenv import dotenv_values
from pydantic import ValidationError
from pydantic_settings import DotEnvSettingsSource, EnvSettingsSource, SettingsError
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver

from autoforex.server.settings import ServerSettings

DEFAULT_CONFIG_FILENAME: Final = "default-config.yaml"
CONFIG_FILE_ENVIRONMENT_VARIABLE: Final = "AUTO_FOREX_SERVER_CONFIG_FILE"
ENV_FILE_ENVIRONMENT_VARIABLE: Final = "AUTO_FOREX_SERVER_ENV_FILE"
_ENVIRONMENT_REFERENCE = re.compile(
    r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}"
)
_MAXIMUM_EXPANSION_PASSES: Final = 20


class ServerConfigurationError(ValueError):
    """Raised when server configuration cannot be loaded or validated."""


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
    *,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _deep_merge(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _configuration_path(parts: tuple[str, ...]) -> str:
    path = ""
    for part in parts:
        if part.startswith("["):
            path += part
        else:
            path = f"{path}.{part}" if path else part
    return path or "<root>"


def _expand_string(
    value: str,
    environment: Mapping[str, str],
    *,
    source: str,
    path: tuple[str, ...],
) -> str:
    expanded = value
    for _ in range(_MAXIMUM_EXPANSION_PASSES):
        if _ENVIRONMENT_REFERENCE.search(expanded) is None:
            return expanded

        def replace(match: re.Match[str]) -> str:
            name = match.group("name")
            default = match.group("default")
            environment_value = environment.get(name)
            if environment_value is not None and (environment_value or default is None):
                replacement = environment_value
            elif default is not None:
                replacement = default
            else:
                raise ServerConfigurationError(
                    f"{source}: {_configuration_path(path)} references unset "
                    f"environment variable {name!r}"
                )
            return replacement

        next_value = _ENVIRONMENT_REFERENCE.sub(replace, expanded)
        if next_value == expanded:
            break
        expanded = next_value
    raise ServerConfigurationError(
        f"{source}: {_configuration_path(path)} contains cyclic or excessively nested "
        "environment references"
    )


def _expand_environment(
    value: Any,
    environment: Mapping[str, str],
    *,
    source: str,
    path: tuple[str, ...] = (),
) -> Any:
    if isinstance(value, str):
        return _expand_string(value, environment, source=source, path=path)
    if isinstance(value, list):
        return [
            _expand_environment(
                item,
                environment,
                source=source,
                path=(*path, f"[{index}]"),
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        return {
            key: _expand_environment(
                item,
                environment,
                source=source,
                path=(*path, str(key)),
            )
            for key, item in value.items()
        }
    return value


def _read_configuration(config_file: Path | None) -> tuple[str, str]:
    if config_file is None:
        resource = files("autoforex.server").joinpath(DEFAULT_CONFIG_FILENAME)
        return resource.read_text(encoding="utf-8"), f"packaged {DEFAULT_CONFIG_FILENAME}"
    try:
        return config_file.read_text(encoding="utf-8"), str(config_file)
    except OSError as error:
        raise ServerConfigurationError(
            f"cannot read server configuration {config_file}: {error}"
        ) from error


def _parse_configuration(text: str, *, source: str) -> dict[str, Any]:
    try:
        parsed = yaml.load(text, Loader=_UniqueKeySafeLoader)
    except yaml.YAMLError as error:
        raise ServerConfigurationError(f"invalid YAML in {source}: {error}") from error
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ServerConfigurationError(f"{source}: the YAML document root must be a mapping")
    non_string_keys = [key for key in parsed if not isinstance(key, str)]
    if non_string_keys:
        raise ServerConfigurationError(
            f"{source}: top-level configuration keys must be strings: {non_string_keys!r}"
        )
    configuration = dict(parsed)
    unknown_keys = sorted(configuration.keys() - ServerSettings.model_fields.keys())
    if unknown_keys:
        raise ServerConfigurationError(
            f"{source}: unknown server setting(s): {', '.join(unknown_keys)}"
        )
    return configuration


def _resolve_configuration_file(config_file: Path | None) -> Path | None:
    if config_file is not None:
        return config_file
    configured_path = os.environ.get(CONFIG_FILE_ENVIRONMENT_VARIABLE)
    return Path(configured_path) if configured_path else None


def _resolve_environment_file(environment_file: Path | None) -> Path:
    if environment_file is not None:
        return environment_file
    return Path(os.environ.get(ENV_FILE_ENVIRONMENT_VARIABLE, ".env"))


def _interpolation_environment(environment_file: Path) -> dict[str, str]:
    file_environment = {
        key: value for key, value in dotenv_values(environment_file).items() if value is not None
    }
    return {**file_environment, **os.environ}


def load_server_settings(
    *,
    config_file: Path | None = None,
    environment_file: Path | None = None,
) -> ServerSettings:
    """Load YAML, then apply dotenv and process-environment overrides."""
    resolved_config_file = _resolve_configuration_file(config_file)
    resolved_environment_file = _resolve_environment_file(environment_file)
    text, source = _read_configuration(resolved_config_file)
    yaml_values = _parse_configuration(text, source=source)
    expanded_values = _expand_environment(
        yaml_values,
        _interpolation_environment(resolved_environment_file),
        source=source,
    )
    try:
        dotenv_values_source = DotEnvSettingsSource(
            ServerSettings,
            env_file=resolved_environment_file,
        )()
        environment_values = EnvSettingsSource(ServerSettings)()
    except SettingsError as error:
        raise ServerConfigurationError(f"invalid server environment overrides: {error}") from error
    merged = _deep_merge(expanded_values, dotenv_values_source)
    merged = _deep_merge(merged, environment_values)
    try:
        return ServerSettings.model_validate(merged)
    except ValidationError as error:
        raise ServerConfigurationError(
            f"invalid server configuration from {source}: {error}"
        ) from error


def write_default_configuration(
    target: Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Write an editable copy of the packaged default configuration."""
    if target.exists() and not overwrite:
        raise FileExistsError(f"configuration file already exists: {target}")
    text, _ = _read_configuration(None)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)
    return target


class ConfigurationCli:
    """Command-line adapter for server configuration files."""

    def run(self, arguments: Sequence[str] | None = None) -> int:
        """Generate or validate server configuration."""
        parser = argparse.ArgumentParser(prog="auto-forex-server-config")
        subparsers = parser.add_subparsers(dest="action", required=True)

        initialize = subparsers.add_parser("init")
        initialize.add_argument(
            "--target",
            type=Path,
            default=Path("auto-forex-server.yaml"),
        )
        initialize.add_argument("--overwrite", action="store_true")

        validate = subparsers.add_parser("validate")
        validate.add_argument("--config", type=Path)
        validate.add_argument("--env-file", type=Path)

        options = parser.parse_args(arguments)
        if options.action == "init":
            try:
                target = write_default_configuration(
                    options.target,
                    overwrite=options.overwrite,
                )
            except OSError as error:
                parser.error(str(error))
            print(target)
            return 0
        try:
            load_server_settings(
                config_file=options.config,
                environment_file=options.env_file,
            )
        except ServerConfigurationError as error:
            parser.error(str(error))
        print("configuration is valid")
        return 0


def main() -> None:
    """Run the server-configuration CLI."""
    raise SystemExit(ConfigurationCli().run())


if __name__ == "__main__":
    main()
