"""Communication protocol and socket message framing for Mastermind game.

Uses newline-delimited JSON messages (NDJSON) over TCP stream sockets.
This prevents TCP packet fragmentation / coalescing issues.
"""

import json
import socket
from typing import Any, Dict, List, Optional, Tuple

DELIMITER = "\n"

# Message action/type constants
TYPE_JOIN = "JOIN"
TYPE_WELCOME = "WELCOME"
TYPE_INFO = "INFO"
TYPE_GAME_START = "GAME_START"
TYPE_GUESS = "GUESS"
TYPE_GUESS_RESULT = "GUESS_RESULT"
TYPE_PLAYER_FINISHED = "PLAYER_FINISHED"
TYPE_GAME_OVER = "GAME_OVER"
TYPE_ERROR = "ERROR"
TYPE_SERVER_SHUTDOWN = "SERVER_SHUTDOWN"


def encode_message(data: Dict[str, Any]) -> bytes:
    """Encode a dictionary to a newline-delimited UTF-8 JSON payload."""
    payload = json.dumps(data, ensure_ascii=False) + DELIMITER
    return payload.encode("utf-8")


def send_message(sock: socket.socket, data: Dict[str, Any]) -> bool:
    """Send a structured dictionary message over a socket.
    
    Returns:
        bool: True if sent successfully, False on socket error.
    """
    try:
        raw_bytes = encode_message(data)
        sock.sendall(raw_bytes)
        return True
    except (socket.error, BrokenPipeError, ConnectionResetError):
        return False


class MessageFramingBuffer:
    """Helper class to accumulate chunks from socket.recv() and extract complete JSON messages."""
    
    def __init__(self):
        self._buffer = ""

    def feed(self, chunk: str) -> List[Dict[str, Any]]:
        """Add new decoded string chunk and return any complete messages parsed."""
        self._buffer += chunk
        messages = []
        
        while DELIMITER in self._buffer:
            line, self._buffer = self._buffer.split(DELIMITER, 1)
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    messages.append(parsed)
            except json.JSONDecodeError:
                # Discard corrupted line and continue
                continue
                
        return messages


# Message factory helpers for clear consistency across server & client
def msg_join(player_name: str) -> Dict[str, Any]:
    return {"type": TYPE_JOIN, "player_name": player_name}


def msg_welcome(player_id: str, player_name: str, status: str, max_guesses: int) -> Dict[str, Any]:
    return {
        "type": TYPE_WELCOME,
        "player_id": player_id,
        "player_name": player_name,
        "status": status,
        "max_guesses": max_guesses,
    }


def msg_info(message: str) -> Dict[str, Any]:
    return {"type": TYPE_INFO, "message": message}


def msg_game_start(max_guesses: int, active_players: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "type": TYPE_GAME_START,
        "max_guesses": max_guesses,
        "active_players": active_players,
        "message": "Game has started! Secret number has been generated. You can guess at any time!",
    }


def msg_guess(guess: str) -> Dict[str, Any]:
    return {"type": TYPE_GUESS, "guess": guess}


def msg_guess_result(
    player_id: str,
    player_name: str,
    displayed_guess: str,
    clue: str,
    guesses_used: int,
    remaining_guesses: int,
    is_correct: bool,
    score: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "type": TYPE_GUESS_RESULT,
        "player_id": player_id,
        "player_name": player_name,
        "displayed_guess": displayed_guess,
        "clue": clue,
        "guesses_used": guesses_used,
        "remaining_guesses": remaining_guesses,
        "is_correct": is_correct,
        "score": score,
    }


def msg_player_finished(
    player_id: str,
    player_name: str,
    is_win: bool,
    guesses_used: int,
    score: int,
    remaining_active: int,
) -> Dict[str, Any]:
    return {
        "type": TYPE_PLAYER_FINISHED,
        "player_id": player_id,
        "player_name": player_name,
        "is_win": is_win,
        "guesses_used": guesses_used,
        "score": score,
        "remaining_active": remaining_active,
    }


def msg_game_over(secret: str, scoreboard: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "type": TYPE_GAME_OVER,
        "secret": secret,
        "scoreboard": scoreboard,
    }


def msg_error(error_message: str) -> Dict[str, Any]:
    return {"type": TYPE_ERROR, "error": error_message}
