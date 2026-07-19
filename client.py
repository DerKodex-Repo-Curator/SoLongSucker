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
# Anthropic uses its own SDK/messages API. OpenAI, Grok (xAI) and Gemini all
# speak the OpenAI chat-completions protocol, so the latter two only differ by
# base_url + api key + model name.
ANTHROPIC = 'anthropic'
OPENAI = 'openai'
GROK = 'grok'
GEMINI = 'gemini'

XAI_BASE_URL = "https://api.x.ai/v1"
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Default model per provider; override with the MODEL environment variable.
DEFAULT_MODELS = {
    ANTHROPIC: "claude-haiku-4-5", # claude-sonnet-5
    OPENAI: "gpt-5-mini",
    GROK: "grok-4.5",
    GEMINI: "gemini-3.5-flash",
}

PROVIDERS = {ANTHROPIC, OPENAI, GROK, GEMINI}

MAX_TOKENS = 5000
MAX_RETRIES = 3
MAX_CHAT_REPLIES = 3      # cap off-turn negotiation replies to avoid chat loops
MAX_ACTION_ATTEMPTS = 3   # re-prompts for a valid action on our own turn

apiname = ANTHROPIC
model = DEFAULT_MODELS[ANTHROPIC]
conversation = []         # alternating user/assistant turns for the LLM
_client = None            # lazily-created SDK client for the chosen provider


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
    raise ValueError(f"Unknown provider: {apiname}")


def _call_anthropic():
    response = _client.messages.create(
        model=model, max_tokens=MAX_TOKENS, messages=conversation)
    if not response.content:
        return ""
    return response.content[0].text


def _call_openai():
    response = _client.chat.completions.create(
        model=model, messages=conversation, max_tokens=MAX_TOKENS)
    if not response.choices:
        return ""
    return response.choices[0].message.content or ""


def chat(prompt):
    """Append the prompt, call the LLM with retry/backoff, append and return
    the reply. On persistent failure returns 'pass' so the game can continue."""
    conversation.append({"role": "user", "content": prompt})
    response = None
    for attempt in range(MAX_RETRIES):
        try:
            response = _call_anthropic() if apiname == ANTHROPIC else _call_openai()
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


async def main(participant, initialPrompt):
    global _client
    _client = make_client()
    uri = "ws://localhost:" + str(messages.port)

    players_to_act = []   # who the moderator expects to act now (rescue: several)
    pending = []          # observed messages not yet shown to the LLM
    chat_replies = 0      # off-turn replies since it was last our turn

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
                    if participant in to_act and participant not in players_to_act:
                        chat_replies = 0  # reset budget when our turn comes round
                    players_to_act = to_act

                # Record what we observed so the LLM has full context next call.
                pending.append(f"{sender}: {text}")

                my_turn = (participant in players_to_act)
                from_moderator = (sender == messages.sender_moderator)

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
                        response = chat(prompt)
                        logger.info(response)
                        if response.strip().lower() == 'pass':
                            break
                        chat_part, action_line = split_action(response)
                        if chat_part:
                            await send_chat(websocket, participant, chat_part)
                        if action_line:
                            await send_chat(websocket, participant, action_line)
                            break
                        # No action found - loop and ask again.
                elif not from_moderator and participant.lower() in str(text).lower() \
                        and chat_replies < MAX_CHAT_REPLIES:
                    # A peer addressed us off-turn: negotiate (chat only).
                    chat_replies += 1
                    prompt = "\n".join(pending)
                    pending = []
                    response = chat(prompt)
                    logger.info(response)
                    if response.strip().lower() != 'pass':
                        chat_part, _ = split_action(response)
                        if chat_part:
                            await send_chat(websocket, participant, chat_part)
                # Otherwise just keep the context buffered for our next turn.

        except (ConnectionClosedOK, ConnectionClosedError):
            logger.warning('connection closed')
        except Exception:
            logger.error(traceback.format_exc())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.setLevel(logging.INFO)
    if len(sys.argv) < 3:
        logger.error('usage: client <provider> <participant name>   '
                     '(provider one of: ' + ', '.join(sorted(PROVIDERS)) + ')')
        sys.exit(1)
    apiname = sys.argv[1].lower()
    if apiname not in PROVIDERS:
        logger.error(f'unknown provider {apiname}; choose one of '
                     + ', '.join(sorted(PROVIDERS)))
        sys.exit(1)
    model = os.environ.get("MODEL", DEFAULT_MODELS[apiname])
    try:
        asyncio.run(main(sys.argv[2], None))
    except KeyboardInterrupt:
        logger.error('interrupted')
    logging.shutdown()
