import os
import re

port = 8765
sender = 'sender'
text = 'text'
type = 'type'
current_player = 'current_player'  # whose turn it is (in moderator messages)
to_act = 'to_act'  # list of players expected to act now (rescue phase: several)
sender_moderator = 'moderator'
type_register = 'register'
type_text = 'type_text'
type_start = 'start'
type_stop = 'stop'
type_state = 'state'    # authoritative state broadcast after a legal action
type_error = 'error'    # directed reply to a player whose action was rejected

# Action commands the engine understands (used to tell a move from free chat).
COMMANDS = {'PLAY', 'CHOOSE', 'KILL', 'TRANSFER', 'RESCUE', 'REFUSE_RESCUE', 'STATUS'}

# Per the rules (see game.py's initial prompt), only these are legal when it
# is not the sender's turn - everything else requires the moderator to have
# named the sender in to_act. STATUS is also harmless off-turn: it's a private
# query, never mutates state.
OFF_TURN_COMMANDS = {'KILL', 'TRANSFER', 'STATUS'}

# LLMs like to decorate commands with markdown (**PLAY jack ON 1**, `STATUS`,
# quoted "> CHOOSE jim"). Strip that decoration before matching.
_MARKDOWN_CHARS = re.compile(r'[*_`]')

def extract_action(text):
    """Return the first line of text that is a game command, with any markdown
    decoration stripped, or None if the text contains no command line."""
    if not text:
        return None
    for line in str(text).splitlines():
        line = _MARKDOWN_CHARS.sub('', line)
        line = line.strip().lstrip('> ').strip()
        if line and line.split()[0].upper() in COMMANDS:
            return line
    return None

def is_action(text):
    """True if a message looks like a game action rather than free chat."""
    return extract_action(text) is not None


# --- Per-game log directories ------------------------------------------------
# Each game gets its own logs/gameN folder (N = how many game folders already
# exist, so pre-existing plain logs/gameN.log files from before this scheme
# don't count). The server creates the folder and records it as "current";
# clients (separate processes) just look it up.
LOGS_DIR = 'logs'
_CURRENT_GAME_POINTER = os.path.join(LOGS_DIR, '.current_game')
_GAME_DIR_RE = re.compile(r'^game(\d+)$')


def _existing_game_dirs():
    if not os.path.isdir(LOGS_DIR):
        return []
    result = []
    for name in os.listdir(LOGS_DIR):
        m = _GAME_DIR_RE.match(name)
        if m and os.path.isdir(os.path.join(LOGS_DIR, name)):
            result.append((int(m.group(1)), name))
    return result


def start_new_game_log_dir():
    """Create logs/gameN for the next N and record it as the current game.
    Server-only; call once per server process, before logging starts."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    n = max((num for num, _ in _existing_game_dirs()), default=0) + 1
    game_dir = os.path.join(LOGS_DIR, f'game{n}')
    os.makedirs(game_dir, exist_ok=True)
    with open(_CURRENT_GAME_POINTER, 'w') as f:
        f.write(game_dir)
    return game_dir


def current_game_log_dir():
    """Return the log directory the server most recently created. Clients
    call this to log alongside the server. Falls back to the highest
    existing logs/gameN folder if the pointer is missing or stale."""
    try:
        with open(_CURRENT_GAME_POINTER) as f:
            path = f.read().strip()
        if path and os.path.isdir(path):
            return path
    except OSError:
        pass
    os.makedirs(LOGS_DIR, exist_ok=True)
    existing = _existing_game_dirs()
    if not existing:
        return LOGS_DIR
    return os.path.join(LOGS_DIR, max(existing)[1])
