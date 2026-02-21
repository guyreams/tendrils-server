"""API key authentication for Tendrils Server."""

import json
import os
import secrets
from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import BaseModel

from config import TOKENS_FILE


class User(BaseModel):
    """A registered API user."""
    owner_id: str
    name: str


# In-memory token store: api_key -> User
_tokens: dict[str, User] = {}


def load_tokens(path: str = TOKENS_FILE) -> dict[str, User]:
    """Load token store from JSON file.

    Returns:
        Dict mapping API keys to User objects.
    """
    _tokens.clear()
    if not Path(path).exists():
        return _tokens
    with open(path) as f:
        data = json.load(f)
    _tokens.update({key: User(**value) for key, value in data.items()})
    return _tokens


def save_tokens(path: str = TOKENS_FILE) -> None:
    """Persist token store to JSON file (atomic write)."""
    tmp_path = path + ".tmp"
    data = {key: user.model_dump() for key, user in _tokens.items()}
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def create_token(owner_id: str, name: str) -> str:
    """Generate a new API key for a user and persist it.

    Args:
        owner_id: Unique identifier for the bot/player.
        name: Display name for the user.

    Returns:
        The generated API key string.

    Raises:
        ValueError: If owner_id is already registered.
    """
    for user in _tokens.values():
        if user.owner_id == owner_id:
            raise ValueError(f"owner_id '{owner_id}' is already registered")

    api_key = "sk_" + secrets.token_hex(32)
    _tokens[api_key] = User(owner_id=owner_id, name=name)
    save_tokens()
    return api_key


def get_current_user(request: Request) -> User:
    """FastAPI dependency: extract and validate Bearer token.

    Usage:
        @router.post("/endpoint")
        def endpoint(user: User = Depends(get_current_user)):
            ...

    Raises:
        HTTPException 401: If token is missing or invalid.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[len("Bearer "):]
    user = _tokens.get(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return user


def get_user_by_token(token: str) -> User | None:
    """Look up a user by raw API key (for WebSocket auth)."""
    return _tokens.get(token)
