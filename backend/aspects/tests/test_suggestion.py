"""Tests for the suggestion system.

Suggestion is now an Aspect subclass. Author name comes from
self.entity.name instead of self.data["name"].
"""

import os

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def dynamodb():
    """Set up mock DynamoDB tables for suggestion tests."""
    with mock_aws():
        os.environ["ENTITY_TABLE"] = "entity-table-test"
        os.environ["LOCATION_TABLE"] = "location-table-test"
        os.environ["SUGGESTION_TABLE"] = "suggestion-table-test"

        client = boto3.resource("dynamodb", region_name="ap-southeast-1")

        # Entity table with contents GSI
        client.create_table(
            TableName="entity-table-test",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "uuid", "AttributeType": "S"},
                {"AttributeName": "location", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "contents",
                    "KeySchema": [
                        {"AttributeName": "location", "KeyType": "HASH"},
                        {"AttributeName": "uuid", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "KEYS_ONLY"},
                    "ProvisionedThroughput": {
                        "ReadCapacityUnits": 1,
                        "WriteCapacityUnits": 1,
                    },
                }
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
        )

        # Location aspect table (Suggestion uses LOCATION_TABLE)
        client.create_table(
            TableName="location-table-test",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "uuid", "AttributeType": "S"},
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
        )

        # Suggestion table
        client.create_table(
            TableName="suggestion-table-test",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "uuid", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
        )

        yield client


def _make_suggestion_aspect(name="TestPlayer"):
    """Create an Entity + Suggestion aspect wired together."""
    from aspects.suggestion import Suggestion
    from aspects.thing import Entity

    entity = Entity()
    entity.data["name"] = name
    entity.data["aspects"] = ["Suggestion"]
    entity.data["primary_aspect"] = "Suggestion"
    entity._save()

    sug = Suggestion()
    sug.data["uuid"] = entity.uuid
    sug._save()
    sug.entity = entity
    return sug


class TestSuggestion:
    """Tests for the suggestion system."""

    def test_suggest_creates_suggestion(self, dynamodb):
        """Submitting a suggestion should create it in DynamoDB."""
        entity_sug = _make_suggestion_aspect(name="TestPlayer")

        result = entity_sug.suggest(text="Add flying mounts")
        assert result["type"] == "suggest_confirm"
        assert "suggestion_uuid" in result
        assert "flying mounts" in result["message"]

    def test_suggest_empty_text(self, dynamodb):
        """Suggesting with empty text should return an error."""
        entity_sug = _make_suggestion_aspect()
        result = entity_sug.suggest(text="")
        assert result["type"] == "error"

    def test_suggest_whitespace_only(self, dynamodb):
        """Suggesting with whitespace-only text should return an error."""
        entity_sug = _make_suggestion_aspect()
        result = entity_sug.suggest(text="   ")
        assert result["type"] == "error"

    def test_suggestions_list_empty(self, dynamodb):
        """Listing suggestions when none exist should return empty list."""
        entity_sug = _make_suggestion_aspect()
        result = entity_sug.suggestions()
        assert result["type"] == "suggestions"
        assert result["count"] == 0
        assert result["suggestions"] == []

    def test_suggestions_list_after_creating(self, dynamodb):
        """Listing suggestions after creating should show the suggestion."""
        entity_sug = _make_suggestion_aspect(name="TestPlayer")
        entity_sug.suggest(text="Add weather system")

        result = entity_sug.suggestions()
        assert result["type"] == "suggestions"
        assert result["count"] == 1
        assert result["suggestions"][0]["text"] == "Add weather system"
        assert result["suggestions"][0]["author"] == "TestPlayer"

    def test_vote_on_suggestion(self, dynamodb):
        """Voting on a suggestion should increment the vote count."""
        author = _make_suggestion_aspect(name="Author")
        create_result = author.suggest(text="Add crafting")
        suggestion_uuid = create_result["suggestion_uuid"]

        # Vote from a different entity
        voter = _make_suggestion_aspect(name="Voter")
        vote_result = voter.vote(suggestion_uuid=suggestion_uuid)
        assert vote_result["type"] == "vote_confirm"
        assert vote_result["votes"] == 1

    def test_vote_duplicate_rejected(self, dynamodb):
        """Voting twice on the same suggestion should be rejected."""
        author = _make_suggestion_aspect(name="Author")
        create_result = author.suggest(text="Add magic")
        suggestion_uuid = create_result["suggestion_uuid"]

        voter = _make_suggestion_aspect(name="Voter")
        voter.vote(suggestion_uuid=suggestion_uuid)
        # Try to vote again
        second_vote = voter.vote(suggestion_uuid=suggestion_uuid)
        assert second_vote["type"] == "error"
        assert "already voted" in second_vote["message"]

    def test_vote_nonexistent_suggestion(self, dynamodb):
        """Voting on a nonexistent suggestion should return an error."""
        entity_sug = _make_suggestion_aspect()
        result = entity_sug.vote(suggestion_uuid="nonexistent-uuid")
        assert result["type"] == "error"
        assert "not found" in result["message"]

    def test_vote_no_uuid(self, dynamodb):
        """Voting without a suggestion UUID should return an error."""
        entity_sug = _make_suggestion_aspect()
        result = entity_sug.vote(suggestion_uuid="")
        assert result["type"] == "error"

    def test_suggestions_sorted_by_votes(self, dynamodb):
        """Suggestions should be sorted by votes descending."""
        author = _make_suggestion_aspect(name="Author")

        # Create two suggestions
        r1 = author.suggest(text="Idea A")
        r2 = author.suggest(text="Idea B")

        # Vote for B twice (from different entities)
        v1 = _make_suggestion_aspect(name="Voter1")
        v1.vote(suggestion_uuid=r2["suggestion_uuid"])

        v2 = _make_suggestion_aspect(name="Voter2")
        v2.vote(suggestion_uuid=r2["suggestion_uuid"])

        # Vote for A once
        v3 = _make_suggestion_aspect(name="Voter3")
        v3.vote(suggestion_uuid=r1["suggestion_uuid"])

        # List — B should be first (2 votes vs 1)
        result = author.suggestions()
        assert result["count"] == 2
        assert result["suggestions"][0]["text"] == "Idea B"
        assert result["suggestions"][0]["votes"] == 2
        assert result["suggestions"][1]["text"] == "Idea A"
        assert result["suggestions"][1]["votes"] == 1
