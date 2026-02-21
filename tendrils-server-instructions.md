# Tendrils Server — Claude Code Build Instructions

## Project Overview

Build a Python game server called **tendrils-server** that acts as a headless Dungeon Master for AI bot combat. The server enforces tabletop RPG rules (based on D&D 5e SRD / Creative Commons content), manages a 2D grid battlefield, orchestrates turn-based combat, and exposes a REST API so that external AI bots can join matches and submit actions.

There is no visual frontend. The server is the rules engine, state manager, and arbiter. AI bots are the players.

---

## Tech Stack

- **Python 3.12+**
- **FastAPI** — REST API framework
- **Uvicorn** — ASGI server
- **Pydantic v2** — data models and validation
- **WebSockets** (via FastAPI) — real-time turn notifications
- In-memory game state (Python dicts) — no database for the prototype

---

## Project Structure

Create this exact directory and file structure:

```
tendrils-server/
├── main.py                     # FastAPI app entry point, mounts routers
├── requirements.txt            # Python dependencies
├── Procfile                    # For Railway/deployment: web: uvicorn main:app --host 0.0.0.0 --port $PORT
├── .gitignore                  # venv/, __pycache__/, *.pyc, .env
├── README.md                   # Project overview, setup instructions, API summary
│
├── config.py                   # Server configuration constants (grid size, turn timeout, etc.)
│
├── models/
│   ├── __init__.py
│   ├── characters.py           # Character/creature data models
│   ├── game_state.py           # GameState, Grid, InitiativeTracker models
│   └── actions.py              # Action request/response models
│
├── engine/
│   ├── __init__.py
│   ├── dice.py                 # Dice rolling utilities
│   ├── grid.py                 # 2D grid, movement, distance, line of sight
│   ├── rules.py                # Action validation, attack resolution, damage calc
│   └── combat.py               # Turn manager, initiative, game loop, win conditions
│
├── api/
│   ├── __init__.py
│   ├── lobby.py                # Game creation, bot registration endpoints
│   ├── game.py                 # Action submission, state retrieval, game log
│   └── ws.py                   # WebSocket endpoint for real-time notifications
│
├── bots/
│   └── example_bot.py          # Reference bot that plays via the API (random legal moves)
│
└── tests/
    ├── __init__.py
    ├── test_dice.py
    ├── test_grid.py
    ├── test_rules.py
    └── test_combat.py
```

---

## Detailed File Specifications

### `config.py`

Define server-wide constants:

```python
GRID_WIDTH = 20          # Grid width in 5ft squares
GRID_HEIGHT = 20         # Grid height in 5ft squares
SQUARE_SIZE_FT = 5       # Each square = 5 feet
TURN_TIMEOUT_SECONDS = 30  # Max time a bot has to submit an action
MAX_PLAYERS_PER_GAME = 6
DEFAULT_MOVEMENT_SPEED = 30  # feet per turn (6 squares)
```

---

### `models/characters.py`

Define Pydantic models for characters/creatures:

```python
class AbilityScores(BaseModel):
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10

class Character(BaseModel):
    id: str                         # Unique identifier
    name: str
    owner_id: str                   # The bot/player that controls this character
    ability_scores: AbilityScores
    max_hp: int
    current_hp: int
    armor_class: int
    speed: int = 30                 # Movement speed in feet
    position: tuple[int, int] | None = None  # Grid position (x, y)
    initiative: int = 0
    is_alive: bool = True
    conditions: list[str] = []      # e.g., ["prone", "grappled"]
    attacks: list[Attack] = []      # Available attacks

class Attack(BaseModel):
    name: str                       # e.g., "Longsword"
    attack_bonus: int               # Added to d20 roll
    damage_dice: str                # e.g., "1d8"
    damage_bonus: int               # Added to damage roll
    damage_type: str                # e.g., "slashing"
    reach: int = 5                  # Reach in feet (5 for melee, higher for ranged)
    range_normal: int | None = None # For ranged attacks
    range_long: int | None = None   # Disadvantage range
```

---

### `models/game_state.py`

```python
class GameStatus(str, Enum):
    WAITING = "waiting"             # Lobby, waiting for players
    ACTIVE = "active"               # Combat in progress
    COMPLETED = "completed"         # Game over

class GridCell(BaseModel):
    x: int
    y: int
    terrain: str = "open"           # "open", "wall", "difficult"
    occupant_id: str | None = None

class GameState(BaseModel):
    game_id: str
    status: GameStatus = GameStatus.WAITING
    grid: list[list[GridCell]]      # 2D grid
    characters: dict[str, Character]  # character_id -> Character
    initiative_order: list[str] = []  # Ordered list of character IDs
    current_turn_index: int = 0
    round_number: int = 1
    turn_deadline: datetime | None = None
    event_log: list[GameEvent] = []
    winner_id: str | None = None

class GameEvent(BaseModel):
    round: int
    character_id: str
    action_type: str
    description: str
    details: dict = {}              # Rolls, damage, etc.
    timestamp: datetime
```

