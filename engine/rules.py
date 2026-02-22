"""D&D 5e SRD combat rules: action validation, attack resolution, damage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from engine.dice import roll, roll_d20
from engine.grid import distance, is_adjacent, line_of_sight
from models.actions import ActionResult, ActionType

if TYPE_CHECKING:
    from models.characters import Attack, Character
    from models.game_state import GameState


def calculate_ability_modifier(score: int) -> int:
    """Calculate ability modifier from a score using the 5e formula.

    Args:
        score: The ability score (e.g. 16).

    Returns:
        The modifier (e.g. +3 for score 16).
    """
    return (score - 10) // 2


def roll_initiative(character: Character) -> int:
    """Roll initiative for a character: d20 + dexterity modifier.

    Args:
        character: The character rolling initiative.

    Returns:
        The initiative roll total.
    """
    dex_mod = calculate_ability_modifier(character.ability_scores.dexterity)
    return roll_d20() + dex_mod


def validate_action(
    action_type: ActionType,
    character: Character,
    game_state: GameState,
    target_id: str | None = None,
    target_position: tuple[int, int] | None = None,
    weapon_name: str | None = None,
) -> tuple[bool, str]:
    """Check if an action is legal for the given character.

    Args:
        action_type: The type of action being attempted.
        character: The character attempting the action.
        game_state: Current game state.
        target_id: Target character ID (for attacks).
        target_position: Target grid position (for movement).
        weapon_name: Name of the weapon to use (for attacks).

    Returns:
        (valid, error_message) tuple.
    """
    if not character.is_alive:
        return False, "Character is dead"

    if character.position is None:
        return False, "Character has no position"

    if action_type == ActionType.END_TURN:
        return True, ""

    if action_type == ActionType.MOVE:
        if target_position is None:
            return False, "Move action requires a target_position"
        return True, ""

    if action_type == ActionType.ATTACK:
        if target_id is None:
            return False, "Attack action requires a target_id"
        if target_id not in game_state.characters:
            return False, f"Target '{target_id}' not found"
        target = game_state.characters[target_id]
        if not target.is_alive:
            return False, "Target is already dead"
        if target.position is None:
            return False, "Target has no position"

        # Find weapon
        weapon = None
        if weapon_name:
            for atk in character.attacks:
                if atk.name.lower() == weapon_name.lower():
                    weapon = atk
                    break
            if weapon is None:
                return False, f"Weapon '{weapon_name}' not found"
        else:
            if not character.attacks:
                return False, "Character has no attacks"
            weapon = character.attacks[0]

        # Check range
        dist = distance(character.position, target.position)
        if weapon.range_normal is not None:
            if dist > weapon.range_normal:
                return False, f"Target is out of range ({dist}ft, max {weapon.range_normal}ft)"
        else:
            if dist > weapon.reach:
                return False, f"Target is out of reach ({dist}ft, reach {weapon.reach}ft)"

        if not line_of_sight(character.position, target.position, game_state.grid):
            return False, "No line of sight to target"

        return True, ""

    if action_type in (ActionType.DODGE, ActionType.DASH, ActionType.DISENGAGE):
        return True, ""

    return False, f"Unknown action type: {action_type}"


def resolve_attack(
    attacker: Character,
    target: Character,
    weapon: Attack,
    game_state: GameState,
) -> ActionResult:
    """Resolve an attack: roll to hit, roll damage if hit, apply damage.

    Args:
        attacker: The attacking character.
        target: The target character.
        weapon: The weapon being used.
        game_state: Current game state.

    Returns:
        ActionResult with full details.
    """
    # Check if target is dodging (disadvantage on attacks)
    disadvantage = "dodging" in target.conditions

    attack_roll = roll_d20(disadvantage=disadvantage)
    total_attack = attack_roll + weapon.attack_bonus

    hit = total_attack >= target.armor_class

    if hit:
        damage_result = roll(weapon.damage_dice)
        total_damage = max(0, damage_result.total + weapon.damage_bonus)
        apply_damage(target, total_damage)

        description = (
            f"{attacker.name} attacks {target.name} with {weapon.name}! "
            f"Roll: {attack_roll}+{weapon.attack_bonus}={total_attack} vs AC {target.armor_class} — HIT! "
            f"Damage: {damage_result.total}+{weapon.damage_bonus}={total_damage} {weapon.damage_type}. "
            f"{target.name} has {target.current_hp} HP remaining."
        )
        if not target.is_alive:
            description += f" {target.name} has been slain!"

        return ActionResult(
            success=True,
            action_type=ActionType.ATTACK,
            description=description,
            attack_roll=total_attack,
            hit=True,
            damage_dealt=total_damage,
            target_hp_remaining=target.current_hp,
        )
    else:
        description = (
            f"{attacker.name} attacks {target.name} with {weapon.name}! "
            f"Roll: {attack_roll}+{weapon.attack_bonus}={total_attack} vs AC {target.armor_class} — MISS!"
        )
        return ActionResult(
            success=True,
            action_type=ActionType.ATTACK,
            description=description,
            attack_roll=total_attack,
            hit=False,
            damage_dealt=0,
            target_hp_remaining=target.current_hp,
        )


def apply_damage(character: Character, damage: int) -> Character:
    """Apply damage to a character, reducing HP and checking for death.

    If the character is an NPC, marks it as 'provoked' so its AI
    knows to retaliate on its next turn.

    Args:
        character: The character taking damage.
        damage: Amount of damage to deal.

    Returns:
        The updated character.
    """
    character.current_hp = max(0, character.current_hp - damage)
    if check_death(character):
        character.is_alive = False
    elif character.is_npc and "provoked" not in character.conditions:
        character.conditions.append("provoked")
    return character


def check_death(character: Character) -> bool:
    """Check if a character is dead (at 0 HP).

    Args:
        character: The character to check.

    Returns:
        True if the character is at 0 HP.
    """
    return character.current_hp <= 0
