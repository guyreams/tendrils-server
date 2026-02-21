"""Character registration, reconnection, and combat start endpoints."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import User, get_current_user
from config import MAX_PLAYERS_PER_GAME, SAVE_FILE
from engine.combat import (
    add_character,
    save_game,
    start_combat,
)
from models.characters import AbilityScores, Attack, Character
from models.game_state import GameState, GameStatus

router = APIRouter()


class JoinGameRequest(BaseModel):
    """Request body for joining the game with a character."""
    name: str
    ability_scores: AbilityScores = AbilityScores()
    max_hp: int
    armor_class: int
    speed: int = 30
    attacks: list[Attack] = []


class JoinGameResponse(BaseModel):
    """Response after joining or reconnecting to the game."""
    character_id: str
    message: str


class StartGameResponse(BaseModel):
    """Response after starting combat."""
    message: str
    initiative_order: list[str]


def _get_game(request: Request) -> GameState:
    """Get the singleton game from app state."""
    return request.app.state.game


def _find_character_by_owner(game_state: GameState, owner_id: str) -> Character | None:
    """Find a character owned by the given owner_id."""
    for char in game_state.characters.values():
        if char.owner_id == owner_id:
            return char
    return None


def _remove_character(game_state: GameState, character_id: str) -> None:
    """Remove a character from the game and clear their grid cell."""
    char = game_state.characters.get(character_id)
    if char is None:
        return
    if char.position is not None:
        x, y = char.position
        if game_state.grid[y][x].occupant_id == character_id:
            game_state.grid[y][x].occupant_id = None
    del game_state.characters[character_id]


def _place_character(game_state: GameState, character: Character) -> None:
    """Find a starting position and place a character on the grid."""
    char_count = len(game_state.characters)
    grid_w = len(game_state.grid[0]) if game_state.grid else 20
    grid_h = len(game_state.grid) if game_state.grid else 20

    positions = [
        (1, 1),
        (grid_w - 2, grid_h - 2),
        (grid_w - 2, 1),
        (1, grid_h - 2),
        (grid_w // 2, 1),
        (grid_w // 2, grid_h - 2),
    ]
    pos = positions[char_count % len(positions)]

    # If position is occupied, find nearby open spot
    px, py = pos
    if game_state.grid[py][px].occupant_id is not None:
        for dx in range(grid_w):
            for dy in range(grid_h):
                nx, ny = (px + dx) % grid_w, (py + dy) % grid_h
                if (
                    game_state.grid[ny][nx].occupant_id is None
                    and game_state.grid[ny][nx].terrain != "wall"
                ):
                    pos = (nx, ny)
                    break
            else:
                continue
            break

    add_character(game_state, character, pos)


@router.post("/join", response_model=JoinGameResponse)
def join_game(
    body: JoinGameRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> JoinGameResponse:
    """Join the game or reconnect to an existing character.

    - If owner_id has a living character: reconnect and return existing character_id.
    - If owner_id has a dead character: remove the dead one, create a new character.
    - If owner_id is new: create a new character.

    The owner_id is derived from the authenticated user's API key.
    """
    game_state = _get_game(request)
    owner_id = user.owner_id

    if game_state.status != GameStatus.WAITING:
        raise HTTPException(
            status_code=400,
            detail="Combat is in progress. Cannot join until it ends.",
        )

    existing = _find_character_by_owner(game_state, owner_id)

    if existing is not None and existing.is_alive:
        # Reconnect to existing living character
        save_game(game_state, SAVE_FILE)
        return JoinGameResponse(
            character_id=existing.id,
            message=f"Reconnected to {existing.name}",
        )

    if existing is not None and not existing.is_alive:
        # Dead character — remove it and create a new one
        old_name = existing.name
        _remove_character(game_state, existing.id)

        character_id = str(uuid4())
        character = Character(
            id=character_id,
            name=body.name,
            owner_id=owner_id,
            ability_scores=body.ability_scores,
            max_hp=body.max_hp,
            current_hp=body.max_hp,
            armor_class=body.armor_class,
            speed=body.speed,
            attacks=body.attacks,
        )
        _place_character(game_state, character)
        save_game(game_state, SAVE_FILE)
        return JoinGameResponse(
            character_id=character_id,
            message=(
                f"Your previous character {old_name} has fallen. "
                f"{body.name} has entered the arena."
            ),
        )

    # New player
    if len(game_state.characters) >= MAX_PLAYERS_PER_GAME:
        raise HTTPException(status_code=400, detail="Game is full")

    character_id = str(uuid4())
    character = Character(
        id=character_id,
        name=body.name,
        owner_id=owner_id,
        ability_scores=body.ability_scores,
        max_hp=body.max_hp,
        current_hp=body.max_hp,
        armor_class=body.armor_class,
        speed=body.speed,
        attacks=body.attacks,
    )
    _place_character(game_state, character)
    save_game(game_state, SAVE_FILE)
    return JoinGameResponse(
        character_id=character_id,
        message=f"{body.name} has entered the arena.",
    )


@router.post("/start", response_model=StartGameResponse)
def start_game(request: Request, user: User = Depends(get_current_user)) -> StartGameResponse:
    """Start combat (requires 2+ characters)."""
    game_state = _get_game(request)

    if game_state.status != GameStatus.WAITING:
        raise HTTPException(status_code=400, detail="Game has already started")

    if len(game_state.characters) < 2:
        raise HTTPException(
            status_code=400,
            detail="Need at least 2 characters to start",
        )

    start_combat(game_state)
    save_game(game_state, SAVE_FILE)

    initiative_names = []
    for char_id in game_state.initiative_order:
        char = game_state.characters[char_id]
        initiative_names.append(f"{char.name} (initiative {char.initiative})")

    return StartGameResponse(
        message="Combat started",
        initiative_order=initiative_names,
    )


@router.get("")
def get_game(request: Request) -> dict:
    """Get game metadata and status."""
    game_state = _get_game(request)

    characters_summary = []
    for char in game_state.characters.values():
        characters_summary.append({
            "id": char.id,
            "name": char.name,
            "owner_id": char.owner_id,
            "current_hp": char.current_hp,
            "max_hp": char.max_hp,
            "position": char.position,
            "is_alive": char.is_alive,
        })

    return {
        "game_id": game_state.game_id,
        "name": game_state.name,
        "status": game_state.status.value,
        "round_number": game_state.round_number,
        "characters": characters_summary,
        "initiative_order": game_state.initiative_order,
        "current_turn_index": game_state.current_turn_index,
        "winner_id": game_state.winner_id,
        "past_combats": len(game_state.combat_log_history),
    }
