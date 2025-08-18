import random
from typing import List, Dict, Optional, Tuple

nParticipants = 4

class GameState:
    def __init__(self, players: List[str]):
        self.players = players
        self.current_player = random.choice(players)
        self.defeated_players = set()
        self.active_players = set(players)
        
        # Each player starts with 7 chips of their color
        self.player_chips = {player: [player] * 7 for player in players}
        
        # Piles on the table - each pile is a list of chip colors
        self.piles = []
        
        # Dead box for killed chips
        self.dead_box = []
        
        # Track if we're in a rescue phase (when a player is about to be defeated)
        self.rescue_phase = False
        self.player_being_rescued = None
        self.rescue_responses = {}
        
    def get_player_total_chips(self, player: str) -> int:
        """Count total chips a player has (including prisoners)"""
        return len(self.player_chips.get(player, []))
    
    def get_player_own_chips(self, player: str) -> int:
        """Count chips of player's own color they possess"""
        return len([chip for chip in self.player_chips.get(player, []) if chip == player])
    
    def get_prisoners(self, player: str) -> List[str]:
        """Get list of prisoner chips (other colors) player possesses"""
        return [chip for chip in self.player_chips.get(player, []) if chip != player]
    
    def is_player_defeated(self, player: str) -> bool:
        """Check if player has no chips and is defeated"""
        return player in self.defeated_players or self.get_player_total_chips(player) == 0

# Global game state
game_state: Optional[GameState] = None

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
    prompt += '  PLAY <color> [ON <pile_number>] - Play a chip of given color on a pile (or create new pile)\n'
    prompt += '  CHOOSE <player> - Choose next player to play (when you have choice)\n'
    prompt += '  KILL <color> - Kill a prisoner chip of given color during capture\n'
    prompt += '  TRANSFER <color> TO <player> - Transfer a prisoner chip to another player\n'
    prompt += '  RESCUE <color> TO <player> - Transfer a prisoner chip during rescue phase\n'
    prompt += '  REFUSE_RESCUE - Refuse to rescue a player during rescue phase\n'
    prompt += '  STATUS - Get current game state\n'
    prompt += 'The start player is ' + players[random.randomrange(0, len(players))] + '. It is his/her turn now.'

def initialize_game(players: List[str]) -> str:
    """Initialize a new game with given players"""
    global game_state
    if len(players) != 4:
        return "Error: So Long Sucker requires exactly 4 players."
    
    game_state = GameState(players)
    return f"Game initialized. Players: {', '.join(players)}. Starting player: {game_state.current_player}"

def get_game_state_description() -> str:
    """Get current game state description"""
    if not game_state:
        return "No game in progress."
    
    desc = f"Current player: {game_state.current_player}\n"
    desc += f"Active players: {', '.join(game_state.active_players)}\n"
    if game_state.defeated_players:
        desc += f"Defeated players: {', '.join(game_state.defeated_players)}\n"
    
    desc += "\nPlayer chips:\n"
    for player in game_state.players:
        if player not in game_state.defeated_players:
            own_chips = game_state.get_player_own_chips(player)
            prisoners = game_state.get_prisoners(player)
            desc += f"  {player}: {own_chips} own chips"
            if prisoners:
                prisoner_counts = {}
                for color in prisoners:
                    prisoner_counts[color] = prisoner_counts.get(color, 0) + 1
                prisoner_desc = ", ".join([f"{count} {color}" for color, count in prisoner_counts.items()])
                desc += f", prisoners: {prisoner_desc}"
            desc += "\n"
    
    desc += f"\nPiles on table: {len([p for p in game_state.piles if p])}\n"
    for i, pile in enumerate(game_state.piles):
        if pile:  # Only show non-empty piles
            desc += f"  Pile {i+1}: {' -> '.join(pile)} (top: {pile[-1]})\n"
    
    desc += f"Dead box: {len(game_state.dead_box)} chips\n"
    
    return desc

