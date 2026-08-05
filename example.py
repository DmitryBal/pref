from preferans.config import load_config
from preferans.engine import PreferansGame

game = PreferansGame(config=load_config(), player_names=["Аня", "Боря", "Вера", "Гена"])
game.deal()

while True:
    player = game.current_player()
    if player is None:
        break
    if game.phase.value == "trading":
        opts = game.available_bids(player)
        print(opts)
        bids = [o for o in opts if o["type"] == "bid"]
        if bids:
            game.bid(player, bids[-1]["contract"])
        else:
            game.pass_bid(player)
    elif game.phase.value == "discarding":
        c1, c2 = game.available_discards(game.declarer())[0]
        game.discard(game.declarer(), c1, c2)
    elif game.phase.value == "ordering":
        o = game.available_orders(game.declarer())[0]
        game.order(game.declarer(), o["contract"], o.get("trump"))
    elif game.phase.value == "whist":
        game.whist(player, game.available_whists(player)[0])
    elif game.phase.value == "playing":
        game.play(player, game.available_plays(player)[0])
