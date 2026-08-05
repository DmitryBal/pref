"""Card model for Russian Preferans.

The game uses a shortened 32-card deck: four suits, ranks 7..A.
Suit seniority (low -> high) for bidding / ordering is: spades, clubs,
diamonds, hearts (the standard Russian ordering of ``пики, трефы, бубны,
червы``).  Card strength inside a trick is by rank only, Ace being highest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple


class Suit:
    """A playing-card suit.  Instances are interned; use the class constants."""

    __slots__ = ("name", "symbol", "order")

    def __init__(self, name: str, symbol: str, order: int) -> None:
        self.name = name
        self.symbol = symbol
        self.order = order

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Suit({self.name})"

    def __str__(self) -> str:
        return self.symbol

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Suit) and other.name == self.name


SPADES = Suit("spades", "\u2660", 0)
CLUBS = Suit("clubs", "\u2663", 1)
DIAMONDS = Suit("diamonds", "\u2666", 2)
HEARTS = Suit("hearts", "\u2665", 3)

SUITS: Tuple[Suit, ...] = (SPADES, CLUBS, DIAMONDS, HEARTS)

# Canonical order of suits by seniority in preferans bidding (low -> high).
SUIT_ORDER: Tuple[Suit, ...] = (SPADES, CLUBS, DIAMONDS, HEARTS)

_SUIT_BY_NAME = {s.name: s for s in SUITS}
_SUIT_BY_SYMBOL = {s.symbol: s for s in SUITS}


class Rank:
    """A card rank.  ``value`` is 7..14 (7 .. Ace) and is used for strength."""

    __slots__ = ("name", "label", "value")

    def __init__(self, name: str, label: str, value: int) -> None:
        self.name = name
        self.label = label
        self.value = value

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Rank({self.name})"

    def __str__(self) -> str:
        return self.label

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Rank) and other.name == self.name


SEVEN = Rank("seven", "7", 7)
EIGHT = Rank("eight", "8", 8)
NINE = Rank("nine", "9", 9)
TEN = Rank("ten", "10", 10)
JACK = Rank("jack", "J", 11)
QUEEN = Rank("queen", "Q", 12)
KING = Rank("king", "K", 13)
ACE = Rank("ace", "A", 14)

# Canonical order of ranks by strength, low -> high.
RANK_ORDER: Tuple[Rank, ...] = (SEVEN, EIGHT, NINE, TEN, JACK, QUEEN, KING, ACE)

_RANK_BY_NAME = {r.name: r for r in RANK_ORDER}
_RANK_BY_LABEL = {r.label: r for r in RANK_ORDER}


@dataclass(frozen=True)
class Card:
    """A single card, identified by suit and rank."""

    suit: Suit
    rank: Rank

    def __hash__(self) -> int:
        return hash((self.suit.name, self.rank.name))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Card)
            and other.suit is self.suit
            and other.rank is self.rank
        )

    def __lt__(self, other: "Card") -> bool:
        # Order primarily by rank for hand display; suits as a tiebreak.
        if self.rank.value != other.rank.value:
            return self.rank.value < other.rank.value
        return self.suit.order < other.suit.order

    def __str__(self) -> str:
        return f"{self.rank.label}{self.suit.symbol}"

    def __repr__(self) -> str:
        return f"Card({self.rank.name}, {self.suit.name})"

    def to_code(self) -> str:
        """Short stable string code, e.g. ``"7S"``, ``"10H"``, ``"AC"``."""
        return f"{self.rank.label}{self.suit.name[0].upper()}"

    def same_suit(self, other: "Card") -> bool:
        return self.suit is other.suit


def full_deck() -> List[Card]:
    """Return the 32-card preferans deck (not shuffled)."""
    return [Card(suit, rank) for suit in SUITS for rank in RANK_ORDER]


def parse_card(text: str) -> Card:
    """Parse a card from a code such as ``"7S"``, ``"10H"`` or ``"A\u2665"``.

    The rank is the leading number / letter, the suit is the trailing letter
    (S/C/D/H) or suit symbol.
    """
    text = text.strip()
    if not text:
        raise ValueError("empty card string")
    # A trailing suit symbol is unambiguous.
    if text[-1] in _SUIT_BY_SYMBOL:
        suit = _SUIT_BY_SYMBOL[text[-1]]
        rank_txt = text[:-1]
    else:
        suit_letter = text[-1].upper()
        suit = {
            "S": SPADES,
            "C": CLUBS,
            "D": DIAMONDS,
            "H": HEARTS,
        }.get(suit_letter)
        if suit is None:
            raise ValueError(f"unknown suit in {text!r}")
        rank_txt = text[:-1]
    if rank_txt not in _RANK_BY_LABEL:
        raise ValueError(f"unknown rank in {text!r}")
    return Card(suit, _RANK_BY_LABEL[rank_txt])


def to_cards(texts: Iterable[str]) -> List[Card]:
    return [parse_card(t) for t in texts]


def parse_suit(value) -> Optional[Suit]:
    """Resolve a suit from a ``Suit``, its name (``"hearts"``), its symbol
    (``"\\u2665"``) or the letter ``"H"``.  Returns None for invalid input."""
    if isinstance(value, Suit):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text == "nt":
        return None
    if text in _SUIT_BY_SYMBOL:
        return _SUIT_BY_SYMBOL[text]
    if text in _SUIT_BY_NAME:
        return _SUIT_BY_NAME[text]
    return {
        "s": SPADES,
        "c": CLUBS,
        "d": DIAMONDS,
        "h": HEARTS,
    }.get(text)


def sort_hand(cards: Iterable[Card]) -> List[Card]:
    """Sort cards by suit (spades..hearts) then rank (7..A), preferans style."""
    return sorted(cards, key=lambda c: (c.suit.order, c.rank.value))


def describe(cards: Iterable[Card]) -> str:
    return " ".join(str(c) for c in sort_hand(cards))
