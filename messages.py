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