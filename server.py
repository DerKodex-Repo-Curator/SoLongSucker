import os
import sys
import asyncio
import webbrowser
from http import HTTPStatus
from pathlib import Path
from websockets import serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
from websockets.http11 import Response
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

# Web viewer: browsers connect on /observe as passive observers and receive a
# structured event stream (game state snapshots + chat). The history buffer
# lets a viewer that connects (or reloads) mid-game catch up.
VIEWER_PATH = Path(__file__).with_name('viewer.html')
observers = set()
observer_history = []

# Safety cap so a wedged game (e.g. bots that never make a legal move) cannot
# run forever. The game normally ends when a single player remains.
max_actions = 1000
action_count = 0
game_over = False

# Pause gate: while cleared, incoming player messages (actions and chat) block
# in their connection handlers and are processed in order on resume. Toggled by
# the space bar in the server terminal or a control message from the viewer.
running = asyncio.Event()
running.set()


async def toggle_pause():
    if running.is_set():
        running.clear()
        logger.info('game PAUSED - press space (or use the viewer button) to resume')
    else:
        running.set()
        logger.info('game RESUMED')
    payload = json.dumps({'event': 'pause', 'paused': not running.is_set()})
    for websocket in list(observers):
        try:
            await websocket.send(payload)
        except (ConnectionClosedOK, ConnectionClosedError):
            observers.discard(websocket)


def setup_keyboard(loop):
    """Toggle pause with the space bar when running in a terminal.
    Returns the saved termios attributes to restore on shutdown, or None."""
    if not sys.stdin.isatty():
        return None
    import termios
    import tty
    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    def on_key():
        ch = os.read(fd, 1)
        if ch == b' ':
            asyncio.ensure_future(toggle_pause())

    loop.add_reader(fd, on_key)
    return old_attrs


def restore_keyboard(old_attrs):
    if old_attrs is None:
        return
    import termios
    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_attrs)


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


event_seq = 0


async def notify_observers(event):
    """Record a viewer event and push it to all connected browser viewers.
    Chat and action events get a global sequence number so the order in
    which the server processed them can be retraced in the viewer."""
    global event_seq
    if event.get('event') in ('chat', 'action'):
        event_seq += 1
        event['seq'] = event_seq
    observer_history.append(event)
    payload = json.dumps(event)
    for websocket in list(observers):
        try:
            await websocket.send(payload)
        except (ConnectionClosedOK, ConnectionClosedError):
            observers.discard(websocket)


async def handle_observer(websocket):
    """Serve a browser viewer: replay history, then stream new events.
    Viewers may send {'type': 'toggle_pause'} to pause/resume the game."""
    for event in observer_history:
        await websocket.send(json.dumps(event))
    await websocket.send(json.dumps({'event': 'pause',
                                     'paused': not running.is_set()}))
    observers.add(websocket)
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except ValueError:
                continue
            if data.get('type') == 'toggle_pause':
                await toggle_pause()
    except (ConnectionClosedOK, ConnectionClosedError):
        pass
    finally:
        observers.discard(websocket)


def process_request(connection, request):
    """Serve the viewer page over plain HTTP on the websocket port."""
    if request.headers.get('Upgrade', '').lower() == 'websocket':
        return None  # normal websocket handshake (players and /observe)
    if request.path in ('/', '/index.html'):
        try:
            body = VIEWER_PATH.read_bytes()
        except OSError:
            return connection.respond(HTTPStatus.INTERNAL_SERVER_ERROR,
                                      'viewer.html not found\n')
        return Response(200, 'OK', Headers([
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Content-Length', str(len(body))),
        ]), body)
    return connection.respond(HTTPStatus.NOT_FOUND, 'Not found\n')


async def start_game():
    """Initialize the engine and send each player their personalized briefing."""
    players = list(clients.keys())
    logger.info('starting game with players: ' + ', '.join(players))
    game.initialize_game(players)
    start_player = game.game_state.current_player
    await notify_observers({
        'event': 'start',
        'players': players,
        'state': game.get_state_snapshot(),
    })
    for participant in players:
        prompt = game.getInitialPrompt(players, participant, start_player)
        await send_to(participant, {
            messages.sender: messages.sender_moderator,
            messages.type: messages.type_start,
            messages.current_player: start_player,
            messages.to_act: game.get_players_to_act(),
            messages.text: prompt,
        })


