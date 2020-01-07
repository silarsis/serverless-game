import uuid


class Mob:
    def __init__(self, data: dict):
        self.data = data
        self.dirty = False
        if not self.data:
            self._create()

    def _create(self):
        self.uuid = uuid.uuid4()

    @property
    def uuid(self) -> str:
        return str(self.data['uuid'])

    @uuid.setter
    def uuid(self, value: str):
        self.data['uuid'] = value
        self.dirty = True
