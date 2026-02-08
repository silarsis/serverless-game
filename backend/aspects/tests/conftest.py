"""Pytest configuration for serverless-game tests."""

import os

# Set AWS region for moto/boto3
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

# Set default table names for testing
os.environ.setdefault("ENTITY_TABLE", "test-entity-table")
os.environ.setdefault("LOCATION_TABLE", "test-location-table")
os.environ.setdefault("LAND_TABLE", "test-land-table")
os.environ.setdefault("THING_TABLE", "test-thing-table")
os.environ.setdefault("SUGGESTION_TABLE", "test-suggestion-table")
