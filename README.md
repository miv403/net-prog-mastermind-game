# Mastermind Multi-Player Socket Game

A networked multi-player **Mastermind** (Sayı Bulmaca) game written in Python using client-server socket programming over TCP on port `6161`.

---

## 🎯 Game Features & Rules

1. **Non-PRNG Secret Generation**:
   - The server generates a random 4-digit secret number in the range `1000` to `9999` using Python's `secrets` module (backed by the OS cryptographically secure entropy source `/dev/urandom`), avoiding pseudo-random number generators (PRNG).
   - All 4 digits in the secret are strictly unique (no repeating digits, first digit is 1–9).

2. **Competitive Clue Feedback & Masking**:
   - When any player submits a guess, the server evaluates it and broadcasts the clue to all players.
   - **Privacy / Masking**: The guessing player sees their actual digits, while opponents see masked digits (`****`) along with the clue:
     ```text
     # Client 1 Screen:
     c1: 4201 # s: 1+2-
     c2: **** # s: 1+1-

     # Client 2 Screen:
     c1: **** # s: 1+2-
     c2: 7125 # s: 1+1-
     ```
   - Clue notation:
     - `+`: Digit exists in the secret and is in the correct position.
     - `-`: Digit exists in the secret but in the wrong position.
     - Example: Secret `7402`, Guess `4201` $\rightarrow$ `1+2-` ('0' is exact, '4' and '2' are misplaced).

3. **Asynchronous / Real-Time Play**:
   - There are **no turn queues**. Any player can guess at any time as fast as they can think.

4. **Guess Limit & Round Completion**:
   - Each player has a maximum of **10 guesses**.
   - The round continues until **every active player** either finds the secret (`4+0-`) or exhausts all 10 guesses.
   - Once all players finish, the secret is revealed (`s: 7402`) and the final leaderboard is broadcast.

5. **Pure Inverse Scoring Function**:
   - Rewards early wild guesses and maintains fairness against algorithmic solvers:
     $$\text{Score}(g) = \left\lfloor \frac{100}{g} \right\rfloor \quad \text{for } 1 \le g \le 10$$
     $$\text{Score}(g) = 0 \quad \text{for } g > 10 \text{ or failed}$$

   | Guess ($g$) | Score |
   |:---:|:---:|
   | **1** | 100 pts |
   | **2** | 50 pts |
   | **3** | 33 pts |
   | **4** | 25 pts |
   | **5** | 20 pts |
   | **6** | 16 pts |
   | **7** | 14 pts |
   | **8** | 12 pts |
   | **9** | 11 pts |
   | **10** | 10 pts |
   | **Failed / >10** | 0 pts |

---

## 🏗️ Project Architecture

```
mastermind-ödev/
├── game_logic.py      # Core rules: secrets RNG, validation, clue evaluation, pure inverse scoring
├── protocol.py        # Stream framing (NDJSON), message types, serialization/deserialization
├── server.py          # Multithreaded TCP server, game state, admin console, clue broadcaster
├── client.py          # Interactive terminal client, background socket listener, masked feed UI
├── tests/
│   ├── test_logic.py                # Unit tests for scoring, evaluation, and RNG constraints
│   └── test_network_integration.py  # End-to-end integration tests over real TCP sockets
└── README.md          # Project documentation
```

### Protocol & Stream Framing
TCP is a byte stream. To prevent packet fragmentation or sticky packet (concatenation) issues, the game uses **Newline-Delimited JSON (NDJSON)**:
- Each message is a UTF-8 JSON object terminated by `\n`.
- Both server and client use `MessageFramingBuffer` to accumulate chunks and extract complete packets reliably.

---

## 🚀 How to Run

### 1. Requirements
- Python 3.8+ (No external third-party dependencies required; uses Python standard library: `socket`, `threading`, `secrets`, `json`).

### 2. Start the Server
Open a terminal and start the server:
```bash
python3 server.py
```
Options:
- `--host`, `-H`: Bind host address (default: `0.0.0.0`)
- `--port`, `-p`: Port number (default: `6161`)

#### Server Admin Console
The server console allows the administrator to control the game in real time:
- `start` : Generates a new secret and starts the game round.
- `secret`: Reveals the current round's secret to the admin.
- `status`: Shows connected players, their guess counts, and status.
- `reset` : Resets the round back to the lobby.
- `kick <id>`: Disconnects a specific client (e.g. `kick c1`).
- `help`  : Displays available commands.
- `quit`  : Cleanly shuts down the server.

### 3. Start Clients
Open separate terminal windows for each player:
```bash
# Terminal for Player 1
python3 client.py --name Alice

# Terminal for Player 2
python3 client.py --name Bob
```
Options:
- `--host`, `-H`: Server host (default: `127.0.0.1`)
- `--port`, `-p`: Server port (default: `6161`)
- `--name`, `-n`: Optional display name

### 4. Gameplay Flow
1. Players connect and wait in the lobby.
2. The server administrator types `start` in the server terminal.
3. Secret is generated (e.g. `7402`).
4. All players submit 4-digit guesses simultaneously at their own pace.
5. Clues are broadcast in real time with opponent guesses masked.
6. When all players either win or use 10 guesses, the server displays the final scores and rankings.

---

## 🧪 Running the Tests

To run the complete automated test suite (both unit tests and network integration tests):
```bash
python3 -m unittest discover tests
```

To run individual test files:
```bash
# Logic and scoring tests
python3 -m unittest tests/test_logic.py

# End-to-end TCP socket integration tests
python3 -m unittest tests/test_network_integration.py
```