def place_chip(player: str, chip_color: str, pile_index: Optional[int] = None) -> Tuple[bool, str, Optional[str]]:
    """
    Place a chip on the table
    Returns (success, message, next_player)
    """
    if not game_state:
        return False, "No game in progress.", None
    
    if player != game_state.current_player:
        return False, f"It's not {player}'s turn. Current player is {game_state.current_player}.", None
    
    if player in game_state.defeated_players:
        return False, f"{player} is defeated and cannot play.", None
    
    # Check if player has the chip
    if chip_color not in game_state.player_chips[player]:
        return False, f"{player} doesn't have a {chip_color} chip.", None
    
    # Remove chip from player
    game_state.player_chips[player].remove(chip_color)
    
    # Place chip
    if pile_index is None or pile_index >= len(game_state.piles):
        # Create new pile
        game_state.piles.append([chip_color])
        pile_location = f"new pile {len(game_state.piles)}"
    else:
        # Add to existing pile
        game_state.piles[pile_index].append(chip_color)
        pile_location = f"pile {pile_index + 1}"
    
    message = f"{player} placed {chip_color} chip on {pile_location}."
    
    # Check for capture (two consecutive chips of same color)
    current_pile = game_state.piles[pile_index if pile_index is not None and pile_index < len(game_state.piles) else -1]
    
    if len(current_pile) >= 2 and current_pile[-1] == current_pile[-2]:
        # Capture occurs
        return handle_capture(current_pile, chip_color, message)
    
    # For simplicity, automatically determine next player according to rules
    # In a full implementation, player would choose within the constraints
    next_player = determine_next_player(player, current_pile)
    
    return True, message, next_player

def handle_capture(pile: List[str], capturing_color: str, base_message: str) -> Tuple[bool, str, Optional[str]]:
    """Handle capture when two consecutive chips of same color are played"""
    capturing_player = capturing_color  # In this game, chip color = player name
    
    # Check if capturing player is defeated
    if capturing_player in game_state.defeated_players:
        # If defeated player's chips cause capture, entire pile goes to dead box
        game_state.dead_box.extend(pile)
        pile.clear()
        message = base_message + f" Capture by defeated player {capturing_player} - entire pile killed."
        
        # Move rebounds to previous player
        return True, message, find_previous_player()
    
    # Normal capture: capturing player chooses one chip to kill, takes the rest
    message = base_message + f" CAPTURE by {capturing_player}! "
    message += f"{capturing_player} must choose one chip from the pile to kill, then takes the rest."
    
    # For now, automatically kill the bottom chip and take the rest
    if pile:
        captured_count = len(pile) - 1  # All chips except the one being killed
        killed_chip = pile.pop(0)  # Kill bottom chip
        game_state.dead_box.append(killed_chip)
        
        # Capturing player takes remaining chips
        game_state.player_chips[capturing_player].extend(pile)
        pile.clear()
        
        message += f" Killed {killed_chip}, captured {captured_count} chips."
    
    return True, message, capturing_player

def determine_next_player(current_player: str, pile: List[str]) -> Optional[str]:
    """Determine who plays next according to the rules"""
    
    # Get colors represented in the pile
    colors_in_pile = set(pile)
    
    # Get active players not represented in pile
    eligible_players = []
    for player in game_state.active_players:
        if player not in colors_in_pile:
            eligible_players.append(player)
    
    if eligible_players:
        # Current player can choose from eligible players
        # For automation, choose the next active player not in pile
        return eligible_players[0]
    else:
        # All active players represented - must give to player whose 
        # most recent chip is furthest down in pile
        furthest_down_player = None
        furthest_down_position = len(pile)
        
        for i, chip_color in enumerate(pile):
            if chip_color in game_state.active_players and i < furthest_down_position:
                furthest_down_position = i
                furthest_down_player = chip_color
        
        return furthest_down_player

