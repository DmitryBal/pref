"""Configuration for the Preferans engine.

The rules of preferans have many widely-accepted variations (some of them
covered by the official ``Кодекс преферанса``, many more being local
"agreements" / ``по договорённости``).  All of these knobs live in a YAML
file; this module loads and validates it and exposes a typed :class:`Config`.

The shipped ``config/default.yaml`` implements the **Сочинка** convention with
four players as a sensible starting point.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

import yaml

from .cards import SUIT_ORDER

CONTRACT_KIND_GAME = "game"  # takes N tricks, trump chosen at order
CONTRACT_KIND_GAME_BP = "game_bp"  # same but the prikup is NOT taken
CONTRACT_KIND_MIZER = "mizer"  # take zero tricks, takes prikup
CONTRACT_KIND_MIZER_BP = "mizer_bp"  # take zero tricks, no prikup

KIND_IS_GAME = {CONTRACT_KIND_GAME, CONTRACT_KIND_GAME_BP}
KIND_IS_MIZER = {CONTRACT_KIND_MIZER, CONTRACT_KIND_MIZER_BP}

BID_STYLE_LEVEL = "level"
BID_STYLE_SUIT = "suit"

WHIST_SOCHE = "soche"
WHIST_LENINGRAD = "leningrad"

RASPAS_MOUNTAIN = "mountain"
RASPAS_ROSTOV = "rostov"

PROG_CONSTANT = "constant"
PROG_ARITHMETIC = "arithmetic"
PROG_GEOMETRIC = "geometric"

PRIKUP_IGNORED = "ignored"
PRIKUP_LEADS_SUIT_ONLY = "leads_suit_only"
PRIKUP_PARTICIPATES = "participates"

SETTLE_TO_WHISTS = "to_whists"
SETTLE_TO_MOUNTAIN_DOUBLE = "to_mountain_double"

END_POOL_PER_PLAYER = "pool_per_player"
END_POOL_SUM = "pool_sum"
END_HANDS = "hands"
END_NONE = "none"

FIRST_VOICE_LEFT_OF_DEALER = "left_of_dealer"


class ConfigError(ValueError):
    """Raised when the YAML configuration is invalid."""


@dataclass
class Contract:
    """A contract that can be traded / ordered and then played."""

    name: str
    tricks: int  # number of tricks the declarer must take (0 for mizer)
    kind: str  # one of the CONTRACT_KIND_* constants
    takes_prikup: bool
    trump: bool  # whether a trump suit is chosen at the order stage
    value: int  # pool points on success; mountain points per missed trick
    whist_per_trick: int  # whists each whistler writes per taken trick
    whist_obligation: int  # tricks the whistling side must take
    label_ru: str = ""

    @property
    def is_mizer(self) -> bool:
        return self.kind in KIND_IS_MIZER

    @property
    def is_game(self) -> bool:
        return self.kind in KIND_IS_GAME


@dataclass
class TradingConfig:
    bid_style: str = BID_STYLE_LEVEL
    # Ordered list of contract names, ascending seniority.  In "level" style
    # the suit is not part of the bid; in "suit" style each step expands into
    # (level, suit) with suits ordered spades < clubs < diamonds < hearts < NT.
    ladder: List[str] = field(default_factory=list)
    first_voice: str = FIRST_VOICE_LEFT_OF_DEALER
    pass_is_permanent: bool = True
    # Trading ends as soon as this many players have passed (Codex: 2).
    ends_after_passes: int = 2
    # If every player passes on their first word -> raspasy.
    raspas_on_all_pass: bool = True
    # "здесь": with only two bidders left the senior hand may match the
    # opponent's bid instead of raising, and wins the trade by seniority.
    allow_here_bid: bool = True
    here_bid_ends_auction: bool = True
    # "Мизер" is a "кабальная" bid: it may only be a player's very first
    # meaningful bid of the deal.
    mizer_is_kabala: bool = True
    # The declared game must not be lower than the winning bid (Codex rule).
    order_must_be_ge_bid: bool = True
    # After winning a trade with "мизер", the declarer must play мизер.
    mizer_winner_must_play_mizer: bool = True


@dataclass
class WhistConfig:
    # Minimum number of whistlers required for each declared level
    # (defenders who pass force the remaining one to whist "в одного").
    min_whistlers: Dict[int, int] = field(default_factory=dict)
    whist_on_mizer: bool = True  # opponents always defend a мизер
    whist_on_without_prikup: bool = True
    # whist calculation style: soche (жлобский + ответственный) or
    # leningrad (джентльменский + полуответственный).
    style: str = WHIST_SOCHE
    # Whistler shortfall penalty magnitude: "full" or "half".
    shortfall_penalty_scale: str = "full"
    # When both whistlers fail the side obligation, who pays:
    # "lower_taker" | "split" | "both".
    shortfall_responsible: str = "lower_taker"
    # Bonus whists written by each opponent for every trick the declarer
    # missed on подсад (консоляция).
    consolation_on_fail: bool = True
    consolation_amount: str = "whist_per_trick"  # or an integer
    consolation_to_passer: bool = True
    # 4-player Codex: the sitting-out dealer also writes консоляция.
    consolation_to_dealer: bool = False
    # A lone whistler writes whists for the tricks of the whole defending side.
    lone_whistler_takes_all_side_tricks: bool = True
    mizer_whists_enabled: bool = False  # whists on мизер are off in Сочинка


@dataclass
class RaspasConfig:
    no_trump: bool = True
    # "mountain": taken tricks go to гора; "rostov": the player who took the
    # least tricks writes whists on the others.
    scoring: str = RASPAS_MOUNTAIN
    price_per_trick: int = 1
    # "constant" | "arithmetic" | "geometric" - how the price grows across
    # consecutive raspasy deals.
    progression: str = PROG_CONSTANT
    progression_values: List[int] = field(default_factory=lambda: [1, 2, 4, 8, 16, 32])
    # Stop raising the price after this many consecutive raspasy deals (None =
    # keep raising forever).
    progression_cap: Optional[int] = None
    # "Амнистия": the smallest trick count is treated as zero, everyone else
    # is charged for the difference (Codex example A=3,B=5,C=2 -> C pays 0).
    amnesty: bool = True
    # Premium for taking zero tricks on raspasy (written to пулька). 0 disables.
    zero_trick_premium_pool: int = 1
    # "ignored" | "leads_suit_only" | "participates":
    #   leads_suit_only - the dealer (sitting out) leads the first two tricks
    #     with the prikup cards, which only show the suit and never win (Codex,
    #     3-player behaviour).
    #   participates - the prikup cards can win those tricks (Codex, 4-player).
    #   ignored - the prikup is not used during raspasy at all.
    prikup_mode: str = PRIKUP_LEADS_SUIT_ONLY
    prikup_shown: bool = True


@dataclass
class ScoringConfig:
    pool_to_whist: int = 10  # 1 пулька point = N whists (+20 in «Питер»)
    mountain_to_whist: int = 10  # 1 горка point = -N whists
    final_amnesty: bool = True  # subtract the smallest горка at the end
    # "to_whists": pool differences settle directly in whists;
    # "to_mountain_double": (max pool - own pool) * 2 goes to гора (Ленинград).
    pool_settlement: str = SETTLE_TO_WHISTS
    # Game end condition: pool_per_player | pool_sum | hands | none
    end_condition: str = END_POOL_PER_PLAYER
    end_target: Optional[float] = 50.0
    max_hands: Optional[int] = None


@dataclass
class PlayConfig:
    # Who leads the first trick of a trump game / мизер:
    #   left_of_declarer  - the position to the declarer's left (Codex "первая рука")
    #   leftmost_whistler - only the first whistling defender leads
    first_lead: str = "left_of_declarer"
    must_follow_suit: bool = True
    # When a player cannot follow the led suit he must play a trump if he has
    # one (only relevant when a trump suit exists).
    trump_if_cannot_follow: bool = True


@dataclass
class Config:
    variant: str = "sochinka"
    num_players: int = 4
    cards_per_player: int = 10
    prikup_size: int = 2
    # With 4 players the dealer deals and sits out ("сидит на прикупе").
    dealer_sits_out: bool = True
    # Index of the first dealer; or "by_lot" to pick randomly.
    first_dealer: str = "0"
    contracts: Dict[str, Contract] = field(default_factory=dict)
    trading: TradingConfig = field(default_factory=TradingConfig)
    whist: WhistConfig = field(default_factory=WhistConfig)
    raspas: RaspasConfig = field(default_factory=RaspasConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    play: PlayConfig = field(default_factory=PlayConfig)

    # ------------------------------------------------------------------ utils

    def contract(self, name: str) -> Contract:
        try:
            return self.contracts[name]
        except KeyError:
            raise KeyError(f"unknown contract {name!r}")

    def ladder(self) -> List[str]:
        return list(self.trading.ladder)

    def bid_rank(self, name: str) -> int:
        """Position of a contract in the bidding ladder (0 = lowest)."""
        try:
            return self.trading.ladder.index(name)
        except ValueError:
            raise ConfigError(f"contract {name!r} is not in the trading ladder")

    def min_whistlers(self, level: int) -> int:
        return self.whist.min_whistlers.get(level, 0)

    @property
    def active_players(self) -> int:
        return 3  # only three players take part in any given hand

    def orderable_from(self, traded: str) -> List[str]:
        """Contracts the declarer may order after winning a trade with
        ``traded`` (Codex: the order must not be lower than the bid)."""
        if not self.trading.order_must_be_ge_bid:
            if self.contract(traded).is_mizer:
                return [n for n in self.ladder() if self.contract(n).is_mizer]
            return [n for n in self.ladder() if self.contract(n).is_game]
        traded_rank = self.bid_rank(traded)
        traded_c = self.contract(traded)
        if traded_c.is_mizer:
            if self.trading.mizer_winner_must_play_mizer:
                return [traded]
            # otherwise: the same мизер family, not lower than the bid
            return [
                n
                for n in self.ladder()
                if self.contract(n).is_mizer and self.bid_rank(n) >= traded_rank
            ]
        # suit-game trade: order any game (incl. без-прикупа) not lower than
        # the bid in the ladder.
        return [
            n
            for n in self.ladder()
            if self.contract(n).is_game and self.bid_rank(n) >= traded_rank
        ]


# ----------------------------------------------------------------------------
# loading


_DEFAULTS_FILENAME = "default.yaml"


def default_config_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "config", _DEFAULTS_FILENAME)


def _raw_defaults() -> Dict[str, Any]:
    with open(default_config_path(), "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _build_contracts(data: Mapping[str, Any], defaults: Mapping[str, Any]) -> Dict[str, Contract]:
    dflt = dict(defaults.get("contracts") or {})
    raw = dict(data.get("contracts") or {})
    merged = {**dflt, **raw}  # user file may override individual contracts
    contracts: Dict[str, Contract] = {}
    for name, spec in merged.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"contract {name!r} must be a mapping")
        tricks = int(spec.get("tricks", 0))
        kind = spec.get("kind", CONTRACT_KIND_GAME)
        if kind == CONTRACT_KIND_MIZER:
            tricks = 0
        takes_prikup = bool(spec.get("takes_prikup", True))
        if kind in (CONTRACT_KIND_GAME_BP, CONTRACT_KIND_MIZER_BP):
            takes_prikup = False
        contracts[name] = Contract(
            name=name,
            tricks=tricks,
            kind=kind,
            takes_prikup=takes_prikup,
            trump=bool(spec.get("trump", True)),
            value=int(spec.get("value", 10)),
            whist_per_trick=int(spec.get("whist_per_trick", 10)),
            whist_obligation=int(spec.get("whist_obligation", 0)),
            label_ru=str(spec.get("label_ru", "")),
        )
    return contracts


def _merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_dict(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: Optional[str] = None) -> Config:
    """Load a configuration from a YAML file.

    If ``path`` is None the shipped ``config/default.yaml`` is used.  Any file
    may be partial: unspecified sections fall back to the defaults.
    """
    base = _raw_defaults()
    if path is None:
        data = base
    else:
        with open(path, "r", encoding="utf-8") as fh:
            user = yaml.safe_load(fh) or {}
        if not isinstance(user, dict):
            raise ConfigError("config file must contain a mapping")
        data = _merge_dict(base, user)

    cfg = Config()
    cfg.variant = str(data.get("variant", cfg.variant))
    cfg.num_players = int(data.get("num_players", cfg.num_players))
    cfg.cards_per_player = int(data.get("cards_per_player", cfg.cards_per_player))
    cfg.prikup_size = int(data.get("prikup_size", cfg.prikup_size))
    cfg.dealer_sits_out = bool(data.get("dealer_sits_out", cfg.dealer_sits_out))
    cfg.first_dealer = str(data.get("first_dealer", cfg.first_dealer))

    cfg.contracts = _build_contracts(data, base)

    tr = data.get("trading") or {}
    cfg.trading = TradingConfig(
        bid_style=tr.get("bid_style", cfg.trading.bid_style),
        ladder=[str(x) for x in (tr.get("ladder") or base["trading"]["ladder"])],
        first_voice=tr.get("first_voice", cfg.trading.first_voice),
        pass_is_permanent=bool(tr.get("pass_is_permanent", cfg.trading.pass_is_permanent)),
        ends_after_passes=int(tr.get("ends_after_passes", cfg.trading.ends_after_passes)),
        raspas_on_all_pass=bool(tr.get("raspas_on_all_pass", cfg.trading.raspas_on_all_pass)),
        allow_here_bid=bool(tr.get("allow_here_bid", cfg.trading.allow_here_bid)),
        here_bid_ends_auction=bool(tr.get("here_bid_ends_auction", cfg.trading.here_bid_ends_auction)),
        mizer_is_kabala=bool(tr.get("mizer_is_kabala", cfg.trading.mizer_is_kabala)),
        order_must_be_ge_bid=bool(tr.get("order_must_be_ge_bid", cfg.trading.order_must_be_ge_bid)),
        mizer_winner_must_play_mizer=bool(
            tr.get("mizer_winner_must_play_mizer", cfg.trading.mizer_winner_must_play_mizer)
        ),
    )

    wh = data.get("whist") or {}
    min_wh = {}
    for k, v in (wh.get("min_whistlers") or {}).items():
        if isinstance(k, str) and not k.isdigit() and k in cfg.contracts:
            level = cfg.contracts[k].tricks
        else:
            level = int(k)
        min_wh[level] = int(v)
    cfg.whist = WhistConfig(
        min_whistlers=min_wh or cfg.whist.min_whistlers,
        whist_on_mizer=bool(wh.get("whist_on_mizer", cfg.whist.whist_on_mizer)),
        whist_on_without_prikup=bool(
            wh.get("whist_on_without_prikup", cfg.whist.whist_on_without_prikup)
        ),
        style=wh.get("style", cfg.whist.style),
        shortfall_penalty_scale=wh.get("shortfall_penalty_scale", cfg.whist.shortfall_penalty_scale),
        shortfall_responsible=wh.get("shortfall_responsible", cfg.whist.shortfall_responsible),
        consolation_on_fail=bool(wh.get("consolation_on_fail", cfg.whist.consolation_on_fail)),
        consolation_amount=wh.get("consolation_amount", cfg.whist.consolation_amount),
        consolation_to_passer=bool(wh.get("consolation_to_passer", cfg.whist.consolation_to_passer)),
        consolation_to_dealer=bool(wh.get("consolation_to_dealer", cfg.whist.consolation_to_dealer)),
        lone_whistler_takes_all_side_tricks=bool(
            wh.get("lone_whistler_takes_all_side_tricks", cfg.whist.lone_whistler_takes_all_side_tricks)
        ),
        mizer_whists_enabled=bool(wh.get("mizer_whists_enabled", cfg.whist.mizer_whists_enabled)),
    )

    rs = data.get("raspas") or {}
    cfg.raspas = RaspasConfig(
        no_trump=bool(rs.get("no_trump", cfg.raspas.no_trump)),
        scoring=rs.get("scoring", cfg.raspas.scoring),
        price_per_trick=int(rs.get("price_per_trick", cfg.raspas.price_per_trick)),
        progression=rs.get("progression", cfg.raspas.progression),
        progression_values=[int(x) for x in (rs.get("progression_values") or cfg.raspas.progression_values)],
        progression_cap=rs.get("progression_cap", cfg.raspas.progression_cap),
        amnesty=bool(rs.get("amnesty", cfg.raspas.amnesty)),
        zero_trick_premium_pool=int(rs.get("zero_trick_premium_pool", cfg.raspas.zero_trick_premium_pool)),
        prikup_mode=rs.get("prikup_mode", cfg.raspas.prikup_mode),
        prikup_shown=bool(rs.get("prikup_shown", cfg.raspas.prikup_shown)),
    )

    sc = data.get("scoring") or {}
    cfg.scoring = ScoringConfig(
        pool_to_whist=int(sc.get("pool_to_whist", cfg.scoring.pool_to_whist)),
        mountain_to_whist=int(sc.get("mountain_to_whist", cfg.scoring.mountain_to_whist)),
        final_amnesty=bool(sc.get("final_amnesty", cfg.scoring.final_amnesty)),
        pool_settlement=sc.get("pool_settlement", cfg.scoring.pool_settlement),
        end_condition=sc.get("end_condition", cfg.scoring.end_condition),
        end_target=sc.get("end_target", cfg.scoring.end_target),
        max_hands=sc.get("max_hands", cfg.scoring.max_hands),
    )

    pl = data.get("play") or {}
    cfg.play = PlayConfig(
        first_lead=pl.get("first_lead", cfg.play.first_lead),
        must_follow_suit=bool(pl.get("must_follow_suit", cfg.play.must_follow_suit)),
        trump_if_cannot_follow=bool(
            pl.get("trump_if_cannot_follow", cfg.play.trump_if_cannot_follow)
        ),
    )

    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    if cfg.num_players not in (3, 4):
        raise ConfigError("num_players must be 3 or 4")
    if cfg.num_players == 4 and not cfg.dealer_sits_out:
        # The alternative "guilty" rotation is supported but the resting player
        # is the previous dealer.
        pass
    if cfg.active_players * cfg.cards_per_player + cfg.prikup_size != 32:
        raise ConfigError(
            "deck size mismatch: 3 players * %d cards + %d prikup must equal 32"
            % (cfg.cards_per_player, cfg.prikup_size)
        )
    if not cfg.trading.ladder:
        raise ConfigError("trading.ladder must list at least one contract")
    seen = set()
    for name in cfg.trading.ladder:
        if name not in cfg.contracts:
            raise ConfigError(f"ladder references unknown contract {name!r}")
        if name in seen:
            raise ConfigError(f"duplicate entry in ladder: {name!r}")
        seen.add(name)
    if cfg.trading.ends_after_passes < 1 or cfg.trading.ends_after_passes >= 3:
        raise ConfigError("trading.ends_after_passes must be 1 or 2")
    if cfg.trading.bid_style not in (BID_STYLE_LEVEL, BID_STYLE_SUIT):
        raise ConfigError(f"unknown bid_style {cfg.trading.bid_style!r}")
    if cfg.whist.style not in (WHIST_SOCHE, WHIST_LENINGRAD):
        raise ConfigError(f"unknown whist.style {cfg.whist.style!r}")
    if cfg.whist.shortfall_penalty_scale not in ("full", "half"):
        raise ConfigError("whist.shortfall_penalty_scale must be 'full' or 'half'")
    if cfg.whist.shortfall_responsible not in ("lower_taker", "split", "both"):
        raise ConfigError("whist.shortfall_responsible must be lower_taker/split/both")
    if cfg.raspas.scoring not in (RASPAS_MOUNTAIN, RASPAS_ROSTOV):
        raise ConfigError(f"unknown raspas.scoring {cfg.raspas.scoring!r}")
    if cfg.raspas.progression not in (PROG_CONSTANT, PROG_ARITHMETIC, PROG_GEOMETRIC):
        raise ConfigError(f"unknown raspas.progression {cfg.raspas.progression!r}")
    if cfg.raspas.prikup_mode not in (PRIKUP_IGNORED, PRIKUP_LEADS_SUIT_ONLY, PRIKUP_PARTICIPATES):
        raise ConfigError(f"unknown raspas.prikup_mode {cfg.raspas.prikup_mode!r}")
    if cfg.raspas.prikup_mode == PRIKUP_PARTICIPATES and cfg.num_players == 3:
        # Allowed (user's choice) but flag it, as the Codex only lets the
        # prikup win tricks in a 4-player game.
        import warnings

        warnings.warn("raspas.prikup_mode='participates' is unusual for a 3-player game")
    if cfg.scoring.end_condition not in (END_POOL_PER_PLAYER, END_POOL_SUM, END_HANDS, END_NONE):
        raise ConfigError(f"unknown scoring.end_condition {cfg.scoring.end_condition!r}")
    if cfg.play.first_lead not in ("left_of_declarer", "leftmost_whistler"):
        raise ConfigError(f"unknown play.first_lead {cfg.play.first_lead!r}")
    for name, c in cfg.contracts.items():
        if c.tricks not in (0, 6, 7, 8, 9, 10):
            raise ConfigError(
                f"contract {name!r} has unsupported trick target {c.tricks} "
                "(expected 0/6/7/8/9/10)"
            )


def suits_for_style(bid_style: str) -> List:
    """Return the list of trump options for the ordering stage.

    In both bidding styles the trump suit for the *order* may be any suit or
    "без козыря" (no trump).
    """
    return list(SUIT_ORDER) + [None]
