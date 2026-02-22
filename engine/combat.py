"""Combat orchestration: game creation, turns, initiative, win conditions."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from config import GRID_HEIGHT, GRID_WIDTH, SPAWN_GOLEM, TURN_TIMEOUT_SECONDS
from engine.dice import roll
from engine.grid import (
    create_grid,
    distance,
    get_valid_moves,
    is_adjacent,
    move_character,
)
from engine.rules import resolve_attack, roll_initiative, validate_action
from models.actions import ActionRequest, ActionResult, ActionType
from models.characters import Character
from models.game_state import GameEvent, GameState, GameStatus


def create_game(game_id: str, name: str = "Arena") -> GameState:
    """Initialize a new game with an empty grid.

    Args:
        game_id: Unique identifier for the game.
        name: Display name for the game.

    Returns:
        A fresh GameState ready for players to join.
    """
    grid = create_grid(GRID_WIDTH, GRID_HEIGHT)
    return GameState(
        game_id=game_id,
        name=name,
        grid=grid,
    )


def spawn_npcs(game_state: GameState) -> None:
    """Spawn any configured NPCs that aren't already present.

    Idempotent — checks for an existing living NPC by name before creating.
    """
    if SPAWN_GOLEM:
        from engine.npc import GOLEM_NAME, NPC_OWNER_ID, create_golem, golem_center_position

        # Already present?
        for char in game_state.characters.values():
            if char.name == GOLEM_NAME and char.is_alive:
                return

        golem = create_golem()
        pos = golem_center_position()
        # If centre is occupied, nudge by searching nearby
        x, y = pos
        if game_state.grid[y][x].occupant_id is not None:
            grid_w = len(game_state.grid[0])
            grid_h = len(game_state.grid)
            for dx in range(grid_w):
                for dy in range(grid_h):
                    nx, ny = (x + dx) % grid_w, (y + dy) % grid_h
                    if (
                        game_state.grid[ny][nx].occupant_id is None
                        and game_state.grid[ny][nx].terrain != "wall"
                    ):
                        pos = (nx, ny)
                        break
                else:
                    continue
                break

        add_character(game_state, golem, pos)


def add_character(
    game_state: GameState,
    character: Character,
    starting_position: tuple[int, int],
) -> GameState:
    """Place a character on the grid and add them to the game.

    Args:
        game_state: Current game state.
        character: The character to add.
        starting_position: (x, y) position to place the character.

    Returns:
        Updated game state.

    Raises:
        ValueError: If the position is invalid or occupied.
    """
    x, y = starting_position
    if y < 0 or y >= len(game_state.grid) or x < 0 or x >= len(game_state.grid[0]):
        raise ValueError(f"Position ({x}, {y}) is out of bounds")

    cell = game_state.grid[y][x]
    if cell.occupant_id is not None:
        raise ValueError(f"Position ({x}, {y}) is already occupied")
    if cell.terrain == "wall":
        raise ValueError(f"Position ({x}, {y}) is a wall")

    character.position = starting_position
    cell.occupant_id = character.id
    game_state.characters[character.id] = character

    return game_state


def start_combat(game_state: GameState) -> GameState:
    """Roll initiative for all characters and begin combat.

    Args:
        game_state: Current game state.

    Returns:
        Updated game state with initiative order and ACTIVE status.

    Raises:
        ValueError: If fewer than 2 characters are in the game.
    """
    player_count = sum(1 for c in game_state.characters.values() if not c.is_npc)
    if player_count < 2:
        raise ValueError("Need at least 2 player characters to start combat")

    # Roll initiative for each character
    for char in game_state.characters.values():
        char.initiative = roll_initiative(char)

    # Sort by initiative (descending), then by dex score as tiebreaker
    sorted_chars = sorted(
        game_state.characters.values(),
        key=lambda c: (c.initiative, c.ability_scores.dexterity),
        reverse=True,
    )
    game_state.initiative_order = [c.id for c in sorted_chars]
    game_state.current_turn_index = 0
    game_state.winner_id = None
    game_state.status = GameStatus.ACTIVE
    game_state.turn_deadline = _new_deadline()

    return game_state


def get_current_turn_character(game_state: GameState) -> Character | None:
    """Get the character whose turn it currently is.

    Args:
        game_state: Current game state.

    Returns:
        The current turn's character, or None if game isn't active.
    """
    if game_state.status != GameStatus.ACTIVE:
        return None
    if not game_state.initiative_order:
        return None
    char_id = game_state.initiative_order[game_state.current_turn_index]
    return game_state.characters.get(char_id)


def process_action(
    game_state: GameState,
    character_id: str,
    action: ActionRequest,
    *,
    _skip_turn_check: bool = False,
) -> tuple[GameState, ActionResult]:
    """Validate and resolve an action, advancing the turn if appropriate.

    Args:
        game_state: Current game state.
        character_id: ID of the acting character.
        action: The requested action.
        _skip_turn_check: Internal flag used when processing NPC turns.
            Skips the "is it your turn?" validation and does not call
            advance_turn (the caller handles advancement).

    Returns:
        (updated_game_state, action_result) tuple.
    """
    character = game_state.characters.get(character_id)
    if character is None:
        return game_state, ActionResult(
            success=False,
            action_type=action.action_type,
            description="Character not found",
            error="Character not found",
        )

    # Validate it's this character's turn (skipped for internal NPC calls)
    if not _skip_turn_check:
        current = get_current_turn_character(game_state)
        if current is None or current.id != character_id:
            return game_state, ActionResult(
                success=False,
                action_type=action.action_type,
                description="It's not your turn",
                error="It's not your turn",
            )

    # Validate the action
    valid, error = validate_action(
        action.action_type,
        character,
        game_state,
        target_id=action.target_id,
        target_position=action.target_position,
        weapon_name=action.weapon_name,
    )
    if not valid:
        return game_state, ActionResult(
            success=False,
            action_type=action.action_type,
            description=error,
            error=error,
        )

    result: ActionResult

    # --- MOVE ---
    if action.action_type == ActionType.MOVE:
        try:
            path = move_character(character_id, action.target_position, game_state)
            result = ActionResult(
                success=True,
                action_type=ActionType.MOVE,
                description=f"{character.name} moves to {action.target_position}.",
                movement_path=path,
            )
        except ValueError as e:
            result = ActionResult(
                success=False,
                action_type=ActionType.MOVE,
                description=str(e),
                error=str(e),
            )

    # --- ATTACK ---
    elif action.action_type == ActionType.ATTACK:
        target = game_state.characters[action.target_id]
        # Find weapon
        weapon = character.attacks[0]
        if action.weapon_name:
            for atk in character.attacks:
                if atk.name.lower() == action.weapon_name.lower():
                    weapon = atk
                    break
        result = resolve_attack(character, target, weapon, game_state)

    # --- DODGE ---
    elif action.action_type == ActionType.DODGE:
        if "dodging" not in character.conditions:
            character.conditions.append("dodging")
        result = ActionResult(
            success=True,
            action_type=ActionType.DODGE,
            description=f"{character.name} takes the Dodge action. Attacks against them have disadvantage.",
        )

    # --- DASH ---
    elif action.action_type == ActionType.DASH:
        result = ActionResult(
            success=True,
            action_type=ActionType.DASH,
            description=f"{character.name} takes the Dash action, gaining {character.speed}ft extra movement.",
        )

    # --- DISENGAGE ---
    elif action.action_type == ActionType.DISENGAGE:
        result = ActionResult(
            success=True,
            action_type=ActionType.DISENGAGE,
            description=f"{character.name} takes the Disengage action.",
        )

    # --- END TURN ---
    elif action.action_type == ActionType.END_TURN:
        result = ActionResult(
            success=True,
            action_type=ActionType.END_TURN,
            description=f"{character.name} ends their turn.",
        )
    else:
        result = ActionResult(
            success=False,
            action_type=action.action_type,
            description="Unknown action type",
            error="Unknown action type",
        )

    # Log the event
    if result.success:
        event = GameEvent(
            round=game_state.round_number,
            character_id=character_id,
            action_type=action.action_type.value,
            description=result.description,
            details={
                "attack_roll": result.attack_roll,
                "hit": result.hit,
                "damage_dealt": result.damage_dealt,
            },
            timestamp=datetime.now(timezone.utc),
        )
        game_state.event_log.append(event)

    # Advance turn on action completion (except MOVE — movement doesn't end turn)
    if result.success and action.action_type not in (ActionType.MOVE,):
        # Check win condition first
        winner = check_win_condition(game_state)
        if winner:
            game_state.winner_id = winner
            game_state.status = GameStatus.COMPLETED
            # Auto-transition: clean up and return to WAITING so the
            # world persists and new characters can join the survivors.
            end_combat(game_state)
        elif not _skip_turn_check:
            advance_turn(game_state)

    return game_state, result


def advance_turn(game_state: GameState) -> GameState:
    """Move to the next character in initiative order.

    Skips dead characters. Increments round if wrapped.
    If the next character is an NPC, automatically resolves its turn
    and keeps advancing until a player's turn is reached.

    Args:
        game_state: Current game state.

    Returns:
        Updated game state.
    """
    if not game_state.initiative_order:
        return game_state

    # Clear dodging condition from the character whose turn just ended
    current = get_current_turn_character(game_state)
    if current and "dodging" in current.conditions:
        current.conditions.remove("dodging")

    order_len = len(game_state.initiative_order)
    attempts = 0
    while attempts < order_len:
        game_state.current_turn_index = (
            (game_state.current_turn_index + 1) % order_len
        )
        if game_state.current_turn_index == 0:
            game_state.round_number += 1

        next_char_id = game_state.initiative_order[game_state.current_turn_index]
        next_char = game_state.characters.get(next_char_id)
        if next_char and next_char.is_alive:
            # If this is an NPC, resolve its turn automatically
            if next_char.is_npc:
                _resolve_npc_turn(game_state, next_char)
                # Continue advancing (the while loop will find the next character)
                attempts += 1
                continue
            break
        attempts += 1

    game_state.turn_deadline = _new_deadline()
    return game_state


def _resolve_npc_turn(game_state: GameState, npc: Character) -> None:
    """Execute an NPC's turn via its AI, logging the result."""
    from engine.npc import resolve_npc_turn

    action = resolve_npc_turn(npc, game_state)
    if action is None:
        action = ActionRequest(action_type=ActionType.END_TURN)

    _, result = process_action(game_state, npc.id, action, _skip_turn_check=True)
    # process_action with _skip_turn_check won't call advance_turn again,
    # the caller (advance_turn) handles that.


