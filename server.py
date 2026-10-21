"""Multi-client Mastermind Game Server.

Features:
- TCP Server listening on port 6161 (configurable).
- Cryptographic non-PRNG secret generation (secrets module).
- Asynchronous, turn-free concurrent guesses from clients.
- Selective clue broadcasting (unmasked for guesser, masked '****' for opponents).
- Inverse scoring function: floor(100 / guesses_used).
- Interactive admin console in terminal (supports 'start', 'status', 'secret', etc.).
- Robust socket stream framing with newline-delimited JSON.
"""

import argparse
import socket
import sys
import threading
import time
from typing import Dict, List, Optional

from game_logic import (
    DIGIT_COUNT,
    MAX_GUESSES,
    calculate_score,
    evaluate_guess,
    generate_secret,
    validate_guess,
)
from protocol import (
    MessageFramingBuffer,
    TYPE_GAME_START,
    TYPE_GUESS,
    TYPE_JOIN,
    encode_message,
    msg_error,
    msg_game_over,
    msg_game_start,
    msg_guess_result,
    msg_info,
    msg_player_finished,
    msg_welcome,
    send_message,
)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 6161


class PlayerSession:
    """Represents a connected player and their game state."""

    def __init__(self, player_id: str, player_name: str, sock: socket.socket, addr):
        self.player_id: str = player_id
        self.player_name: str = player_name
        self.socket: socket.socket = sock
        self.address = addr
        self.guesses_used: int = 0
        self.finished: bool = False
        self.won: bool = False
        self.score: int = 0
        self.guess_history: List[dict] = []  # List of {"guess": str, "clue": str}
        self.connected: bool = True

    def reset_for_round(self):
        """Reset state for a new round."""
        self.guesses_used = 0
        self.finished = False
        self.won = False
        self.score = 0
        self.guess_history = []


