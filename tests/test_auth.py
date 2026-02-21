"""Tests for API key authentication and admin endpoints."""

import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from auth import (
    User,
    _tokens,
    create_token,
    delete_token,
    get_token_for_owner,
    get_user_by_token,
    load_tokens,
    rotate_token,
    save_tokens,
    update_user,
)


@pytest.fixture(autouse=True)
def _clear_tokens():
    """Reset token store before each test."""
    _tokens.clear()
    yield
    _tokens.clear()


class TestTokenStore:
    """Tests for load_tokens / save_tokens / create_token."""

    def test_load_nonexistent_returns_empty(self, tmp_path):
        path = str(tmp_path / "missing.json")
        tokens = load_tokens(path)
        assert tokens == {}

    def test_create_and_save_roundtrip(self, tmp_path):
        path = str(tmp_path / "tokens.json")
        load_tokens(path)

        key = create_token("bot_a", "Bot A")
        save_tokens(path)

        # Load into a fresh store
        _tokens.clear()
        loaded = load_tokens(path)
        assert key in loaded
        assert loaded[key].owner_id == "bot_a"
        assert loaded[key].name == "Bot A"

    def test_create_token_prefix(self):
        key = create_token("bot_a", "Bot A")
        assert key.startswith("sk_")
        assert len(key) == 3 + 64  # "sk_" + 32 bytes hex

    def test_duplicate_owner_id_rejected(self):
        create_token("bot_a", "Bot A")
        with pytest.raises(ValueError, match="already registered"):
            create_token("bot_a", "Bot A Again")

    def test_get_user_by_token(self):
        key = create_token("bot_a", "Bot A")
        user = get_user_by_token(key)
        assert user is not None
        assert user.owner_id == "bot_a"

    def test_get_user_by_invalid_token(self):
        assert get_user_by_token("sk_doesnotexist") is None


