"""Interactive Mastermind Game Client.

Features:
- Connects to TCP server on port 6161.
- Background receiver thread for real-time clue broadcasts without blocking input.
- Displays the competitive feed:
    s: **** (or s: <revealed> at round over)
    c1: 4201 # s: 1+2-
    c2: **** # s: 1+1-
- Client-side pre-validation for friendly instant feedback.
- Pure inverse scoring display and game-over leaderboard.
- Clean terminal input handling.
"""

import argparse
import readline  # Enhances terminal input editing
import socket
import sys
import threading
import time
from typing import Optional

from game_logic import MAX_GUESSES, validate_guess
from protocol import (
    MessageFramingBuffer,
    TYPE_ERROR,
    TYPE_GAME_OVER,
    TYPE_GAME_START,
    TYPE_GUESS,
    TYPE_GUESS_RESULT,
    TYPE_INFO,
    TYPE_JOIN,
    TYPE_PLAYER_FINISHED,
    TYPE_WELCOME,
    msg_guess,
    msg_join,
    send_message,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6161


class MastermindClient:
    """Client handling socket communications and interactive terminal interface."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, name: Optional[str] = None):
        self.host = host
        self.port = port
        self.preferred_name = name
        self.sock: Optional[socket.socket] = None
        self.running = False

        self.player_id: str = "c?"
        self.player_name: str = "Player"
        self.game_state: str = "WAITING"
        self.guesses_used: int = 0
        self.remaining_guesses: int = MAX_GUESSES
        self.is_finished: bool = False
        self.current_secret_display: str = "****"

        self.prompt_text = "Enter 4-digit guess: "
        self.print_lock = threading.Lock()

    def print_clean(self, text: str):
        """Print text to stdout while preserving user terminal input line."""
        with self.print_lock:
            # Clear line, print text, and restore newline
            sys.stdout.write(f"\r\033[K{text}\n")
            sys.stdout.flush()

    def connect(self):
        """Connect to the game server and start background listener."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((self.host, self.port))
            self.running = True
        except Exception as e:
            print(f"[ERROR] Could not connect to server at {self.host}:{self.port} -> {e}")
            sys.exit(1)

        # Start receiver thread
        recv_thread = threading.Thread(target=self._receive_loop, daemon=True, name="ClientRecv")
        recv_thread.start()

        # Send preferred name if provided
        if self.preferred_name:
            send_message(self.sock, msg_join(self.preferred_name))

        # Run user input loop on main thread
        self._input_loop()

    def _receive_loop(self):
        """Background thread receiving messages from the server."""
        buffer = MessageFramingBuffer()
        try:
            while self.running:
                data = self.sock.recv(4096)
                if not data:
                    self.print_clean("[DISCONNECT] Server closed the connection.")
                    self.running = False
                    break

                text_chunk = data.decode("utf-8", errors="replace")
                messages = buffer.feed(text_chunk)

                for msg in messages:
                    self._handle_server_message(msg)

        except (ConnectionResetError, BrokenPipeError, socket.error):
            if self.running:
                self.print_clean("[ERROR] Connection to server lost.")
            self.running = False

    def _handle_server_message(self, msg: dict):
        """Handle an incoming parsed message from the server."""
        msg_type = msg.get("type")

        if msg_type == TYPE_WELCOME:
            self.player_id = msg.get("player_id", "c?")
            self.player_name = msg.get("player_name", self.player_id)
            status = msg.get("status", "WAITING")
            self.game_state = status
            self.print_clean("=" * 55)
            self.print_clean(f" Connected to Mastermind Server as [{self.player_id}] ({self.player_name})")
            self.print_clean(f" Current Server State: {status}")
            self.print_clean(f" Guess Limit: {msg.get('max_guesses', 10)} guesses | Scoring: Inverse floor(100/g)")
            self.print_clean("=" * 55)
            if status != "RUNNING":
                self.print_clean("-> Waiting for server administrator to type 'start'...\n")

        elif msg_type == TYPE_INFO:
            info_text = msg.get("message", "")
            self.print_clean(f"[INFO] {info_text}")

        elif msg_type == TYPE_GAME_START:
            self.game_state = "RUNNING"
            self.guesses_used = 0
            self.remaining_guesses = msg.get("max_guesses", MAX_GUESSES)
            self.is_finished = False
            self.current_secret_display = "****"

            self.print_clean("\n" + "=" * 55)
            self.print_clean(" >>> GAME STARTED! SECRET GENERATED (1000-9999) <<<")
            self.print_clean(" All players can guess simultaneously! No turns.")
            self.print_clean(f" s: {self.current_secret_display}")
            self.print_clean("=" * 55 + "\n")

        elif msg_type == TYPE_GUESS_RESULT:
            # Format: c1: 4201 # s: 1+2-  or  c2: **** # s: 1+1-
            p_id = msg.get("player_id", "")
            displayed_guess = msg.get("displayed_guess", "****")
            clue = msg.get("clue", "")
            is_self = (p_id == self.player_id)

            if is_self:
                self.guesses_used = msg.get("guesses_used", self.guesses_used)
                self.remaining_guesses = msg.get("remaining_guesses", self.remaining_guesses)

            # Display feed entry exactly matching the specified format
            line = f"{p_id}: {displayed_guess} # s: {clue}"
            if is_self:
                line += f"  (Your Attempt {self.guesses_used}/{MAX_GUESSES})"
            self.print_clean(line)

        elif msg_type == TYPE_PLAYER_FINISHED:
            p_id = msg.get("player_id", "")
            p_name = msg.get("player_name", p_id)
            is_win = msg.get("is_win", False)
            guesses = msg.get("guesses_used", 0)
            score = msg.get("score", 0)
            remaining_active = msg.get("remaining_active", 0)
            is_self = (p_id == self.player_id)

            if is_self:
                self.is_finished = True
                if is_win:
                    self.print_clean(f"\n[CONGRATULATIONS!] You found the secret number in {guesses} guesses!")
                    self.print_clean(f"Points earned: {score} pts. Waiting for other players to finish...\n")
                else:
                    self.print_clean(f"\n[ROUND OVER FOR YOU] You used all {guesses} attempts. Score: 0 pts.")
                    self.print_clean("Waiting for other players to finish...\n")
            else:
                status_str = f"found the secret in {guesses} guesses ({score} pts)" if is_win else "exhausted all guesses"
                self.print_clean(f"[FEED] {p_id} ({p_name}) {status_str}! ({remaining_active} players still playing)")

        elif msg_type == TYPE_GAME_OVER:
            self.game_state = "ROUND_OVER"
            secret = msg.get("secret", "????")
            self.current_secret_display = secret
            scoreboard = msg.get("scoreboard", [])

            self.print_clean("\n" + "=" * 55)
            self.print_clean(f" ROUND FINISHED!  s: {secret}")
            self.print_clean("=" * 55)
            self.print_clean(f"{'RANK':<6}{'PLAYER':<12}{'STATUS':<10}{'GUESSES':<10}{'SCORE'}")
            self.print_clean("-" * 55)
            for entry in scoreboard:
                rank = f"#{entry['rank']}"
                p_display = f"{entry['player_id']}"
                if entry["player_name"] != entry["player_id"]:
                    p_display += f" ({entry['player_name']})"
                status = "WON" if entry["won"] else "FAILED"
                guesses = f"{entry['guesses_used']}/{MAX_GUESSES}"
                score = f"{entry['score']} pts"
                self.print_clean(f"{rank:<6}{p_display:<12}{status:<10}{guesses:<10}{score}")
            self.print_clean("=" * 55)
            self.print_clean("Waiting for server admin to start a new round or type 'quit' to exit.\n")

        elif msg_type == TYPE_ERROR:
            err = msg.get("error", "An error occurred.")
            self.print_clean(f"[ERROR FROM SERVER] {err}")

    def _input_loop(self):
        """Main thread loop for reading player input and sending guesses."""
        while self.running:
            try:
                raw_input = input()
            except (KeyboardInterrupt, EOFError):
                self.print_clean("\n[CLIENT] Exiting game...")
                self.running = False
                break

            cmd = raw_input.strip()
            if not cmd:
                continue

            if cmd.lower() in ("quit", "exit"):
                self.print_clean("[CLIENT] Leaving game...")
                self.running = False
                break

            # If game is not running
            if self.game_state != "RUNNING":
                self.print_clean("[NOTE] Game has not started yet. Waiting for server admin to type 'start'.")
                continue

            # If client is already finished in this round
            if self.is_finished:
                self.print_clean("[NOTE] You have already completed this round. Please wait for others to finish.")
                continue

            # Validate locally for instant user feedback
            is_valid, err_msg = validate_guess(cmd)
            if not is_valid:
                self.print_clean(f"[INVALID INPUT] {err_msg} (e.g., 4201)")
                continue

            # Send guess to server
            success = send_message(self.sock, msg_guess(cmd))
            if not success:
                self.print_clean("[ERROR] Failed to send guess to server.")
                break

        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="Mastermind Network Game Client")
    parser.add_argument("--host", "-H", default=DEFAULT_HOST, help=f"Server host IP (default: {DEFAULT_HOST})")
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT, help=f"Server port (default: {DEFAULT_PORT})")
    parser.add_argument("--name", "-n", default=None, help="Player display name (optional)")
    args = parser.parse_args()

    client = MastermindClient(host=args.host, port=args.port, name=args.name)
    client.connect()


if __name__ == "__main__":
    main()
