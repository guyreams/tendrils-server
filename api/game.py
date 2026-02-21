"""Action submission, state retrieval, and game log endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from engine.combat import get_current_turn_character, process_action
from models.actions import ActionRequest, ActionResult, ActionType, TurnState
from models.game_state import GameStatus

router = APIRouter()


def _get_games(request: Request) -> dict:
    """Get the games store from app state."""
    return request.app.state.games


@router.get("/{game_id}/state")
def get_game_state(
    game_id: str,
    request: Request,
    character_id: str = Query(..., description="Your character's ID"),
) -> dict:
    """Get current game state from a specific character's perspective.

    Returns a TurnState-like object with the character's view of the battlefield.
    """
    games = _get_games(request)
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")

    game_state = games[game_id]
    if character_id not in game_state.characters:
        raise HTTPException(status_code=404, detail="Character not found in this game")

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
        "game_id": game_id,
        "status": game_state.status.value,
        "round_number": game_state.round_number,
        "is_your_turn": is_my_turn,
        "your_character": character.model_dump(),
        "visible_characters": [c.model_dump() for c in visible],
        "available_actions": [a.value for a in available_actions],
        "turn_deadline": game_state.turn_deadline.isoformat() if game_state.turn_deadline else None,
        "winner_id": game_state.winner_id,
    }


@router.post("/{game_id}/action", response_model=ActionResult)
def submit_action(
    game_id: str,
    action: ActionRequest,
    request: Request,
) -> ActionResult:
    """Submit an action for the current turn.

    Returns 400 if it's not this character's turn or the action is invalid.
    """
    games = _get_games(request)
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")

    game_state = games[game_id]
    if game_state.status != GameStatus.ACTIVE:
        raise HTTPException(
            status_code=400,
            detail=f"Game is not active (status: {game_state.status.value})",
        )

    if action.character_id not in game_state.characters:
        raise HTTPException(status_code=404, detail="Character not found")

    current = get_current_turn_character(game_state)
    if current is None or current.id != action.character_id:
        raise HTTPException(status_code=409, detail="It's not your turn")

    _, result = process_action(game_state, action.character_id, action)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return result


@router.get("/{game_id}/log")
def get_game_log(game_id: str, request: Request) -> list[dict]:
    """Get the full event log for spectators/replay."""
    games = _get_games(request)
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")

    game_state = games[game_id]
    return [event.model_dump() for event in game_state.event_log]