def check_win_condition(game_state: GameState) -> str | None:
    """Check if only one team has living player characters.

    NPCs are excluded — they are part of the environment, not a team.

    Args:
        game_state: Current game state.

    Returns:
        The winner's owner_id if there's a winner, else None.
    """
    alive_owners: set[str] = set()
    for char in game_state.characters.values():
        if char.is_alive and not char.is_npc:
            alive_owners.add(char.owner_id)

    if len(alive_owners) == 1:
        return alive_owners.pop()
    if len(alive_owners) == 0:
        return None  # Everyone is dead — draw
    return None


def remove_dead_characters(game_state: GameState) -> None:
    """Remove all dead characters from the game and clear their grid cells.

    Args:
        game_state: Current game state (mutated in place).
    """
    dead_ids = [
        cid for cid, char in game_state.characters.items()
        if not char.is_alive
    ]
    for cid in dead_ids:
        char = game_state.characters[cid]
        if char.position is not None:
            x, y = char.position
            if game_state.grid[y][x].occupant_id == cid:
                game_state.grid[y][x].occupant_id = None
        del game_state.characters[cid]


def end_combat(game_state: GameState) -> None:
    """Transition from COMPLETED back to WAITING after combat ends.

    The world persists: dead characters are removed, survivors keep their
    state, and the combat log is archived into history. The game returns
    to WAITING so new characters can join and start a fresh combat round.
    NPCs are respawned (with full HP) so they're ready for the next fight.

    Args:
        game_state: Current game state (mutated in place).
    """
    remove_dead_characters(game_state)

    # Reset surviving NPCs to full HP and clear conditions
    for char in game_state.characters.values():
        if char.is_npc:
            char.current_hp = char.max_hp
            char.conditions = []

    # Archive the current combat log
    if game_state.event_log:
        game_state.combat_log_history.append(list(game_state.event_log))
        game_state.event_log = []

    game_state.initiative_order = []
    game_state.current_turn_index = 0
    game_state.round_number = 1
    game_state.turn_deadline = None
    game_state.status = GameStatus.WAITING

    # Respawn any NPCs that died
    spawn_npcs(game_state)


