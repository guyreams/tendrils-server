"""Tests for API key authentication and admin endpoints."""

import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from auth import User, _tokens, create_token, get_user_by_token, load_tokens, save_tokens


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
