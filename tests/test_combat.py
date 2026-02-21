"""Tests for combat orchestration: initiative, turns, win conditions."""

import os
import tempfile

import pytest

from engine.combat import (
    add_character,
    advance_turn,
    check_win_condition,
    create_game,
    get_current_turn_character,
    load_game,
    process_action,
    remove_dead_characters,
    save_game,
    start_combat,
    transition_to_waiting,
)
from models.actions import ActionRequest, ActionType
from models.characters import AbilityScores, Attack, Character
from models.game_state import GameStatus


def _make_character(
    char_id: str,
    owner_id: str,
    hp: int = 20,
    dex: int = 14,
) -> Character:
    """Helper to create a test character."""
    return Character(
        id=char_id,
        name=f"Char_{char_id}",
        owner_id=owner_id,
        ability_scores=AbilityScores(dexterity=dex),
        max_hp=hp,
        current_hp=hp,
        armor_class=15,
        speed=30,
        attacks=[
            Attack(
                name="Sword",
                attack_bonus=5,
                damage_dice="1d8",
                damage_bonus=3,
                damage_type="slashing",
                reach=5,
            )
        ],
    )


class TestCreateGame:
    """Tests for create_game()."""

    def test_creates_game_with_id(self):
        gs = create_game("game1")
        assert gs.game_id == "game1"
        assert gs.status == GameStatus.WAITING

    def test_grid_initialized(self):
        gs = create_game("game1")
        assert len(gs.grid) > 0
        assert len(gs.grid[0]) > 0

    def test_empty_characters(self):
        gs = create_game("game1")
        assert len(gs.characters) == 0


class TestAddCharacter:
    """Tests for add_character()."""

    def test_add_character(self):
        gs = create_game("game1")
        char = _make_character("c1", "owner1")
        add_character(gs, char, (5, 5))
        assert "c1" in gs.characters
        assert gs.characters["c1"].position == (5, 5)
        assert gs.grid[5][5].occupant_id == "c1"

    def test_add_to_occupied_fails(self):
        gs = create_game("game1")
        char1 = _make_character("c1", "owner1")
        char2 = _make_character("c2", "owner2")
        add_character(gs, char1, (5, 5))
        with pytest.raises(ValueError, match="occupied"):
            add_character(gs, char2, (5, 5))

    def test_add_out_of_bounds_fails(self):
        gs = create_game("game1")
        char = _make_character("c1", "owner1")
        with pytest.raises(ValueError, match="out of bounds"):
            add_character(gs, char, (100, 100))


