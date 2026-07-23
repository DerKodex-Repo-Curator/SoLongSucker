import asyncio
from websockets import connect
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
import json
import os
import sys
import traceback
import logging
import messages
import time

logger = logging.getLogger(__name__)

# --- Provider configuration -------------------------------------------------
# Anthropic uses its own SDK/messages API. Every other provider here speaks
# the OpenAI chat-completions protocol (including all four Chinese providers
# via their OpenAI-compatible endpoints), so they only differ by base_url +
# api key + model name.
ANTHROPIC = 'anthropic'
OPENAI = 'openai'
GROK = 'grok'
GEMINI = 'gemini'
KIMI = 'kimi'
DEEPSEEK = 'deepseek'
QWEN = 'qwen'
GLM = 'glm'

XAI_BASE_URL = "https://api.x.ai/v1"
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
KIMI_BASE_URL = "https://api.moonshot.ai/v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
GLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"

# Default model per provider; override with the MODEL environment variable.
DEFAULT_MODELS = {
    ANTHROPIC: "claude-sonnet-5", # cheaper: claude-haiku-4-5
    OPENAI: "gpt-5-mini",
    GROK: "grok-4.5",
    GEMINI: "gemini-3.5-flash",
    KIMI: "kimi-k2.5",
    DEEPSEEK: "deepseek-v4-flash",
    QWEN: "qwen-plus",
    GLM: "glm-4.6",
}

PROVIDERS = {ANTHROPIC, OPENAI, GROK, GEMINI, KIMI, DEEPSEEK, QWEN, GLM}

MAX_TOKENS = 16000  # includes adaptive-thinking tokens, not only the visible reply
MAX_RETRIES = 3
# Cap off-turn replies between two game actions so agents chatting with each
# other cannot loop forever. Every accepted action resets the budget, so a
# player can intervene vocally at any point of the game.
MAX_CHAT_REPLIES = 3
MAX_ACTION_ATTEMPTS = 3   # re-prompts for a valid action on our own turn

HINTS_FILE = 'strategy-hints.md'

apiname = ANTHROPIC
model = DEFAULT_MODELS[ANTHROPIC]
conversation = []         # alternating user/assistant turns for the LLM
_client = None            # lazily-created SDK client for the chosen provider
_cached_message_index = None  # index of the conversation message currently
                               # carrying the cache_control breakpoint


def make_client():
    """Create the SDK client for the selected provider (lazy, so unused
    providers' missing API keys never matter)."""
    if apiname == ANTHROPIC:
        from anthropic import Anthropic
        return Anthropic()
    from openai import OpenAI
    if apiname == OPENAI:
        return OpenAI()
    if apiname == GROK:
        return OpenAI(base_url=XAI_BASE_URL, api_key=os.environ.get("XAI_API_KEY"))
    if apiname == GEMINI:
        return OpenAI(base_url=GEMINI_OPENAI_BASE_URL,
                      api_key=os.environ.get("GEMINI_API_KEY"))
    if apiname == KIMI:
        return OpenAI(base_url=KIMI_BASE_URL, api_key=os.environ.get("MOONSHOT_API_KEY"))
    if apiname == DEEPSEEK:
        return OpenAI(base_url=DEEPSEEK_BASE_URL, api_key=os.environ.get("DEEPSEEK_API_KEY"))
    if apiname == QWEN:
        return OpenAI(base_url=QWEN_BASE_URL, api_key=os.environ.get("DASHSCOPE_API_KEY"))
    if apiname == GLM:
        return OpenAI(base_url=GLM_BASE_URL, api_key=os.environ.get("ZHIPU_API_KEY"))
    raise ValueError(f"Unknown provider: {apiname}")


def _call_anthropic():
    response = _client.messages.create(
        model=model, max_tokens=MAX_TOKENS, messages=conversation,
        output_config={"effort": "medium"})
    # Sonnet 5 runs adaptive thinking by default, so content may contain
    # thinking blocks before the text block - extract only text.
    return "".join(block.text for block in response.content
                   if block.type == "text")


def _call_openai_compatible():
    """Shared chat-completions call for every provider that speaks the
    OpenAI protocol (OpenAI itself, Grok, Gemini, and the four Chinese
    providers) - they differ only in the client's base_url/api_key set up
    in make_client()."""
    response = _client.chat.completions.create(
        model=model, messages=conversation, max_tokens=MAX_TOKENS)
    if not response.choices:
        return ""
    return response.choices[0].message.content or ""


