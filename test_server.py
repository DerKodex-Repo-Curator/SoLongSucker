#!/usr/bin/env python3
"""Integration test for the authoritative server over real WebSockets.

Uses scripted mock clients (no LLM calls) to verify the server wiring:
personalized start briefings, legal moves -> authoritative state broadcasts with
the correct turn, out-of-turn moves -> a directed error to only the offender,
and game end -> a stop broadcast with the winner.
"""

import asyncio
import json
import random

import websockets

import messages
import game
import server

URI = "ws://localhost:" + str(messages.port)
PLAYERS = ["alice", "bob", "charlie", "diana"]

results = []


def check(condition, name, detail=""):
    results.append(condition)
    status = "PASS" if condition else "FAIL"
    print(f"  {status}: {name}" + (f" - {detail}" if detail else ""))
    return condition


async def recv_json(ws, timeout=5):
    raw = await asyncio.wait_for(ws.recv(), timeout)
    return json.loads(raw)


async def drain(ws, timeout=0.4):
    """Collect all currently-queued messages, returning when idle."""
    msgs = []
    try:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout)
            msgs.append(json.loads(raw))
    except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
        pass
    return msgs


async def send(ws, sender, text):
    await ws.send(json.dumps({
        messages.sender: sender,
        messages.type: messages.type_text,
        messages.text: text,
    }))


async def run():
    random.seed(1)
    # Fresh server state bound to this event loop.
    server.lock = asyncio.Lock()
    server.shutdown_event = asyncio.Event()
    server.clients = {}
    server.action_count = 0
    server.game_over = False
    server.nClients = game.nParticipants

    srv = await websockets.serve(server.handler, "localhost", messages.port)
    try:
        conns = {}
        for p in PLAYERS:
            ws = await websockets.connect(URI)
            conns[p] = ws
            await ws.send(json.dumps({
                messages.type: messages.type_register,
                messages.sender: p,
            }))

        # 1. Each player gets a personalized start briefing with the turn set.
        starts = {p: await recv_json(conns[p]) for p in PLAYERS}
        ok_type = all(m[messages.type] == messages.type_start for m in starts.values())
        ok_personal = all(f"You are player {p}" in starts[p][messages.text] for p in PLAYERS)
        start_player = starts[PLAYERS[0]][messages.current_player]
        check(ok_type, "All players receive a start message")
        check(ok_personal, "Start briefings are personalized")
        check(start_player in PLAYERS, "Start message names current player", str(start_player))

        for p in PLAYERS:
            await drain(conns[p])

        others = [p for p in PLAYERS if p != start_player]

        # 2. Start player makes a legal opening play -> state broadcast to everyone.
        await send(conns[start_player], start_player, f"PLAY {start_player}")
        state_msgs = {p: await drain(conns[p]) for p in PLAYERS}
        all_got_state = all(any(m[messages.type] == messages.type_state for m in state_msgs[p])
                            for p in PLAYERS)
        check(all_got_state, "Legal play broadcasts authoritative state to all")
        # New single-chip pile => start player must still choose; turn unchanged.
        last_cp = [m for m in state_msgs[start_player]
                   if m[messages.type] == messages.type_state][-1][messages.current_player]
        check(last_cp == start_player, "Turn stays with start player pending CHOOSE",
              f"current_player={last_cp}")

        # 3. CHOOSE an eligible player -> turn advances to them.
        chosen = others[0]
        await send(conns[start_player], start_player, f"CHOOSE {chosen}")
        msgs = await drain(conns[chosen])
        state = [m for m in msgs if m[messages.type] == messages.type_state]
        check(bool(state) and state[-1][messages.current_player] == chosen,
              "CHOOSE advances the turn to the chosen player",
              str(state[-1][messages.current_player]) if state else "no state")
        for p in PLAYERS:
            await drain(conns[p])

        # 4. Out-of-turn action -> directed error to the offender only.
        offender = others[1]
        await send(conns[offender], offender, f"PLAY {offender}")
        off_msgs = await drain(conns[offender])
        got_error = any(m[messages.type] == messages.type_error for m in off_msgs)
        check(got_error, "Out-of-turn action returns a directed error")
        # Nobody else should have received that error.
        leaked = False
        for p in PLAYERS:
            if p == offender:
                continue
            other_msgs = await drain(conns[p])
            if any(m[messages.type] == messages.type_error for m in other_msgs):
                leaked = True
        check(not leaked, "Directed error is not broadcast to other players")

        # 5. Force a near-win, then a legal move ends the game with a winner.
        game.game_state.active_players = {chosen}
        game.game_state.defeated_players = set(PLAYERS) - {chosen}
        game.game_state.current_player = chosen
        await send(conns[chosen], chosen, f"PLAY {chosen}")
        # Collect from all clients until a stop arrives or we time out.
        stop_seen = None
        for p in PLAYERS:
            for m in await drain(conns[p]):
                if m[messages.type] == messages.type_stop:
                    stop_seen = m
        check(stop_seen is not None and chosen in stop_seen[messages.text],
              "Game end broadcasts a stop message naming the winner",
              stop_seen[messages.text] if stop_seen else "no stop message")

        for ws in conns.values():
            await ws.close()
    finally:
        srv.close()
        await srv.wait_closed()

    passed = sum(1 for r in results if r)
    print("\n" + "=" * 50)
    print(f"SERVER TEST SUMMARY: {passed}/{len(results)} checks passed")
    return passed == len(results)


if __name__ == "__main__":
    ok = asyncio.run(run())
    raise SystemExit(0 if ok else 1)
