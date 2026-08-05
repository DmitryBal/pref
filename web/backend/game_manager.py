import random
import uuid

from pref.preferans.config import load_config
from pref.preferans.engine import PreferansGame


class GameManager:

    def __init__(self):
        self.games = {}

    def create(self, players):

        room = str(uuid.uuid4())

        game = PreferansGame(
            config=load_config(),
            player_names=players,
            rng=random.Random()
        )

        self.games[room] = game

        return room

    def get(self, room):

        return self.games[room]

    def remove(self, room):

        self.games.pop(room, None)


manager = GameManager()