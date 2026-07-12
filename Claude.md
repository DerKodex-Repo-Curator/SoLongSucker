We are developing the game 'So long sucker' together.
The game rules are in the rules.md file.
Four ai chatbots will play the game as clients while communicating via the game server.
The implementations of clients and server are in client.py and server.py, respectively. They communicate asnchronously via websockets.
The server also serves as a game engine, which accepts a number of game actions with a strict prescribed syntax.
