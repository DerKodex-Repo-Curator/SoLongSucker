import random

nParticipants = 4

def getRules():
    f = open('rules.md', 'r')
    rules = f.read()
    f.close()
    return rules

def getInitialPrompt(players, player):
    prompt = 'You are playing the game \'So long sucker\'.\n'
    prompt += 'The players/participants in the game are: ' + ', '.join(players) + '.\n'
    prompt += 'You are player ' + player + '.\n'
    prompt += 'The rules of the game are as follows:\n'
    prompt += getRules()
    prompt += 'You can freely converse with all the other players by addressing them by their name. They will do the same.\n'
    prompt += 'When it is your turn, you can perform an action. The game moderator will answer, whether the action could be parsed and whether it is legal. '
    prompt += 'If the action is accepted, the moderator informs all players about the changed game state.\n'
    prompt += 'The available actions with their required strict syntax are:\n'
# TODO: actions
    prompt += 'The start player is ' + players[random.randomrange(0, len(players))] + '. It is his/her turn now.'