def transition_to_waiting(game_state: GameState) -> None:
    """Reset a COMPLETED game back to WAITING for the next round.

    Dead characters are removed. Survivors keep their current state.

    Args:
        game_state: Current game state (mutated in place).
    """
    remove_dead_characters(game_state)
    game_state.initiative_order = []
    game_state.current_turn_index = 0
    game_state.round_number = 1
    game_state.turn_deadline = None
    game_state.winner_id = None
    game_state.event_log = []
    game_state.status = GameStatus.WAITING


def save_game(game_state: GameState, path: str) -> None:
    """Persist game state to a JSON file.

    Writes to a temporary file first, then renames for atomicity.

    Args:
        game_state: The game state to save.
        path: File path to write to.
    """
    tmp_path = path + ".tmp"
    data = game_state.model_dump(mode="json")
    with open(tmp_path, "w") as f:
        json.dump(data, f, default=str)
    os.replace(tmp_path, path)


def load_game(path: str) -> GameState | None:
    """Load game state from a JSON file.

    Args:
        path: File path to read from.

    Returns:
        The loaded GameState, or None if the file doesn't exist.
    """
    if not Path(path).exists():
        return None
    with open(path) as f:
        data = json.load(f)
    return GameState.model_validate(data)


def _new_deadline() -> datetime:
    """Generate a new turn deadline from now."""
    from datetime import timedelta
    return datetime.now(timezone.utc) + timedelta(seconds=TURN_TIMEOUT_SECONDS)
