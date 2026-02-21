"""Tests for dice rolling utilities."""

import random

import pytest

from engine.dice import DiceResult, roll, roll_d20


class TestRoll:
    """Tests for the roll() function."""

    def test_basic_roll(self):
        """Roll 1d6 with a seeded RNG produces expected result."""
        rng = random.Random(42)
        result = roll("1d6", rng=rng)
        assert isinstance(result, DiceResult)
        assert len(result.rolls) == 1
        assert 1 <= result.rolls[0] <= 6
        assert result.modifier == 0
        assert result.total == result.rolls[0]

    def test_multiple_dice(self):
        """Roll 3d6 produces 3 individual rolls."""
        rng = random.Random(42)
        result = roll("3d6", rng=rng)
        assert len(result.rolls) == 3
        assert all(1 <= r <= 6 for r in result.rolls)
        assert result.total == sum(result.rolls)

    def test_positive_modifier(self):
        """Roll 1d8+3 adds modifier correctly."""
        rng = random.Random(42)
        result = roll("1d8+3", rng=rng)
        assert result.modifier == 3
        assert result.total == result.rolls[0] + 3

    def test_negative_modifier(self):
        """Roll 1d8-2 subtracts modifier correctly."""
        rng = random.Random(42)
        result = roll("1d8-2", rng=rng)
        assert result.modifier == -2
        assert result.total == result.rolls[0] - 2

    def test_d20(self):
        """Roll 1d20 produces value in range 1-20."""
        rng = random.Random(42)
        result = roll("1d20", rng=rng)
        assert 1 <= result.total <= 20

    def test_notation_stored(self):
        """Notation string is preserved in result."""
        result = roll("2d6+3")
        assert result.notation == "2d6+3"

    def test_invalid_notation(self):
        """Invalid notation raises ValueError."""
        with pytest.raises(ValueError):
            roll("bad")
        with pytest.raises(ValueError):
            roll("d6")
        with pytest.raises(ValueError):
            roll("2d")

    def test_seeded_determinism(self):
        """Same seed produces same results."""
        result1 = roll("4d6", rng=random.Random(123))
        result2 = roll("4d6", rng=random.Random(123))
        assert result1.rolls == result2.rolls
        assert result1.total == result2.total


class TestRollD20:
    """Tests for the roll_d20() function."""

    def test_straight_roll(self):
        """Straight d20 roll is in range."""
        rng = random.Random(42)
        result = roll_d20(rng=rng)
        assert 1 <= result <= 20

    def test_advantage_takes_higher(self):
        """Advantage takes the higher of two rolls."""
        rng = random.Random(42)
        # Pre-calculate what the two rolls would be
        check_rng = random.Random(42)
        r1 = check_rng.randint(1, 20)
        r2 = check_rng.randint(1, 20)
        expected = max(r1, r2)

        result = roll_d20(advantage=True, rng=rng)
        assert result == expected

    def test_disadvantage_takes_lower(self):
        """Disadvantage takes the lower of two rolls."""
        rng = random.Random(42)
        check_rng = random.Random(42)
        r1 = check_rng.randint(1, 20)
        r2 = check_rng.randint(1, 20)
        expected = min(r1, r2)

        result = roll_d20(disadvantage=True, rng=rng)
        assert result == expected

    def test_advantage_and_disadvantage_cancel(self):
        """Advantage + disadvantage = straight roll."""
        rng = random.Random(42)
        check_rng = random.Random(42)
        expected = check_rng.randint(1, 20)

        result = roll_d20(advantage=True, disadvantage=True, rng=rng)
        assert result == expected
