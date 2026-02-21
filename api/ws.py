"""WebSocket endpoint for real-time game notifications."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from models.game_state import GameStatus

router = APIRouter()

# Track connected clients: game_id -> list of (character_id, websocket)
connections: dict[str, list[tuple[str, WebSocket]]] = {}


async def broadcast_to_game(game_id: str, message: dict[str, Any]) -> None:
    """Send a message to all WebSocket clients in a game.

    Args:
        game_id: The game to broadcast to.
        message: The JSON-serializable message to send.
    """
    if game_id not in connections:
        return
    disconnected = []
    for i, (char_id, ws) in enumerate(connections[game_id]):
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.append(i)
    # Clean up disconnected clients
    for i in reversed(disconnected):
        connections[game_id].pop(i)


async def notify_turn_start(game_id: str, character_id: str, round_number: int) -> None:
    """Notify all clients that a new turn has started.

    Args:
        game_id: The game ID.
        character_id: The character whose turn it is.
        round_number: The current round.
    """
    await broadcast_to_game(game_id, {
        "type": "turn_start",
        "character_id": character_id,
        "round_number": round_number,
    })


async def notify_action_result(game_id: str, result: dict[str, Any]) -> None:
    """Notify all clients of an action result.

    Args:
        game_id: The game ID.
        result: The action result data.
    """
    await broadcast_to_game(game_id, {
        "type": "action_result",
        **result,
    })


async def notify_game_over(game_id: str, winner_id: str | None) -> None:
    """Notify all clients that the game is over.

    Args:
        game_id: The game ID.
        winner_id: The winning player's owner_id, or None for a draw.
    """
    await broadcast_to_game(game_id, {
        "type": "game_over",
        "winner_id": winner_id,
    })


@router.websocket("/{game_id}/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    game_id: str,
    character_id: str = Query(...),
) -> None:
    """WebSocket endpoint for real-time game notifications.

    Clients connect and receive turn_start, action_result, and game_over messages.
    """
    await websocket.accept()

    if game_id not in connections:
        connections[game_id] = []
    connections[game_id].append((character_id, websocket))

    try:
        await websocket.send_json({
            "type": "connected",
            "game_id": game_id,
            "character_id": character_id,
        })

        # Keep connection alive, listen for client messages (optional)
        while True:
            try:
                data = await websocket.receive_text()
                # Clients primarily use REST for actions, but we keep the
                # connection open for notifications
            except WebSocketDisconnect:
                break
    finally:
        # Remove this connection
        if game_id in connections:
            connections[game_id] = [
                (cid, ws) for cid, ws in connections[game_id]
                if ws != websocket
            ]
            if not connections[game_id]:
                del connections[game_id]
