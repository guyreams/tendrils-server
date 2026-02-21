"""FastAPI app entry point for Tendrils Server."""

from fastapi import FastAPI

from api.lobby import router as lobby_router
from api.game import router as game_router
from api.ws import router as ws_router

app = FastAPI(
    title="Tendrils Server",
    description="A headless Dungeon Master for AI bot combat arenas",
    version="0.1.0",
)

# In-memory game store
app.state.games = {}

app.include_router(lobby_router, prefix="/games", tags=["Lobby"])
app.include_router(game_router, prefix="/games", tags=["Game"])
app.include_router(ws_router, prefix="/games", tags=["WebSocket"])


@app.get("/")
def root() -> dict:
    """Root endpoint returning server info."""
    return {"name": "Tendrils Server", "version": "0.1.0", "status": "running"}


@app.get("/health")
def health() -> dict:
    """Health check endpoint."""
    return {"healthy": True}
