"""Hand scoring and final settlement for Preferans.

Three accounts per player are tracked:
  * пулька (pool) - written for played games / мизер and raspasy zero premiums;
  * горка (mountain) - penalty for подсад (missed tricks) and raspasy tricks;
  * висты (whists) - a zero-sum balance of whists written on each other.

The final result converts everything into whists using configurable rates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import (
    Config,
    RASPAS_ROSTOV,
)


@dataclass
class ScoreDelta:
    """Change of a single player's score for one hand."""

    pool: int = 0
    mountain: int = 0
    whists: int = 0  # net whist balance change (positive = earned)


@dataclass
class HandResult:
    """The outcome of one hand: per-player score deltas + a readable log."""

    deltas: Dict[int, ScoreDelta] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    declarer: Optional[int] = None
    contract: Optional[str] = None
    is_raspas: bool = False

    def log(self, line: str) -> None:
        self.notes.append(line)

    def delta(self, player: int) -> ScoreDelta:
        if player not in self.deltas:
            self.deltas[player] = ScoreDelta()
        return self.deltas[player]


def _write_whist(result: HandResult, writer: int, target: int, amount: int) -> None:
    """Player ``writer`` writes ``amount`` whists on ``target``."""
    if amount == 0:
        return
    result.delta(writer).whists += amount
    result.delta(target).whists -= amount


def _consolation_amount(cfg: Config, contract_name: str) -> int:
    amount = cfg.whist.consolation_amount
    if isinstance(amount, int):
        return amount
    return cfg.contract(contract_name).whist_per_trick


def raspas_price(cfg: Config, raspas_index: int) -> int:
    """Price charged per (amnestied) trick on the ``raspas_index``-th
    consecutive raspasy deal (0 = first)."""
    price = cfg.raspas.price_per_trick
    if cfg.raspas.progression == "constant":
        return price
    values = list(cfg.raspas.progression_values or [])
    cap = cfg.raspas.progression_cap
    if cap is not None:
        raspas_index = min(raspas_index, max(0, cap - 1))
    if not values:
        values = [1, 2, 4, 8, 16, 32]
    if cfg.raspas.progression == "geometric":
        return price * values[min(raspas_index, len(values) - 1)]
    # arithmetic
    step = values[1] - values[0] if len(values) > 1 else 1
    return price + (values[0] - price) + step * raspas_index


def score_raspas(
    cfg: Config,
    active: List[int],
    tricks: Dict[int, int],
    raspas_index: int,
    hand_no: int,
) -> HandResult:
    """Score a raspasy deal.  ``tricks`` maps player -> taken tricks."""
    result = HandResult(is_raspas=True)
    result.log(f"распасы #{hand_no}: " + ", ".join(f"P{p}={n}" for p, n in tricks.items()))

    price = raspas_price(cfg, raspas_index)
    if cfg.raspas.scoring == RASPAS_ROSTOV:
        # Ростов: the player who took the fewest tricks writes whists on the
        # others (the fewest-taker is the beneficiary).
        least = min(tricks.values())
        best = [p for p in active if tricks[p] == least]
        result.log(f"наименьшее число взяток: {least} (игроки {best})")
        for b in best:
            for p in active:
                diff = tricks[p] - least
                if diff > 0:
                    _write_whist(result, b, p, diff * price)
        return result

    # mountain scoring
    base = 0
    if cfg.raspas.amnesty:
        base = min(tricks[p] for p in active) if active else 0
        result.log(f"амнистия: минимальные взятки {base} принимаются за 0")
    for p in active:
        net = max(0, tricks[p] - base)
        amount = net * price
        result.delta(p).mountain += amount
        result.log(f"игрок {p}: {net} взяток -> горка +{amount}")
        if tricks[p] == 0 and cfg.raspas.zero_trick_premium_pool:
            result.delta(p).pool += cfg.raspas.zero_trick_premium_pool
            result.log(f"игрок {p}: 0 взяток -> пулька +{cfg.raspas.zero_trick_premium_pool}")
    return result


def score_game(
    cfg: Config,
    contract_name: str,
    declarer: int,
    whistlers: List[int],
    passers: List[int],
    tricks: Dict[int, int],
    dealer: int,
    active_players: List[int],
) -> HandResult:
    """Score a trump game or мизер.

    ``tricks`` maps every active player to the number of tricks taken.
    """
    c = cfg.contract(contract_name)
    result = HandResult(declarer=declarer, contract=contract_name)
    result.log(f"контракт: {contract_name}, разыгрывающий {declarer}")

    declarer_tricks = tricks.get(declarer, 0)
    side_tricks = sum(tricks[p] for p in whistlers + passers if p in tricks)
    whistler_tricks = sum(tricks[w] for w in whistlers if w in tricks)

    if c.is_mizer:
        return _score_mizer(cfg, result, c, declarer, whistlers,
                            declarer_tricks, tricks, dealer, active_players)

    missed = max(0, c.tricks - declarer_tricks)
    result.log(f"игрок {declarer} взял {declarer_tricks}/{c.tricks} "
               f"(недобор {missed})")
    if missed == 0:
        result.delta(declarer).pool += c.value
        result.log(f"игра сыграна: пулька {declarer} +{c.value}")
    else:
        amount = c.value * missed
        result.delta(declarer).mountain += amount
        result.log(f"подсад: горка {declarer} +{amount}")

    # ---- whistlers write whists for the tricks they took -----------------
    if len(whistlers) == 1 and cfg.whist.lone_whistler_takes_all_side_tricks:
        w = whistlers[0]
        amount = c.whist_per_trick * side_tricks
        _write_whist(result, w, declarer, amount)
        result.log(f"вистующий {w} (в одного) пишет висты {amount}")
    else:
        for w in whistlers:
            amount = c.whist_per_trick * tricks.get(w, 0)
            _write_whist(result, w, declarer, amount)
            result.log(f"вистующий {w} пишет висты {amount}")

    # ---- консоляция on подсад -------------------------------------------
    if missed > 0 and cfg.whist.consolation_on_fail:
        cons = _consolation_amount(cfg, contract_name) * missed
        writers = list(whistlers)
        if cfg.whist.consolation_to_passer:
            writers += list(passers)
        for w in writers:
            _write_whist(result, w, declarer, cons)
            result.log(f"консоляция: {w} пишет на {declarer} {cons}")
        if cfg.whist.consolation_to_dealer and dealer not in active_players:
            # only a sitting-out dealer (4-player game) writes консоляция
            _write_whist(result, dealer, declarer, cons)
            result.log(f"консоляция: сдающий {dealer} пишет на {declarer} {cons}")

    # ---- whistling side obligation ---------------------------------------
    # The obligation rests on the whistlers alone: a passer's tricks do not
    # help the whistling side (a lone whistler must take them "в одного").
    obligation = c.whist_obligation
    if obligation > 0 and whistlers:
        short = obligation - whistler_tricks
        if short > 0:
            _apply_whist_shortfall(cfg, result, c, whistlers, tricks, short)
    return result


