"""Tests for Entity and Aspect base classes (formerly Thing)."""

import unittest
from os import environ
from unittest.mock import patch

import boto3
from moto import mock_aws

from aspects import thing

environ["ENTITY_TABLE"] = "test-entity-table"
environ["LOCATION_TABLE"] = "test-location-table"
environ["MESSAGE_DELAYER_ARN"] = "test"
environ["AWS_DEFAULT_REGION"] = "ap-southeast-1"


def _create_entity_table():
    """Create the entity DynamoDB table for testing."""
    boto3.resource("dynamodb").create_table(
        TableName=environ["ENTITY_TABLE"],
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
                    "ReadCapacityUnits": 5,
                    "WriteCapacityUnits": 5,
                },
            }
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )


def _create_location_table():
    """Create the shared aspect DynamoDB table for testing."""
    boto3.resource("dynamodb").create_table(
        TableName=environ["LOCATION_TABLE"],
        KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "uuid", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )


class TestEntity(unittest.TestCase):
    """Unit tests for the Entity class."""

    def setUp(self):
        """Set up mocked resources for testing."""
        self.mock = mock_aws()
        self.mock.start()
        _create_entity_table()
        _create_location_table()
        roleName = "serverless-game-prod-StepFunctionsServiceRole-RANDOM"
        environ["THING_TOPIC_ARN"] = boto3.resource("sns").create_topic(Name="ThingTopic").arn
        role = boto3.client("iam").create_role(
            RoleName=roleName,
            AssumeRolePolicyDocument="""
Version: "2012-10-17"
    Statement:
    -
        Sid: "AllowStepFunctionsServiceToAssumeRole"
        Effect: "Allow"
        Action:
        - "sts:AssumeRole"
        Principal:
        Service: "states.${AWS::Region}.amazonaws.com"
        """,
        )
        boto3.client("stepfunctions").create_state_machine(
            name="test",
            definition="""
{
    "StartAt": "Delay",
    "Comment": "Publish to SNS with delay",
    "States": {
        "Delay": {
            "Type": "Wait",
            "SecondsPath": "$.delay_seconds",
            "Next": "Publish to SNS"
        },
        "Publish to SNS": {
            "Type": "Task",
            "Resource": "arn:aws:states:::sns:publish",
            "Parameters": {
                "TopicArn": "arn:aws:sns:ap-southeast-1:1234567890:ThingTopicName",
                "Message.$": "$.data",
                "MessageAttributes": {
                    "aspect": {
                        "DataType": "String",
                        "StringValue": "$.data.aspect"
                    }
                }
            },
            "End": true
        }
    }
}
""",
            roleArn=role["Role"]["Arn"],
        )

    def tearDown(self):
        """Tear down mocked resources after testing."""
        self.mock.stop()

    def test_create(self):
        """Test creation of Entity instance."""
        e = thing.Entity()
        e._save()
        self.assertNotEqual(e.uuid, "")
        self.assertIsNotNone(e.uuid)

    def test_load(self):
        """Test loading Entity from UUID."""
        e = thing.Entity(tid="tid1")
        e._save()
        uuid = e.uuid
        e2 = thing.Entity(uuid, "tid2")
        self.assertEqual(e2.tid, "tid2")
        self.assertEqual(e2.uuid, uuid)

    def test_keyerror_on_load_nonexistent(self):
        """Test loading non-existent Entity raises KeyError."""
        with self.assertRaises(KeyError):
            thing.Entity("nonexistent-uuid", "tid")

    def test_destroy(self):
        """Test destroying and reloading an Entity."""
        e = thing.Entity()
        e._save()
        uuid = e.uuid
        e.destroy()
        with self.assertRaises(KeyError):
            thing.Entity(uuid, "tid2")

    def test_name_property(self):
        """Test name property getter and setter."""
        e = thing.Entity()
        e.name = "TestEntity"
        e._save()
        loaded = thing.Entity(uuid=e.uuid)
        self.assertEqual(loaded.name, "TestEntity")

    def test_name_default(self):
        """Test name defaults to first 8 chars of uuid."""
        e = thing.Entity()
        self.assertEqual(e.name, e.uuid[:8])

    def test_location_property(self):
        """Test location property getter and setter."""
        room = thing.Entity()
        room._save()

        e = thing.Entity()
        e._save()
        e.location = room.uuid
        self.assertEqual(e.location, room.uuid)

    def test_contents_property(self):
        """Test contents property queries the contents GSI."""
        room = thing.Entity()
        room._save()

        child1 = thing.Entity()
        child1.data["location"] = room.uuid
        child1._save()

        child2 = thing.Entity()
        child2.data["location"] = room.uuid
        child2._save()

        contents = room.contents
        self.assertEqual(len(contents), 2)
        self.assertIn(child1.uuid, contents)
        self.assertIn(child2.uuid, contents)

    def test_connection_id_property(self):
        """Test connection_id property get/set."""
        e = thing.Entity()
        e._save()
        self.assertIsNone(e.connection_id)

        e.connection_id = "conn-123"
        loaded = thing.Entity(uuid=e.uuid)
        self.assertEqual(loaded.connection_id, "conn-123")

        e.connection_id = None
        loaded2 = thing.Entity(uuid=e.uuid)
        self.assertIsNone(loaded2.connection_id)

    def test_backward_compat_alias(self):
        """Test Thing = Entity backward compatibility alias."""
        self.assertIs(thing.Thing, thing.Entity)

    def test_aspects_field(self):
        """Test that new entities have empty aspects list."""
        e = thing.Entity()
        self.assertEqual(e.data["aspects"], [])
        self.assertEqual(e.data["primary_aspect"], "")

    # --- Aspect lazy creation tests ---

    def test_aspect_lazy_creation(self):
        """Verify aspect() auto-creates an aspect record when none exists."""
        from aspects.inventory import Inventory

        e = thing.Entity()
        e.data["aspects"] = ["Inventory"]
        e.data["primary_aspect"] = "Inventory"
        e._save()

        inv = e.aspect("Inventory")
        self.assertIsInstance(inv, Inventory)
        self.assertEqual(inv.data["uuid"], e.uuid)

        # Verify the record was persisted in the aspect table
        from aspects.aws_client import get_dynamodb_table

        table = get_dynamodb_table("LOCATION_TABLE")
        item = table.get_item(Key={"uuid": e.uuid}).get("Item")
        self.assertIsNotNone(item)
        self.assertEqual(item["uuid"], e.uuid)

    def test_aspect_caching(self):
        """Verify aspect() returns the same cached instance on repeat calls."""
        e = thing.Entity()
        e.data["aspects"] = ["Inventory"]
        e._save()

        inv1 = e.aspect("Inventory")
        inv2 = e.aspect("Inventory")
        self.assertIs(inv1, inv2)

    def test_aspect_loads_existing(self):
        """Verify aspect() loads pre-existing aspect data from the table."""
        from aspects.aws_client import get_dynamodb_table

        e = thing.Entity()
        e.data["aspects"] = ["Inventory"]
        e._save()

        # Pre-create an aspect record with custom data
        table = get_dynamodb_table("LOCATION_TABLE")
        table.put_item(Item={"uuid": e.uuid, "carry_capacity": 99})

        inv = e.aspect("Inventory")
        self.assertEqual(inv.data.get("carry_capacity"), 99)

    def test_aspect_entity_backref(self):
        """Verify aspect() sets the entity back-reference on the aspect."""
        e = thing.Entity()
        e.data["aspects"] = ["Inventory"]
        e._save()

        inv = e.aspect("Inventory")
        self.assertIs(inv.entity, e)

    # --- receive_command dispatch tests ---

    @patch.object(thing.Entity, "push_event")
    def test_receive_command_dispatches(self, mock_push):
        """Verify receive_command routes to the correct aspect method."""
        e = thing.Entity()
        e.data["name"] = "TestPlayer"
        e.data["location"] = "some-room"
        e.data["aspects"] = ["Communication"]
        e.data["primary_aspect"] = "Communication"
        e._save()

        result = e.receive_command("say", message="hello world")
        self.assertEqual(result["type"], "say_confirm")
        self.assertIn("hello world", result["message"])

    @patch.object(thing.Entity, "push_event")
    def test_receive_command_unknown(self, mock_push):
        """Verify receive_command returns error for unknown commands."""
        e = thing.Entity()
        e.data["aspects"] = ["Communication"]
        e.data["primary_aspect"] = "Communication"
        e._save()

        result = e.receive_command("nonexistent_command")
        self.assertEqual(result["type"], "error")
        self.assertIn("Unknown command", result["message"])

    @patch.object(thing.Entity, "push_event")
    def test_receive_command_help(self, mock_push):
        """Verify receive_command routes 'help' to Entity.help()."""
        e = thing.Entity()
        e.data["aspects"] = ["Communication"]
        e.data["primary_aspect"] = "Communication"
        e._save()

        result = e.receive_command("help")
        self.assertEqual(result["type"], "help")
        cmd_names = [c["name"] for c in result["commands"]]
        self.assertIn("say", cmd_names)

    # --- Connection management tests ---

    def test_attach_connection(self):
        """Verify attach_connection persists connection_id to the database."""
        e = thing.Entity()
        e._save()

        result = e.attach_connection(connection_id="ws-test-123")
        self.assertEqual(result["status"], "connected")

        reloaded = thing.Entity(uuid=e.uuid)
        self.assertEqual(reloaded.connection_id, "ws-test-123")

    def test_detach_connection(self):
        """Verify detach_connection removes connection_id from the database."""
        e = thing.Entity()
        e.data["connection_id"] = "ws-test-456"
        e._save()

        result = e.detach_connection()
        self.assertEqual(result["status"], "disconnected")

        reloaded = thing.Entity(uuid=e.uuid)
        self.assertIsNone(reloaded.connection_id)

    # --- Broadcast tests ---

    def test_broadcast_to_location(self):
        """Verify broadcast_to_location sends events to co-located entities."""
        room = thing.Entity()
        room._save()

        player1 = thing.Entity()
        player1.data["location"] = room.uuid
        player1._save()

        player2 = thing.Entity()
        player2.data["location"] = room.uuid
        player2._save()

        player3 = thing.Entity()
        player3.data["location"] = room.uuid
        player3._save()

        event = {"type": "test", "message": "broadcast test"}
        with patch.object(thing.Entity, "push_event") as mock_push:
            player1.broadcast_to_location(room.uuid, event, exclude_self=True)

        # push_event is called for player2 and player3 but not player1
        self.assertEqual(mock_push.call_count, 2)
