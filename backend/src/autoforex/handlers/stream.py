"""Run OANDA price streams in Fargate."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import signal

import boto3
import httpx
from botocore.exceptions import BotoCoreError, ClientError

from autoforex.adapters.aws.appconfig import AppConfigSettingsProvider
from autoforex.adapters.aws.queue import SqsPricePublisher
from autoforex.adapters.aws.secrets import SecretsManagerBrokerCredentialProvider
from autoforex.adapters.aws.users import DynamoDbUserStreamRepository
from autoforex.adapters.brokers.oanda import OandaPriceStream
from autoforex.application.ingestion import IngestionService
from autoforex.ports.identity import BrokerCredentialProvider
from autoforex.ports.settings import OperationalSettings, UserStreamSettings

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


async def _consume(
    settings: UserStreamSettings,
    credentials: BrokerCredentialProvider,
    service: IngestionService,
    reconnect_max_delay_seconds: int,
) -> None:
    delay = 1.0
    while True:
        try:
            token = await asyncio.to_thread(credentials.token_for, settings.secret_id)
            logger.info(
                "opening OANDA stream user_id=%s symbols=%s",
                settings.user_id,
                ",".join(settings.symbols),
            )
            stream = OandaPriceStream(
                settings.oanda_environment,
                settings.account_id,
                settings.symbols,
                token,
            )
            await service.consume(stream.prices())
            delay = 1.0
        except asyncio.CancelledError:
            raise
        except (
            BotoCoreError,
            ClientError,
            httpx.HTTPError,
            OSError,
            ValueError,
            KeyError,
        ) as error:
            logger.warning("OANDA stream disconnected user_id=%s: %s", settings.user_id, error)
            await asyncio.sleep(delay + random.random())
            delay = min(delay * 2, reconnect_max_delay_seconds)


async def _cancel(task: asyncio.Task[None]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def run() -> None:
    appconfig = AppConfigSettingsProvider(
        os.environ["APPCONFIG_APPLICATION_ID"],
        os.environ["APPCONFIG_ENVIRONMENT_ID"],
        os.environ["APPCONFIG_PROFILE_ID"],
        boto3.client("appconfigdata"),
    )
    users = DynamoDbUserStreamRepository(
        boto3.resource("dynamodb").Table(os.environ["USERS_TABLE_NAME"]),
        os.environ["DEPLOYMENT_ENVIRONMENT"],
    )
    credentials = SecretsManagerBrokerCredentialProvider(boto3.client("secretsmanager"))
    publisher = SqsPricePublisher(os.environ["PRICE_QUEUE_URL"], boto3.client("sqs"))
    service = IngestionService(publisher)
    current_operational: OperationalSettings | None = None
    current_streams: dict[str, UserStreamSettings] = {}
    stream_tasks: dict[str, asyncio.Task[None]] = {}

    try:
        while True:
            operational = await asyncio.to_thread(appconfig.get)
            desired_streams = (
                {item.user_id: item for item in await asyncio.to_thread(users.active_streams)}
                if operational.ingestion_enabled
                else {}
            )

            for user_id, task in tuple(stream_tasks.items()):
                settings_changed = current_streams.get(user_id) != desired_streams.get(user_id)
                operation_changed = current_operational != operational
                if settings_changed or operation_changed or task.done():
                    await _cancel(task)
                    del stream_tasks[user_id]

            for user_id, settings in desired_streams.items():
                if user_id not in stream_tasks:
                    stream_tasks[user_id] = asyncio.create_task(
                        _consume(
                            settings,
                            credentials,
                            service,
                            operational.reconnect_max_delay_seconds,
                        )
                    )

            if not operational.ingestion_enabled and current_operational != operational:
                logger.info("price ingestion is disabled in AppConfig")
            current_operational = operational
            current_streams = desired_streams
            await asyncio.sleep(appconfig.next_poll_interval_seconds)
    finally:
        await asyncio.gather(*(_cancel(task) for task in stream_tasks.values()))


def main() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for name in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(name, lambda: [task.cancel() for task in asyncio.all_tasks(loop)])
    try:
        loop.run_until_complete(run())
    except asyncio.CancelledError:
        logger.info("price ingestion stopped")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