def find_previous_player() -> Optional[str]:
    """Find the player who gave the move to current player (for rebound)"""
    # This would need to be tracked in game state for full implementation
    # For now, return next active player
    active_list = list(game_state.active_players)
    if active_list:
        return active_list[0]
    return None

def transfer_prisoner(player: str, chip_color: str, target_player: str) -> Tuple[bool, str]:
    """
    Transfer a prisoner chip to another player
    Returns (success, message)
    """
    if not game_state:
        return False, "No game in progress."
    
    if player in game_state.defeated_players:
        return False, f"{player} is defeated and cannot transfer chips."
    
    if target_player in game_state.defeated_players:
        return False, f"Cannot transfer to defeated player {target_player}."
    
    if target_player not in game_state.players:
        return False, f"{target_player} is not a player in this game."
    
    # Check if player has the chip and it's a prisoner (not their own color)
    if chip_color not in game_state.player_chips[player]:
        return False, f"{player} doesn't have a {chip_color} chip."
    
    if chip_color == player:
        return False, f"{player} cannot transfer their own color chips."
    
    # Perform transfer
    game_state.player_chips[player].remove(chip_color)
    game_state.player_chips[target_player].append(chip_color)
    
    return True, f"{player} transferred {chip_color} chip to {target_player}."

def kill_prisoner(player: str, chip_color: str) -> Tuple[bool, str]:
    """
    Kill a prisoner chip
    Returns (success, message)
    """
    if not game_state:
        return False, "No game in progress."
    
    if player in game_state.defeated_players:
        return False, f"{player} is defeated and cannot kill chips."
    
    # Check if player has the chip and it's a prisoner (not their own color)
    if chip_color not in game_state.player_chips[player]:
        return False, f"{player} doesn't have a {chip_color} chip."
    
    if chip_color == player:
        return False, f"{player} cannot kill their own color chips (except from captured piles)."
    
    # Kill the chip
    game_state.player_chips[player].remove(chip_color)
    game_state.dead_box.append(chip_color)
    
    return True, f"{player} killed {chip_color} prisoner chip."

def check_defeat_and_rescue(potential_next_player: str) -> Tuple[bool, str, Optional[str]]:
    """
    Check if a player is defeated and handle rescue phase
    Returns (needs_rescue, message, actual_next_player)
    """
    if game_state.get_player_total_chips(potential_next_player) > 0:
        return False, "", potential_next_player
    
    # Player has no chips - check for rescue
    prisoners_available = False
    rescue_holders = []
    
    for player in game_state.active_players:
        if player != potential_next_player and player not in game_state.defeated_players:
            prisoners = game_state.get_prisoners(player)
            if prisoners:
                prisoners_available = True
                rescue_holders.append(player)
    
    if not prisoners_available:
        # No rescue possible - player is defeated
        game_state.defeated_players.add(potential_next_player)
        game_state.active_players.discard(potential_next_player)
        
        # Move rebounds
        rebound_player = find_previous_player()
        message = f"{potential_next_player} is defeated! No rescue possible. Move rebounds to {rebound_player}."
        
        # Check if rebound player is also defeated (cascade)
        if rebound_player and game_state.get_player_total_chips(rebound_player) == 0:
            return check_defeat_and_rescue(rebound_player)
        
        return False, message, rebound_player
    
    # Rescue phase needed
    game_state.rescue_phase = True
    game_state.player_being_rescued = potential_next_player
    game_state.rescue_responses = {}
    
    message = f"{potential_next_player} has no chips! Rescue phase: players with prisoners must declare if they will transfer chips to save them."
    message += f" Players who can rescue: {', '.join(rescue_holders)}"
    
    return True, message, None