class MastermindServer:
    """Game server orchestrating connections, game rounds, broadcasts, and console administration."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self.server_sock: Optional[socket.socket] = None
        self.running: bool = False

        # State lock to guard game state and players dict across threads
        self.lock = threading.Lock()
        self.players: Dict[str, PlayerSession] = {}
        self.player_counter: int = 1

        self.game_state: str = "LOBBY"  # "LOBBY", "RUNNING", "ROUND_OVER"
        self.secret: Optional[str] = None
        self.round_number: int = 0

    def start(self):
        """Start the server socket, listener thread, and interactive admin console."""
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.server_sock.bind((self.host, self.port))
            self.server_sock.listen(10)
            self.running = True
            print(f"[SERVER] Mastermind Server started on {self.host}:{self.port}")
            print("[SERVER] Type 'help' for admin commands. Type 'start' to begin a game.")
        except Exception as e:
            print(f"[ERROR] Failed to bind to {self.host}:{self.port}: {e}")
            sys.exit(1)

        # Accept loop in background thread
        accept_thread = threading.Thread(target=self._accept_loop, daemon=True, name="AcceptLoop")
        accept_thread.start()

        # Run admin console on main thread
        self._admin_console()

    def _accept_loop(self):
        """Accept incoming client socket connections."""
        while self.running:
            try:
                client_sock, addr = self.server_sock.accept()
            except (socket.error, OSError):
                break

            with self.lock:
                player_id = f"c{self.player_counter}"
                self.player_counter += 1
                player_name = player_id
                session = PlayerSession(player_id, player_name, client_sock, addr)
                self.players[player_id] = session

            print(f"[CONNECT] Player {player_id} connected from {addr[0]}:{addr[1]}")

            # Send welcome message
            send_message(
                client_sock,
                msg_welcome(
                    player_id=player_id,
                    player_name=player_name,
                    status=self.game_state,
                    max_guesses=MAX_GUESSES,
                ),
            )

            # Inform others
            self.broadcast(msg_info(f"Player {player_id} joined the lobby. ({len(self.players)} connected)"))

            # Start client communication thread
            client_thread = threading.Thread(
                target=self._client_handler,
                args=(session,),
                daemon=True,
                name=f"Handler-{player_id}",
            )
            client_thread.start()

    def _client_handler(self, player: PlayerSession):
        """Handle incoming stream messages from a specific client."""
        buffer = MessageFramingBuffer()
        sock = player.socket

        try:
            while self.running and player.connected:
                data = sock.recv(4096)
                if not data:
                    break

                text_chunk = data.decode("utf-8", errors="replace")
                messages = buffer.feed(text_chunk)

                for msg in messages:
                    self._handle_client_message(player, msg)

        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self._handle_client_disconnect(player)

    def _handle_client_message(self, player: PlayerSession, msg: dict):
        """Process a framed message from a player."""
        msg_type = msg.get("type")

        if msg_type == TYPE_JOIN:
            custom_name = msg.get("player_name", "").strip()
            if custom_name:
                with self.lock:
                    player.player_name = custom_name
                print(f"[RENAME] Player {player.player_id} set name to '{player.player_name}'")

        elif msg_type == TYPE_GUESS:
            guess_str = str(msg.get("guess", "")).strip()
            self._process_guess(player, guess_str)

    def _process_guess(self, player: PlayerSession, guess_str: str):
        """Validate and evaluate a guess from a player."""
        with self.lock:
            if self.game_state != "RUNNING":
                send_message(
                    player.socket,
                    msg_error("Game is not currently running. Waiting for server admin to start."),
                )
                return

            if player.finished:
                if player.won:
                    send_message(player.socket, msg_error("You have already found the secret!"))
                else:
                    send_message(player.socket, msg_error("You have exhausted all 10 guesses!"))
                return

            # Validate guess rules
            is_valid, err_msg = validate_guess(guess_str)
            if not is_valid:
                send_message(player.socket, msg_error(f"Invalid guess '{guess_str}': {err_msg}"))
                return

            # Guess is valid -> increment count
            player.guesses_used += 1
            guesses_used = player.guesses_used
            remaining = MAX_GUESSES - guesses_used

            # Evaluate against secret
            plus, minus, clue = evaluate_guess(self.secret, guess_str)
            player.guess_history.append({"guess": guess_str, "clue": clue})

            is_correct = plus == DIGIT_COUNT
            score = 0

            if is_correct:
                player.won = True
                player.finished = True
                player.score = calculate_score(guesses_used)
                score = player.score
            elif guesses_used >= MAX_GUESSES:
                player.won = False
                player.finished = True
                player.score = 0
                score = 0

            print(
                f"[GUESS] {player.player_id} ({player.player_name}): {guess_str} -> {clue} "
                f"(Attempt {guesses_used}/{MAX_GUESSES})"
            )

            # Broadcast guess result:
            # Guesser sees actual digits: c1: 4201 # s: 1+2-
            # Opponents see masked digits: c1: **** # s: 1+2-
            for p_id, p_sess in list(self.players.items()):
                if not p_sess.connected:
                    continue
                displayed = guess_str if p_id == player.player_id else "****"
                result_packet = msg_guess_result(
                    player_id=player.player_id,
                    player_name=player.player_name,
                    displayed_guess=displayed,
                    clue=clue,
                    guesses_used=guesses_used,
                    remaining_guesses=remaining,
                    is_correct=is_correct,
                    score=score if is_correct else None,
                )
                send_message(p_sess.socket, result_packet)

            # If player finished (win or max guesses reached)
            if player.finished:
                remaining_active = sum(
                    1 for p in self.players.values() if p.connected and not p.finished
                )
                finish_packet = msg_player_finished(
                    player_id=player.player_id,
                    player_name=player.player_name,
                    is_win=player.won,
                    guesses_used=player.guesses_used,
                    score=player.score,
                    remaining_active=remaining_active,
                )
                self._broadcast_unlocked(finish_packet)

                if player.won:
                    print(f"[WIN] {player.player_id} found secret in {guesses_used} guesses! Score: {score} pts.")
                else:
                    print(f"[EXHAUSTED] {player.player_id} ran out of guesses (10/10). Score: 0 pts.")

                # Check if all connected players are finished
                self._check_round_completion_unlocked()

    def _check_round_completion_unlocked(self):
        """Check if all connected players have finished their attempts. Must be called while holding self.lock."""
        active_connected = [p for p in self.players.values() if p.connected]
        if not active_connected:
            return

        all_done = all(p.finished for p in active_connected)
        if all_done:
            self._end_round_unlocked()

    def _end_round_unlocked(self):
        """Conclude the round, compute scoreboard, and broadcast final results. Must be called with lock held."""
        self.game_state = "ROUND_OVER"
        print(f"\n[ROUND OVER] Round {self.round_number} has concluded! Secret was: {self.secret}")

        # Build scoreboard sorted by score descending, then guesses_used ascending
        connected_players = [p for p in self.players.values() if p.connected]
        connected_players.sort(
            key=lambda p: (-p.score, p.guesses_used if p.won else 999, p.player_id)
        )

        scoreboard = []
        for rank, p in enumerate(connected_players, 1):
            scoreboard.append({
                "rank": rank,
                "player_id": p.player_id,
                "player_name": p.player_name,
                "won": p.won,
                "guesses_used": p.guesses_used,
                "score": p.score,
            })

        print("\n--- FINAL SCOREBOARD ---")
        for entry in scoreboard:
            status = "FOUND" if entry["won"] else "FAILED"
            print(
                f"Rank #{entry['rank']}: {entry['player_id']} ({entry['player_name']}) - "
                f"{status} in {entry['guesses_used']} guesses -> {entry['score']} pts"
            )
        print("------------------------\n")
        print("[SERVER] Type 'start' to begin another round.")

        # Broadcast GAME_OVER with revealed secret and scoreboard
        game_over_msg = msg_game_over(secret=self.secret, scoreboard=scoreboard)
        self._broadcast_unlocked(game_over_msg)

    def _handle_client_disconnect(self, player: PlayerSession):
        """Handle player disconnection cleanly."""
        with self.lock:
            player.connected = False
            try:
                player.socket.close()
            except Exception:
                pass

            print(f"[DISCONNECT] Player {player.player_id} ({player.player_name}) disconnected.")

            # Inform remaining clients
            self._broadcast_unlocked(msg_info(f"Player {player.player_id} disconnected."))

            # If game is running, check if remaining players are all finished
            if self.game_state == "RUNNING":
                self._check_round_completion_unlocked()

    def broadcast(self, message: dict):
        """Thread-safe broadcast message to all connected clients."""
        with self.lock:
            self._broadcast_unlocked(message)

    def _broadcast_unlocked(self, message: dict):
        """Broadcast message to all connected clients without acquiring lock."""
        for p in list(self.players.values()):
            if p.connected:
                send_message(p.socket, message)

    def start_game(self):
        """Command handler to initiate a new game round."""
        with self.lock:
            active_clients = [p for p in self.players.values() if p.connected]
            if not active_clients:
                print("[SERVER] Cannot start: No players connected!")
                return

            if self.game_state == "RUNNING":
                print("[SERVER] A game is already in progress! Type 'stop' or 'reset' first.")
                return

            self.round_number += 1
            # Generate secret using Python's secrets module (non-PRNG OS entropy)
            self.secret = generate_secret()
            self.game_state = "RUNNING"

            # Reset each player for this round
            player_list = []
            for p in active_clients:
                p.reset_for_round()
                player_list.append({"player_id": p.player_id, "player_name": p.player_name})

            print(f"\n==========================================")
            print(f"[GAME] Round #{self.round_number} STARTED!")
            print(f"[GAME] Secret Generated (secrets module): {self.secret}")
            print(f"[GAME] Active Players: {', '.join(p.player_id for p in active_clients)}")
            print(f"==========================================\n")

            # Broadcast GAME_START to all players
            start_msg = msg_game_start(max_guesses=MAX_GUESSES, active_players=player_list)
            self._broadcast_unlocked(start_msg)

    def _admin_console(self):
        """Interactive terminal console for server administration."""
        while self.running:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                cmd = line.strip().lower()
                if not cmd:
                    continue

                if cmd == "start":
                    self.start_game()

                elif cmd == "secret":
                    with self.lock:
                        if self.secret:
                            print(f"[SECRET] Current round secret is: {self.secret}")
                        else:
                            print("[SECRET] No active secret (round not started).")

                elif cmd in ("status", "players"):
                    with self.lock:
                        print(f"[STATUS] State: {self.game_state} | Round: {self.round_number}")
                        print(f"[STATUS] Connected Players ({len(self.players)}):")
                        for p in self.players.values():
                            conn_str = "Connected" if p.connected else "Disconnected"
                            fin_str = "Done" if p.finished else "Guessing"
                            print(
                                f"  - {p.player_id} ({p.player_name}): [{conn_str}] [{fin_str}] "
                                f"Guesses: {p.guesses_used}/{MAX_GUESSES}, Score: {p.score}"
                            )

                elif cmd in ("reset", "stop"):
                    with self.lock:
                        self.game_state = "LOBBY"
                        self.secret = None
                        print("[SERVER] Game reset to LOBBY state.")
                        self._broadcast_unlocked(msg_info("Server admin reset the game to lobby."))

                elif cmd.startswith("kick "):
                    target_id = cmd.split(" ", 1)[1].strip()
                    with self.lock:
                        target = self.players.get(target_id)
                        if target and target.connected:
                            target.connected = False
                            try:
                                target.socket.close()
                            except Exception:
                                pass
                            print(f"[SERVER] Kicked player {target_id}.")
                        else:
                            print(f"[SERVER] Player '{target_id}' not found or already disconnected.")

                elif cmd == "help":
                    print("\n--- Admin Console Commands ---")
                    print("  start         : Start a new game round")
                    print("  secret        : View the current round's secret number")
                    print("  status        : View connected players and game status")
                    print("  reset / stop  : Reset round back to lobby")
                    print("  kick <id>     : Kick a player by ID (e.g. kick c1)")
                    print("  quit / exit   : Shut down the server")
                    print("------------------------------\n")

                elif cmd in ("quit", "exit"):
                    print("[SERVER] Shutting down...")
                    self.shutdown()
                    break

                else:
                    print(f"[SERVER] Unknown command '{cmd}'. Type 'help' for available commands.")

            except (KeyboardInterrupt, EOFError):
                print("\n[SERVER] Interrupted. Shutting down...")
                self.shutdown()
                break

    def shutdown(self):
        """Cleanly close all player sockets and server socket."""
        self.running = False
        with self.lock:
            for p in self.players.values():
                try:
                    p.socket.close()
                except Exception:
                    pass
            self.players.clear()

        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="Mastermind Network Game Server")
    parser.add_argument("--host", "-H", default=DEFAULT_HOST, help=f"Host address (default: {DEFAULT_HOST})")
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT, help=f"Port number (default: {DEFAULT_PORT})")
    args = parser.parse_args()

    server = MastermindServer(host=args.host, port=args.port)
    server.start()


if __name__ == "__main__":
    main()
