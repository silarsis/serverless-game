import uuid
import boto3
import environ


table = boto3.resource('dynamodb').Table(environ.get('THING_TABLE'))


class Thing:
    def __init__(self, data: dict):
        self.data = data
        self.dirty = False
        if not self.data:
            self._create()

    def _create(self):
        self.uuid = uuid.uuid4()
        self.data['mixins'] = {}
        self.dirty = True

    def _save(self):
        if self.dirty:
            table.put_item(Item=self.data)
            self.dirty = False

    @property
    def uuid(self) -> str:
        return str(self.data['uuid'])

    @uuid.setter
    def uuid(self, value: str):
        self.data['uuid'] = value
        self.dirty = True

    @property
    def mixins(self):
        return self.data['mixins']

    def add_mixin(self, mixin):
        self.data['mixins'][mixin] = lambda x: \
            print("called mixin {} for {}".format(mixin, x))
        self.dirty = True

    def remove_mixin(self, mixin):
        del(self.data['mixins'][mixin])
        self.dirty = True
