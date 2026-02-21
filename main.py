"""FastAPI app entry point for Tendrils Server."""

from fastapi import FastAPI

from api.lobby import router as lobby_router
from api.game import router as game_router
from api.ws import router as ws_router
from config import GAME_ID, GAME_NAME, SAVE_FILE
from engine.combat import create_game, end_combat, load_game, save_game
from models.game_state import GameStatus

app = FastAPI(
    title="Tendrils Server",
    description="A headless Dungeon Master for AI bot combat arenas",
    version="0.1.0",
)

# Load or create the singleton game
loaded = load_game(SAVE_FILE)
if loaded is not None:
    app.state.game = loaded
    # If the server restarts while in COMPLETED state, transition to WAITING
    if loaded.status == GameStatus.COMPLETED:
        end_combat(loaded)
        save_game(loaded, SAVE_FILE)
else:
    app.state.game = create_game(GAME_ID, name=GAME_NAME)

app.include_router(lobby_router, prefix="/game", tags=["Lobby"])
app.include_router(game_router, prefix="/game", tags=["Game"])
app.include_router(ws_router, prefix="/game", tags=["WebSocket"])


@app.get("/")
def root() -> dict:
    """Root endpoint returning server info."""
    return {"name": "Tendrils Server", "version": "0.1.0", "status": "running"}


@app.get("/health")
def health() -> dict:
    """Health check endpoint."""
    return {"healthy": True}
