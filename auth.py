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


def delete_token(owner_id: str) -> bool:
    """Remove a user and their API key from the token store.

    Args:
        owner_id: The owner_id of the user to delete.

    Returns:
        True if the user was found and deleted, False if not found.
    """
    key_to_delete = None
    for key, user in _tokens.items():
        if user.owner_id == owner_id:
            key_to_delete = key
            break
    if key_to_delete is None:
        return False
    del _tokens[key_to_delete]
    save_tokens()
    return True


def update_user(owner_id: str, name: str) -> bool:
    """Update the display name for an existing user.

    Args:
        owner_id: The owner_id of the user to update.
        name: The new display name.

    Returns:
        True if the user was found and updated, False if not found.
    """
    for user in _tokens.values():
        if user.owner_id == owner_id:
            user.name = name
            save_tokens()
            return True
    return False


def get_token_for_owner(owner_id: str) -> str | None:
    """Look up the API key for a given owner_id.

    Args:
        owner_id: The owner_id to search for.

    Returns:
        The API key string, or None if the owner_id is not registered.
    """
    for key, user in _tokens.items():
        if user.owner_id == owner_id:
            return key
    return None


def rotate_token(owner_id: str) -> str | None:
    """Generate a new API key for an existing user, invalidating the old one.

    Args:
        owner_id: The owner_id whose key should be rotated.

    Returns:
        The new API key string, or None if the owner_id is not registered.
    """
    old_key = None
    old_user = None
    for key, user in _tokens.items():
        if user.owner_id == owner_id:
            old_key = key
            old_user = user
            break
    if old_key is None or old_user is None:
        return None
    del _tokens[old_key]
    new_key = "sk_" + secrets.token_hex(32)
    _tokens[new_key] = old_user
    save_tokens()
    return new_key
