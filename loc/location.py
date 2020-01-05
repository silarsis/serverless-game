import uuid


class Location:
    def __init__(self, data: dict):
        self.data = data
        self.dirty = False
        if not self.data:
            self._create()

    def _create(self):
        self.exits = {}
        self.uuid = uuid.uuid4()

    @property
    def exits(self) -> dict:
        return self.data['exits']

    @exits.setter
    def exits(self, value: dict):
        self.data['exits'] = value
        self.dirty = True

    @property
    def uuid(self) -> str:
        return str(self.data['uuid'])

    @uuid.setter
    def uuid(self, value: str):
        self.data['uuid'] = value
        self.dirty = True
