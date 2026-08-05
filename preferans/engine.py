"""Core game engine for Russian Preferans.

The engine is a state machine moving through the phases of a hand:

    AWAITING_DEAL -> TRADING -> (WHIST ->) DISCARDING -> ORDERING -> PLAYING
                   \-> RASPAS -> PLAYING
                   -> HAND_DONE -> GAME_OVER

Every action is validated; introspection methods (``available_*``,
``hand_of``, ``prikup``, ``debug_snapshot``) make every phase debuggable, and
``state(player_id)`` gives the legal view of a specific player.
"""

from __future__ import annotations

import random
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from . import scoring as sc
from .cards import (
    Card,
    Suit,
    SUIT_ORDER,
    full_deck,
    parse_card,
    parse_suit,
    sort_hand,
)
from .config import (
    Config,
    PRIKUP_LEADS_SUIT_ONLY,
    PRIKUP_PARTICIPATES,
    load_config,
)


class Phase(Enum):
    AWAITING_DEAL = "awaiting_deal"
    TRADING = "trading"
    WHIST = "whist"
    DISCARDING = "discarding"
    ORDERING = "ordering"
    PLAYING = "playing"
    HAND_DONE = "hand_done"
    GAME_OVER = "game_over"


class IllegalAction(Exception):
    """Raised when an API call is not valid in the current situation."""


# Sentinel owner for a prikup card that leads (and can win) a raspasy trick.
_PRIKUP_OWNER = "prikup"

# Sentinel for a "без козыря" bid in suit-style trading (no-trump ranks
# highest within its level).
NO_TRUMP_BID = "nt"

# Trump options for the ordering stage: any suit, or "без козыря" (None).
TRUMP_OPTIONS = list(SUIT_ORDER) + [None]


def _suit_rank(value) -> int:
    """Seniority of a suit option (0..4); ``None`` and NO_TRUMP_BID are the
    highest (no trump)."""
    if value is None:
        return 4
    if isinstance(value, str):  # NO_TRUMP_BID
        return 4
    return value.order


def _weight(card: Card, trump: Optional[Suit], led_suit: Optional[Suit]) -> Tuple[int, int]:
    """Trick-taking strength of a card.  Trumps beat the led suit, which beats
    off-suit discards.  Returns a comparable tuple."""
    if trump is not None and card.suit is trump:
        return (1, card.rank.value)
    if led_suit is not None and card.suit is led_suit:
        return (0, card.rank.value)
    return (-1, card.rank.value)