# One named entry point per provider, as called out in CALL_FUNCTIONS below -
# all currently identical since every non-Anthropic provider here is
# OpenAI-protocol compatible.
_call_openai = _call_openai_compatible
_call_grok = _call_openai_compatible
_call_gemini = _call_openai_compatible
_call_kimi = _call_openai_compatible
_call_deepseek = _call_openai_compatible
_call_qwen = _call_openai_compatible
_call_glm = _call_openai_compatible

CALL_FUNCTIONS = {
    ANTHROPIC: _call_anthropic,
    OPENAI: _call_openai,
    GROK: _call_grok,
    GEMINI: _call_gemini,
    KIMI: _call_kimi,
    DEEPSEEK: _call_deepseek,
    QWEN: _call_qwen,
    GLM: _call_glm,
}

def _mark_cache_breakpoint():
    """Move the prompt-cache breakpoint onto the latest user message. Only
    Anthropic uses cache_control; only one breakpoint needs to be live since
    the conversation only ever grows - the cached prefix covers everything
    before it, so re-tagging older messages would just burn breakpoints
    (max 4 per request) for no benefit."""
    global _cached_message_index
    if apiname != ANTHROPIC:
        return
    if _cached_message_index is not None:
        old = conversation[_cached_message_index]
        if isinstance(old["content"], list):
            old["content"][-1].pop("cache_control", None)
    new_index = len(conversation) - 1
    conversation[new_index]["content"] = [{
        "type": "text",
        "text": conversation[new_index]["content"],
        "cache_control": {"type": "ephemeral"},
    }]
    _cached_message_index = new_index


def chat(prompt):
    """Append the prompt, call the LLM with retry/backoff, append and return
    the reply. On persistent failure returns 'pass' so the game can continue."""
    conversation.append({"role": "user", "content": prompt})
    _mark_cache_breakpoint()
    response = None
    for attempt in range(MAX_RETRIES):
        try:
            response = CALL_FUNCTIONS[apiname]()
            if response and response.strip():
                break
            logger.warning('empty LLM response, retrying')
        except Exception:
            logger.warning(f'LLM call failed (attempt {attempt + 1}):\n'
                           + traceback.format_exc())
        time.sleep(2 ** attempt)
    if not response or not response.strip():
        response = 'pass'
    conversation.append({"role": "assistant", "content": response})
    return response


def split_action(response):
    """Split an LLM reply into (chat_part, action_line). action_line is the
    first line that is a known command (markdown decoration stripped), or
    None if there is none."""
    chat_lines = []
    action_line = None
    for line in response.splitlines():
        candidate = messages.extract_action(line) if action_line is None else None
        if candidate:
            action_line = candidate
        else:
            chat_lines.append(line)
    chat_part = "\n".join(chat_lines).strip()
    return chat_part, action_line


async def send_chat(websocket, participant, text):
    await websocket.send(json.dumps({
        messages.sender: participant,
        messages.type: messages.type_text,
        messages.text: text,
    }))


