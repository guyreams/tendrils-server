"""Admin endpoints for user registration and API key management."""

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from auth import User, _tokens, create_token
from config import ADMIN_SECRET

router = APIRouter()


class RegisterRequest(BaseModel):
    """Request body for registering a new API user."""
    owner_id: str
    name: str


class RegisterResponse(BaseModel):
    """Response after registering a new user."""
    api_key: str
    owner_id: str


@router.post("/register", response_model=RegisterResponse)
def register_user(
    body: RegisterRequest,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> RegisterResponse:
    """Register a new bot/player and return an API key.

    Requires the X-Admin-Secret header to match the server's admin secret.
    """
    if x_admin_secret != ADMIN_SECRET:
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
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret")

    return [
        {"owner_id": user.owner_id, "name": user.name}
        for user in _tokens.values()
    ]
