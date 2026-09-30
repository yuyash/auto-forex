"""Configure a user stream and global ingestion settings."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--environment", choices=("alpha", "beta", "prod"), required=True)
    parser.add_argument("--user-pool-id", required=True)
    parser.add_argument("--users-table-name", default="Users")
    parser.add_argument("--appconfig-application-id", required=True)
    parser.add_argument("--appconfig-environment-id", required=True)
    parser.add_argument("--appconfig-profile-id", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--oanda-environment", choices=("practice", "live"), default="practice")
    return parser.parse_args()


def main() -> None:
    args = arguments()
    token = getpass.getpass("OANDA API token: ")
    if not token:
        raise ValueError("OANDA API token is required")

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    secrets = session.client("secretsmanager")
    cognito = session.client("cognito-idp")
    appconfig = session.client("appconfig")
    users = session.resource("dynamodb").Table(args.users_table_name)

    cognito_user = cognito.admin_get_user(
        UserPoolId=args.user_pool_id,
        Username=args.username,
    )
    attributes = {item["Name"]: item["Value"] for item in cognito_user["UserAttributes"]}
    user_id = attributes["sub"]
    secret_suffix = hashlib.sha256(user_id.encode()).hexdigest()
    secret_name = f"auto-forex/{args.environment}/oanda/{secret_suffix}"
    secret_value = json.dumps({"token": token}, separators=(",", ":"))
    try:
        secrets.create_secret(
            Name=secret_name,
            SecretString=secret_value,
            Tags=[
                {"Key": "Project", "Value": "auto-forex"},
                {"Key": "Environment", "Value": args.environment},
            ],
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceExistsException":
            raise
        secrets.put_secret_value(SecretId=secret_name, SecretString=secret_value)

    now = datetime.now(UTC).isoformat()
    users.update_item(
        Key={"user_id": user_id},
        UpdateExpression=(
            "SET username = :username, email = :email, #environment = :environment, "
            "#status = :status, broker = :broker, oanda_account_id = :account_id, "
            "oanda_environment = :oanda_environment, oanda_secret_id = :secret_id, "
            "symbols = :symbols, stream_enabled = :enabled, stream_status = :stream_status, "
            "created_at = if_not_exists(created_at, :now), updated_at = :now"
        ),
        ExpressionAttributeNames={"#environment": "environment", "#status": "status"},
        ExpressionAttributeValues={
            ":username": cognito_user["Username"],
            ":email": attributes.get("email", ""),
            ":environment": args.environment,
            ":status": "ACTIVE",
            ":broker": "OANDA",
            ":account_id": args.account_id,
            ":oanda_environment": args.oanda_environment,
            ":secret_id": secret_name,
            ":symbols": args.symbols,
            ":enabled": True,
            ":stream_status": f"{args.environment}#ENABLED",
            ":now": now,
        },
    )
    configuration = json.dumps(
        {
            "ingestion_enabled": True,
            "reconnect_max_delay_seconds": 30,
        },
        separators=(",", ":"),
    )
    version = appconfig.create_hosted_configuration_version(
        ApplicationId=args.appconfig_application_id,
        ConfigurationProfileId=args.appconfig_profile_id,
        Content=configuration.encode(),
        ContentType="application/json",
    )
    appconfig.start_deployment(
        ApplicationId=args.appconfig_application_id,
        EnvironmentId=args.appconfig_environment_id,
        ConfigurationProfileId=args.appconfig_profile_id,
        ConfigurationVersion=str(version["VersionNumber"]),
        DeploymentStrategyId="AppConfig.AllAtOnce",
    )
    print(f"Configured stream for user_id={user_id} and enabled global ingestion.")


if __name__ == "__main__":
    main()
