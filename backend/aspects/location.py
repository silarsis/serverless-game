from typing import Dict, List, Optional

from boto3.dynamodb.conditions import Key

from aspects.handler import lambdaHandler
from aspects.thing import IdType, Thing, callable

ExitsType = Dict[str, IdType]


class Location(Thing):
    "All location aware things will have a Location aspect"

    _tableName = "LOCATION_TABLE"

    @property
    def exits(self) -> ExitsType:
        return self.data["exits"]

    @callable
    def add_exit(self, direction: str, destination: IdType) -> ExitsType:
        self.data["exits"][direction] = destination
        self._save()
        return self.data["exits"]

    @callable
    def remove_exit(self, direction: str) -> ExitsType:
        if direction in self.data["exits"]:
            del self.data["exits"][direction]
            self._save()
        return self.data["exits"]

    @property
    def contents(self) -> List[IdType]:
        return [  # TODO: factor this out to deal with large response sets
            item["uuid"]
            for item in self._table.query(
                IndexName="contents",
                Select="ALL_PROJECTED_ATTRIBUTES",
                KeyConditionExpression=Key("location").eq(self.uuid),
            )["Items"]
        ]

    @property
    def location(self) -> Optional[IdType]:
        return self.data["location"]

    @location.setter
    def location(self, loc_id: IdType):
        self.data["location"] = loc_id
        self._save()

    @callable
    def create(self) -> None:
        self.data["exits"] = {}
        super().create()

    @callable
    def destroy(self):
        dest = (
            self.location or "Nowhere"
        )  # TODO: Figure out a better location for dropping objects
        for item in self.contents:
            Location(item, self.tid).location = dest
        self._table.delete_item(Key={"uuid": self.uuid})


handler = lambdaHandler(Location)
