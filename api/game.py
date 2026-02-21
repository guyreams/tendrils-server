"""Action submission, state retrieval, and game log endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from auth import User, get_current_user
from config import SAVE_FILE
from engine.combat import get_current_turn_character, process_action, save_game
from models.actions import ActionRequest, ActionResult, ActionType, TurnState
from models.game_state import GameState, GameStatus

router = APIRouter()


def _get_game(request: Request) -> GameState:
    """Get the singleton game from app state."""
    return request.app.state.game


def _find_character_by_owner(game_state: GameState, owner_id: str) -> str | None:
    """Find the character_id belonging to an owner. Returns None if not found."""
    for char in game_state.characters.values():
        if char.owner_id == owner_id:
            return char.id
    return None


@router.get("/state")
def get_game_state(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    """Get current game state from the authenticated user's perspective."""
    game_state = _get_game(request)

    character_id = _find_character_by_owner(game_state, user.owner_id)
    if character_id is None:
        raise HTTPException(status_code=404, detail="You have no character in this game")

    character = game_state.characters[character_id]

    # All other characters are visible (no fog of war in Phase 1)
    visible = [
        c for c in game_state.characters.values()
        if c.id != character_id
    ]

    # Determine available actions
    available_actions = [ActionType.END_TURN]
    if character.is_alive:
        available_actions = [
            ActionType.MOVE,
            ActionType.ATTACK,
            ActionType.DODGE,
            ActionType.DASH,
            ActionType.DISENGAGE,
            ActionType.END_TURN,
        ]

    current = get_current_turn_character(game_state)
    is_my_turn = current is not None and current.id == character_id

    return {
        "game_id": game_state.game_id,
        "status": game_state.status.value,
        "round_number": game_state.round_number,
        "is_your_turn": is_my_turn,
        "your_character": character.model_dump(),
        "visible_characters": [c.model_dump() for c in visible],
        "available_actions": [a.value for a in available_actions],
        "turn_deadline": game_state.turn_deadline.isoformat() if game_state.turn_deadline else None,
        "winner_id": game_state.winner_id,
        "past_combats": len(game_state.combat_log_history),
    }


@router.post("/action", response_model=ActionResult)
def submit_action(
    action: ActionRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> ActionResult:
    """Submit an action for the current turn.

    The character_id is derived from the authenticated user's token.
    """
    game_state = _get_game(request)

    if game_state.status != GameStatus.ACTIVE:
        raise HTTPException(
            status_code=400,
            detail=f"Game is not active (status: {game_state.status.value})",
        )

    # Resolve character from authenticated user
    character_id = _find_character_by_owner(game_state, user.owner_id)
    if character_id is None:
        raise HTTPException(status_code=404, detail="You have no character in this game")

    # Inject character_id into the action for the engine
    action.character_id = character_id

    current = get_current_turn_character(game_state)
    if current is None or current.id != character_id:
        raise HTTPException(status_code=409, detail="It's not your turn")

    _, result = process_action(game_state, character_id, action)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    save_game(game_state, SAVE_FILE)
    return result


@router.get("/log")
def get_game_log(request: Request) -> list[dict]:
    """Get the event log for the current or most recent combat."""
    game_state = _get_game(request)
    return [event.model_dump() for event in game_state.event_log]


@router.get("/history")
def get_combat_history(request: Request) -> list[list[dict]]:
    """Get archived logs from all past combats."""
    game_state = _get_game(request)
    return [
        [event.model_dump() for event in combat]
        for combat in game_state.combat_log_history
    ]
