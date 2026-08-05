from enum import Enum

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


# ==========================
# ENUMS
# ==========================

class Suit(str, Enum):
    SPADES = "SPADES"
    CLUBS = "CLUBS"
    DIAMONDS = "DIAMONDS"
    HEARTS = "HEARTS"
    NT = "NT"


class BidAction(str, Enum):
    BID = "BID"
    PASS = "PASS"


class ContractType(str, Enum):
    GAME = "GAME"
    MISERE = "MISERE"
    RASPAS = "RASPAS"


class WhistDecision(str, Enum):
    WHIST = "WHIST"
    HALF_WHIST = "HALF_WHIST"
    PASS = "PASS"


# ==========================
# DTO
# ==========================

class BidRequest(BaseModel):
    action: BidAction
    level: int | None = None
    suit: Suit | None = None


class ContractRequest(BaseModel):
    type: ContractType
    level: int | None = None
    suit: Suit | None = None


class WhistRequest(BaseModel):
    decision: WhistDecision


class MoveRequest(BaseModel):
    card_id: str


class DiscardRequest(BaseModel):
    card_ids: list[str]


# ==========================
# API
# ==========================

@app.post("/api/v1/games/{game_id}/bids")
def make_bid(game_id: str, request: BidRequest):
    """
    Сделать заявку на торгах либо сказать пас.
    """
    return {
        "gameId": game_id,
        "accepted": True,
        "request": request
    }


@app.post("/api/v1/games/{game_id}/contract")
def declare_contract(game_id: str, request: ContractRequest):
    """
    Объявить игру после получения прикупа.
    """
    return {
        "gameId": game_id,
        "accepted": True,
        "contract": request
    }


@app.post("/api/v1/games/{game_id}/whist")
def declare_whist(game_id: str, request: WhistRequest):
    """
    Объявить вист / полувист / пас.
    """
    return {
        "gameId": game_id,
        "accepted": True,
        "decision": request.decision
    }


@app.post("/api/v1/games/{game_id}/moves")
def make_move(game_id: str, request: MoveRequest):
    """
    Сходить картой.
    """
    return {
        "gameId": game_id,
        "accepted": True,
        "cardId": request.card_id
    }


@app.post("/api/v1/games/{game_id}/talon")
def take_talon(game_id: str):
    """
    Получить прикуп.
    """
    return {
        "gameId": game_id,
        "cards": [
            {
                "id": "card_31",
                "rank": "A",
                "suit": "SPADES"
            },
            {
                "id": "card_32",
                "rank": "10",
                "suit": "HEARTS"
            }
        ]
    }


@app.post("/api/v1/games/{game_id}/talon/discard")
def discard_cards(game_id: str, request: DiscardRequest):
    """
    Снести две карты после получения прикупа.
    """
    return {
        "gameId": game_id,
        "accepted": True,
        "discarded": request.card_ids
    }
