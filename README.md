# Preferans Engine (Русский преферанс)

A pure-Python core engine for the Russian card game **преферанс** (Preferans).
No AI, no bots: it provides APIs for every action (bids, whist, discards,
orders, plays), keeps the state machine honest, and exposes every phase for
debugging (all hands visible, all legal actions enumerated).  Every rules
variation is configurable through a YAML file.

## Features

- 3- or 4-player table (the dealer sits out on the prikup in the 4-player game).
- Full phase flow: `deal → trading → (whist) → discarding → ordering → playing`,
  or `→ raspasy → playing`.
- Codex bidding: bid ladder `six < seven < eight < мизер < nine < ten <
  мизер без прикупа < десять без прикупа`, the «здесь» bid, кабальная мизер,
  order-not-lower-than-bid.
- Whist with obligation (4/2/1 tricks), консоляция, whistling shortfall
  penalties, жлобский/ответственный and джентльменский/полуответственный styles.
- Raspasy with амнистия, zero-trick premium, mountain or Ростов scoring, and
  configurable prikup behaviour (ignored / leads suit only / participates).
- Pool / горка / whists scoring and the final «роспись пульки» with горка
  amnesty and configurable pool settlement.
- Fully debuggable: `debug_snapshot()` shows every hand, `state(player_id)`
  gives each player's legal view, `available_*` lists all legal actions.

## Quick start

```python
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
```

Run the scripted demo:

```bash
python3 -m examples.playthrough
```

Run the tests (stdlib `unittest`, no pytest needed):

```bash
python3 -m unittest discover -s tests
```

## API overview

### Setup
- `PreferansGame(config=None, player_names=None, rng=None)` — create a game.
  Pass `config` to use custom rules (see below).  `rng` may be a seeded
  `random.Random` for reproducible runs.

### Actions (all validated against the current phase/turn)
- `deal()` / `next_hand()` — shuffle, deal, start a new hand.
- `bid(player, action, suit=None)` — `"pass"`, `"here"`, or a ladder contract
  name (`"six"`, `"seven"`, ..., `"mizer"`, `"ten_without_prikup"`).  In
  `bid_style: suit` pass the suit too.
- `pass_bid(player)` / `here_bid(player)` — conveniences.
- `discard(player, card1, card2)` — declarer's снос (cards may be `Card`s or
  strings like `"7S"`).
- `order(player, contract, trump=None)` — final declaration; `trump` may be a
  `Suit`, a suit name (`"hearts"`), or `None` (без козыря).
- `whist(player, choice)` — `"whist"` or `"pass"`.
- `play(player, card)` — play a card to the current trick.

### Introspection / debugging
- `current_player()`, `declarer()`, `contract()`, `trump()`.
- `hand_of(player)`, `prikup()`.
- `available_bids(player)`, `available_whists(player)`, `available_orders(player)`,
  `available_discards(player)`, `available_plays(player)`.
- `state(player)` — legal view for a player (their hand + public info).
- `debug_snapshot()` — full state including every player's hand.
- `render()` — human-readable console table.
- `result()` — `HandResult` of the last hand; `history` — all results.

Cards are compared / passed as `Card` objects (see `preferans.cards`); any
action also accepts card codes (`"7S"`, `"10H"`, `"A♠"`) which are parsed via
`parse_card`.

## Configuration

All rules live in `config/default.yaml` (Сочинка, 4 players).  Load a partial
file and the defaults are merged underneath:

```python
game = PreferansGame(config=load_config("my_rules.yaml"))
```

Every section is a documented knob:

| Section | What it controls |
|---|---|
| `contracts` | Trick counts, values, whist rates/obligations, мизер vs game, без-прикупа |
| `trading` | Bid style (`level`/`suit`), ladder, «здесь», кабальная мизер, end-of-auction rules |
| `whist` | Minimum whistlers per level, obligation, консоляция, penalty style, мизер whists |
| `raspas` | Scoring (mountain/rostov), amnesty, progression, zero premium, prikup mode |
| `play` | First lead, must-follow-suit, trump-if-cannot-follow |
| `scoring` | Whist conversion rates, горка amnesty, pool settlement, game-end condition |

### Example variants
- **Ленинград / Питер**: `whist.style: leningrad`, `scoring.pool_to_whist: 20`,
  `scoring.pool_settlement: to_mountain_double`.
- **3-player**: `num_players: 3` (nobody sits out), and typically
  `raspas.prikup_mode: leads_suit_only`.
- **Rостов**: `raspas.scoring: rostov`.
- **Прогрессивные распасы**: `raspas.progression: geometric`.
- **Сочинка 1–2–3** progression: `progression_values: [1, 2, 3]`.

## Project layout

```
preferans/cards.py    card model, 32-card deck, parsing, sorting
preferans/config.py   YAML schema, loader, defaults merging, ladder logic
preferans/engine.py   PreferansGame state machine + public/debug API
preferans/scoring.py  hand scoring and final settlement
config/default.yaml   the default (Сочинка) rule set
examples/             scripted playthrough
tests/                stdlib unittest suite
```

## Notes on rules (Кодекс)

The rules are modelled after the Кодекс (Russian Preferans rules), including:
- «Здесь» is only allowed with two bidders left and on the senior hand.
- Мизер is кабальная (only a first bid) by default; toggle via
  `trading.mizer_is_kabala`.
- The whistle obligation rests on the whistlers alone — a passer's tricks do
  not count towards the side's obligation.
- On raspasy the smallest trick count is amnestied (treated as zero) by default.
- Whists are zero-sum; pool and горка are converted to whists at the end.
