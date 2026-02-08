"""Tests for Entity and Aspect base classes (formerly Thing)."""

import unittest
from os import environ

import boto3
from moto import mock_aws

from aspects import thing

environ["ENTITY_TABLE"] = "test-entity-table"
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


class TestEntity(unittest.TestCase):
    """Unit tests for the Entity class."""

    def setUp(self):
        """Set up mocked resources for testing."""
        self.mock = mock_aws()
        self.mock.start()
        _create_entity_table()
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


# TODO: Test aspect() lazy creation, receive_command dispatch, help()
