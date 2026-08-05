from pydantic import BaseModel


class CreateRoomRequest(BaseModel):
    players: list[str]


class PlayCardRequest(BaseModel):
    player: int
    card: str


class BidRequest(BaseModel):
    player: int
    contract: str | None = None
    suit: str | None = None
    action: str


class OrderRequest(BaseModel):
    contract: str
    trump: str | None = None


class DiscardRequest(BaseModel):
    first: str
    second: str


class WhistRequest(BaseModel):
    player: int
    action: str