import unittest
from moto import mock_dynamodb2, mock_sns, mock_stepfunctions
import boto3
from aspects import thing
from os import environ


class ThingTestClass(thing.Thing):
    _tableName = 'testing'


environ['testing'] = 'test_table'
environ['MESSAGE_DELAYER_ARN'] = 'test'


class TestThing(unittest.TestCase):
    def _createTestTable(self):
        boto3.resource('dynamodb').create_table(
            TableName=environ['testing'],
            KeySchema=[
                {'AttributeName': 'uuid', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'uuid', 'AttributeType': 'S'}
            ]
        )

    def _createTestSNS(self):
        environ['THING_TOPIC_ARN'] = boto3.resource('sns').create_topic(Name='ThingTopic').arn

    def _createTestSFN(self):
        boto3.client('stepfunction').create_state_machine(
            name='test'
        )

    def test_fail_no_tablename(self):
        with self.assertRaises(AssertionError):
            thing.Thing()

    @mock_dynamodb2
    def test_keyerror_on_load_nonexistent(self):
        self._createTestTable()
        with self.assertRaises(KeyError):
            ThingTestClass('uuid', 'tid')

    @mock_dynamodb2
    def test_create(self):
        self._createTestTable()
        t = ThingTestClass('', 'tid')
        self.assertEqual(t.tid, 'tid')
        self.assertNotEqual(t.uuid, '')

    @mock_dynamodb2
    def test_load(self):
        self._createTestTable()
        t = ThingTestClass('', 'tid')
        uuid = t.uuid
        del(t)
        t = ThingTestClass(uuid, 'tid2')
        self.assertEqual(t.tid, 'tid2')
        self.assertEqual(t.uuid, uuid)

    @mock_dynamodb2
    def test_destroy(self):
        self._createTestTable()
        t = ThingTestClass('', 'tid')
        uuid = t.uuid
        t.destroy()
        with self.assertRaises(KeyError):
            t = ThingTestClass(uuid, 'tid2')

    # @mock_dynamodb2
    # @mock_stepfunctions
    # def test_tick(self):
    #     self._createTestTable()
    #     self._createTestSFN()
    #     t = ThingTestClass('', 'tid')
    #     t.tick()
    #     # TODO: Check that it self-scheduled

    @mock_dynamodb2
    def test_prohibited_sets(self):
        self._createTestTable()
        t = ThingTestClass('', 'tid')
        with self.assertRaises(AttributeError):
            t.tid = 'test'
            t.uuid = 'test'

    @mock_dynamodb2
    def test_aspectName(self):
        self._createTestTable()
        t = ThingTestClass('', 'tid')
        self.assertEqual(t.aspectName, 'ThingTestClass')

# TODO: Test aspect and all the eventing code (_sendEvent and callback and such)