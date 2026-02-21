"""Action request and response models for Tendrils Server."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from models.characters import Character


class ActionType(str, Enum):
    """Available action types a bot can take."""
    MOVE = "move"
    ATTACK = "attack"
    DODGE = "dodge"
    DASH = "dash"                   # Double movement
    DISENGAGE = "disengage"         # Move without opportunity attacks
    END_TURN = "end_turn"


class ActionRequest(BaseModel):
    """A bot's requested action."""
    character_id: str
    action_type: ActionType
    target_id: str | None = None        # For attacks
    target_position: tuple[int, int] | None = None  # For movement
    weapon_name: str | None = None      # For attacks


class ActionResult(BaseModel):
    """The server's response after processing an action."""
    success: bool
    action_type: ActionType
    description: str                    # Human-readable narrative
    attack_roll: int | None = None
    hit: bool | None = None
    damage_dealt: int | None = None
    target_hp_remaining: int | None = None
    movement_path: list[tuple[int, int]] | None = None
    error: str | None = None            # If action was invalid


class TurnState(BaseModel):
    """What the bot receives when it's their turn."""
    game_id: str
    round_number: int
    your_character: Character
    visible_characters: list[Character]  # Enemies/allies the bot can see
    available_actions: list[ActionType]
    turn_deadline: datetime
