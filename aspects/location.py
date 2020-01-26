from aspects.thing import Thing, IdType
import boto3
from boto3.dynamodb.conditions import Key
import logging
from aspects.handler import lambdaHandler
from typing import List, Dict


ExitsType = Dict[str, IdType]


class Location(Thing):
    " All location aware things will have a Location aspect "
    _tableName = 'LOCATION_TABLE'

    def __init__(self, uuid: IdType = None, tid: str = None):
        super().__init__(uuid, tid)
        self._contents = boto3.resource('dynamodb').Table('CONTENTS_TABLE')
        self._locations = boto3.resource('dynamodb').Table('LOCATIONS_TABLE')
        self._condition = Key('uuid').eq(self.uuid)

    @property
    def exits(self) -> ExitsType:
        return self.data['exits']

    def add_exit(self, direction: str, destination: IdType) -> ExitsType:
        self.data['exits'][direction] = destination
        self.dirty = True
        return self.data['exits']

    def remove_exit(self, direction: str) -> ExitsType:
        if direction in self.data['exits']:
            del(self.data['exits'][direction])
            self.dirty = True
        return self.data['exits']

    @property
    def contents(self) -> List[IdType]:
        return self.data.setdefault('contents', [])

    def add_contents(self, value: IdType) -> List[IdType]:
        self.contents.append(value)
        logging.debug("{} now contains {}".format(self.uuid, value))
        self.dirty = False
        return self.contents

    def remove_contents(self, value: IdType) -> List[IdType]:
        if value in self.contents:
            self.contents.remove(value)
            logging.debug("{} no longer contains {}".format(self.uuid, value))
            self.dirty = True
        return self.contents

    @property
    def locations(self) -> List[IdType]:
        return self.data.setdefault('locations', [])

    def add_location(self, value: IdType) -> List[IdType]:
        self.locations.append(value)
        logging.debug("{} is now located in {}".format(self.uuid, value))
        self.dirty = True
        return self.locations

    def remove_location(self, value: IdType) -> List[IdType]:
        if value in self.locations:
            self.locations.remove(value)
            logging.debug("{} is no longer located in {}".format(self.uuid, value))
            self.dirty = True
        return self.locations

    def move(self, from_loc: IdType, to_loc: IdType):
        self.add_location(to_loc)
        self.remove_location(from_loc)

    def create(self) -> None:
        self.data['exits'] = {}
        super().create()

    def destroy(self):
        if self.locations:
            dest = self.locations[0]
        else:
            dest = 'Nowhere'  # TODO: Figure out a better solution for this
        for item in self.contents:
            Location(item, self.tid).move(self.uuid, dest)
        for loc in self.locations:
            Location(loc).remove_contents(self.uuid)
            self.remove_location(loc)


handler = lambdaHandler(Location)
