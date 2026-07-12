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

# Safety cap so a wedged game (e.g. bots that never make a legal move) cannot
# run forever. The game normally ends when a single player remains.
max_actions = 1000
action_count = 0
game_over = False


async def registerClient(participant, websocket):
    async with lock:
        clients[participant] = websocket
        logger.info('registered participant ' + participant)


async def send_to(participant, data):
    """Send a message to a single participant (if still connected)."""
    websocket = clients.get(participant)
    if websocket is None:
        return
    try:
        await websocket.send(json.dumps(data, indent=2))
    except (ConnectionClosedOK, ConnectionClosedError):
        logger.warning('connection closed: ' + participant)


async def broadcast(data, exclude_sender=True):
    logger.debug('broadcast')
    jsonStr = json.dumps(data, indent=2)
    logger.debug(jsonStr)
    sender = data.get(messages.sender)
    for participant, websocket in list(clients.items()):
        if exclude_sender and participant == sender:
            continue
        try:
            await websocket.send(jsonStr)
        except (ConnectionClosedOK, ConnectionClosedError):
            logger.warning('connection closed: ' + participant)
            continue


async def start_game():
    """Initialize the engine and send each player their personalized briefing."""
    players = list(clients.keys())
    logger.info('starting game with players: ' + ', '.join(players))
    game.initialize_game(players)
    start_player = game.game_state.current_player
    for participant in players:
        prompt = game.getInitialPrompt(players, participant, start_player)
        await send_to(participant, {
            messages.sender: messages.sender_moderator,
            messages.type: messages.type_start,
            messages.current_player: start_player,
            messages.text: prompt,
        })


async def announce_state(result_message):
    """Broadcast the authoritative state and whose turn it is to everyone."""
    current = game.game_state.current_player
    text = (result_message + "\n\n" + game.get_game_state_description()
            + f"\nIt is now {current}'s turn.")
    await broadcast({
        messages.sender: messages.sender_moderator,
        messages.type: messages.type_state,
        messages.current_player: current,
        messages.text: text,
    }, exclude_sender=False)


async def end_game(winner_message):
    """Announce the winner and stop all clients."""
    global game_over
    game_over = True
    await broadcast({
        messages.sender: messages.sender_moderator,
        messages.type: messages.type_stop,
        messages.text: winner_message,
    }, exclude_sender=False)
    shutdown_event.set()


async def handle_action(sender, text):
    """Run a game action through the engine and broadcast the outcome."""
    global action_count

    # STATUS is a private query: answer only the requester, don't disturb play.
    if text.strip().split()[0].upper() == 'STATUS':
        success, message = game.parse_and_execute_action(sender, text)
        await send_to(sender, {
            messages.sender: messages.sender_moderator,
            messages.type: messages.type_state,
            messages.current_player: game.game_state.current_player,
            messages.text: message,
        })
        return

    action_count += 1
    success, message = game.parse_and_execute_action(sender, text)

    if not success:
        # Illegal/unparseable move: tell only the offending player so they can retry.
        logger.info(f'rejected action from {sender}: {message}')
        await send_to(sender, {
            messages.sender: messages.sender_moderator,
            messages.type: messages.type_error,
            messages.current_player: game.game_state.current_player,
            messages.text: f"Your action '{text.strip()}' was rejected: {message}",
        })
        return

    logger.info(f'{sender} action accepted: {message}')
    await announce_state(message)

    game_ended, end_msg, winner = game.check_game_end()
    if game_ended:
        await end_game(end_msg)


async def handler(websocket):
    try:
        while not shutdown_event.is_set():
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
                    async with lock:
                        await start_game()

            elif msg_type == messages.type_text:
                if game_over:
                    continue
                if action_count >= max_actions:
                    logger.warning('max actions reached - stopping')
                    await end_game('Game stopped: maximum number of actions reached.')
                    break
                logger.info(sender + ': ' + str(text))
                # Serialize engine access; free chat is just rebroadcast.
                if messages.is_action(text):
                    async with lock:
                        await handle_action(sender, text)
                else:
                    await broadcast(data)
    except (ConnectionClosedOK, ConnectionClosedError):
        logger.warning('connection closed')
    except asyncio.exceptions.CancelledError:
        logger.warning('cancelled')
    except Exception:
        logger.error(traceback.format_exc())


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
    except Exception:
        logger.error(traceback.format_exc())
    logging.shutdown()
