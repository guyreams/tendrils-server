"""Dice rolling utilities for Tendrils Server."""

import random
import re

from pydantic import BaseModel


class DiceResult(BaseModel):
    """Result of a dice roll."""
    total: int
    rolls: list[int]
    modifier: int
    notation: str


def roll(notation: str, rng: random.Random | None = None) -> DiceResult:
    """Parse and roll dice notation like '2d6+3', '1d20', '4d6-1'.

    Args:
        notation: Dice notation string (e.g. "2d6+3").
        rng: Optional Random instance for seeded/testing rolls.

    Returns:
        DiceResult with total, individual rolls, modifier, and notation.
    """
    rng = rng or random.Random()
    notation = notation.strip().lower()

    match = re.match(r"^(\d+)d(\d+)([+-]\d+)?$", notation)
    if not match:
        raise ValueError(f"Invalid dice notation: {notation}")

    num_dice = int(match.group(1))
    die_size = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0

    rolls = [rng.randint(1, die_size) for _ in range(num_dice)]
    total = sum(rolls) + modifier

    return DiceResult(
        total=total,
        rolls=rolls,
        modifier=modifier,
        notation=notation,
    )


def roll_d20(
    advantage: bool = False,
    disadvantage: bool = False,
    rng: random.Random | None = None,
) -> int:
    """Roll a d20, optionally with advantage or disadvantage.

    Args:
        advantage: Roll twice, take the higher.
        disadvantage: Roll twice, take the lower.
        rng: Optional Random instance for seeded/testing rolls.

    Returns:
        The resulting d20 roll.
    """
    rng = rng or random.Random()

    if advantage and disadvantage:
        # They cancel out — straight roll
        return rng.randint(1, 20)

    if advantage:
        return max(rng.randint(1, 20), rng.randint(1, 20))

    if disadvantage:
        return min(rng.randint(1, 20), rng.randint(1, 20))

    return rng.randint(1, 20)
