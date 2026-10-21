"""Game logic module for Mastermind network game.

Implements:
- Non-PRNG secret generation using Python's `secrets` module (cryptographic hardware entropy).
- Guess validation (4 unique digits, range 1000-9999).
- Clue evaluation (exact position '+' and wrong position '-').
- Pure inverse scoring function: score = floor(100 / guesses_used).
"""

import secrets
from typing import Tuple

MAX_GUESSES = 10
DIGIT_COUNT = 4


def generate_secret() -> str:
    """Generate a random 4-digit secret number with unique digits between 1000 and 9999.
    
    Uses Python's `secrets` module (CSPRNG backed by OS entropy pool /dev/urandom),
    avoiding pseudo-random number generators (PRNG) like `random.random()`.
    
    Returns:
        str: A 4-digit string with distinct digits where the first digit is 1-9.
    """
    sys_rand = secrets.SystemRandom()
    
    # First digit must be 1-9 (range 1000-9999, no leading zero)
    digits = [str(sys_rand.choice(range(1, 10)))]
    
    # Remaining 3 digits chosen from 0-9 without repetition
    available = [str(d) for d in range(10) if str(d) != digits[0]]
    for _ in range(DIGIT_COUNT - 1):
        chosen = sys_rand.choice(available)
        digits.append(chosen)
        available.remove(chosen)
        
    return "".join(digits)


def validate_guess(guess: str) -> Tuple[bool, str]:
    """Validate a player's guess according to game rules.
    
    Rules:
    - Must be a string of length 4.
    - Must consist only of numerical digits.
    - First digit cannot be '0' (range 1000-9999).
    - All 4 digits must be distinct (unique).
    
    Args:
        guess: The guess string from the client.
        
    Returns:
        Tuple[bool, str]: (is_valid, error_message_if_invalid)
    """
    if not isinstance(guess, str):
        return False, "Guess must be a string."
    
    guess = guess.strip()
    
    if len(guess) != DIGIT_COUNT:
        return False, f"Guess must be exactly {DIGIT_COUNT} digits."
    
    if not guess.isdigit():
        return False, "Guess must contain only numerical digits."
    
    if guess[0] == "0":
        return False, "First digit cannot be 0 (range 1000 to 9999)."
    
    if len(set(guess)) != DIGIT_COUNT:
        return False, "All digits must be unique (no duplicate digits)."
    
    return True, ""


def evaluate_guess(secret: str, guess: str) -> Tuple[int, int, str]:
    """Evaluate a guess against the secret number.
    
    Args:
        secret: 4-digit secret string with unique digits.
        guess: 4-digit guess string with unique digits.
        
    Returns:
        Tuple[int, int, str]:
            - plus_count: Number of digits in the correct position.
            - minus_count: Number of digits present in secret but in wrong position.
            - clue_str: Formatted clue string (e.g. '1+2-').
    """
    plus_count = 0
    minus_count = 0
    
    for i in range(DIGIT_COUNT):
        if guess[i] == secret[i]:
            plus_count += 1
        elif guess[i] in secret:
            minus_count += 1
            
    clue_str = f"{plus_count}+{minus_count}-"
    return plus_count, minus_count, clue_str


def calculate_score(guesses_used: int, max_guesses: int = MAX_GUESSES) -> int:
    """Calculate the player's score using the pure inverse function.
    
    Formula:
        Score(g) = floor(100 / g) for 1 <= g <= max_guesses
        Score(g) = 0 for g > max_guesses or failed.
        
    Points breakdown:
        Guess 1:  100 pts
        Guess 2:   50 pts
        Guess 3:   33 pts
        Guess 4:   25 pts
        Guess 5:   20 pts
        Guess 6:   16 pts
        Guess 7:   14 pts
        Guess 8:   12 pts
        Guess 9:   11 pts
        Guess 10:  10 pts
        Failed:     0 pts
        
    Args:
        guesses_used: Number of guesses taken to find the secret.
        max_guesses: Maximum allowed guesses (default 10).
        
    Returns:
        int: Earned points.
    """
    if guesses_used < 1 or guesses_used > max_guesses:
        return 0
    
    return 100 // guesses_used
