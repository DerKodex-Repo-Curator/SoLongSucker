# So Long Sucker for LLMs

This repository contains a framework that allows four LLMs to play the social game 'So long Sucker' together.

The game was invented by the famous John Nash and his colleagues, who were game theory researchers.

The game was mentioned in the interesting biography [The Man from the Future: The Visionary Ideas of John von Neumann](https://www.penguin.co.uk/books/313705/the-man-from-the-future-by-bhattacharya-ananyo/9780241398869) written by Ananyo Bhattacharya.
Including the anecdote that the befriended researchers had serious animosities against each other after playing a round on a social evening.

This is, because the game implicitly requires to form coalitions, to cooperate, but only temporarily until the coalition partner necessarily has to be deceived to win the game.

This makes it a perfect benchmark for the capabilities of today's LLMs w.r.t their understanding of social interactions, and whether they have or can build a theory of mind, i.e. the cognitive ability to attribute mental states to other people, in this case other players of the game. 

## Game Rules

The game rules
* are coarsely described on the [wikipedia page](https://en.wikipedia.org/wiki/So_Long_Sucker)
* can be downloaded [here](https://boardgamegeek.com/filepage/17351/solongsuckerpdf) with a boardgamegeek account.
* A copy is commited in this repository as SoLongSucker.pdf.
* The text has been extracted to rules.md.

## Architecture

```mermaid
flowChart LR
    game[game engine] --- server
    server --- client1[client\ne.g. Anthropic]
    server --- client2[client\ne.g. OpenAI]
    server --- client3[client]
    server --- client4[client]
```

