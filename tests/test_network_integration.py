"""End-to-end network integration tests for Mastermind socket game.

Verifies:
- TCP connection between server and multiple concurrent clients.
- Admin 'start' command initiates round.
- Unmasked clue sent to guesser and masked '****' clue sent to opponents.
- Concurrent turn-free guessing.
- Round continues until all players finish (win or exhaust 10 guesses).
- Pure inverse scoring calculation and final GAME_OVER broadcast with revealed secret.
"""

import socket
import threading
import time
import unittest

from game_logic import calculate_score, evaluate_guess
from protocol import (
    MessageFramingBuffer,
    TYPE_GAME_OVER,
    TYPE_GAME_START,
    TYPE_GUESS_RESULT,
    TYPE_PLAYER_FINISHED,
    TYPE_WELCOME,
    msg_guess,
    msg_join,
    send_message,
)
from server import MastermindServer

TEST_HOST = "127.0.0.1"
TEST_PORT = 6162  # Dedicated port for test


class TestNetworkIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Start server on a background thread
        cls.server = MastermindServer(host=TEST_HOST, port=TEST_PORT)
        cls.server.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cls.server.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        cls.server.server_sock.bind((TEST_HOST, TEST_PORT))
        cls.server.server_sock.listen(5)
        cls.server.running = True

        cls.accept_thread = threading.Thread(
            target=cls.server._accept_loop, daemon=True, name="TestServerAccept"
        )
        cls.accept_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _create_client_connection(self):
        """Helper to create and return a connected socket, framing buffer, and parsed message queue."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((TEST_HOST, TEST_PORT))
        buf = MessageFramingBuffer()
        queue = []
        return sock, buf, queue

    def _read_next_message_type(self, sock, buf, queue, expected_type, timeout=3.0):
        """Read messages until the expected type is received or timeout."""
        start = time.time()
        while time.time() - start < timeout:
            for i, m in enumerate(queue):
                if m.get("type") == expected_type:
                    return queue.pop(i)

            sock.settimeout(0.5)
            try:
                data = sock.recv(4096)
                if data:
                    new_msgs = buf.feed(data.decode("utf-8"))
                    queue.extend(new_msgs)
            except socket.timeout:
                pass
        return None

    def test_multi_client_flow_and_masking(self):
        """Test full gameplay scenario with 2 players, masking, and inverse scoring."""
        # 1. Connect Client 1 and Client 2
        c1_sock, c1_buf, c1_queue = self._create_client_connection()
        c2_sock, c2_buf, c2_queue = self._create_client_connection()

        # Both receive WELCOME
        w1 = self._read_next_message_type(c1_sock, c1_buf, c1_queue, TYPE_WELCOME)
        w2 = self._read_next_message_type(c2_sock, c2_buf, c2_queue, TYPE_WELCOME)
        self.assertIsNotNone(w1)
        self.assertIsNotNone(w2)

        # 2. Server admin starts game
        self.server.start_game()

        # Both clients receive GAME_START
        s1 = self._read_next_message_type(c1_sock, c1_buf, c1_queue, TYPE_GAME_START)
        s2 = self._read_next_message_type(c2_sock, c2_buf, c2_queue, TYPE_GAME_START)
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)

        # Force known secret for deterministic evaluation test
        test_secret = "7402"
        with self.server.lock:
            self.server.secret = test_secret

        # 3. Client 1 guesses 4201
        send_message(c1_sock, msg_guess("4201"))

        # Client 1 should see: c1: 4201 # s: 1+2-
        r1_for_c1 = self._read_next_message_type(c1_sock, c1_buf, c1_queue, TYPE_GUESS_RESULT)
        self.assertIsNotNone(r1_for_c1)
        self.assertEqual(r1_for_c1["player_id"], "c1")
        self.assertEqual(r1_for_c1["displayed_guess"], "4201")
        self.assertEqual(r1_for_c1["clue"], "1+2-")

        # Client 2 should see masked: c1: **** # s: 1+2-
        r1_for_c2 = self._read_next_message_type(c2_sock, c2_buf, c2_queue, TYPE_GUESS_RESULT)
        self.assertIsNotNone(r1_for_c2)
        self.assertEqual(r1_for_c2["player_id"], "c1")
        self.assertEqual(r1_for_c2["displayed_guess"], "****")
        self.assertEqual(r1_for_c2["clue"], "1+2-")

        # 4. Client 2 guesses 7125
        send_message(c2_sock, msg_guess("7125"))

        # Client 2 sees unmasked: c2: 7125 # s: 1+1-
        r2_for_c2 = self._read_next_message_type(c2_sock, c2_buf, c2_queue, TYPE_GUESS_RESULT)
        self.assertIsNotNone(r2_for_c2)
        self.assertEqual(r2_for_c2["player_id"], "c2")
        self.assertEqual(r2_for_c2["displayed_guess"], "7125")
        self.assertEqual(r2_for_c2["clue"], "1+1-")

        # Client 1 sees masked: c2: **** # s: 1+1-
        r2_for_c1 = self._read_next_message_type(c1_sock, c1_buf, c1_queue, TYPE_GUESS_RESULT)
        self.assertIsNotNone(r2_for_c1)
        self.assertEqual(r2_for_c1["player_id"], "c2")
        self.assertEqual(r2_for_c1["displayed_guess"], "****")
        self.assertEqual(r2_for_c1["clue"], "1+1-")

        # 5. Client 1 guesses the correct secret 7402 (on attempt #2)
        send_message(c1_sock, msg_guess(test_secret))
        win_msg_c1 = self._read_next_message_type(c1_sock, c1_buf, c1_queue, TYPE_PLAYER_FINISHED)
        self.assertIsNotNone(win_msg_c1)
        self.assertTrue(win_msg_c1["is_win"])
        self.assertEqual(win_msg_c1["guesses_used"], 2)
        # Score for guess 2 should be floor(100/2) = 50 pts
        self.assertEqual(win_msg_c1["score"], 50)

        # Client 2 should be informed that c1 finished, but round is still running for c2
        self.assertEqual(self.server.game_state, "RUNNING")

        # 6. Client 2 guesses correct on attempt #2: 7402
        send_message(c2_sock, msg_guess(test_secret))
        win_msg_c2 = self._read_next_message_type(c2_sock, c2_buf, c2_queue, TYPE_PLAYER_FINISHED)
        self.assertIsNotNone(win_msg_c2)
        self.assertTrue(win_msg_c2["is_win"])
        self.assertEqual(win_msg_c2["score"], 50)

        # 7. Now all connected players have finished. Server should broadcast GAME_OVER
        game_over_c1 = self._read_next_message_type(c1_sock, c1_buf, c1_queue, TYPE_GAME_OVER)
        game_over_c2 = self._read_next_message_type(c2_sock, c2_buf, c2_queue, TYPE_GAME_OVER)

        self.assertIsNotNone(game_over_c1)
        self.assertIsNotNone(game_over_c2)
        self.assertEqual(game_over_c1["secret"], "7402")
        self.assertEqual(len(game_over_c1["scoreboard"]), 2)

        # Cleanup test sockets
        c1_sock.close()
        c2_sock.close()

    def test_player_exhausts_guesses(self):
        """Test that a player exhausting 10 guesses receives 0 pts and triggers game over when all players are done."""
        c1_sock, c1_buf, c1_queue = self._create_client_connection()
        self._read_next_message_type(c1_sock, c1_buf, c1_queue, TYPE_WELCOME)

        self.server.start_game()
        self._read_next_message_type(c1_sock, c1_buf, c1_queue, TYPE_GAME_START)

        with self.server.lock:
            self.server.secret = "9876"

        # Make 10 wrong guesses with unique digits
        guesses = [
            "1234", "1235", "1230", "1245", "1240",
            "1250", "1345", "1340", "1350", "1450"
        ]
        for i, g in enumerate(guesses, 1):
            send_message(c1_sock, msg_guess(g))
            res = self._read_next_message_type(c1_sock, c1_buf, c1_queue, TYPE_GUESS_RESULT)
            self.assertIsNotNone(res)
            self.assertEqual(res["guesses_used"], i)

        # Player finished message (loss)
        finish_msg = self._read_next_message_type(c1_sock, c1_buf, c1_queue, TYPE_PLAYER_FINISHED)
        self.assertIsNotNone(finish_msg)
        self.assertFalse(finish_msg["is_win"])
        self.assertEqual(finish_msg["guesses_used"], 10)
        self.assertEqual(finish_msg["score"], 0)

        # Game over broadcast
        game_over = self._read_next_message_type(c1_sock, c1_buf, c1_queue, TYPE_GAME_OVER)
        self.assertIsNotNone(game_over)
        self.assertEqual(game_over["secret"], "9876")
        self.assertEqual(game_over["scoreboard"][0]["score"], 0)
        self.assertFalse(game_over["scoreboard"][0]["won"])

        c1_sock.close()


if __name__ == "__main__":
    unittest.main()
