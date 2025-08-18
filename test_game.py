#!/usr/bin/env python3

import game

def test_game_engine():
    print("Testing So Long Sucker Game Engine")
    print("=" * 40)
    
    # Test game initialization
    players = ["alice", "bob", "charlie", "diana"]
    result = game.initialize_game(players)
    print(f"Game initialization: {result}")
    
    # Test game state
    print("\nInitial game state:")
    print(game.get_game_state_description())
    
    # Test action parser with a realistic game sequence
    test_actions = [
        ("charlie", "PLAY charlie"),  # Charlie starts (current player)
        ("charlie", "CHOOSE alice"),  # Charlie chooses alice to play next
        ("alice", "PLAY alice ON 1"), # Alice plays on charlie's pile
        ("alice", "CHOOSE bob"),      # Alice chooses bob
        ("bob", "PLAY bob"),          # Bob creates new pile
        ("bob", "CHOOSE diana"),      # Bob chooses diana
        ("diana", "PLAY diana ON 2"), # Diana plays her own chip on pile 2
        ("diana", "CHOOSE alice"),    # Diana chooses alice
        ("alice", "PLAY alice ON 2"), # Alice plays on pile 2
        ("alice", "CHOOSE charlie"),  # Alice chooses charlie
        ("charlie", "PLAY charlie ON 1"), # Charlie plays on pile 1 - should trigger capture!
        ("charlie", "STATUS"),        # Check final state
    ]
    
    print("\nTesting action parser:")
    print("-" * 30)
    
    for player, action in test_actions:
        print(f"\n{player}: {action}")
        success, message = game.parse_and_execute_action(player, action)
        print(f"Result: {'SUCCESS' if success else 'FAILED'} - {message}")
        
        # Show updated state after successful actions
        if success and action != "STATUS":
            print("Updated state:")
            print(game.get_game_state_description())
    
    print("\nTest completed!")

if __name__ == "__main__":
    test_game_engine()