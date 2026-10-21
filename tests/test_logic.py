"""Unit tests for game_logic.py."""

import unittest
from game_logic import (
    generate_secret,
    validate_guess,
    evaluate_guess,
    calculate_score,
    MAX_GUESSES,
)


class TestGameLogic(unittest.TestCase):
    def test_generate_secret_constraints(self):
        """Test that generate_secret creates valid 4-digit numbers with unique digits."""
        for _ in range(500):
            secret = generate_secret()
            self.assertEqual(len(secret), 4)
            self.assertTrue(secret.isdigit())
            # Range 1000 - 9999 means first digit is not '0'
            self.assertNotEqual(secret[0], "0")
            # All digits must be unique
            self.assertEqual(len(set(secret)), 4)
            val = int(secret)
            self.assertTrue(1000 <= val <= 9999)

    def test_validate_guess(self):
        """Test input validation for guesses."""
        # Valid guesses
        self.assertTrue(validate_guess("1234")[0])
        self.assertTrue(validate_guess("7402")[0])
        self.assertTrue(validate_guess("9876")[0])

        # Invalid: wrong length
        self.assertFalse(validate_guess("123")[0])
        self.assertFalse(validate_guess("12345")[0])
        self.assertFalse(validate_guess("")[0])

        # Invalid: non-numeric
        self.assertFalse(validate_guess("12a4")[0])
        self.assertFalse(validate_guess("abcd")[0])

        # Invalid: leading zero (< 1000)
        self.assertFalse(validate_guess("0123")[0])

        # Invalid: duplicate digits
        self.assertFalse(validate_guess("1123")[0])
        self.assertFalse(validate_guess("1223")[0])
        self.assertFalse(validate_guess("1233")[0])
        self.assertFalse(validate_guess("4444")[0])

    def test_evaluate_guess_examples(self):
        """Test clue calculation with user's examples and edge cases."""
        # User example 1: secret=7402, guess=4201 -> 1+2-
        # 0 is exact (+1), 4 and 2 in secret but wrong pos (2-), 1 not in secret
        plus, minus, clue = evaluate_guess("7402", "4201")
        self.assertEqual(plus, 1)
        self.assertEqual(minus, 2)
        self.assertEqual(clue, "1+2-")

        # User example 2: secret=7402, guess=7125 -> 1+1-
        # 7 is exact (+1), 2 is in secret wrong pos (1-), 1 and 5 not in secret
        plus, minus, clue = evaluate_guess("7402", "7125")
        self.assertEqual(plus, 1)
        self.assertEqual(minus, 1)
        self.assertEqual(clue, "1+1-")

        # Exact win: secret=7402, guess=7402 -> 4+0-
        plus, minus, clue = evaluate_guess("7402", "7402")
        self.assertEqual(plus, 4)
        self.assertEqual(minus, 0)
        self.assertEqual(clue, "4+0-")

        # Complete miss: secret=7402, guess=1356 -> 0+0-
        plus, minus, clue = evaluate_guess("7402", "1356")
        self.assertEqual(plus, 0)
        self.assertEqual(minus, 0)
        self.assertEqual(clue, "0+0-")

        # All correct digits, all wrong places: secret=7402, guess=2047 -> 0+4-
        plus, minus, clue = evaluate_guess("7402", "2047")
        self.assertEqual(plus, 0)
        self.assertEqual(minus, 4)
        self.assertEqual(clue, "0+4-")

    def test_calculate_score(self):
        """Test pure inverse scoring table."""
        expected = {
            1: 100,
            2: 50,
            3: 33,
            4: 25,
            5: 20,
            6: 16,
            7: 14,
            8: 12,
            9: 11,
            10: 10,
        }
        for g, pts in expected.items():
            self.assertEqual(calculate_score(g), pts, f"Failed for guess {g}")

        # Out of bounds / failed
        self.assertEqual(calculate_score(0), 0)
        self.assertEqual(calculate_score(11), 0)
        self.assertEqual(calculate_score(99), 0)
        self.assertEqual(calculate_score(-1), 0)


if __name__ == "__main__":
    unittest.main()
