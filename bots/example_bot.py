"""Reference bot that plays Tendrils Server via the REST API.

Creates a game, joins a Fighter and a Rogue, starts combat, and plays
each turn by picking simple tactical actions:
  - If an enemy is adjacent, attack.
  - If an enemy is visible but not adjacent, move toward them.
  - Otherwise, end turn.

Usage:
    1. Start the server:  uvicorn main:app --reload
    2. Run this bot:      python bots/example_bot.py
"""

import sys
import time

import httpx

BASE_URL = "http://localhost:8000"


def main() -> None:
    """Run a complete game between a Fighter and a Rogue."""
    client = httpx.Client(base_url=BASE_URL, timeout=10.0)

    # 1. Create a game
    print("Creating game...")
    resp = client.post("/games", json={"name": "Bot Arena"})
    resp.raise_for_status()
    game_id = resp.json()["game_id"]
    print(f"  Game ID: {game_id}")

    # 2. Join two characters
    fighter_data = {
        "owner_id": "bot_a",
        "name": "Gruk the Fighter",
        "max_hp": 52,
        "armor_class": 18,
        "speed": 30,
        "ability_scores": {
            "strength": 16,
            "dexterity": 12,
            "constitution": 14,
            "intelligence": 8,
            "wisdom": 10,
            "charisma": 10,
        },
        "attacks": [
            {
                "name": "Longsword",
                "attack_bonus": 5,
                "damage_dice": "1d8",
                "damage_bonus": 3,
                "damage_type": "slashing",
                "reach": 5,
            }
        ],
    }

    rogue_data = {
        "owner_id": "bot_b",
        "name": "Silka the Rogue",
        "max_hp": 38,
        "armor_class": 15,
        "speed": 30,
        "ability_scores": {
            "strength": 10,
            "dexterity": 18,
            "constitution": 12,
            "intelligence": 14,
            "wisdom": 12,
            "charisma": 14,
        },
        "attacks": [
            {
                "name": "Shortsword",
                "attack_bonus": 6,
                "damage_dice": "1d6",
                "damage_bonus": 4,
                "damage_type": "piercing",
                "reach": 5,
            }
        ],
    }

    print("Joining Fighter...")
    resp = client.post(f"/games/{game_id}/join", json=fighter_data)
    resp.raise_for_status()
    fighter_id = resp.json()["character_id"]
    print(f"  Fighter ID: {fighter_id}")

    print("Joining Rogue...")
    resp = client.post(f"/games/{game_id}/join", json=rogue_data)
    resp.raise_for_status()
    rogue_id = resp.json()["character_id"]
    print(f"  Rogue ID: {rogue_id}")

    # Map owner_id to character_id for both bots
    bots = {
        fighter_id: "bot_a",
        rogue_id: "bot_b",
    }

    # 3. Start combat
    print("\nStarting combat...")
    resp = client.post(f"/games/{game_id}/start")
    resp.raise_for_status()
    start_data = resp.json()
    print(f"  {start_data['message']}")
    for entry in start_data["initiative_order"]:
        print(f"    {entry}")

    # 4. Game loop
    print("\n--- COMBAT ---\n")
    max_rounds = 100
    turn_count = 0

    while turn_count < max_rounds * 2:
        turn_count += 1

        # Check game status
        resp = client.get(f"/games/{game_id}")
        resp.raise_for_status()
        game_info = resp.json()

        if game_info["status"] == "completed":
            print(f"\n*** GAME OVER! Winner: {game_info['winner_id']} ***")
            break

        # Try each bot's perspective to find whose turn it is
        for char_id in [fighter_id, rogue_id]:
            resp = client.get(
                f"/games/{game_id}/state",
                params={"character_id": char_id},
            )
            resp.raise_for_status()
            state = resp.json()

            if not state["is_your_turn"]:
                continue

            my_char = state["your_character"]
            enemies = [
                c for c in state["visible_characters"]
                if c["owner_id"] != my_char["owner_id"] and c["is_alive"]
            ]

            print(
                f"Round {state['round_number']} | "
                f"{my_char['name']} (HP: {my_char['current_hp']}/{my_char['max_hp']})"
            )

            if not enemies:
                # No enemies — end turn
                _submit_action(client, game_id, char_id, "end_turn")
                break

            enemy = enemies[0]
            my_pos = tuple(my_char["position"])
            enemy_pos = tuple(enemy["position"])
            dist = max(abs(my_pos[0] - enemy_pos[0]), abs(my_pos[1] - enemy_pos[1])) * 5

            if dist <= 5:
                # Adjacent — attack!
                _submit_action(
                    client, game_id, char_id, "attack",
                    target_id=enemy["id"],
                )
            else:
                # Move toward enemy
                dx = _sign(enemy_pos[0] - my_pos[0])
                dy = _sign(enemy_pos[1] - my_pos[1])
                target = (my_pos[0] + dx, my_pos[1] + dy)
                success = _submit_action(
                    client, game_id, char_id, "move",
                    target_position=list(target),
                )
                if not success:
                    # Movement failed, just end turn
                    _submit_action(client, game_id, char_id, "end_turn")

            break

        time.sleep(0.1)  # Small delay for readability

    # 5. Print the full event log
    print("\n--- EVENT LOG ---\n")
    resp = client.get(f"/games/{game_id}/log")
    resp.raise_for_status()
    for event in resp.json():
        print(f"  [Round {event['round']}] {event['description']}")

    client.close()


def _submit_action(
    client: httpx.Client,
    game_id: str,
    character_id: str,
    action_type: str,
    target_id: str | None = None,
    target_position: list[int] | None = None,
) -> bool:
    """Submit an action and print the result. Returns True if successful."""
    payload: dict = {
        "character_id": character_id,
        "action_type": action_type,
    }
    if target_id:
        payload["target_id"] = target_id
    if target_position:
        payload["target_position"] = target_position

    resp = client.post(f"/games/{game_id}/action", json=payload)
    if resp.status_code == 200:
        result = resp.json()
        print(f"  -> {result['description']}")
        return True
    else:
        detail = resp.json().get("detail", resp.text)
        print(f"  -> FAILED: {detail}")
        return False


def _sign(n: int) -> int:
    """Return -1, 0, or 1 based on the sign of n."""
    if n > 0:
        return 1
    if n < 0:
        return -1
    return 0


if __name__ == "__main__":
    main()
