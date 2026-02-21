"""Server-wide configuration constants for Tendrils Server."""

GRID_WIDTH = 20          # Grid width in 5ft squares
GRID_HEIGHT = 20         # Grid height in 5ft squares
SQUARE_SIZE_FT = 5       # Each square = 5 feet
TURN_TIMEOUT_SECONDS = 30  # Max time a bot has to submit an action
MAX_PLAYERS_PER_GAME = 6
DEFAULT_MOVEMENT_SPEED = 30  # feet per turn (6 squares)
SAVE_FILE = "game_state.json"  # Persistence file for the singleton game
GAME_NAME = "Tendrils Arena"   # Name of the single persistent game
GAME_ID = "tendrils"           # Fixed game ID
