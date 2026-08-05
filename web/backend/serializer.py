from typing import Any


class GameSerializer:

    @staticmethod
    def serialize(game) -> dict[str, Any]:

        return {
            "phase": game.phase.value,
            "current_player": game.current_player(),
            "players": GameSerializer.players(game),
            "history": len(game.history)
        }

    @staticmethod
    def players(game):

        result = []

        for i, name in enumerate(game.player_names):

            result.append({
                "id": i,
                "name": name
            })

        return result