class TestStartCombat:
    """Tests for start_combat()."""

    def test_start_sets_active(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        start_combat(gs)
        assert gs.status == GameStatus.ACTIVE

    def test_initiative_order_set(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        start_combat(gs)
        assert len(gs.initiative_order) == 2
        assert set(gs.initiative_order) == {"c1", "c2"}

    def test_start_with_one_char_fails(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        add_character(gs, c1, (1, 1))
        with pytest.raises(ValueError, match="at least 2"):
            start_combat(gs)

    def test_turn_deadline_set(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        start_combat(gs)
        assert gs.turn_deadline is not None


class TestGetCurrentTurnCharacter:
    """Tests for get_current_turn_character()."""

    def test_returns_first_in_initiative(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        start_combat(gs)
        current = get_current_turn_character(gs)
        assert current is not None
        assert current.id == gs.initiative_order[0]

    def test_returns_none_if_waiting(self):
        gs = create_game("game1")
        assert get_current_turn_character(gs) is None


class TestAdvanceTurn:
    """Tests for advance_turn()."""

    def test_advances_to_next(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        start_combat(gs)

        first_id = gs.initiative_order[0]
        advance_turn(gs)
        current = get_current_turn_character(gs)
        assert current is not None
        assert current.id != first_id

    def test_round_increments_on_wrap(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        start_combat(gs)
        assert gs.round_number == 1
        advance_turn(gs)  # Turn 2
        advance_turn(gs)  # Back to turn 1 -> round 2
        assert gs.round_number == 2

    def test_skips_dead_characters(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        c3 = _make_character("c3", "owner1")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        add_character(gs, c3, (5, 5))
        start_combat(gs)

        # Kill the second character in initiative order
        second_id = gs.initiative_order[1]
        gs.characters[second_id].is_alive = False
        gs.characters[second_id].current_hp = 0

        advance_turn(gs)
        current = get_current_turn_character(gs)
        assert current is not None
        assert current.id != second_id
        assert current.is_alive


class TestCheckWinCondition:
    """Tests for check_win_condition()."""

    def test_no_winner_both_alive(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        assert check_win_condition(gs) is None

    def test_winner_when_one_team_dead(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        gs.characters["c2"].is_alive = False
        gs.characters["c2"].current_hp = 0
        assert check_win_condition(gs) == "owner1"

    def test_no_winner_all_dead(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        gs.characters["c1"].is_alive = False
        gs.characters["c2"].is_alive = False
        assert check_win_condition(gs) is None


class TestProcessAction:
    """Tests for process_action()."""

    def test_end_turn_advances(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        start_combat(gs)

        current_id = get_current_turn_character(gs).id
        action = ActionRequest(
            character_id=current_id,
            action_type=ActionType.END_TURN,
        )
        _, result = process_action(gs, current_id, action)
        assert result.success
        assert get_current_turn_character(gs).id != current_id

    def test_wrong_turn_fails(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        start_combat(gs)

        current_id = get_current_turn_character(gs).id
        other_id = "c1" if current_id == "c2" else "c2"
        action = ActionRequest(
            character_id=other_id,
            action_type=ActionType.END_TURN,
        )
        _, result = process_action(gs, other_id, action)
        assert not result.success
        assert "not your turn" in result.error.lower()

    def test_move_action(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (8, 8))
        start_combat(gs)

        current = get_current_turn_character(gs)
        old_pos = current.position
        # Move one square right
        target = (old_pos[0] + 1, old_pos[1])
        action = ActionRequest(
            character_id=current.id,
            action_type=ActionType.MOVE,
            target_position=target,
        )
        _, result = process_action(gs, current.id, action)
        assert result.success
        assert current.position == target


class TestSaveAndLoadGame:
    """Tests for save_game() and load_game()."""

    def test_save_and_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "test_save.json")
        gs = create_game("game1", name="Test Arena")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))

        save_game(gs, path)
        loaded = load_game(path)

        assert loaded is not None
        assert loaded.game_id == "game1"
        assert loaded.name == "Test Arena"
        assert "c1" in loaded.characters
        assert "c2" in loaded.characters
        assert loaded.characters["c1"].position == (1, 1)
        assert loaded.characters["c2"].position == (3, 3)

    def test_load_nonexistent_returns_none(self, tmp_path):
        path = str(tmp_path / "does_not_exist.json")
        assert load_game(path) is None

    def test_save_preserves_active_state(self, tmp_path):
        path = str(tmp_path / "active_save.json")
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        start_combat(gs)

        save_game(gs, path)
        loaded = load_game(path)

        assert loaded.status == GameStatus.ACTIVE
        assert len(loaded.initiative_order) == 2
        assert loaded.round_number == 1


class TestRemoveDeadCharacters:
    """Tests for remove_dead_characters()."""

    def test_removes_dead_keeps_alive(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        gs.characters["c2"].is_alive = False
        gs.characters["c2"].current_hp = 0

        remove_dead_characters(gs)

        assert "c1" in gs.characters
        assert "c2" not in gs.characters
        assert gs.grid[3][3].occupant_id is None

    def test_clears_grid_occupant(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        add_character(gs, c1, (5, 5))
        gs.characters["c1"].is_alive = False

        remove_dead_characters(gs)
        assert gs.grid[5][5].occupant_id is None

    def test_no_dead_is_noop(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        add_character(gs, c1, (1, 1))

        remove_dead_characters(gs)
        assert "c1" in gs.characters


class TestTransitionToWaiting:
    """Tests for transition_to_waiting()."""

    def test_resets_to_waiting(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        start_combat(gs)

        # Simulate game completion
        gs.characters["c2"].is_alive = False
        gs.characters["c2"].current_hp = 0
        gs.status = GameStatus.COMPLETED
        gs.winner_id = "owner1"

        transition_to_waiting(gs)

        assert gs.status == GameStatus.WAITING
        assert gs.winner_id is None
        assert gs.initiative_order == []
        assert gs.round_number == 1
        assert gs.event_log == []

    def test_removes_dead_keeps_survivors(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1")
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        start_combat(gs)

        gs.characters["c2"].is_alive = False
        gs.characters["c2"].current_hp = 0
        gs.status = GameStatus.COMPLETED

        transition_to_waiting(gs)

        assert "c1" in gs.characters
        assert "c2" not in gs.characters
        assert gs.characters["c1"].is_alive

    def test_survivors_keep_current_hp(self):
        gs = create_game("game1")
        c1 = _make_character("c1", "owner1", hp=50)
        c2 = _make_character("c2", "owner2")
        add_character(gs, c1, (1, 1))
        add_character(gs, c2, (3, 3))
        start_combat(gs)

        # Survivor took some damage
        gs.characters["c1"].current_hp = 30
        gs.characters["c2"].is_alive = False
        gs.characters["c2"].current_hp = 0
        gs.status = GameStatus.COMPLETED

        transition_to_waiting(gs)

        assert gs.characters["c1"].current_hp == 30
        assert gs.characters["c1"].max_hp == 50
