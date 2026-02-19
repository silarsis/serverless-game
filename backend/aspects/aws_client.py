"""AWS Client Configuration.

This module provides centralized AWS client configuration that supports
both real AWS and LocalStack environments based on environment variables.

Environment Variables:
    LOCALSTACK_ENDPOINT: URL for LocalStack (e.g., http://localhost:4566)
    AWS_ACCESS_KEY_ID: AWS access key (use 'test' for LocalStack)
    AWS_SECRET_ACCESS_KEY: AWS secret key (use 'test' for LocalStack)
    AWS_DEFAULT_REGION: AWS region (default: ap-southeast-1)
"""

import os
from typing import Optional

import boto3


def get_localstack_endpoint() -> Optional[str]:
    """Get LocalStack endpoint URL from environment."""
    return os.environ.get("LOCALSTACK_ENDPOINT")


def is_localstack() -> bool:
    """Check if we're running against LocalStack."""
    return get_localstack_endpoint() is not None


def get_dynamodb_resource():
    """Get DynamoDB resource configured for current environment."""
    endpoint = get_localstack_endpoint()
    if endpoint:
        return boto3.resource(
            "dynamodb",
            endpoint_url=endpoint,
            region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
        )
    return boto3.resource("dynamodb")


def get_dynamodb_table(table_name_env_var: str):
    """Get a DynamoDB table by environment variable name."""
    table_name = os.environ.get(table_name_env_var)
    if not table_name:
        raise ValueError(f"Environment variable {table_name_env_var} is not set")
    return get_dynamodb_resource().Table(table_name)


def get_sns_resource():
    """Get SNS resource configured for current environment."""
    endpoint = get_localstack_endpoint()
    if endpoint:
        return boto3.resource(
            "sns",
            endpoint_url=endpoint,
            region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
        )
    return boto3.resource("sns")


def get_sns_topic(topic_arn_env_var: str = "THING_TOPIC_ARN"):
    """Get an SNS topic by environment variable name."""
    topic_arn = os.environ.get(topic_arn_env_var)
    if not topic_arn:
        raise ValueError(f"Environment variable {topic_arn_env_var} is not set")
    return get_sns_resource().Topic(topic_arn)


def get_stepfunctions_client():
    """Get Step Functions client configured for current environment."""
    endpoint = get_localstack_endpoint()
    if endpoint:
        return boto3.client(
            "stepfunctions",
            endpoint_url=endpoint,
            region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
        )
    return boto3.client("stepfunctions")


def get_lambda_client():
    """Get Lambda client configured for current environment."""
    endpoint = get_localstack_endpoint()
    if endpoint:
        return boto3.client(
            "lambda",
            endpoint_url=endpoint,
            region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
        )
    return boto3.client("lambda")


def get_api_gateway_client():
    """Get API Gateway Management API client for WebSocket operations."""
    callback_url = os.environ.get("WEBSOCKET_API_ENDPOINT")
    endpoint = get_localstack_endpoint()

    if endpoint:
        # LocalStack mode - WebSocket management endpoint
        return boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=f"{endpoint}/_aws/execute-api",
            region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
        )

    # Real AWS - use the WebSocket API endpoint (must include stage)
    if callback_url:
        return boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=callback_url,
            region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1"),
        )

    raise ValueError("WEBSOCKET_API_ENDPOINT environment variable not set")