---

### `models/actions.py`

Define what bots can request and what the server returns:

```python
class ActionType(str, Enum):
    MOVE = "move"
    ATTACK = "attack"
    DODGE = "dodge"
    DASH = "dash"                   # Double movement
    DISENGAGE = "disengage"         # Move without opportunity attacks
    END_TURN = "end_turn"

class ActionRequest(BaseModel):
    action_type: ActionType
    target_id: str | None = None        # For attacks
    target_position: tuple[int, int] | None = None  # For movement
    weapon_name: str | None = None      # For attacks

class ActionResult(BaseModel):
    success: bool
    action_type: ActionType
    description: str                    # Human-readable narrative
    attack_roll: int | None = None
    hit: bool | None = None
    damage_dealt: int | None = None
    target_hp_remaining: int | None = None
    movement_path: list[tuple[int, int]] | None = None
    error: str | None = None            # If action was invalid

class TurnState(BaseModel):
    """What the bot receives when it's their turn."""
    game_id: str
    round_number: int
    your_character: Character
    visible_characters: list[Character]  # Enemies/allies the bot can see
    available_actions: list[ActionType]
    turn_deadline: datetime
```

---

### `engine/dice.py`

Implement dice rolling:

- `roll(notation: str) -> DiceResult` — Parse and roll dice notation like "2d6+3", "1d20", "4d6"
- `roll_d20(advantage: bool = False, disadvantage: bool = False) -> int`
- `DiceResult` model with: `total`, `rolls` (individual die results), `modifier`, `notation`

Use Python's `random` module. Seed support for testing.

---

### `engine/grid.py`

Implement spatial logic:

- `create_grid(width, height) -> list[list[GridCell]]` — Initialize empty grid
- `distance(pos1, pos2) -> int` — Distance in feet between two positions (use 5e grid rules: diagonal = 5ft)
- `get_valid_moves(character, grid) -> list[tuple[int, int]]` — All positions a character can move to given their speed, walls, and other occupants
- `move_character(character_id, target_pos, game_state) -> list[tuple[int, int]]` — Move character, return path taken. Validate movement cost.
- `is_adjacent(pos1, pos2) -> bool` — Are two positions within 5ft (adjacent squares including diagonals)
- `line_of_sight(pos1, pos2, grid) -> bool` — Can pos1 see pos2? (Simple: blocked by walls only)

Grid uses (x, y) coordinates. (0,0) is top-left.

---

### `engine/rules.py`

Implement D&D 5e SRD combat rules:

- `validate_action(action, character, game_state) -> tuple[bool, str]` — Check if action is legal. Return (valid, error_message).
- `resolve_attack(attacker, target, weapon, game_state) -> ActionResult` — Roll to hit (d20 + attack_bonus vs AC), roll damage if hit, apply damage.
- `calculate_ability_modifier(score: int) -> int` — Standard 5e formula: (score - 10) // 2
- `roll_initiative(character) -> int` — d20 + dexterity modifier
- `apply_damage(character, damage: int) -> Character` — Reduce HP, check for death
- `check_death(character) -> bool` — Is character at 0 HP?

Key rules to enforce:
- A character can take ONE action per turn (Attack, Dodge, Dash, Disengage)
- A character can move up to their speed on their turn (can split movement before/after action)
- Attack rolls: d20 + attack_bonus >= target AC = hit
- Dodge action: attacks against this character have disadvantage until their next turn
- Dash action: double movement speed this turn
- Disengage action: movement doesn't provoke opportunity attacks this turn

---

### `engine/combat.py`

Implement the combat orchestration:

- `create_game(game_id: str) -> GameState` — Initialize a new game with empty grid
- `add_character(game_state, character, starting_position) -> GameState` — Place a character on the grid
- `start_combat(game_state) -> GameState` — Roll initiative for all characters, set turn order, set status to ACTIVE
- `get_current_turn_character(game_state) -> Character` — Who's turn is it?
- `process_action(game_state, character_id, action) -> tuple[GameState, ActionResult]` — Validate + resolve action, advance turn if needed
- `advance_turn(game_state) -> GameState` — Move to next character in initiative, increment round if wrapped
- `check_win_condition(game_state) -> str | None` — Return winner's owner_id if only one team has living characters, else None

Game loop flow:
1. Bots register characters
2. Host starts combat
3. Server rolls initiative, notifies first bot
4. Bot submits action, server validates and resolves
5. Server advances to next turn, notifies next bot
6. Repeat until win condition met

---

### `api/lobby.py` — FastAPI Router

Endpoints:

