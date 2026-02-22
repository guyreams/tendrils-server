"""NPC definitions and server-controlled AI logic."""

from __future__ import annotations

from uuid import uuid4

from config import GRID_HEIGHT, GRID_WIDTH
from engine.grid import is_adjacent
from models.actions import ActionRequest, ActionType
from models.characters import AbilityScores, Attack, Character
from models.game_state import GameState

# Reserved owner_id for all server NPCs — no real user can have this.
NPC_OWNER_ID = "__npc__"

# ---------------------------------------------------------------------------
# GOLEM definition
# ---------------------------------------------------------------------------

GOLEM_NAME = "GOLEM"


def create_golem() -> Character:
    """Create a fresh GOLEM character.

    The GOLEM is a stationary practice dummy:
    - High HP (100) so bots can whale on it
    - High AC (8) — easy to hit so bots get positive feedback
    - Speed 0 — cannot move
    - Single weak attack: Stone Fist dealing 1 fixed damage
    - Only retaliates when struck first (tracked via 'provoked' condition)
    """
    return Character(
        id=str(uuid4()),
        name=GOLEM_NAME,
        owner_id=NPC_OWNER_ID,
        ability_scores=AbilityScores(
            strength=18,
            dexterity=6,
            constitution=20,
            intelligence=3,
            wisdom=10,
            charisma=1,
        ),
        max_hp=100,
        current_hp=100,
        armor_class=8,
        speed=0,
        attacks=[
            Attack(
                name="Stone Fist",
                attack_bonus=6,
                damage_dice="1d1",
                damage_bonus=0,
                damage_type="bludgeoning",
                reach=5,
            ),
        ],
        is_npc=True,
    )


def golem_center_position() -> tuple[int, int]:
    """Return the center of the grid for GOLEM placement."""
    return (GRID_WIDTH // 2, GRID_HEIGHT // 2)


# ---------------------------------------------------------------------------
# NPC AI — called by the engine when it's an NPC's turn
# ---------------------------------------------------------------------------


def resolve_npc_turn(character: Character, game_state: GameState) -> ActionRequest | None:
    """Decide what action an NPC takes on its turn.

    Returns an ActionRequest to feed into process_action, or None to end turn.
    """
    if character.name == GOLEM_NAME:
        return _golem_ai(character, game_state)
    # Future NPCs can be added here.
    return ActionRequest(action_type=ActionType.END_TURN)


def _golem_ai(golem: Character, game_state: GameState) -> ActionRequest:
    """GOLEM AI: attack an adjacent enemy only if provoked.

    'provoked' is added to the GOLEM's conditions when it takes damage.
    On its turn it picks the first adjacent living enemy and strikes,
    then clears the provoked flag.  If not provoked or nobody is adjacent,
    it simply ends its turn.
    """
    if "provoked" not in golem.conditions:
        return ActionRequest(action_type=ActionType.END_TURN)

    # Find an adjacent living enemy to retaliate against
    for char in game_state.characters.values():
        if char.id == golem.id or not char.is_alive:
            continue
        if char.position is None or golem.position is None:
            continue
        if is_adjacent(golem.position, char.position):
            # Clear provoked before attacking (we get one retaliation per provocation cycle)
            golem.conditions.remove("provoked")
            return ActionRequest(
                action_type=ActionType.ATTACK,
                target_id=char.id,
            )

    # Provoked but nobody adjacent — clear it and pass
    golem.conditions.remove("provoked")
    return ActionRequest(action_type=ActionType.END_TURN)