class PreferansGame:
    def __init__(
        self,
        config: Optional[Config] = None,
        player_names: Optional[Sequence[str]] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.config = config or load_config()
        self.cfg = self.config
        self._rng = rng if rng is not None else random.Random()
        self.num_players = self.cfg.num_players
        self.names = {
            i: (player_names[i] if player_names and i < len(player_names) else f"Player{i}")
            for i in range(self.num_players)
        }
        self.scores = {i: sc.PlayerScore() for i in range(self.num_players)}

        self.phase = Phase.AWAITING_DEAL
        self.hand_number = 0
        self.history: List[sc.HandResult] = []
        self.log: List[str] = []
        self._raspas_streak = 0
        self._bid_base: Dict[str, int] = self._build_bid_bases()

        if str(self.cfg.first_dealer).lower() == "by_lot":
            self._dealer = self._rng.randrange(self.num_players)
        else:
            self._dealer = int(self.cfg.first_dealer) % self.num_players

        self._reset_hand_state()
        self._log(f"игра началась: {self.num_players} игрока, вариант {self.cfg.variant}")

    # ------------------------------------------------------------------ utils

    def _log(self, message: str) -> None:
        self.log.append(message)

    def _check_phase(self, phase: Phase) -> None:
        if self.phase != phase:
            raise IllegalAction(
                f"invalid phase {self.phase.value!r}, expected {phase.value!r}"
            )

    def _check_player(self, player_id: int) -> None:
        if not 0 <= player_id < self.num_players:
            raise IllegalAction(f"unknown player {player_id}")

    def next_active(self, player_id: int) -> int:
        """Next active (non-resting) player clockwise from ``player_id``."""
        p = player_id
        for _ in range(self.num_players):
            p = (p + 1) % self.num_players
            if p in self._active:
                return p
        raise IllegalAction("no active players")

    def active_players(self) -> List[int]:
        return list(self._active)

    def hand_of(self, player_id: int) -> List[Card]:
        self._check_player(player_id)
        return sort_hand(self._hands.get(player_id, []))

    def prikup(self) -> List[Card]:
        return list(self._prikup or [])

    def current_player(self) -> Optional[int]:
        if self.phase == Phase.TRADING:
            return self._current_bidder
        if self.phase == Phase.WHIST:
            return self._whist_current
        if self.phase in (Phase.DISCARDING, Phase.ORDERING):
            return self._declarer
        if self.phase == Phase.PLAYING:
            return self._playing_player()
        return None

    def declarer(self) -> Optional[int]:
        return self._declarer

    def trump(self) -> Optional[Suit]:
        return self._trump

    def contract(self) -> Optional[str]:
        return self._ordered_contract or self._traded_contract

    # --------------------------------------------------------------- bidding

    def _build_bid_bases(self) -> Dict[str, int]:
        """Base flat seniority index of every ladder entry.  In 'suit' style
        each trump level occupies 5 slots (spades..no-trump); мизер-style
        entries occupy one slot each."""
        base: Dict[str, int] = {}
        offset = 0
        for name in self.cfg.ladder():
            c = self.cfg.contract(name)
            base[name] = offset
            offset += 5 if c.trump else 1
        return base

    def _bid_unit(self, contract: str, suit) -> int:
        """Flat seniority of a bid ``(contract, suit)``."""
        if self.cfg.trading.bid_style == "level":
            return self.cfg.bid_rank(contract)
        return self._bid_base[contract] + _suit_rank(suit)

    def _current_high_index(self) -> int:
        if self._high_contract is None:
            return -1
        return self._bid_unit(self._high_contract, self._high_suit)

    def _remaining_bidders(self) -> List[int]:
        return [p for p in self._active if p not in self._passed]

    def _is_senior(self, a: int, b: int) -> bool:
        voices = []
        p = self.next_active(self._dealer)
        for _ in range(len(self._active)):
            voices.append(p)
            p = self.next_active(p)
        return voices.index(a) < voices.index(b)

    # ------------------------------------------------------------- hand setup

    def _reset_hand_state(self) -> None:
        self._active: List[int] = []
        self._hands: Dict[int, List[Card]] = {}
        self._prikup: Optional[List[Card]] = None
        self._prikup_revealed = False

        self._passed = set()
        self._current_bidder: Optional[int] = None
        self._bids: Dict[int, str] = {}
        self._bid_suits: Dict[int, object] = {}
        self._high_contract: Optional[str] = None
        self._high_suit: object = None
        self._high_bidder: Optional[int] = None

        self._declarer: Optional[int] = None
        self._traded_contract: Optional[str] = None
        self._traded_suit: object = None
        self._ordered_contract: Optional[str] = None
        self._ordered_trump: Optional[Suit] = None
        self._discards: List[Card] = []

        self._whist_order: List[int] = []
        self._whist_choices: Dict[int, str] = {}
        self._whist_current: Optional[int] = None
        self._whistlers: List[int] = []
        self._passers: List[int] = []

        self._is_raspas = False
        self._trump: Optional[Suit] = None
        self._trick_number = 0
        self._trick_leader: Optional[int] = None  # None == prikup leads
        self._trick_led_suit: Optional[Suit] = None
        self._trick_plays: List[Tuple[int, Card]] = []
        self._prikup_lead_card: Optional[Card] = None
        self._prikup_led_count = 0
        self._tricks_taken: Dict[int, List[List[Card]]] = {}
        self._result: Optional[sc.HandResult] = None

    def deal(self) -> None:
        """Shuffle, deal and start the next hand (first hand or the next one)."""
        if self.phase in (Phase.HAND_DONE, Phase.AWAITING_DEAL):
            self.hand_number += 1
            if self.hand_number > 1:
                self._dealer = (self._dealer + 1) % self.num_players
            self._setup_hand()
        else:
            raise IllegalAction(f"cannot deal while phase is {self.phase.value!r}")

    def next_hand(self) -> None:
        """Convenience alias for :meth:`deal` after a hand finished."""
        self.deal()

    def _setup_hand(self) -> None:
        self._reset_hand_state()
        if self.cfg.num_players == 3:
            self._active = list(range(self.num_players))
        elif self.cfg.dealer_sits_out:
            self._active = [p for p in range(self.num_players) if p != self._dealer]
        else:
            resting = (self._dealer - 1) % self.num_players
            self._active = [p for p in range(self.num_players) if p != resting]

        deck = full_deck()
        self._rng.shuffle(deck)
        idx = 0
        self._prikup = []
        for p in self._active:
            self._hands[p] = deck[idx:idx + self.cfg.cards_per_player]
            idx += self.cfg.cards_per_player
        self._prikup = deck[idx:idx + self.cfg.prikup_size]

        self._log(f"--- раздача {self.hand_number}, сдающий {self._dealer} ---")
        self._start_trading()

    # ------------------------------------------------------------------ trade

    def _start_trading(self) -> None:
        self.phase = Phase.TRADING
        self._current_bidder = self.next_active(self._dealer)
        self._log(f"торговля: первый голос {self._current_bidder}")

    def _next_bidder(self, after: Optional[int]) -> Optional[int]:
        p = after
        if p is None:
            p = self._current_bidder
        for _ in range(self.num_players):
            p = (p + 1) % self.num_players
            if p in self._active and p not in self._passed:
                return p
        return None

    def bid(self, player_id: int, action: str, suit=None) -> None:
        """Make a bid during trading.

        ``action`` is ``"pass"``, ``"here"`` (здесь) or a contract name from
        the ladder (e.g. ``"seven"``).  In ``bid_style: suit`` a trump contract
        may carry a ``suit`` (``None`` = "без козыря").
        """
        self._check_phase(Phase.TRADING)
        self._check_player(player_id)
        if player_id != self._current_bidder:
            raise IllegalAction(f"not {player_id}'s turn to bid")
        if action == "pass":
            self._do_pass(player_id)
        elif action == "here":
            self._do_here(player_id)
        else:
            self._do_bid(player_id, action, suit)

    def pass_bid(self, player_id: int) -> None:
        self.bid(player_id, "pass")

    def here_bid(self, player_id: int) -> None:
        self.bid(player_id, "here")

    def _do_pass(self, player_id: int) -> None:
        self._passed.add(player_id)
        self._log(f"игрок {player_id} пасует")
        self._current_bidder = self._next_bidder(player_id)
        self._end_trading_if_done()

    def _do_bid(self, player_id: int, contract: str, suit) -> None:
        if contract not in self.cfg.contracts:
            raise IllegalAction(f"unknown contract {contract!r}")
        if contract not in self.cfg.ladder():
            raise IllegalAction(f"{contract!r} cannot be traded")
        c = self.cfg.contract(contract)
        if c.trump:
            if suit is not None and suit != NO_TRUMP_BID and _as_suit(suit) is None:
                raise IllegalAction("suit must be a Suit, a suit name or None")
            if suit is not None and suit != NO_TRUMP_BID:
                suit = _as_suit(suit)
        if self.cfg.trading.bid_style == "suit" and c.trump and suit is None:
            suit = NO_TRUMP_BID  # "без козыря"
        unit = self._bid_unit(contract, suit)
        if unit <= self._current_high_index():
            raise IllegalAction(f"bid {contract!r} is not higher than the current bid")
        if (
            c.is_mizer
            and self.cfg.trading.mizer_is_kabala
            and (player_id in self._bids or player_id in self._passed)
        ):
            raise IllegalAction(
                "мизер is кабальная: it may only be a player's first bid of the deal"
            )
        self._bids[player_id] = contract
        self._bid_suits[player_id] = suit
        self._high_contract = contract
        self._high_suit = suit
        self._high_bidder = player_id
        self._log(f"игрок {player_id} объявляет {contract}"
                  + (f" {suit}" if suit else ""))
        self._current_bidder = self._next_bidder(player_id)
        self._end_trading_if_done()

    def _do_here(self, player_id: int) -> None:
        if not self.cfg.trading.allow_here_bid:
            raise IllegalAction("'here' bids are disabled by config")
        if self._high_bidder is None or self._high_bidder == player_id:
            raise IllegalAction("'here' requires the opponent to hold the high bid")
        remaining = self._remaining_bidders()
        if len(remaining) != 2:
            raise IllegalAction("'here' is only allowed with two bidders left")
        if not self._is_senior(player_id, self._high_bidder):
            raise IllegalAction("'here' is only allowed on the senior hand")
        self._log(f"игрок {player_id} говорит «здесь»")
        self._declare_winner(player_id, self._high_contract, self._high_suit)

    def _end_trading_if_done(self) -> None:
        remaining = self._remaining_bidders()
        if not remaining:
            if self.cfg.trading.raspas_on_all_pass:
                self._start_raspas()
            else:
                raise IllegalAction("all passed but raspasy are disabled by config")
            return
        if (
            len(remaining) == 1
            and len(self._passed) >= self.cfg.trading.ends_after_passes
            and remaining[0] in self._bids
        ):
            self._declare_winner(remaining[0], self._bids[remaining[0]],
                                 self._bid_suits[remaining[0]])

    def _declare_winner(self, player: int, contract: str, suit) -> None:
        self._declarer = player
        self._traded_contract = contract
        self._traded_suit = suit
        self._log(f"торговлю выигрывает {player} с заявкой {contract}"
                  + (f" {suit}" if suit else ""))
        c = self.cfg.contract(contract)
        self._set_mizer_whistlers()
        if c.is_mizer:
            if c.takes_prikup:
                self._take_prikup()
                self.phase = Phase.DISCARDING
                self._log(f"мизерист {player} берёт прикуп и сносит две карты")
            else:
                self._begin_play(None)
        else:
            if c.takes_prikup:
                self._take_prikup()
                self.phase = Phase.DISCARDING
                self._log(f"игрок {player} берёт прикуп и сносит две карты")
            else:
                self.phase = Phase.ORDERING
                self._log(f"игрок {player} заказывает игру без прикупа")

    def _set_mizer_whistlers(self) -> None:
        # Opponents always defend a мизер; no whist decision is asked.
        if self._declarer is not None:
            first = self.next_active(self._declarer)
            second = self.next_active(first)
            self._whistlers = [first, second]
            self._passers = []

    def _take_prikup(self) -> None:
        self._prikup_revealed = True
        self._hands[self._declarer] = list(self._hands[self._declarer]) + list(self._prikup)
        self._log(f"прикуп открыт: {' '.join(str(c) for c in self._prikup)}")

    def _start_raspas(self) -> None:
        self._is_raspas = True
        self._trump = None
        self.phase = Phase.PLAYING
        self._log("все спасовали — распасы (без козыря)")
        self._begin_play(self.next_active(self._dealer))

    # ------------------------------------------------------------------ prikup

    def _raspas_prikup_used(self) -> bool:
        return (
            self._is_raspas
            and self.cfg.raspas.prikup_mode in (PRIKUP_LEADS_SUIT_ONLY, PRIKUP_PARTICIPATES)
            and self._prikup is not None
            and len(self._prikup) > 0
        )

    def discard(self, player_id: int, card1, card2) -> None:
        self._check_phase(Phase.DISCARDING)
        self._check_player(player_id)
        if player_id != self._declarer:
            raise IllegalAction("only the declarer discards")
        c1 = _as_card(card1)
        c2 = _as_card(card2)
        if c1 == c2:
            raise IllegalAction("cannot discard the same card twice")
        hand = self._hands[player_id]
        if c1 not in hand or c2 not in hand:
            raise IllegalAction("both discarded cards must be in hand")
        hand.remove(c1)
        hand.remove(c2)
        self._discards = [c1, c2]
        self._log(f"снос {player_id}: {c1} {c2}")
        if self.cfg.contract(self._traded_contract).is_mizer:
            self._begin_play(None)
        else:
            self.phase = Phase.ORDERING
            self._log(f"игрок {player_id} заказывает игру")

    # ------------------------------------------------------------------ order

    def order(self, player_id: int, contract: str, trump: Optional[Suit] = None) -> None:
        """Declare the final contract and trump suit (``trump=None`` = без козыря).
        Only needed for trump games."""
        self._check_phase(Phase.ORDERING)
        self._check_player(player_id)
        if player_id != self._declarer:
            raise IllegalAction("only the declarer orders the game")
        if contract not in self.cfg.orderable_from(self._traded_contract):
            raise IllegalAction(
                f"cannot order {contract!r} after trading {self._traded_contract!r}"
            )
        c = self.cfg.contract(contract)
        if not c.trump:
            if trump is not None:
                raise IllegalAction(f"contract {contract!r} has no trump suit")
        else:
            if trump is not None and _as_suit(trump) is None:
                raise IllegalAction("trump must be a Suit, a suit name or None (без козыря)")
            if trump is not None:
                trump = _as_suit(trump)
            if not self._order_option_legal(contract, trump):
                raise IllegalAction(
                    f"order {trump} is lower than the traded suit of the same level"
                )
        self._ordered_contract = contract
        self._ordered_trump = trump
        self._log(f"заказ: {contract}"
                  + (f" с козырем {trump}" if trump else " без козыря"))
        if (
            self.cfg.contract(contract).kind == "game_bp"
            and self.cfg.whist.whist_on_without_prikup
        ):
            self._auto_whist()
        else:
            self._start_whist()

    # ------------------------------------------------------------------ whist

    def _start_whist(self) -> None:
        self.phase = Phase.WHIST
        first = self.next_active(self._declarer)
        second = self.next_active(first)
        self._whist_order = [first, second]
        self._whist_current = first
        self._log(f"вист: решают {first} и {second}")

    def _auto_whist(self) -> None:
        first = self.next_active(self._declarer)
        second = self.next_active(first)
        self._whistlers = [first, second]
        self._passers = []
        self._log("вист (обязательный) на обоих противников")
        self._begin_play(self._first_leader())

    def _min_whistlers(self) -> int:
        return self.cfg.min_whistlers(self.cfg.contract(self.contract()).tricks)

    def whist(self, player_id: int, choice: str) -> None:
        self._check_phase(Phase.WHIST)
        self._check_player(player_id)
        if player_id != self._whist_current:
            raise IllegalAction(f"not {player_id}'s turn to decide whist")
        if choice not in ("whist", "pass"):
            raise IllegalAction("whist choice must be 'whist' or 'pass'")
        decided = list(self._whist_choices)
        whistlers_now = sum(1 for c in self._whist_choices.values() if c == "whist")
        remaining_after = len(self._whist_order) - len(decided) - 1
        if (
            choice == "pass"
            and whistlers_now + remaining_after < self._min_whistlers()
        ):
            raise IllegalAction("too few whistlers - 'pass' is not allowed here")
        self._whist_choices[player_id] = choice
        self._log(f"игрок {player_id}: {'вист' if choice == 'whist' else 'пас'}")
        idx = self._whist_order.index(player_id)
        if idx + 1 < len(self._whist_order):
            self._whist_current = self._whist_order[idx + 1]
            return
        self._whistlers = [p for p, c in self._whist_choices.items() if c == "whist"]
        self._passers = [p for p, c in self._whist_choices.items() if c == "pass"]
        if not self._whistlers:
            self._resolve_without_whist()
        else:
            self._begin_play(self._first_leader())

    def _resolve_without_whist(self) -> None:
        c = self.cfg.contract(self.contract())
        result = sc.HandResult(declarer=self._declarer, contract=self.contract())
        result.log("оба противника спасуют — разыгрывающий получает контракт")
        result.delta(self._declarer).pool += c.value
        self._finish_hand(result)

    # ------------------------------------------------------------------ play

    def _begin_play(self, first_leader: int) -> None:
        self.phase = Phase.PLAYING
        self._trump = self._ordered_trump if not self._is_raspas else None
        self._trick_number = 0
        self._prikup_led_count = 0
        self._tricks_taken = {p: [] for p in self._active}
        self._start_trick(first_leader)

    def _first_leader(self) -> int:
        if self._is_raspas:
            return self.next_active(self._dealer)
        if self.cfg.play.first_lead == "leftmost_whistler" and self._whistlers:
            return self._whistlers[0]
        return self.next_active(self._declarer)

    def _start_trick(self, leader: int) -> None:
        self._trick_number += 1
        self._trick_plays = []
        self._prikup_lead_card = None
        self._trick_led_suit = None
        if (
            self._raspas_prikup_used()
            and self._prikup_led_count < len(self._prikup)
        ):
            card = self._prikup[self._prikup_led_count]
            self._prikup_led_count += 1
            self._prikup_lead_card = card
            self._trick_led_suit = card.suit
            self._trick_leader = None  # prikup leads
            self._log(f"взятка {self._trick_number}: прикуп ходит {card}")
        else:
            self._trick_leader = leader
            self._log(f"взятка {self._trick_number}: ходит {leader}")

    def _playing_order(self) -> List[int]:
        if self._trick_leader is None:
            first = self.next_active(self._dealer)
            return [first, self.next_active(first), self.next_active(self.next_active(first))]
        return [
            self._trick_leader,
            self.next_active(self._trick_leader),
            self.next_active(self.next_active(self._trick_leader)),
        ]

    def _playing_player(self) -> int:
        return self._playing_order()[len(self._trick_plays)]

    def play(self, player_id: int, card) -> None:
        self._check_phase(Phase.PLAYING)
        self._check_player(player_id)
        if player_id != self._playing_player():
            raise IllegalAction(f"not {player_id}'s turn to play")
        c = _as_card(card)
        legal = self.available_plays(player_id)
        if c not in legal:
            raise IllegalAction(f"cannot play {c}; legal: {[str(x) for x in legal]}")
        self._hands[player_id].remove(c)
        self._trick_plays.append((player_id, c))
        if self._trick_led_suit is None:
            self._trick_led_suit = c.suit
        if len(self._trick_plays) == 3:
            self._resolve_trick()

    def _resolve_trick(self) -> None:
        candidates = list(self._trick_plays)
        if (
            self._prikup_lead_card is not None
            and self.cfg.raspas.prikup_mode == PRIKUP_PARTICIPATES
        ):
            candidates.append((_PRIKUP_OWNER, self._prikup_lead_card))
        winner, wcard = max(
            candidates, key=lambda pc: _weight(pc[1], self._trump, self._trick_led_suit)
        )
        self._log(
            f"взятка {self._trick_number}: "
            + " ".join(f"{p}={c}" for p, c in self._trick_plays)
            + f" -> взял {winner} ({wcard})"
        )
        if winner is not _PRIKUP_OWNER:
            self._tricks_taken[winner].append([c for _, c in self._trick_plays])
        else:
            self._log(f"взятку {self._trick_number} берёт прикуп")
        if self._trick_number >= self.cfg.cards_per_player:
            self._score_hand()
            return
        if self._raspas_prikup_used() and self._prikup_led_count < len(self._prikup):
            self._start_trick(self._first_leader())
            return
        next_leader = (
            self.next_active(self._dealer) if winner is _PRIKUP_OWNER else winner
        )
        self._start_trick(next_leader)

    # ------------------------------------------------------------- scoring

    def _trick_counts(self) -> Dict[int, int]:
        return {p: len(ts) for p, ts in self._tricks_taken.items()}

    def _score_hand(self) -> None:
        counts = self._trick_counts()
        if self._is_raspas:
            result = sc.score_raspas(
                self.cfg, self._active, counts, self._raspas_streak, self.hand_number
            )
            self._raspas_streak += 1
        else:
            self._raspas_streak = 0
            result = sc.score_game(
                self.cfg,
                self.contract(),
                self._declarer,
                self._whistlers,
                self._passers,
                counts,
                self._dealer,
                self._active,
            )
        self._finish_hand(result)

    def _finish_hand(self, result: sc.HandResult) -> None:
        self._result = result
        self.history.append(result)
        for p, d in result.deltas.items():
            self.scores[p].apply(d)
        self._log(
            "ИТОГ: "
            + ", ".join(
                f"P{p}: пулька {self.scores[p].pool} гора {self.scores[p].mountain} "
                f"висты {self.scores[p].whists:+d}"
                for p in range(self.num_players)
            )
        )
        for note in result.notes:
            self._log("  " + note)
        if sc.game_is_over(self.cfg, self.scores, self.hand_number):
            self.phase = Phase.GAME_OVER
            self._log("игра окончена")
        else:
            self.phase = Phase.HAND_DONE

    def result(self) -> Optional[sc.HandResult]:
        return self._result

    # ------------------------------------------------------------- queries

    def available_bids(self, player_id: int) -> List[dict]:
        """Legal trading actions for ``player_id`` as a list of dicts."""
        if self.phase != Phase.TRADING or player_id != self._current_bidder:
            return []
        opts: List[dict] = [{"type": "pass"}]
        high = self._current_high_index()
        for name in self.cfg.ladder():
            c = self.cfg.contract(name)
            if (
                c.is_mizer
                and self.cfg.trading.mizer_is_kabala
                and (player_id in self._bids or player_id in self._passed)
            ):
                continue
            if self.cfg.trading.bid_style == "suit" and c.trump:
                for option in TRUMP_OPTIONS:
                    if self._bid_unit(name, option) > high:
                        opts.append({
                            "type": "bid",
                            "contract": name,
                            "suit": None if option is None else option.name,
                        })
            else:
                if self._bid_unit(name, None) > high:
                    opts.append({"type": "bid", "contract": name})
        remaining = self._remaining_bidders()
        if (
            self.cfg.trading.allow_here_bid
            and len(remaining) == 2
            and self._high_bidder not in (None, player_id)
            and self._is_senior(player_id, self._high_bidder)
        ):
            opts.append({
                "type": "here",
                "contract": self._high_contract,
                "suit": _suit_to_name(self._high_suit),
            })
        return opts

    def available_whists(self, player_id: int) -> List[str]:
        if self.phase != Phase.WHIST or player_id != self._whist_current:
            return []
        decided = list(self._whist_choices)
        whistlers_now = sum(1 for c in self._whist_choices.values() if c == "whist")
        remaining_after = len(self._whist_order) - len(decided) - 1
        opts = ["whist"]
        if whistlers_now + remaining_after >= self._min_whistlers():
            opts.append("pass")
        return opts

    def _order_option_legal(self, name: str, trump) -> bool:
        """Whether ordering ``name`` with trump ``trump`` is allowed after the
        traded bid (same-level suit must not be lower than the traded suit)."""
        if (
            self.cfg.trading.bid_style == "suit"
            and self.cfg.trading.order_must_be_ge_bid
            and name == self._traded_contract
            and self._traded_suit is not None
            and _suit_rank(trump) < _suit_rank(self._traded_suit)
        ):
            return False
        return True

    def available_orders(self, player_id: int) -> List[dict]:
        if self.phase != Phase.ORDERING or player_id != self._declarer:
            return []
        opts: List[dict] = []
        for name in self.cfg.orderable_from(self._traded_contract):
            c = self.cfg.contract(name)
            if c.trump:
                for option in TRUMP_OPTIONS:
                    if not self._order_option_legal(name, option):
                        continue
                    opts.append({
                        "contract": name,
                        "trump": None if option is None else option.name,
                    })
            else:
                opts.append({"contract": name, "trump": None})
        return opts

    def available_discards(self, player_id: int) -> List[Tuple[Card, Card]]:
        if self.phase != Phase.DISCARDING or player_id != self._declarer:
            return []
        hand = self._hands[player_id]
        return [(a, b) for i, a in enumerate(hand) for b in hand[i + 1:]]

    def available_plays(self, player_id: int) -> List[Card]:
        if self.phase != Phase.PLAYING or player_id != self._playing_player():
            return []
        hand = self._hands[player_id]
        led = self._trick_led_suit
        if led is None:
            return sort_hand(hand)
        follow = [c for c in hand if c.suit is led]
        if follow:
            return sort_hand(follow)
        if self.cfg.play.trump_if_cannot_follow and self._trump is not None:
            trumps = [c for c in hand if c.suit is self._trump]
            if trumps:
                return sort_hand(trumps)
        return sort_hand(hand)

    # ------------------------------------------------------------- views

    def state(self, player_id: int) -> dict:
        """Legal view of the game for one player (their hand + public info)."""
        self._check_player(player_id)
        return {
            "phase": self.phase.value,
            "hand_number": self.hand_number,
            "dealer": self._dealer,
            "active_players": self._active,
            "names": self.names,
            "you": player_id,
            "current_player": self.current_player(),
            "your_hand": [str(c) for c in self.hand_of(player_id)],
            "declarer": self._declarer,
            "traded_contract": self._traded_contract,
            "ordered_contract": self._ordered_contract,
            "trump": self._trump.name if self._trump else None,
            "is_raspas": self._is_raspas,
            "prikup": [str(c) for c in self.prikup()] if self._prikup_revealed else None,
            "bids": self._bids_public(),
            "whistlers": self._whistlers,
            "passers": self._passers,
            "trick_number": self._trick_number,
            "current_trick": [(p, str(c)) for p, c in self._trick_plays],
            "tricks_taken": {p: len(ts) for p, ts in self._tricks_taken.items()},
            "scores": self._scores_public(),
            "legal_actions": self._legal_actions(player_id),
        }

    def _bids_public(self) -> Dict[str, list]:
        return {
            str(p): [c, _suit_to_name(self._bid_suits.get(p))]
            for p, c in self._bids.items()
        }

    def _scores_public(self) -> Dict[str, dict]:
        return {
            str(p): {"pool": s.pool, "mountain": s.mountain, "whists": s.whists}
            for p, s in self.scores.items()
        }

    def _legal_actions(self, player_id: int) -> List[dict]:
        if self.phase == Phase.TRADING:
            return self.available_bids(player_id)
        if self.phase == Phase.WHIST:
            return [{"type": c} for c in self.available_whists(player_id)]
        if self.phase == Phase.DISCARDING:
            return {"type": "discard_two_cards",
                    "options": len(self.available_discards(player_id))}
        if self.phase == Phase.ORDERING:
            return self.available_orders(player_id)
        if self.phase == Phase.PLAYING:
            return [{"type": "play",
                     "cards": [str(c) for c in self.available_plays(player_id)]}]
        return []

    def debug_snapshot(self) -> dict:
        """Full internal state, including every player's hand - for debugging."""
        return {
            "phase": self.phase.value,
            "hand_number": self.hand_number,
            "dealer": self._dealer,
            "active_players": self._active,
            "names": self.names,
            "hands": {
                p: [str(c) for c in sort_hand(self._hands.get(p, []))]
                for p in range(self.num_players)
            },
            "prikup": [str(c) for c in self.prikup()],
            "prikup_revealed": self._prikup_revealed,
            "bids": self._bids_public(),
            "passed": sorted(self._passed),
            "current_bidder": self._current_bidder,
            "high_bid": [self._high_contract, _suit_to_name(self._high_suit)],
            "declarer": self._declarer,
            "traded_contract": self._traded_contract,
            "ordered_contract": self._ordered_contract,
            "trump": self._trump.name if self._trump else None,
            "discards": [str(c) for c in self._discards],
            "whistlers": self._whistlers,
            "passers": self._passers,
            "whist_choices": self._whist_choices,
            "is_raspas": self._is_raspas,
            "trick_number": self._trick_number,
            "trick_leader": self._trick_leader,
            "trick_led_suit": self._trick_led_suit.name if self._trick_led_suit else None,
            "current_trick": [(p, str(c)) for p, c in self._trick_plays],
            "prikup_lead_card": str(self._prikup_lead_card) if self._prikup_lead_card else None,
            "tricks_taken": {p: len(ts) for p, ts in self._tricks_taken.items()},
            "raspas_streak": self._raspas_streak,
            "scores": self._scores_public(),
            "game_over": self.phase == Phase.GAME_OVER,
        }

    def render(self) -> str:
        """Human readable text snapshot of the table (console debugging)."""
        lines = [
            f"=== hand {self.hand_number} | {self.phase.value} ===",
            f"dealer: {self._dealer} | active: {self._active}",
        ]
        if self._is_raspas:
            lines.append("RASPASY (no trump)")
        else:
            lines.append(
                f"declarer: {self._declarer} | contract: {self.contract()}"
                f" | trump: {self._trump}"
            )
        for p in range(self.num_players):
            hand = " ".join(str(c) for c in sort_hand(self._hands.get(p, [])))
            s = self.scores[p]
            lines.append(
                f"  P{p} {self.names[p]:<12} [{hand}] "
                f"пуля {s.pool} гора {s.mountain} висты {s.whists:+d}"
            )
        if self._prikup is not None:
            shown = self._prikup_revealed
            lines.append(
                f"  prikup: {' '.join(str(c) for c in self._prikup)}"
                + (" (shown)" if shown else " (hidden)")
            )
        if self._trick_plays:
            lines.append("  trick: " + " ".join(f"{p}={c}" for p, c in self._trick_plays))
        return "\n".join(lines)


def _as_card(value) -> Card:
    if isinstance(value, Card):
        return value
    if isinstance(value, str):
        return parse_card(value)
    raise IllegalAction(f"cannot interpret {value!r} as a card")


def _as_suit(value):
    """Resolve a suit from a ``Suit`` or a suit name/symbol/letter string."""
    return parse_suit(value)


def _suit_to_name(value) -> Optional[str]:
    if value is None or value == NO_TRUMP_BID:
        return None
    return value.name