```
POST /games
    - Creates a new game, returns game_id
    - Request body: { "name": "My Arena" } (optional)
    - Response: { "game_id": "...", "status": "waiting" }

POST /games/{game_id}/join
    - Register a bot and its character to a game
    - Request body: Character data (name, ability_scores, attacks, etc.)
    - Response: { "character_id": "...", "message": "Joined game" }

POST /games/{game_id}/start
    - Start combat (only when 2+ characters have joined)
    - Response: { "message": "Combat started", "initiative_order": [...] }

GET /games/{game_id}
    - Get game metadata and status
    - Response: GameState summary (no hidden info)
```

---

### `api/game.py` — FastAPI Router

Endpoints:

```
GET /games/{game_id}/state
    - Get current game state from a specific character's perspective
    - Query param: character_id (required)
    - Response: TurnState (filtered to what that character can see)

POST /games/{game_id}/action
    - Submit an action for the current turn
    - Request body: ActionRequest + character_id
    - Response: ActionResult
    - Returns 400 if it's not this character's turn
    - Returns 400 if the action is invalid

GET /games/{game_id}/log
    - Full event log for spectators/replay
    - Response: list[GameEvent]
```

---

### `api/ws.py` — WebSocket Router

```
WS /games/{game_id}/ws?character_id={character_id}
    - Real-time notifications
    - Server sends: turn_start (it's your turn), action_result (what just happened),
      game_over (winner announced)
    - Client sends: nothing (use REST for actions) or optionally actions via WS
```

---

### `main.py`

```python
from fastapi import FastAPI
from api.lobby import router as lobby_router
from api.game import router as game_router
from api.ws import router as ws_router

app = FastAPI(
    title="Tendrils Server",
    description="A headless Dungeon Master for AI bot combat arenas",
    version="0.1.0"
)

# In-memory game store
games: dict[str, GameState] = {}

app.include_router(lobby_router, prefix="/games", tags=["Lobby"])
app.include_router(game_router, prefix="/games", tags=["Game"])
app.include_router(ws_router, prefix="/games", tags=["WebSocket"])

@app.get("/")
def root():
    return {"name": "Tendrils Server", "version": "0.1.0", "status": "running"}

@app.get("/health")
def health():
    return {"healthy": True}
```

---

### `bots/example_bot.py`

Build a standalone Python script that:

1. Creates a game via POST /games
2. Joins two characters (a Fighter and a Rogue) via POST /games/{id}/join
3. Starts combat via POST /games/{id}/start
4. Polls for turn state via GET /games/{id}/state
5. On each turn, picks a random valid action:
   - If an enemy is adjacent, attack
   - If an enemy is visible but not adjacent, move toward them
   - Otherwise, end turn
6. Loops until game over
7. Prints the full event log

Use `httpx` as the HTTP client. Add `httpx` to requirements.txt.

---

### `requirements.txt`

```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
pydantic>=2.0.0
websockets>=12.0
httpx>=0.27.0
pytest>=8.0.0
```

---

### `.gitignore`

```
venv/
__pycache__/
*.pyc
.env
.pytest_cache/
```

---

### `README.md`

Write a README that includes:

1. **Project name**: Tendrils Server
2. **One-line description**: A headless Dungeon Master server for AI bot combat arenas
3. **What it does**: Enforces D&D 5e SRD combat rules on a 2D grid, orchestrates turn-based matches between AI bots via REST API
4. **Quick start**: How to install deps, run the server, run the example bot
5. **API overview**: Table of endpoints with methods and descriptions
6. **How to build a bot**: Brief guide on the join → poll → act loop
7. **Current limitations**: Prototype status, melee only (Phase 1), no persistence

---

## Implementation Notes

- Use `uuid4()` for generating game_id and character_id values
- All game state is stored in a module-level dict in main.py (passed to routers via dependency injection or app.state)
- FastAPI's dependency injection should be used to access the game store
- All models use Pydantic v2 syntax (model_validator, field_validator, etc.)
- Return proper HTTP status codes: 404 for missing games, 400 for invalid actions, 409 for wrong turn
- Add docstrings to all public functions
- Add type hints everywhere
- The server should be fully functional end-to-end: create game → join → start → play → win

---

## Testing Notes

Write pytest tests for:

- `test_dice.py`: Dice parsing and rolling, seeded results
- `test_grid.py`: Distance calculation, valid moves, movement, adjacency
- `test_rules.py`: Attack resolution, action validation, damage application
- `test_combat.py`: Initiative, turn advancement, win condition detection

Use `pytest` with basic assertions. No mocking frameworks needed for the prototype.

---

## What NOT to Build Yet

- No database / persistence
- No authentication / API keys
- No matchmaking or ELO
- No spellcasting or spell slots
- No ranged weapon disadvantage at long range
- No opportunity attacks (mentioned but don't implement in Phase 1)
- No death saves (character dies at 0 HP for simplicity)
- No multi-attack
- No terrain effects beyond walls and difficult terrain
- No fog of war (all characters see everything for now)