async def announce_state(result_message):
    """Broadcast the authoritative state and whose turn it is to everyone."""
    current = game.game_state.current_player
    text = (result_message + "\n\n" + game.get_game_state_description()
            + "\n" + game.get_turn_phase_description())
    await broadcast({
        messages.sender: messages.sender_moderator,
        messages.type: messages.type_state,
        messages.current_player: current,
        messages.to_act: game.get_players_to_act(),
        messages.text: text,
    }, exclude_sender=False)
    await notify_observers({
        'event': 'state',
        'message': result_message,
        'state': game.get_state_snapshot(),
    })


async def end_game(winner_message):
    """Announce the winner and stop all clients."""
    global game_over
    game_over = True
    await broadcast({
        messages.sender: messages.sender_moderator,
        messages.type: messages.type_stop,
        messages.text: winner_message,
    }, exclude_sender=False)
    await notify_observers({
        'event': 'stop',
        'message': winner_message,
        'state': game.get_state_snapshot(),
    })
    shutdown_event.set()


async def handle_action(sender, text):
    """Run a game action through the engine and broadcast the outcome."""
    global action_count

    # STATUS is a private query: answer only the requester, don't disturb play.
    if text.strip().split()[0].upper() == 'STATUS':
        logger.info(f'{sender} requested STATUS')
        success, message = game.parse_and_execute_action(sender, text)
        await send_to(sender, {
            messages.sender: messages.sender_moderator,
            messages.type: messages.type_state,
            messages.current_player: game.game_state.current_player,
            messages.to_act: game.get_players_to_act(),
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
            messages.to_act: game.get_players_to_act(),
            messages.text: f"Your action '{text.strip()}' was rejected: {message}",
        })
        await notify_observers({
            'event': 'action',
            'sender': sender,
            'text': text.strip(),
            'accepted': False,
            'message': message,
        })
        return

    logger.info(f'{sender} action accepted: {message}')
    await notify_observers({
        'event': 'action',
        'sender': sender,
        'text': text.strip(),
        'accepted': True,
        'message': message,
    })
    await announce_state(message)

    game_ended, end_msg, winner = game.check_game_end()
    if game_ended:
        await end_game(end_msg)


async def handler(websocket):
    if websocket.request is not None and websocket.request.path.startswith('/observe'):
        await handle_observer(websocket)
        return
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
                # Pause gate: hold this message until the game is resumed.
                await running.wait()
                if game_over:
                    continue
                if action_count >= max_actions:
                    logger.warning('max actions reached - stopping')
                    await end_game('Game stopped: maximum number of actions reached.')
                    break
                logger.info(sender + ': ' + str(text))
                # Serialize engine access; free chat is just rebroadcast.
                # extract_action tolerates markdown-decorated commands and
                # commands buried after chat lines.
                action_line = messages.extract_action(text)
                if action_line:
                    async with lock:
                        await handle_action(sender, action_line)
                else:
                    await broadcast(data)
                    await notify_observers({
                        'event': 'chat',
                        'sender': sender,
                        'text': text,
                    })
    except (ConnectionClosedOK, ConnectionClosedError):
        logger.warning('connection closed')
    except asyncio.exceptions.CancelledError:
        logger.warning('cancelled')
    except Exception:
        logger.error(traceback.format_exc())


async def main():
    server = await serve(handler, "localhost", messages.port,
                         process_request=process_request)
    url = f'http://localhost:{messages.port}/'
    logger.info('started server at port ' + str(messages.port))
    logger.info('game viewer at ' + url)
    old_attrs = setup_keyboard(asyncio.get_running_loop())
    if old_attrs is not None:
        logger.info('press SPACE to pause/resume the game')
    webbrowser.open(url)
    try:
        await shutdown_event.wait()
    finally:
        restore_keyboard(old_attrs)
    server.close()
    await server.wait_closed()


if __name__ == "__main__":
    try:
        game_dir = messages.start_new_game_log_dir()
        logging.basicConfig(level=logging.INFO, handlers=[
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(game_dir, 'server.log')),
        ])
        logger.setLevel(logging.INFO)
        logger.info('logging this game to ' + game_dir)
        nClients = game.nParticipants
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning('interrupted')
    except Exception:
        logger.error(traceback.format_exc())
    logging.shutdown()
