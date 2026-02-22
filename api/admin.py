"""Admin endpoints for user registration and API key management."""

from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel

from auth import (
    User,
    _tokens,
    create_token,
    delete_token,
    update_user,
    get_token_for_owner,
    rotate_token,
)
import config
from config import SAVE_FILE, save_secret
from engine.combat import save_game, end_combat
from models.game_state import GameStatus

router = APIRouter()


class RegisterRequest(BaseModel):
    """Request body for registering a new API user."""
    owner_id: str
    name: str


class RegisterResponse(BaseModel):
    """Response after registering a new user."""
    api_key: str
    owner_id: str


class UpdateUserRequest(BaseModel):
    """Request body for updating user details."""
    name: str


class UpdateUserResponse(BaseModel):
    """Response after updating a user."""
    owner_id: str
    name: str


class DeleteUserResponse(BaseModel):
    """Response after deleting a user."""
    message: str
    character_removed: bool


class ChangeSecretRequest(BaseModel):
    """Request body for changing the admin secret."""
    new_secret: str


class ChangeSecretResponse(BaseModel):
    """Response after changing the admin secret."""
    message: str


@router.put("/secret", response_model=ChangeSecretResponse)
def change_admin_secret(
    body: ChangeSecretRequest,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> ChangeSecretResponse:
    """Change the admin secret at runtime.

    Requires the current X-Admin-Secret header. The new secret takes
    effect immediately — subsequent requests must use it.
    """
    if x_admin_secret != config.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret")

    if not body.new_secret or len(body.new_secret) < 8:
        raise HTTPException(
            status_code=400,
            detail="New secret must be at least 8 characters",
        )

    config.ADMIN_SECRET = body.new_secret
    save_secret()
    return ChangeSecretResponse(message="Admin secret updated")


@router.post("/register", response_model=RegisterResponse)
def register_user(
    body: RegisterRequest,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> RegisterResponse:
    """Register a new bot/player and return an API key.

    Requires the X-Admin-Secret header to match the server's admin secret.
    """
    if x_admin_secret != config.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret")

    try:
        api_key = create_token(body.owner_id, body.name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return RegisterResponse(api_key=api_key, owner_id=body.owner_id)


@router.get("/users")
def list_users(
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> list[dict]:
    """List all registered users. Does not expose API keys.

    Requires the X-Admin-Secret header.
    """
    if x_admin_secret != config.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret")

    return [
        {"owner_id": user.owner_id, "name": user.name}
        for user in _tokens.values()
    ]


@router.get("/users/{owner_id}/token", response_model=RegisterResponse)
def get_user_token(
    owner_id: str,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> RegisterResponse:
    """Retrieve the API key for a specific user.

    Requires the X-Admin-Secret header.
    """
    if x_admin_secret != config.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret")

    api_key = get_token_for_owner(owner_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail=f"owner_id '{owner_id}' not found")

    return RegisterResponse(api_key=api_key, owner_id=owner_id)


@router.patch("/users/{owner_id}", response_model=UpdateUserResponse)
def edit_user(
    owner_id: str,
    body: UpdateUserRequest,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> UpdateUserResponse:
    """Update a user's display name.

    Requires the X-Admin-Secret header.
    """
    if x_admin_secret != config.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret")

    updated = update_user(owner_id, body.name)
    if not updated:
        raise HTTPException(status_code=404, detail=f"owner_id '{owner_id}' not found")

    return UpdateUserResponse(owner_id=owner_id, name=body.name)


@router.post("/users/{owner_id}/rotate-token", response_model=RegisterResponse)
def rotate_user_token(
    owner_id: str,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> RegisterResponse:
    """Rotate the API key for an existing user. The old key is invalidated immediately.

    Requires the X-Admin-Secret header.
    """
    if x_admin_secret != config.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret")

    new_key = rotate_token(owner_id)
    if new_key is None:
        raise HTTPException(status_code=404, detail=f"owner_id '{owner_id}' not found")

    return RegisterResponse(api_key=new_key, owner_id=owner_id)


@router.delete("/users/{owner_id}", response_model=DeleteUserResponse)
def delete_user(
    owner_id: str,
    request: Request,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> DeleteUserResponse:
    """Delete a user, their API key, and any in-game character.

    Requires the X-Admin-Secret header.
    """
    if x_admin_secret != config.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret")

    deleted = delete_token(owner_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"owner_id '{owner_id}' not found")

    # Clean up any character belonging to this owner in the game
    character_removed = False
    game_state = request.app.state.game
    char_to_remove = None
    for char in game_state.characters.values():
        if char.owner_id == owner_id:
            char_to_remove = char
            break

    if char_to_remove is not None:
        # Clear grid cell
        if char_to_remove.position is not None:
            x, y = char_to_remove.position
            if game_state.grid[y][x].occupant_id == char_to_remove.id:
                game_state.grid[y][x].occupant_id = None
        # Remove from initiative order if in active combat
        if char_to_remove.id in game_state.initiative_order:
            game_state.initiative_order.remove(char_to_remove.id)
            if game_state.initiative_order:
                game_state.current_turn_index = (
                    game_state.current_turn_index % len(game_state.initiative_order)
                )
        # Remove from characters dict
        del game_state.characters[char_to_remove.id]
        character_removed = True

        # Check if combat should end (fewer than 2 alive owners)
        if game_state.status == GameStatus.ACTIVE:
            alive_owners = {
                c.owner_id for c in game_state.characters.values() if c.is_alive
            }
            if len(alive_owners) <= 1:
                if alive_owners:
                    game_state.winner_id = alive_owners.pop()
                game_state.status = GameStatus.COMPLETED
                end_combat(game_state)

        save_game(game_state, SAVE_FILE)

    return DeleteUserResponse(
        message=f"User '{owner_id}' deleted",
        character_removed=character_removed,
    )