async def main(participant, initialPrompt, hints=None):
    global _client
    _client = make_client()
    uri = "ws://localhost:" + str(messages.port)

    players_to_act = []   # who the moderator expects to act now (rescue: several)
    pending = []          # observed messages not yet shown to the LLM
    chat_replies = 0      # off-turn replies since the last game action

    last_action_line = None   # normalized text of the previous action attempt
    action_repeat_count = 0   # consecutive repeats of last_action_line

    def note_action_line(line):
        """Log a warning when the LLM proposes the same action line two or
        more times in a row, whether or not it actually reached the server -
        a sign it isn't updating its picture of the game state."""
        nonlocal last_action_line, action_repeat_count
        normalized = line.strip().upper()
        if normalized == last_action_line:
            action_repeat_count += 1
            logger.warning(f'{participant} repeated the same action attempt '
                           f'{action_repeat_count + 1}x in a row: "{line}"')
        else:
            last_action_line = normalized
            action_repeat_count = 0

    async with connect(uri) as websocket:
        try:
            await websocket.send(json.dumps({
                messages.type: messages.type_register,
                messages.sender: participant,
            }))

            while True:
                message = await websocket.recv()
                data = json.loads(message)
                sender = data.get(messages.sender)
                message_type = data.get(messages.type)
                text = data.get(messages.text)
                cp = data.get(messages.current_player)
                to_act = data.get(messages.to_act)

                if sender == participant:
                    continue
                if message_type == messages.type_stop:
                    logger.info('game over: ' + str(text))
                    break

                # Moderator messages say who must act now. Fall back to the
                # current player for messages without an explicit to_act list.
                if to_act is None and cp is not None:
                    to_act = [cp]
                if to_act is not None:
                    players_to_act = to_act

                from_moderator = (sender == messages.sender_moderator)

                # A start/state broadcast marks a new game action: reset the
                # off-turn chat budget so everyone may speak up again.
                if from_moderator and message_type in (messages.type_start,
                                                       messages.type_state):
                    chat_replies = 0

                # The private game briefing; optionally add strategy hints.
                if message_type == messages.type_start and hints:
                    text = str(text) + "\n\nStrategy hints:\n" + hints

                # Record what we observed so the LLM has full context next call.
                pending.append(f"{sender}: {text}")

                my_turn = (participant in players_to_act)

                if my_turn and from_moderator:
                    # The moderator (start/state/error message) says it's our
                    # move. Acting only on moderator messages means peer chat
                    # during our turn just buffers instead of squeezing extra
                    # actions out of the LLM.
                    # Re-prompt until we get a usable action (or give up).
                    for attempt in range(MAX_ACTION_ATTEMPTS):
                        prompt = "\n".join(pending)
                        pending = []
                        if attempt > 0:
                            prompt += ("\n(Moderator: you must act now. Reply with exactly "
                                       "one valid action command as a plain unformatted line.)")
                        # Run the blocking LLM call in a thread: a long thinking
                        # pass must not block the event loop, or websocket
                        # keepalive pings go unanswered and the connection drops.
                        response = await asyncio.to_thread(chat, prompt)
                        logger.info(response)
                        lines = [l.strip().lower() for l in response.strip().splitlines() if l.strip()]
                        if lines and all(l == 'pass' for l in lines):
                            break
                        chat_part, action_line = split_action(response)
                        if chat_part:
                            await send_chat(websocket, participant, chat_part)
                        if action_line:
                            note_action_line(action_line)
                            await send_chat(websocket, participant, action_line)
                            break
                        # No action found - loop and ask again.
                elif chat_replies < MAX_CHAT_REPLIES:
                    # Off-turn: every observed message (moderator state or peer
                    # chat) is an opportunity to intervene - negotiate, warn,
                    # persuade the current player. The LLM replies 'pass' to
                    # stay silent. Actions are forwarded too, but only the ones
                    # rule 4 actually allows off-turn (messages.OFF_TURN_COMMANDS)
                    # - the server remains the sole judge of legality otherwise;
                    # this just avoids wasting a round-trip on requests the LLM
                    # already knows are out of turn.
                    prompt = "\n".join(pending)
                    pending = []
                    response = await asyncio.to_thread(chat, prompt)
                    logger.info(response)
                    if response.strip().lower() != 'pass':
                        chat_replies += 1
                        chat_part, action_line = split_action(response)
                        if chat_part:
                            await send_chat(websocket, participant, chat_part)
                        if action_line:
                            note_action_line(action_line)
                            command = action_line.split()[0].upper()
                            if command in messages.OFF_TURN_COMMANDS:
                                await send_chat(websocket, participant, action_line)
                            else:
                                # Not our turn: only KILL/TRANSFER/STATUS are
                                # legal here (see rules). Don't spend a wasted
                                # round-trip on the server rejecting it - tell
                                # the LLM locally so it stays in its history.
                                note = (f"(local notice: '{action_line}' was not sent - "
                                        f"it is not your turn, only KILL/TRANSFER/STATUS "
                                        f"are allowed off-turn)")
                                pending.append(note)
                # Budget exhausted: keep the context buffered for our next call.

        except (ConnectionClosedOK, ConnectionClosedError):
            logger.warning('connection closed')
        except Exception:
            logger.error(traceback.format_exc())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.setLevel(logging.INFO)
    args = [a for a in sys.argv[1:] if a != '--hints']
    with_hints = '--hints' in sys.argv[1:]
    if len(args) < 2:
        logger.error('usage: client <provider> <participant name> [--hints]   '
                     '(provider one of: ' + ', '.join(sorted(PROVIDERS)) + ')')
        sys.exit(1)
    apiname = args[0].lower()
    if apiname not in PROVIDERS:
        logger.error(f'unknown provider {apiname}; choose one of '
                     + ', '.join(sorted(PROVIDERS)))
        sys.exit(1)
    participant = args[1]
    game_dir = messages.current_game_log_dir()
    file_handler = logging.FileHandler(os.path.join(game_dir, f'{participant}.log'))
    file_handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
    logging.getLogger().addHandler(file_handler)
    logger.info('logging this game to ' + game_dir)
    model = os.environ.get("MODEL", DEFAULT_MODELS[apiname])
    hints = None
    if with_hints:
        with open(HINTS_FILE, 'r') as f:
            hints = f.read()
        logger.info('strategy hints enabled')
    try:
        asyncio.run(main(participant, None, hints))
    except KeyboardInterrupt:
        logger.error('interrupted')
    logging.shutdown()
