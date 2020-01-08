import uuid

# TODO: Turn this into a mixin / lambda in it's own right


class Location:
    def __init__(self, data: dict):
        self.data = data
        self.dirty = False
        if not self.data:
            self._create()

    def _create(self):
        self.uuid = uuid.uuid4()

    @property
    def exits(self) -> dict:
        return self.data['exits']

    @exits.setter
    def exits(self, value: dict):
        self.data['exits'] = value
        self.dirty = True

    def add_exit(self, direction: str, destination: str):
        self.data['exits'][direction] = destination
        self.dirty = True

    @property
    def uuid(self) -> str:
        return str(self.data['uuid'])

    @uuid.setter
    def uuid(self, value: str):
        self.data['uuid'] = value
        self.dirty = True
