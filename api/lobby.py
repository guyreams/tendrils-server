"""Game creation and bot registration endpoints."""

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config import MAX_PLAYERS_PER_GAME
from engine.combat import add_character, create_game, start_combat
from models.characters import AbilityScores, Attack, Character
from models.game_state import GameStatus

router = APIRouter()


class CreateGameRequest(BaseModel):
    """Request body for creating a new game."""
    name: str = "Arena"


class CreateGameResponse(BaseModel):
    """Response after creating a game."""
    game_id: str
    status: str


class JoinGameRequest(BaseModel):
    """Request body for joining a game with a character."""
    owner_id: str
    name: str
    ability_scores: AbilityScores = AbilityScores()
    max_hp: int
    armor_class: int
    speed: int = 30
    attacks: list[Attack] = []


class JoinGameResponse(BaseModel):
    """Response after joining a game."""
    character_id: str
    message: str


class StartGameResponse(BaseModel):
    """Response after starting combat."""
    message: str
    initiative_order: list[str]


def _get_games(request: Request) -> dict:
    """Get the games store from app state."""
    return request.app.state.games


@router.post("", response_model=CreateGameResponse)
def create_new_game(body: CreateGameRequest, request: Request) -> CreateGameResponse:
    """Create a new game and return the game_id."""
    games = _get_games(request)
    game_id = str(uuid4())
    game_state = create_game(game_id, name=body.name)
    games[game_id] = game_state
    return CreateGameResponse(game_id=game_id, status=game_state.status.value)


@router.post("/{game_id}/join", response_model=JoinGameResponse)
def join_game(game_id: str, body: JoinGameRequest, request: Request) -> JoinGameResponse:
    """Register a bot and its character to a game."""
    games = _get_games(request)
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")

    game_state = games[game_id]
    if game_state.status != GameStatus.WAITING:
        raise HTTPException(status_code=400, detail="Game has already started")

    if len(game_state.characters) >= MAX_PLAYERS_PER_GAME:
        raise HTTPException(status_code=400, detail="Game is full")

    character_id = str(uuid4())
    character = Character(
        id=character_id,
        name=body.name,
        owner_id=body.owner_id,
        ability_scores=body.ability_scores,
        max_hp=body.max_hp,
        current_hp=body.max_hp,
        armor_class=body.armor_class,
        speed=body.speed,
        attacks=body.attacks,
    )

    # Auto-assign a starting position (spread characters along the edges)
    char_count = len(game_state.characters)
    grid_w = len(game_state.grid[0]) if game_state.grid else 20
    grid_h = len(game_state.grid) if game_state.grid else 20

    # Place characters at different corners/edges
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
                if game_state.grid[ny][nx].occupant_id is None and game_state.grid[ny][nx].terrain != "wall":
                    pos = (nx, ny)
                    break
            else:
                continue
            break

    add_character(game_state, character, pos)
    return JoinGameResponse(character_id=character_id, message="Joined game")


@router.post("/{game_id}/start", response_model=StartGameResponse)
def start_game(game_id: str, request: Request) -> StartGameResponse:
    """Start combat in a game (requires 2+ characters)."""
    games = _get_games(request)
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")

    game_state = games[game_id]
    if game_state.status != GameStatus.WAITING:
        raise HTTPException(status_code=400, detail="Game has already started")

    if len(game_state.characters) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 characters to start")

    start_combat(game_state)

    initiative_names = []
    for char_id in game_state.initiative_order:
        char = game_state.characters[char_id]
        initiative_names.append(f"{char.name} (initiative {char.initiative})")

    return StartGameResponse(
        message="Combat started",
        initiative_order=initiative_names,
    )


@router.get("/{game_id}")
def get_game(game_id: str, request: Request) -> dict:
    """Get game metadata and status."""
    games = _get_games(request)
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")

    game_state = games[game_id]
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
    }
