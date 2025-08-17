import sys
import asyncio
from websockets import serve
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
import json
import traceback
import logging
import messages
import game

logger = logging.getLogger(__name__)
lock = asyncio.Lock()
nClients = 4
clients = dict()
shutdown_event = asyncio.Event()
max_messages = 10

async def registerClient(participant, websocket):
    async with lock:       
        clients[participant] = websocket
        logger.info('registered participant ' + participant) 

async def broadcast(data):
    logger.debug('broadcast')
    async with lock:
        jsonStr = json.dumps(data, indent=2)
        logger.debug(jsonStr)
        for participant, websocket in clients.items():
            if participant != data.get(messages.sender):
                logger.debug('  '+participant)
                try:
                    await websocket.send(jsonStr)
                except (ConnectionClosedOK, ConnectionClosedError):
                    logger.warning('connection closed: ' + participant)
                    continue
                logger.debug('  sent')

async def handler(websocket):
    messageCount = 0
    try:
        while messageCount < max_messages:
            messageCount += 1
            logger.debug('await recv')
            message = await websocket.recv()
            logger.debug('message received: ' + message)
            data = json.loads(message)
            sender = data.get(messages.sender)            
            msg_type = data.get(messages.type)
            text = data.get(messages.text)
            if msg_type == messages.type_register:
                await registerClient(sender, websocket)
                if len(clients) >= nClients:
                    logger.info(str(len(clients)) + ' clients registered')
                    prompt = game.getInitialPrompt(list(clients.keys()), sender)
                    await broadcast({
                        messages.sender: messages.sender_moderator,
                        messages.type: messages.type_start,
                        messages.text: prompt
                        })
            elif msg_type == messages.type_text:
                logger.info(sender + ': ' + text)
                await broadcast(data)
        logger.info('stopping clients...')
        await broadcast({ messages.sender: messages.sender_moderator, messages.type: messages.type_stop })
    except KeyboardInterrupt:
        logger.warning('interrupted')
    except (ConnectionClosedOK, ConnectionClosedError):
        logger.warning('connection closed')
    except asyncio.exceptions.CancelledError:
        logger.warning('cancelled')
    except:
        logger.error(traceback.format_exc())
    shutdown_event.set()

async def main():
    server = await serve(handler, "localhost", messages.port)
    logger.info('started server at port ' + str(messages.port))
    await shutdown_event.wait()
    server.close()
    await server.wait_closed()

if __name__ == "__main__":
    try:
        logging.basicConfig(level=logging.INFO)
        logger.setLevel(logging.INFO)
        nClients = game.nParticipants
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning('interrupted')
    except:
        logger.error(traceback.format_exc())
    logging.shutdown()


