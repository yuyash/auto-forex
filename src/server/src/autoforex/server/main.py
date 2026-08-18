"""Console entry point for the AutoForex gRPC daemon."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from autoforex.server.composition import ServerApplication
from autoforex.server.configuration import ServerConfigurationError, load_server_settings
from autoforex.server.process import ServerProcess


def main(arguments: Sequence[str] | None = None) -> None:
    """Build and run the configured server process."""
    parser = argparse.ArgumentParser(prog="auto-forex-server")
    parser.add_argument(
        "--config",
        type=Path,
        help="YAML configuration file (or AUTO_FOREX_SERVER_CONFIG_FILE)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="dotenv file (or AUTO_FOREX_SERVER_ENV_FILE; default: .env)",
    )
    options = parser.parse_args(arguments)
    try:
        settings = load_server_settings(
            config_file=options.config,
            environment_file=options.env_file,
        )
    except ServerConfigurationError as error:
        parser.error(str(error))
    application = ServerApplication.build(settings)
    process = ServerProcess.create(application)
    try:
        process.run()
    finally:
        process.stop()


if __name__ == "__main__":
    main()
