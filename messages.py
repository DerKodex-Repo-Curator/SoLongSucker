port = 8765
sender = 'sender'
text = 'text'
type = 'type'
current_player = 'current_player'  # whose turn it is (in moderator messages)
sender_moderator = 'moderator'
type_register = 'register'
type_text = 'type_text'
type_start = 'start'
type_stop = 'stop'
type_state = 'state'    # authoritative state broadcast after a legal action
type_error = 'error'    # directed reply to a player whose action was rejected

# Action commands the engine understands (used to tell a move from free chat).
COMMANDS = {'PLAY', 'CHOOSE', 'KILL', 'TRANSFER', 'RESCUE', 'REFUSE_RESCUE', 'STATUS'}

def is_action(text):
    """True if a message looks like a game action rather than free chat."""
    if not text:
        return False
    return text.strip().split()[0].upper() in COMMANDS