def handle_rescue_response(player: str, will_rescue: bool, chip_color: str = None, target: str = None) -> Tuple[bool, str, Optional[str]]:
    """
    Handle a player's response during rescue phase
    Returns (rescue_complete, message, next_player)
    """
    if not game_state.rescue_phase:
        return False, "Not in rescue phase.", None
    
    if player in game_state.rescue_responses:
        return False, f"{player} has already responded to the rescue.", None
    
    if will_rescue:
        if not chip_color or not target:
            return False, "Must specify chip color and target for rescue transfer.", None
        
        if target != game_state.player_being_rescued:
            return False, f"Can only transfer to {game_state.player_being_rescued} during rescue.", None
        
        success, transfer_msg = transfer_prisoner(player, chip_color, target)
        if not success:
            return False, transfer_msg, None
        
        # Rescue successful
        game_state.rescue_phase = False
        game_state.rescue_responses = {}
        rescued_player = game_state.player_being_rescued
        game_state.player_being_rescued = None
        
        return True, f"RESCUE: {transfer_msg} {rescued_player} is saved!", rescued_player
    
    # Player refuses to rescue
    game_state.rescue_responses[player] = False
    
    # Check if all eligible players have responded
    eligible_rescuers = []
    for p in game_state.active_players:
        if p != game_state.player_being_rescued and p not in game_state.defeated_players:
            if game_state.get_prisoners(p):
                eligible_rescuers.append(p)
    
    if len(game_state.rescue_responses) >= len(eligible_rescuers):
        # All refused - player is defeated
        defeated_player = game_state.player_being_rescued
        game_state.defeated_players.add(defeated_player)
        game_state.active_players.discard(defeated_player)
        game_state.rescue_phase = False
        game_state.rescue_responses = {}
        game_state.player_being_rescued = None
        
        rebound_player = find_previous_player()
        return True, f"All players refused rescue. {defeated_player} is defeated! Move rebounds to {rebound_player}.", rebound_player
    
    return False, f"{player} refuses to rescue. Waiting for other players' responses.", None

def choose_chip_to_kill(player: str, pile_index: int, chip_color: str) -> Tuple[bool, str]:
    """
    Choose which chip to kill during capture
    Returns (success, message)
    """
    if not game_state:
        return False, "No game in progress."
    
    if player in game_state.defeated_players:
        return False, f"{player} is defeated and cannot make choices."
    
    if pile_index >= len(game_state.piles):
        return False, f"Pile {pile_index + 1} doesn't exist."
    
    pile = game_state.piles[pile_index]
    if chip_color not in pile:
        return False, f"Color {chip_color} is not in pile {pile_index + 1}."
    
    # Kill the chosen chip
    pile.remove(chip_color)
    game_state.dead_box.append(chip_color)
    
    # Player takes the remaining chips as prisoners
    game_state.player_chips[player].extend(pile)
    captured_count = len(pile)
    pile.clear()
    
    return True, f"{player} killed {chip_color} and captured {captured_count} chips."

def choose_next_player(current_player: str, next_player: str) -> Tuple[bool, str]:
    """
    Choose the next player to play
    Returns (success, message)
    """
    if not game_state:
        return False, "No game in progress."
    
    if current_player != game_state.current_player:
        return False, f"It's not {current_player}'s turn."
    
    if next_player not in game_state.active_players:
        return False, f"{next_player} is not an active player."
    
    if next_player in game_state.defeated_players:
        return False, f"{next_player} is defeated and cannot play."
    
    # Update current player
    game_state.current_player = next_player
    
    # Check if chosen player is defeated (has no chips)
    needs_rescue, rescue_msg, actual_next = check_defeat_and_rescue(next_player)
    if needs_rescue:
        return True, f"{current_player} chose {next_player}. {rescue_msg}"
    elif actual_next != next_player:
        game_state.current_player = actual_next
        return True, f"{current_player} chose {next_player}. {rescue_msg}"
    
    return True, f"{current_player} chose {next_player} to play next."

