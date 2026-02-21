"""Tests for D&D 5e SRD combat rules."""

import pytest

from engine.rules import (
    apply_damage,
    calculate_ability_modifier,
    check_death,
    roll_initiative,
    validate_action,
)
from engine.grid import create_grid
from models.actions import ActionType
from models.characters import AbilityScores, Attack, Character
from models.game_state import GameState


def _make_character(
    char_id: str = "c1",
    owner_id: str = "owner1",
    position: tuple[int, int] | None = (2, 2),
    hp: int = 20,
    ac: int = 15,
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
        armor_class=ac,
        speed=30,
        position=position,
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


def _make_game_state() -> GameState:
    """Helper to create a test game state with two characters."""
    grid = create_grid(10, 10)
    gs = GameState(game_id="test", grid=grid)

    c1 = _make_character("c1", "owner1", position=(2, 2))
    c2 = _make_character("c2", "owner2", position=(3, 2))

    gs.characters["c1"] = c1
    gs.characters["c2"] = c2
    gs.grid[2][2].occupant_id = "c1"
    gs.grid[2][3].occupant_id = "c2"

    return gs


class TestAbilityModifier:
    """Tests for calculate_ability_modifier()."""

    def test_score_10(self):
        assert calculate_ability_modifier(10) == 0

    def test_score_16(self):
        assert calculate_ability_modifier(16) == 3

    def test_score_8(self):
        assert calculate_ability_modifier(8) == -1

    def test_score_1(self):
        assert calculate_ability_modifier(1) == -5

    def test_score_20(self):
        assert calculate_ability_modifier(20) == 5

    def test_score_11(self):
        """Odd scores round down."""
        assert calculate_ability_modifier(11) == 0

    def test_score_9(self):
        assert calculate_ability_modifier(9) == -1


class TestRollInitiative:
    """Tests for roll_initiative()."""

    def test_returns_int(self):
        char = _make_character(dex=14)
        result = roll_initiative(char)
        assert isinstance(result, int)

    def test_includes_dex_modifier(self):
        """Initiative should be d20 + dex modifier, so range is (1+mod) to (20+mod)."""
        char = _make_character(dex=14)  # +2 modifier
        results = [roll_initiative(char) for _ in range(100)]
        assert min(results) >= 3   # 1 + 2
        assert max(results) <= 22  # 20 + 2


class TestValidateAction:
    """Tests for validate_action()."""

    def test_end_turn_always_valid(self):
        gs = _make_game_state()
        valid, err = validate_action(ActionType.END_TURN, gs.characters["c1"], gs)
        assert valid
        assert err == ""

    def test_attack_valid_adjacent(self):
        gs = _make_game_state()
        valid, err = validate_action(
            ActionType.ATTACK, gs.characters["c1"], gs, target_id="c2",
        )
        assert valid

    def test_attack_no_target(self):
        gs = _make_game_state()
        valid, err = validate_action(
            ActionType.ATTACK, gs.characters["c1"], gs,
        )
        assert not valid
        assert "target_id" in err.lower()

    def test_attack_dead_target(self):
        gs = _make_game_state()
        gs.characters["c2"].is_alive = False
        gs.characters["c2"].current_hp = 0
        valid, err = validate_action(
            ActionType.ATTACK, gs.characters["c1"], gs, target_id="c2",
        )
        assert not valid
        assert "dead" in err.lower()

    def test_attack_out_of_range(self):
        gs = _make_game_state()
        gs.characters["c2"].position = (9, 9)
        valid, err = validate_action(
            ActionType.ATTACK, gs.characters["c1"], gs, target_id="c2",
        )
        assert not valid
        assert "reach" in err.lower() or "range" in err.lower()

    def test_dead_character_cant_act(self):
        gs = _make_game_state()
        gs.characters["c1"].is_alive = False
        valid, err = validate_action(
            ActionType.ATTACK, gs.characters["c1"], gs, target_id="c2",
        )
        assert not valid
        assert "dead" in err.lower()

    def test_dodge_valid(self):
        gs = _make_game_state()
        valid, err = validate_action(ActionType.DODGE, gs.characters["c1"], gs)
        assert valid

    def test_dash_valid(self):
        gs = _make_game_state()
        valid, err = validate_action(ActionType.DASH, gs.characters["c1"], gs)
        assert valid

    def test_move_requires_position(self):
        gs = _make_game_state()
        valid, err = validate_action(
            ActionType.MOVE, gs.characters["c1"], gs,
        )
        assert not valid
        assert "target_position" in err.lower()


class TestApplyDamage:
    """Tests for apply_damage() and check_death()."""

    def test_basic_damage(self):
        char = _make_character(hp=20)
        apply_damage(char, 5)
        assert char.current_hp == 15
        assert char.is_alive

    def test_lethal_damage(self):
        char = _make_character(hp=20)
        apply_damage(char, 20)
        assert char.current_hp == 0
        assert not char.is_alive

    def test_overkill_damage(self):
        """Damage beyond 0 HP doesn't go negative."""
        char = _make_character(hp=10)
        apply_damage(char, 50)
        assert char.current_hp == 0
        assert not char.is_alive

    def test_zero_damage(self):
        char = _make_character(hp=20)
        apply_damage(char, 0)
        assert char.current_hp == 20
        assert char.is_alive

    def test_check_death_alive(self):
        char = _make_character(hp=20)
        assert not check_death(char)

    def test_check_death_dead(self):
        char = _make_character(hp=20)
        char.current_hp = 0
        assert check_death(char)
