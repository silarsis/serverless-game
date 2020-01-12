from os import environ
from ..lib import state
from typing import Callable, Dict


class Thing(state.State):
    def __init__(self, uuid: str = None):
        super().__init__(uuid, environ['THING_TABLE'])

    @property
    def mixins(self) -> Dict[str, Callable]:
        if 'mixins' not in self.data:
            self.data['mixins'] = {}
            self.dirty = True
        return self.data['mixins']

    def add_mixin(self, mixin: str) -> None:
        # This will become an AWS lambda call eventually
        self.data['mixins'][mixin] = lambda x: \
            print("called mixin {} for {}".format(mixin, x))
        self.dirty = True

    def remove_mixin(self, mixin: str) -> None:
        del(self.data['mixins'][mixin])
        self.dirty = True
