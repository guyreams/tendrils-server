# Tendrils Server

A headless Dungeon Master server for AI bot combat arenas.

## What It Does

Tendrils Server enforces D&D 5e SRD combat rules on a 2D grid and orchestrates turn-based matches between AI bots via a REST API. There is no visual frontend — the server is the rules engine, state manager, and arbiter. AI bots are the players.

## Quick Start

### Install dependencies

```bash
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

### Run the server

```bash
uvicorn main:app --reload
```

The server starts at `http://localhost:8000`. API docs are at `http://localhost:8000/docs`.

### Run the example bot

In a separate terminal (with the server running):

```bash
python bots/example_bot.py
```

### Run tests

```bash
pytest tests/ -v
```

## API Overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Server info |
| GET | `/health` | Health check |
| POST | `/games` | Create a new game |
| POST | `/games/{id}/join` | Register a character to a game |
| POST | `/games/{id}/start` | Start combat |
| GET | `/games/{id}` | Get game metadata and status |
| GET | `/games/{id}/state?character_id=X` | Get game state from a character's perspective |
| POST | `/games/{id}/action` | Submit an action |
| GET | `/games/{id}/log` | Get the full event log |
| WS | `/games/{id}/ws?character_id=X` | Real-time notifications |

## How to Build a Bot

1. **Create a game** — `POST /games`
2. **Join with a character** — `POST /games/{id}/join` with character stats and attacks
3. **Start combat** — `POST /games/{id}/start` (needs 2+ characters)
4. **Poll for your turn** — `GET /games/{id}/state?character_id=YOUR_ID` and check `is_your_turn`
5. **Submit actions** — `POST /games/{id}/action` with your character ID and action type
6. **Repeat** until `status` is `"completed"`

### Action types

- `move` — Move to a grid position (provide `target_position`)
- `attack` — Attack a target (provide `target_id`, optionally `weapon_name`)
- `dodge` — Attacks against you have disadvantage until your next turn
- `dash` — Double your movement speed this turn
- `disengage` — Your movement doesn't provoke opportunity attacks
- `end_turn` — End your turn

## Current Limitations

- **Prototype status** — In-memory only, no persistence
- **Melee only** — Ranged weapon mechanics not fully implemented
- **No spellcasting** — Spell slots and spells are not in Phase 1
- **No authentication** — No API keys or auth required
- **No matchmaking** — Games are created and joined manually
- **Simplified death** — Characters die at 0 HP (no death saves)
- **No opportunity attacks** — Mentioned in rules but not implemented
- **No fog of war** — All characters see everything
