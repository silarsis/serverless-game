import unittest
from os import environ

import boto3
from moto import mock_dynamodb, mock_iam, mock_sns, mock_stepfunctions

from aspects import thing


class ThingTestClass(thing.Thing):
    _tableName = "testing"


environ["testing"] = "test_table"
environ["MESSAGE_DELAYER_ARN"] = "test"
environ["AWS_DEFAULT_REGION"] = "ap-southeast-1"


class TestThing(unittest.TestCase):
    def setUp(self):
        self.mocks = [mock_dynamodb(), mock_sns(), mock_stepfunctions(), mock_iam()]
        [mock.start() for mock in self.mocks]
        roleName = "serverless-game-prod-StepFunctionsServiceRole-RANDOM"
        boto3.resource("dynamodb").create_table(
            TableName=environ["testing"],
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "uuid", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
        )
        environ["THING_TOPIC_ARN"] = (
            boto3.resource("sns").create_topic(Name="ThingTopic").arn
        )
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
        [mock.stop() for mock in self.mocks]

    def test_fail_no_tablename(self):
        with self.assertRaises(AssertionError):
            thing.Thing()

    def test_keyerror_on_load_nonexistent(self):
        with self.assertRaises(KeyError):
            ThingTestClass("uuid", "tid")

    def test_create(self):
        t = ThingTestClass("", "tid")
        self.assertEqual(t.tid, "tid")
        self.assertNotEqual(t.uuid, "")

    def test_load(self):
        t = ThingTestClass("", "tid")
        uuid = t.uuid
        del t
        t = ThingTestClass(uuid, "tid2")
        self.assertEqual(t.tid, "tid2")
        self.assertEqual(t.uuid, uuid)

    def test_destroy(self):
        t = ThingTestClass("", "tid")
        uuid = t.uuid
        t.destroy()
        with self.assertRaises(KeyError):
            t = ThingTestClass(uuid, "tid2")

    # def test_tick(self):
    #     self._createTestTable()
    #     self._createTestSFN()
    #     t = ThingTestClass('', 'tid')
    #     t.tick()
    #     # TODO: Check that it self-scheduled

    def test_prohibited_sets(self):
        t = ThingTestClass("", "tid")
        with self.assertRaises(AttributeError):
            t.tid = "test"
            t.uuid = "test"

    def test_aspectName(self):
        t = ThingTestClass("", "tid")
        self.assertEqual(t.aspectName, "ThingTestClass")


# TODO: Test aspect and all the eventing code (_sendEvent and callback and such)
