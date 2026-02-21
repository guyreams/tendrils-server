"""Character and creature data models for Tendrils Server."""

from pydantic import BaseModel


class Attack(BaseModel):
    """A weapon or natural attack a character can make."""
    name: str                       # e.g., "Longsword"
    attack_bonus: int               # Added to d20 roll
    damage_dice: str                # e.g., "1d8"
    damage_bonus: int               # Added to damage roll
    damage_type: str                # e.g., "slashing"
    reach: int = 5                  # Reach in feet (5 for melee)
    range_normal: int | None = None # For ranged attacks
    range_long: int | None = None   # Disadvantage range


class AbilityScores(BaseModel):
    """The six core ability scores."""
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10


class Character(BaseModel):
    """A character or creature on the battlefield."""
    id: str                         # Unique identifier
    name: str
    owner_id: str                   # The bot/player that controls this character
    ability_scores: AbilityScores = AbilityScores()
    max_hp: int
    current_hp: int
    armor_class: int
    speed: int = 30                 # Movement speed in feet
    position: tuple[int, int] | None = None  # Grid position (x, y)
    initiative: int = 0
    is_alive: bool = True
    conditions: list[str] = []     # e.g., ["prone", "grappled"]
    attacks: list[Attack] = []     # Available attacks
