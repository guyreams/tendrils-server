"""Server-wide configuration constants for Tendrils Server."""

import os

GRID_WIDTH = 20          # Grid width in 5ft squares
GRID_HEIGHT = 20         # Grid height in 5ft squares
SQUARE_SIZE_FT = 5       # Each square = 5 feet
TURN_TIMEOUT_SECONDS = 30  # Max time a bot has to submit an action
MAX_PLAYERS_PER_GAME = 6
DEFAULT_MOVEMENT_SPEED = 30  # feet per turn (6 squares)
DATA_DIR = os.environ.get("DATA_DIR", ".")  # Persistent data directory
SAVE_FILE = os.path.join(DATA_DIR, "game_state.json")
GAME_NAME = "Tendrils Arena"   # Name of the single persistent game
GAME_ID = "tendrils"           # Fixed game ID
TOKENS_FILE = os.path.join(DATA_DIR, "tokens.json")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "change-me-in-production")