def _apply_whist_shortfall(
    cfg: Config,
    result: HandResult,
    c,
    whistlers: List[int],
    tricks: Dict[int, int],
    short: int,
) -> None:
    value = c.value * short
    scale = 0.5 if cfg.whist.shortfall_penalty_scale == "half" else 1.0
    if len(whistlers) == 1:
        payers = [(whistlers[0], value)]
        result.log(f"вистующий {whistlers[0]} недобрал вистовых взяток ({short})")
    elif cfg.whist.shortfall_responsible == "both":
        payers = [(w, value) for w in whistlers]
        result.log(f"оба вистующих недобрали вистовых взяток ({short})")
    elif cfg.whist.shortfall_responsible == "split":
        payers = [(w, value / len(whistlers)) for w in whistlers]
        result.log(f"вистовой недобор ({short}) делится поровну")
    else:  # lower_taker
        w_lo = min(whistlers, key=lambda w: tricks.get(w, 0))
        others = [w for w in whistlers if w != w_lo]
        if others and tricks.get(others[0], 0) == tricks.get(w_lo, 0):
            payers = [(w, value / len(whistlers)) for w in whistlers]
            result.log("взяли поровну - штраф делится")
        else:
            payers = [(w_lo, value)]
            result.log(f"меньше всех взял вистующий {w_lo}")
    for player, amount in payers:
        amount = int(round(amount * scale))
        if amount:
            result.delta(player).mountain += amount
            result.log(f"горка {player} +{amount} за вистовой недобор")


def _score_mizer(
    cfg: Config,
    result: HandResult,
    c,
    declarer: int,
    whistlers: List[int],
    declarer_tricks: int,
    tricks: Dict[int, int],
    dealer: int,
    active_players: List[int],
) -> HandResult:
    result.log(f"мизерист {declarer} взял {declarer_tricks} взяток")
    if declarer_tricks == 0:
        result.delta(declarer).pool += c.value
        result.log(f"мизер сыгран: пулька {declarer} +{c.value}")
    else:
        amount = c.value * declarer_tricks
        result.delta(declarer).mountain += amount
        result.log(f"ремиз на мизере: горка {declarer} +{amount}")
    if cfg.whist.mizer_whists_enabled:
        for w in whistlers:
            amount = c.whist_per_trick * tricks.get(w, 0)
            _write_whist(result, w, declarer, amount)
            result.log(f"вистующий {w} пишет висты {amount}")
    return result


# ---------------------------------------------------------------------------
# Final settlement
# ---------------------------------------------------------------------------


@dataclass
class PlayerScore:
    pool: int = 0
    mountain: int = 0
    whists: int = 0

    def apply(self, d: ScoreDelta) -> None:
        self.pool += d.pool
        self.mountain += d.mountain
        self.whists += d.whists


def final_settlement(cfg: Config, scores: Dict[int, PlayerScore]) -> Dict[int, float]:
    """Convert every player's pool/mountain/whists into a net whist total.

    The result is the classic "роспись пульки" with an amnesty on the горка.
    """
    n = len(scores)
    mountain = {p: s.mountain for p, s in scores.items()}
    pool = {p: s.pool for p, s in scores.items()}

    if cfg.scoring.pool_settlement == "to_mountain_double":
        max_pool = max(pool.values()) if pool else 0
        for p in pool:
            mountain[p] += (max_pool - pool[p]) * 2

    if cfg.scoring.final_amnesty:
        min_m = min(mountain.values()) if mountain else 0
        mountain = {p: m - min_m for p, m in mountain.items()}

    avg_m = sum(mountain.values()) / n if n else 0
    avg_p = sum(pool.values()) / n if n else 0

    net: Dict[int, float] = {}
    for p, s in scores.items():
        m_whists = (avg_m - mountain[p]) * cfg.scoring.mountain_to_whist
        p_whists = (pool[p] - avg_p) * cfg.scoring.pool_to_whist
        net[p] = s.whists + m_whists + p_whists
    return net


def game_is_over(cfg: Config, scores: Dict[int, PlayerScore], hand_no: int) -> bool:
    ec = cfg.scoring.end_condition
    if ec == "none":
        return False
    if ec == "hands":
        return cfg.scoring.max_hands is not None and hand_no >= cfg.scoring.max_hands
    target = cfg.scoring.end_target or 0
    if ec == "pool_sum":
        return sum(s.pool for s in scores.values()) >= target
    if ec == "pool_per_player":
        return all(s.pool >= target for s in scores.values())
    return False