class TestAdminEndpoint:
    """Tests for POST /admin/register."""

    @pytest.fixture
    def client(self, tmp_path):
        """Create a test client with a temporary token store."""
        # Patch TOKENS_FILE for this test
        import auth
        import config
        old_tokens_file = config.TOKENS_FILE
        config.TOKENS_FILE = str(tmp_path / "tokens.json")
        auth.TOKENS_FILE = config.TOKENS_FILE

        from main import app
        load_tokens(config.TOKENS_FILE)
        yield TestClient(app)

        config.TOKENS_FILE = old_tokens_file
        auth.TOKENS_FILE = old_tokens_file

    def test_register_success(self, client):
        resp = client.post(
            "/admin/register",
            json={"owner_id": "bot_a", "name": "Bot A"},
            headers={"X-Admin-Secret": "change-me-in-production"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["owner_id"] == "bot_a"
        assert data["api_key"].startswith("sk_")

    def test_register_wrong_secret(self, client):
        resp = client.post(
            "/admin/register",
            json={"owner_id": "bot_a", "name": "Bot A"},
            headers={"X-Admin-Secret": "wrong-secret"},
        )
        assert resp.status_code == 403

    def test_register_missing_secret(self, client):
        resp = client.post(
            "/admin/register",
            json={"owner_id": "bot_a", "name": "Bot A"},
        )
        assert resp.status_code == 422  # Missing required header

    def test_register_duplicate_owner(self, client):
        client.post(
            "/admin/register",
            json={"owner_id": "bot_a", "name": "Bot A"},
            headers={"X-Admin-Secret": "change-me-in-production"},
        )
        resp = client.post(
            "/admin/register",
            json={"owner_id": "bot_a", "name": "Bot A Again"},
            headers={"X-Admin-Secret": "change-me-in-production"},
        )
        assert resp.status_code == 409


class TestAuthProtection:
    """Tests that protected endpoints require valid auth."""

    @pytest.fixture
    def client(self, tmp_path):
        """Create a test client with a temporary token store."""
        import auth
        import config
        old_tokens_file = config.TOKENS_FILE
        config.TOKENS_FILE = str(tmp_path / "tokens.json")
        auth.TOKENS_FILE = config.TOKENS_FILE

        from main import app
        load_tokens(config.TOKENS_FILE)
        yield TestClient(app)

        config.TOKENS_FILE = old_tokens_file
        auth.TOKENS_FILE = old_tokens_file

    def _register_and_get_key(self, client) -> str:
        resp = client.post(
            "/admin/register",
            json={"owner_id": "tester", "name": "Tester"},
            headers={"X-Admin-Secret": "change-me-in-production"},
        )
        return resp.json()["api_key"]

    def test_join_requires_auth(self, client):
        resp = client.post(
            "/game/join",
            json={"name": "Test", "max_hp": 20, "armor_class": 15},
        )
        assert resp.status_code == 401

    def test_join_rejects_bad_token(self, client):
        resp = client.post(
            "/game/join",
            json={"name": "Test", "max_hp": 20, "armor_class": 15},
            headers={"Authorization": "Bearer sk_badtoken"},
        )
        assert resp.status_code == 401

    def test_join_with_valid_token(self, client):
        key = self._register_and_get_key(client)
        resp = client.post(
            "/game/join",
            json={
                "name": "Test Fighter",
                "max_hp": 20,
                "armor_class": 15,
                "attacks": [{
                    "name": "Sword",
                    "attack_bonus": 5,
                    "damage_dice": "1d8",
                    "damage_bonus": 3,
                    "damage_type": "slashing",
                }],
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200
        assert "character_id" in resp.json()

    def test_state_requires_auth(self, client):
        resp = client.get("/game/state")
        assert resp.status_code == 401

    def test_action_requires_auth(self, client):
        resp = client.post(
            "/game/action",
            json={"action_type": "end_turn"},
        )
        assert resp.status_code == 401

    def test_start_requires_auth(self, client):
        resp = client.post("/game/start")
        assert resp.status_code == 401

    def test_public_endpoints_no_auth(self, client):
        """Public endpoints should work without auth."""
        assert client.get("/").status_code == 200
        assert client.get("/health").status_code == 200
        assert client.get("/game").status_code == 200
        assert client.get("/game/log").status_code == 200
        assert client.get("/game/history").status_code == 200


class TestOwnershipEnforcement:
    """Tests that users can only act on their own characters."""

    @pytest.fixture
    def setup(self, tmp_path):
        """Set up two registered users with characters."""
        import auth
        import config
        old_tokens_file = config.TOKENS_FILE
        config.TOKENS_FILE = str(tmp_path / "tokens.json")
        auth.TOKENS_FILE = config.TOKENS_FILE

        from main import app
        load_tokens(config.TOKENS_FILE)
        client = TestClient(app)

        # Register two users
        resp = client.post(
            "/admin/register",
            json={"owner_id": "user_a", "name": "User A"},
            headers={"X-Admin-Secret": "change-me-in-production"},
        )
        key_a = resp.json()["api_key"]

        resp = client.post(
            "/admin/register",
            json={"owner_id": "user_b", "name": "User B"},
            headers={"X-Admin-Secret": "change-me-in-production"},
        )
        key_b = resp.json()["api_key"]

        char_data = {
            "name": "Fighter",
            "max_hp": 20,
            "armor_class": 15,
            "attacks": [{
                "name": "Sword",
                "attack_bonus": 5,
                "damage_dice": "1d8",
                "damage_bonus": 3,
                "damage_type": "slashing",
            }],
        }

        # Join characters
        resp = client.post(
            "/game/join",
            json={**char_data, "name": "Fighter A"},
            headers={"Authorization": f"Bearer {key_a}"},
        )
        char_a_id = resp.json()["character_id"]

        resp = client.post(
            "/game/join",
            json={**char_data, "name": "Fighter B"},
            headers={"Authorization": f"Bearer {key_b}"},
        )
        char_b_id = resp.json()["character_id"]

        yield {
            "client": client,
            "key_a": key_a,
            "key_b": key_b,
            "char_a_id": char_a_id,
            "char_b_id": char_b_id,
        }

        config.TOKENS_FILE = old_tokens_file
        auth.TOKENS_FILE = old_tokens_file

    def test_state_returns_own_character(self, setup):
        """GET /game/state returns the character belonging to the token owner."""
        client = setup["client"]
        resp = client.get(
            "/game/state",
            headers={"Authorization": f"Bearer {setup['key_a']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["your_character"]["id"] == setup["char_a_id"]

    def test_state_different_user_sees_own_char(self, setup):
        """Each user sees their own character via /game/state."""
        client = setup["client"]
        resp = client.get(
            "/game/state",
            headers={"Authorization": f"Bearer {setup['key_b']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["your_character"]["id"] == setup["char_b_id"]


class TestTokenHelpers:
    """Tests for delete_token / update_user / get_token_for_owner / rotate_token."""

    def test_delete_token_success(self):
        create_token("bot_a", "Bot A")
        assert delete_token("bot_a") is True
        assert len(_tokens) == 0

    def test_delete_token_not_found(self):
        assert delete_token("nonexistent") is False

    def test_delete_token_persists(self, tmp_path):
        path = str(tmp_path / "tokens.json")
        load_tokens(path)
        key = create_token("bot_a", "Bot A")
        save_tokens(path)
        delete_token("bot_a")
        save_tokens(path)

        _tokens.clear()
        loaded = load_tokens(path)
        assert key not in loaded
        assert len(loaded) == 0

    def test_update_user_success(self):
        create_token("bot_a", "Bot A")
        assert update_user("bot_a", "New Name") is True
        for user in _tokens.values():
            if user.owner_id == "bot_a":
                assert user.name == "New Name"

    def test_update_user_not_found(self):
        assert update_user("nonexistent", "Name") is False

    def test_update_user_persists(self, tmp_path):
        path = str(tmp_path / "tokens.json")
        load_tokens(path)
        key = create_token("bot_a", "Bot A")
        save_tokens(path)
        update_user("bot_a", "Updated")
        save_tokens(path)

        _tokens.clear()
        loaded = load_tokens(path)
        assert loaded[key].name == "Updated"

    def test_get_token_for_owner_success(self):
        key = create_token("bot_a", "Bot A")
        assert get_token_for_owner("bot_a") == key

    def test_get_token_for_owner_not_found(self):
        assert get_token_for_owner("nonexistent") is None

    def test_rotate_token_success(self):
        old_key = create_token("bot_a", "Bot A")
        new_key = rotate_token("bot_a")
        assert new_key is not None
        assert new_key != old_key
        assert new_key.startswith("sk_")
        assert old_key not in _tokens
        assert new_key in _tokens
        assert _tokens[new_key].owner_id == "bot_a"
        assert _tokens[new_key].name == "Bot A"

    def test_rotate_token_not_found(self):
        assert rotate_token("nonexistent") is None

    def test_rotate_token_old_key_invalid(self):
        old_key = create_token("bot_a", "Bot A")
        rotate_token("bot_a")
        assert get_user_by_token(old_key) is None

    def test_rotate_token_persists(self, tmp_path):
        path = str(tmp_path / "tokens.json")
        load_tokens(path)
        old_key = create_token("bot_a", "Bot A")
        save_tokens(path)
        new_key = rotate_token("bot_a")
        save_tokens(path)

        _tokens.clear()
        loaded = load_tokens(path)
        assert old_key not in loaded
        assert new_key in loaded


ADMIN_HEADERS = {"X-Admin-Secret": "change-me-in-production"}


class TestAdminCRUD:
    """Tests for the admin CRUD endpoints (get-token, edit, rotate, delete)."""

    @pytest.fixture
    def client(self, tmp_path):
        """Create a test client with a temporary token store."""
        import auth
        import config
        old_tokens_file = config.TOKENS_FILE
        config.TOKENS_FILE = str(tmp_path / "tokens.json")
        auth.TOKENS_FILE = config.TOKENS_FILE

        from main import app
        load_tokens(config.TOKENS_FILE)
        yield TestClient(app)

        config.TOKENS_FILE = old_tokens_file
        auth.TOKENS_FILE = old_tokens_file

    def _register(self, client, owner_id: str, name: str) -> str:
        """Register a user and return the API key."""
        resp = client.post(
            "/admin/register",
            json={"owner_id": owner_id, "name": name},
            headers=ADMIN_HEADERS,
        )
        return resp.json()["api_key"]

    def _join(self, client, key: str, name: str = "Fighter") -> str:
        """Join the game with a character and return the character_id."""
        resp = client.post(
            "/game/join",
            json={
                "name": name,
                "max_hp": 20,
                "armor_class": 15,
                "attacks": [{
                    "name": "Sword",
                    "attack_bonus": 5,
                    "damage_dice": "1d8",
                    "damage_bonus": 3,
                    "damage_type": "slashing",
                }],
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        return resp.json()["character_id"]

    # ── GET /admin/users/{owner_id}/token ──

    def test_get_token_success(self, client):
        key = self._register(client, "bot_a", "Bot A")
        resp = client.get("/admin/users/bot_a/token", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["api_key"] == key
        assert resp.json()["owner_id"] == "bot_a"

    def test_get_token_not_found(self, client):
        resp = client.get("/admin/users/nonexistent/token", headers=ADMIN_HEADERS)
        assert resp.status_code == 404

    def test_get_token_wrong_secret(self, client):
        resp = client.get(
            "/admin/users/bot_a/token",
            headers={"X-Admin-Secret": "wrong"},
        )
        assert resp.status_code == 403

    # ── PATCH /admin/users/{owner_id} ──

    def test_edit_user_success(self, client):
        self._register(client, "bot_a", "Bot A")
        resp = client.patch(
            "/admin/users/bot_a",
            json={"name": "New Name"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["owner_id"] == "bot_a"
        assert resp.json()["name"] == "New Name"

        # Verify it persisted to user list
        users_resp = client.get("/admin/users", headers=ADMIN_HEADERS)
        users = users_resp.json()
        bot_a = next(u for u in users if u["owner_id"] == "bot_a")
        assert bot_a["name"] == "New Name"

    def test_edit_user_not_found(self, client):
        resp = client.patch(
            "/admin/users/nonexistent",
            json={"name": "Name"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 404

    def test_edit_user_wrong_secret(self, client):
        resp = client.patch(
            "/admin/users/bot_a",
            json={"name": "Name"},
            headers={"X-Admin-Secret": "wrong"},
        )
        assert resp.status_code == 403

    # ── POST /admin/users/{owner_id}/rotate-token ──

    def test_rotate_token_success(self, client):
        old_key = self._register(client, "bot_a", "Bot A")
        resp = client.post("/admin/users/bot_a/rotate-token", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        new_key = resp.json()["api_key"]
        assert new_key != old_key
        assert new_key.startswith("sk_")

        # Old key should be rejected
        resp2 = client.get(
            "/game/state",
            headers={"Authorization": f"Bearer {old_key}"},
        )
        assert resp2.status_code == 401

        # New key should work
        resp3 = client.get(
            "/game",
            headers={"Authorization": f"Bearer {new_key}"},
        )
        assert resp3.status_code == 200

    def test_rotate_token_not_found(self, client):
        resp = client.post("/admin/users/nonexistent/rotate-token", headers=ADMIN_HEADERS)
        assert resp.status_code == 404

    def test_rotate_token_wrong_secret(self, client):
        resp = client.post(
            "/admin/users/bot_a/rotate-token",
            headers={"X-Admin-Secret": "wrong"},
        )
        assert resp.status_code == 403

    # ── DELETE /admin/users/{owner_id} ──

    def test_delete_user_success(self, client):
        self._register(client, "bot_a", "Bot A")
        resp = client.delete("/admin/users/bot_a", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["message"] == "User 'bot_a' deleted"

        # Verify user is gone from the list
        users_resp = client.get("/admin/users", headers=ADMIN_HEADERS)
        owner_ids = [u["owner_id"] for u in users_resp.json()]
        assert "bot_a" not in owner_ids

    def test_delete_user_not_found(self, client):
        resp = client.delete("/admin/users/nonexistent", headers=ADMIN_HEADERS)
        assert resp.status_code == 404

    def test_delete_user_wrong_secret(self, client):
        resp = client.delete(
            "/admin/users/bot_a",
            headers={"X-Admin-Secret": "wrong"},
        )
        assert resp.status_code == 403

    def test_delete_user_with_no_character(self, client):
        """Deleting a user who never joined should report character_removed=false."""
        self._register(client, "bot_a", "Bot A")
        resp = client.delete("/admin/users/bot_a", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["character_removed"] is False

    def test_delete_user_removes_character(self, client):
        """Deleting a user should remove their character from the game."""
        key = self._register(client, "bot_a", "Bot A")
        self._join(client, key, "Fighter A")

        # Confirm character is in the game
        game = client.get("/game").json()
        assert any(c["name"] == "Fighter A" for c in game["characters"])

        resp = client.delete("/admin/users/bot_a", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["character_removed"] is True

        # Character should be gone
        game = client.get("/game").json()
        assert not any(c.get("owner_id") == "bot_a" for c in game["characters"])

    def test_delete_user_token_invalidated(self, client):
        """After deleting a user, their API key should be rejected."""
        key = self._register(client, "bot_a", "Bot A")
        client.delete("/admin/users/bot_a", headers=ADMIN_HEADERS)

        resp = client.get(
            "/game/state",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 401

    def test_rotate_then_join(self, client):
        """After rotating a key, the new key should work for joining."""
        self._register(client, "bot_a", "Bot A")
        resp = client.post("/admin/users/bot_a/rotate-token", headers=ADMIN_HEADERS)
        new_key = resp.json()["api_key"]

        join_resp = client.post(
            "/game/join",
            json={
                "name": "Rotated Fighter",
                "max_hp": 20,
                "armor_class": 15,
                "attacks": [{
                    "name": "Sword",
                    "attack_bonus": 5,
                    "damage_dice": "1d8",
                    "damage_bonus": 3,
                    "damage_type": "slashing",
                }],
            },
            headers={"Authorization": f"Bearer {new_key}"},
        )
        assert join_resp.status_code == 200
        assert "character_id" in join_resp.json()
