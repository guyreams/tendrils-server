"""Game state, grid, and event models for Tendrils Server."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from models.characters import Character


class GameStatus(str, Enum):
    """Possible states for a game."""
    WAITING = "waiting"             # Lobby, waiting for players
    ACTIVE = "active"               # Combat in progress
    COMPLETED = "completed"         # Game over


class GridCell(BaseModel):
    """A single cell on the battle grid."""
    x: int
    y: int
    terrain: str = "open"           # "open", "wall", "difficult"
    occupant_id: str | None = None


class GameEvent(BaseModel):
    """A logged event from the game."""
    round: int
    character_id: str
    action_type: str
    description: str
    details: dict = {}              # Rolls, damage, etc.
    timestamp: datetime


class GameState(BaseModel):
    """The full state of a game."""
    game_id: str
    name: str = "Arena"
    status: GameStatus = GameStatus.WAITING
    grid: list[list[GridCell]]      # 2D grid [y][x]
    characters: dict[str, Character] = {}  # character_id -> Character
    initiative_order: list[str] = []  # Ordered list of character IDs
    current_turn_index: int = 0
    round_number: int = 1
    turn_deadline: datetime | None = None
    event_log: list[GameEvent] = []
    winner_id: str | None = None
