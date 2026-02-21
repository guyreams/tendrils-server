"""WebSocket endpoint for real-time game notifications."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from auth import get_user_by_token
from models.game_state import GameStatus

router = APIRouter()

# Track connected clients: list of (character_id, websocket)
connections: list[tuple[str, WebSocket]] = []


async def broadcast(message: dict[str, Any]) -> None:
    """Send a message to all connected WebSocket clients.

    Args:
        message: The JSON-serializable message to send.
    """
    disconnected = []
    for i, (char_id, ws) in enumerate(connections):
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.append(i)
    # Clean up disconnected clients
    for i in reversed(disconnected):
        connections.pop(i)


async def notify_turn_start(character_id: str, round_number: int) -> None:
    """Notify all clients that a new turn has started."""
    await broadcast({
        "type": "turn_start",
        "character_id": character_id,
        "round_number": round_number,
    })


async def notify_action_result(result: dict[str, Any]) -> None:
    """Notify all clients of an action result."""
    await broadcast({
        "type": "action_result",
        **result,
    })


async def notify_game_over(winner_id: str | None) -> None:
    """Notify all clients that the game is over."""
    await broadcast({
        "type": "game_over",
        "winner_id": winner_id,
    })


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
) -> None:
    """WebSocket endpoint for real-time game notifications.

    Authenticate via the `token` query parameter (same API key used for REST).
    The server resolves the user's character from the token.
    """
    # Authenticate
    user = get_user_by_token(token)
    if user is None:
        await websocket.close(code=4001, reason="Invalid API key")
        return

    # Find the user's character
    game_state = websocket.app.state.game
    character_id = None
    for char in game_state.characters.values():
        if char.owner_id == user.owner_id:
            character_id = char.id
            break

    if character_id is None:
        await websocket.close(code=4002, reason="No character found for this user")
        return

    await websocket.accept()
    connections.append((character_id, websocket))

    try:
        await websocket.send_json({
            "type": "connected",
            "character_id": character_id,
        })

        # Keep connection alive, listen for client messages (optional)
        while True:
            try:
                data = await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        # Remove this connection
        for i, (cid, ws) in enumerate(connections):
            if ws == websocket:
                connections.pop(i)
                break