def check_game_end() -> Tuple[bool, str, Optional[str]]:
    """
    Check if game has ended and determine winner
    Returns (game_ended, message, winner)
    """
    if not game_state:
        return False, "No game in progress.", None
    
    if len(game_state.active_players) <= 1:
        if len(game_state.active_players) == 1:
            winner = list(game_state.active_players)[0]
            return True, f"Game Over! {winner} wins!", winner
        else:
            return True, "Game Over! No players remaining.", None
    
    return False, "", None

def update_current_player(new_player: str) -> bool:
    """Update the current player and handle any cascading defeats"""
    if not game_state:
        return False
    
    game_state.current_player = new_player
    
    # Check for defeat and rescue
    needs_rescue, rescue_msg, actual_next = check_defeat_and_rescue(new_player)
    if actual_next and actual_next != new_player:
        game_state.current_player = actual_next
    
    return True

def parse_and_execute_action(player: str, action_string: str) -> Tuple[bool, str]:
    """
    Parse an action string and execute the corresponding action
    Returns (success, message)
    """
    if not game_state:
        return False, "No game in progress."
    
    action_string = action_string.strip().upper()
    parts = action_string.split()
    
    if not parts:
        return False, "No action specified."
    
    command = parts[0]
    
    try:
        if command == "PLAY":
            if len(parts) < 2:
                return False, "PLAY command requires a color. Usage: PLAY <color> [ON <pile_number>]"
            
            color = parts[1].lower()
            pile_index = None
            
            # Check for "ON <pile_number>" syntax
            if len(parts) >= 4 and parts[2] == "ON":
                try:
                    pile_index = int(parts[3]) - 1  # Convert to 0-based index
                except ValueError:
                    return False, f"Invalid pile number: {parts[3]}"
            
            success, message, next_player = place_chip(player, color, pile_index)
            if success and next_player:
                update_current_player(next_player)
                
                # Check for game end
                game_ended, end_msg, winner = check_game_end()
                if game_ended:
                    message += f" {end_msg}"
            
            return success, message
        
        elif command == "CHOOSE":
            if len(parts) < 2:
                return False, "CHOOSE command requires a player name. Usage: CHOOSE <player>"
            
            next_player = parts[1].lower()
            return choose_next_player(player, next_player)
        
        elif command == "KILL":
            if len(parts) < 2:
                return False, "KILL command requires a color. Usage: KILL <color>"
            
            color = parts[1].lower()
            return kill_prisoner(player, color)
        
        elif command == "TRANSFER":
            if len(parts) < 4 or parts[2] != "TO":
                return False, "TRANSFER command syntax: TRANSFER <color> TO <player>"
            
            color = parts[1].lower()
            target_player = parts[3].lower()
            return transfer_prisoner(player, color, target_player)
        
        elif command == "RESCUE":
            if len(parts) < 4 or parts[2] != "TO":
                return False, "RESCUE command syntax: RESCUE <color> TO <player>"
            
            color = parts[1].lower()
            target_player = parts[3].lower()
            success, transfer_msg, next_player = handle_rescue_response(player, True, color, target_player)
            
            if success and next_player:
                update_current_player(next_player)
                
                # Check for game end
                game_ended, end_msg, winner = check_game_end()
                if game_ended:
                    transfer_msg += f" {end_msg}"
            
            return success, transfer_msg
        
        elif command == "REFUSE_RESCUE":
            success, message, next_player = handle_rescue_response(player, False)
            
            if success and next_player:
                update_current_player(next_player)
                
                # Check for game end
                game_ended, end_msg, winner = check_game_end()
                if game_ended:
                    message += f" {end_msg}"
            
            return success, message
        
        elif command == "STATUS":
            return True, get_game_state_description()
        
        else:
            return False, f"Unknown command: {command}. Available commands: PLAY, CHOOSE, KILL, TRANSFER, RESCUE, REFUSE_RESCUE, STATUS"
    
    except Exception as e:
        return False, f"Error executing action: {str(e)}"