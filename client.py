import asyncio
from websockets import connect
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
import json
import sys
import traceback
import logging
import messages
import random
import time
from anthropic import Anthropic
from openai import OpenAI

logger = logging.getLogger(__name__)
ANTHROPIC = 'anthropic'
OPENAI = 'openai'
apiname = ANTHROPIC
conversation = []
clientAnthropic = Anthropic()
clientOpenAI = OpenAI()

def chatAnthropic():     
    response = clientAnthropic.messages.create(
        model="claude-3-5-sonnet-20241022",  # or claude-3-opus-20240229 or claude-3-haiku-20240307
        max_tokens=5000,
        messages=conversation
    )
    return response.content[0].text

def chatOpenAI():
    response = clientOpenAI.chat.completions.create(
        model = "gpt-4o",
        messages = conversation,
        max_tokens=5000
        #, temperature=0.9
    )  
    return response.choices[0].message.content

def chat(prompt):
    time.sleep(1)
    conversation.append({"role": "user", "content": prompt})
    response = ''
    if apiname == ANTHROPIC:
        response = chatAnthropic()
    else:
        response = chatOpenAI()
    conversation.append({"role": "assistant", "content": response})
    return response

async def main(participant, initialPrompt):
    uri = "ws://localhost:" + str(messages.port)
    async with connect(uri) as websocket:
        try:
            await websocket.send(json.dumps({
                messages.type: messages.type_register,
                messages.sender: participant
            }))
            while True:
                logger.debug('await recv')
                message = await websocket.recv()
                logger.debug('message received ' + message)
                data = json.loads(message)
                sender = data.get(messages.sender)
                message_type = data.get(messages.type)
                text = data.get(messages.text)
                if sender == participant:
                    continue
                if sender == messages.sender_moderator and message_type == messages.type_stop:
                    break
                prompt = sender + ': ' + text
                if sender == messages.sender_moderator and message_type == messages.type_start:
                    prompt += ' Responses of other participants and the moderator will be prefixed by their respective name followed by a colon."'
                    prompt += ' You can always pass on giving a direct answer by merely giving the response "pass" (without the quotes).'
                response = chat(prompt)
                logger.info(response)
                if response != 'pass':
                    await websocket.send(json.dumps({
                        messages.sender: participant,
                        messages.type: messages.type_text,
                        messages.text: response
                    }))
        except (ConnectionClosedOK, ConnectionClosedError):
            logger.warning('connection closed')
        except:
            logger.error(traceback.format_exc())

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.setLevel(logging.INFO)
    if len(sys.argv) < 4:
        logger.error('usage: client <chatbot api> <participant name> <initial prompt>')
        sys.exit()
    try:
        apiname = sys.argv[1]
        asyncio.run(main(sys.argv[2], sys.argv[3]))
    except KeyboardInterrupt:
        logger.error('interrupted')
    logging.shutdown()
