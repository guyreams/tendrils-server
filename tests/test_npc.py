"""Tests for NPC spawning, GOLEM AI, and integration with the combat loop."""

import pytest

from engine.combat import (
    add_character,
    advance_turn,
    check_win_condition,
    create_game,
    end_combat,
    get_current_turn_character,
    process_action,
    spawn_npcs,
    start_combat,
)
from engine.npc import (
    GOLEM_NAME,
    NPC_OWNER_ID,
    create_golem,
    golem_center_position,
    resolve_npc_turn,
)
from models.actions import ActionRequest, ActionType
from models.characters import AbilityScores, Attack, Character
from models.game_state import GameStatus


def _make_player(
    char_id: str,
    owner_id: str,
    hp: int = 20,
    dex: int = 14,
) -> Character:
    """Helper to create a test player character."""
    return Character(
        id=char_id,
        name=f"Player_{char_id}",
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


# ---------------------------------------------------------------------------
# GOLEM creation
# ---------------------------------------------------------------------------

class TestCreateGolem:
    def test_golem_properties(self):
        g = create_golem()
        assert g.name == GOLEM_NAME
        assert g.owner_id == NPC_OWNER_ID
        assert g.is_npc is True
        assert g.max_hp == 100
        assert g.current_hp == 100
        assert g.speed == 0
        assert g.armor_class == 8
        assert len(g.attacks) == 1
        assert g.attacks[0].name == "Stone Fist"

    def test_golem_center(self):
        x, y = golem_center_position()
        assert x == 10
        assert y == 10


# ---------------------------------------------------------------------------
# spawn_npcs
# ---------------------------------------------------------------------------

class TestSpawnNPCs:
    def test_spawns_golem_on_empty_game(self):
        gs = create_game("test")
        assert len(gs.characters) == 0
        spawn_npcs(gs)
        assert len(gs.characters) == 1
        golem = list(gs.characters.values())[0]
        assert golem.name == GOLEM_NAME
        assert golem.is_npc is True
        assert golem.position == golem_center_position()

    def test_idempotent(self):
        gs = create_game("test")
        spawn_npcs(gs)
        spawn_npcs(gs)
        npcs = [c for c in gs.characters.values() if c.is_npc]
        assert len(npcs) == 1

    def test_finds_alternate_position_if_center_occupied(self):
        gs = create_game("test")
        cx, cy = golem_center_position()
        # Place a player at the center
        p = _make_player("p1", "owner1")
        add_character(gs, p, (cx, cy))
        spawn_npcs(gs)
        golem = [c for c in gs.characters.values() if c.is_npc][0]
        assert golem.position != (cx, cy)
        assert golem.position is not None


# ---------------------------------------------------------------------------
# Win condition excludes NPCs
# ---------------------------------------------------------------------------

class TestWinConditionWithNPC:
    def test_npc_not_counted_as_team(self):
        gs = create_game("test")
        spawn_npcs(gs)
        p1 = _make_player("p1", "owner1")
        p2 = _make_player("p2", "owner2")
        add_character(gs, p1, (1, 1))
        add_character(gs, p2, (3, 3))
        # Kill p2 — owner1 should win, GOLEM should not prevent that
        gs.characters["p2"].is_alive = False
        gs.characters["p2"].current_hp = 0
        assert check_win_condition(gs) == "owner1"

    def test_npc_alone_no_winner(self):
        gs = create_game("test")
        spawn_npcs(gs)
        p1 = _make_player("p1", "owner1")
        add_character(gs, p1, (1, 1))
        gs.characters["p1"].is_alive = False
        # Only NPC alive — no winner (draw)
        assert check_win_condition(gs) is None


# ---------------------------------------------------------------------------
# GOLEM AI behaviour
# ---------------------------------------------------------------------------

class TestGolemAI:
    def test_ends_turn_when_not_provoked(self):
        gs = create_game("test")
        golem = create_golem()
        add_character(gs, golem, (10, 10))
        action = resolve_npc_turn(golem, gs)
        assert action.action_type == ActionType.END_TURN

    def test_attacks_adjacent_when_provoked(self):
        gs = create_game("test")
        golem = create_golem()
        add_character(gs, golem, (10, 10))
        p1 = _make_player("p1", "owner1")
        add_character(gs, p1, (10, 11))  # adjacent
        golem.conditions.append("provoked")
        action = resolve_npc_turn(golem, gs)
        assert action.action_type == ActionType.ATTACK
        assert action.target_id == "p1"
        # provoked should be cleared
        assert "provoked" not in golem.conditions

    def test_ends_turn_when_provoked_but_nobody_adjacent(self):
        gs = create_game("test")
        golem = create_golem()
        add_character(gs, golem, (10, 10))
        p1 = _make_player("p1", "owner1")
        add_character(gs, p1, (1, 1))  # far away
        golem.conditions.append("provoked")
        action = resolve_npc_turn(golem, gs)
        assert action.action_type == ActionType.END_TURN
        assert "provoked" not in golem.conditions


# ---------------------------------------------------------------------------
# Provocation via damage
# ---------------------------------------------------------------------------

class TestProvocation:
    def test_damage_provokes_npc(self):
        from engine.rules import apply_damage
        golem = create_golem()
        assert "provoked" not in golem.conditions
        apply_damage(golem, 5)
        assert "provoked" in golem.conditions

    def test_damage_does_not_provoke_player(self):
        from engine.rules import apply_damage
        p = _make_player("p1", "owner1")
        apply_damage(p, 5)
        assert "provoked" not in p.conditions

    def test_killing_blow_does_not_provoke(self):
        from engine.rules import apply_damage
        golem = create_golem()
        apply_damage(golem, 999)
        assert not golem.is_alive
        assert "provoked" not in golem.conditions


# ---------------------------------------------------------------------------
# Combat-start requirement (NPCs don't count toward 2-player minimum)
# ---------------------------------------------------------------------------

class TestCombatStartWithNPC:
    def test_need_two_players_not_just_npc(self):
        gs = create_game("test")
        spawn_npcs(gs)
        p1 = _make_player("p1", "owner1")
        add_character(gs, p1, (1, 1))
        with pytest.raises(ValueError, match="at least 2"):
            start_combat(gs)

    def test_two_players_with_npc_starts_fine(self):
        gs = create_game("test")
        spawn_npcs(gs)
        p1 = _make_player("p1", "owner1")
        p2 = _make_player("p2", "owner2")
        add_character(gs, p1, (1, 1))
        add_character(gs, p2, (3, 3))
        start_combat(gs)
        assert gs.status == GameStatus.ACTIVE
        # GOLEM should be in initiative order
        golem_id = [c.id for c in gs.characters.values() if c.is_npc][0]
        assert golem_id in gs.initiative_order


# ---------------------------------------------------------------------------
# End-of-combat respawn
# ---------------------------------------------------------------------------

class TestEndCombatRespawn:
    def test_golem_respawns_after_death(self):
        gs = create_game("test")
        spawn_npcs(gs)
        p1 = _make_player("p1", "owner1")
        p2 = _make_player("p2", "owner2")
        add_character(gs, p1, (1, 1))
        add_character(gs, p2, (3, 3))
        start_combat(gs)

        # Kill the GOLEM
        golem = [c for c in gs.characters.values() if c.is_npc][0]
        golem.current_hp = 0
        golem.is_alive = False
        gs.status = GameStatus.COMPLETED
        gs.winner_id = "owner1"

        end_combat(gs)

        assert gs.status == GameStatus.WAITING
        npcs = [c for c in gs.characters.values() if c.is_npc]
        assert len(npcs) == 1
        assert npcs[0].is_alive
        assert npcs[0].current_hp == npcs[0].max_hp

    def test_surviving_golem_healed_after_combat(self):
        gs = create_game("test")
        spawn_npcs(gs)
        p1 = _make_player("p1", "owner1")
        p2 = _make_player("p2", "owner2")
        add_character(gs, p1, (1, 1))
        add_character(gs, p2, (3, 3))
        start_combat(gs)

        golem = [c for c in gs.characters.values() if c.is_npc][0]
        golem.current_hp = 50
        golem.conditions.append("provoked")

        gs.characters["p2"].is_alive = False
        gs.characters["p2"].current_hp = 0
        gs.status = GameStatus.COMPLETED
        gs.winner_id = "owner1"

        end_combat(gs)

        golem_after = [c for c in gs.characters.values() if c.is_npc][0]
        assert golem_after.current_hp == golem_after.max_hp
        assert "provoked" not in golem_after.conditions
