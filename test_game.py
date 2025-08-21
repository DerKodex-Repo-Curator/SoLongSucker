#!/usr/bin/env python3

import game

# Global test tracking
test_results = []

def assert_test(condition, test_name, description=""):
    """Helper function to track test results"""
    result = {
        'name': test_name,
        'passed': condition,
        'description': description
    }
    test_results.append(result)
    status = "PASS" if condition else "FAIL"
    print(f"  {status}: {test_name}" + (f" - {description}" if description else ""))
    return condition

def test_basic_gameplay():
    """Test basic game flow and capture"""
    print("=== Testing Basic Gameplay ===")
    
    players = ["alice", "bob", "charlie", "diana"]
    result = game.initialize_game(players)
    assert_test(result.startswith("Game initialized"), "Game initialization")
    
    # Use the actual starting player
    starting_player = game.game_state.current_player
    
    test_actions = [
        (starting_player, f"PLAY {starting_player}"),
        (starting_player, "CHOOSE bob"),  # Choose someone not in pile
        ("bob", "PLAY bob ON 1"),
        ("bob", "CHOOSE diana"),
        ("diana", "PLAY diana"),
        ("diana", "CHOOSE charlie"),
        ("charlie", "PLAY charlie ON 2"),
        ("charlie", "CHOOSE alice"),
        ("alice", "PLAY alice ON 2"),
        ("alice", "CHOOSE bob"),
        ("bob", "PLAY bob ON 1"),  # Triggers capture by bob
    ]
    
    current_player = starting_player
    for expected_player, action in test_actions:
        # Update expected player to current for actions after player changes
        if action.startswith("CHOOSE"):
            # For CHOOSE actions, extract the chosen player
            chosen_player = action.split()[1]
            success, message = game.parse_and_execute_action(current_player, action)
            assert_test(success, f"Action: {current_player} {action}", message if not success else "")
            if success:
                current_player = chosen_player
        else:
            success, message = game.parse_and_execute_action(current_player, action)
            assert_test(success, f"Action: {current_player} {action}", message if not success else "")

def test_prisoner_management():
    """Test killing and transferring prisoners"""
    print("\n=== Testing Prisoner Management ===")
    
    players = ["alice", "bob", "charlie", "diana"]
    game.initialize_game(players)
    
    # Set up scenario where alice has prisoners
    game.game_state.player_chips["alice"] = ["alice", "alice", "bob", "charlie"]
    
    # Test killing prisoner
    success, msg = game.kill_prisoner("alice", "bob")
    assert_test(success, "Kill prisoner", msg if not success else "")
    
    # Test transferring prisoner
    success, msg = game.transfer_prisoner("alice", "charlie", "diana")
    assert_test(success, "Transfer prisoner", msg if not success else "")
    
    # Test invalid operations
    success, msg = game.kill_prisoner("alice", "alice")  # Can't kill own chips
    assert_test(not success, "Reject killing own chip", "Should fail when trying to kill own chip")
    
    success, msg = game.transfer_prisoner("alice", "alice", "bob")  # Can't transfer own chips
    assert_test(not success, "Reject transferring own chip", "Should fail when trying to transfer own chip")

def test_rescue_mechanics():
    """Test rescue phase when player has no chips"""
    print("\n=== Testing Rescue Mechanics ===")
    
    players = ["alice", "bob", "charlie", "diana"]
    game.initialize_game(players)
    
    # Set up rescue scenario
    game.game_state.player_chips["alice"] = []  # Alice has no chips
    game.game_state.player_chips["bob"] = ["bob", "bob", "alice"]  # Bob has alice prisoner
    game.game_state.player_chips["charlie"] = ["charlie", "diana"]  # Charlie has diana prisoner
    game.game_state.current_player = "bob"
    
    # Try to choose alice (should trigger rescue)
    success, msg = game.choose_next_player("bob", "alice")
    assert_test(success, "Trigger rescue phase", msg if not success else "")
    
    # Test rescue response
    success, msg, next_player = game.handle_rescue_response("bob", True, "alice", "alice")
    assert_test(success, "Execute rescue transfer", msg if not success else "")
    if success and next_player:
        assert_test(next_player == "alice", "Rescued player gets turn", f"Expected alice, got {next_player}")

def test_defeat_and_rebound():
    """Test player defeat and move rebound"""
    print("\n=== Testing Defeat and Rebound ===")
    
    players = ["alice", "bob", "charlie", "diana"]
    game.initialize_game(players)
    
    # Set up defeat scenario - alice has no chips, no one can rescue
    game.game_state.player_chips["alice"] = []
    game.game_state.player_chips["bob"] = ["bob", "bob"]  # No prisoners
    game.game_state.player_chips["charlie"] = ["charlie", "charlie"]
    game.game_state.player_chips["diana"] = ["diana", "diana"]
    game.game_state.current_player = "bob"
    game.game_state.previous_player = "diana"
    
    # Choose alice - should result in defeat and rebound to bob
    success, msg = game.choose_next_player("bob", "alice")
    assert_test(success, "Process defeat and rebound", msg if not success else "")
    # When alice is defeated, move rebounds to the previous player (bob, who chose alice)
    assert_test(game.game_state.current_player == "bob", "Move rebounds to previous player", f"Expected bob, got {game.game_state.current_player}")
    assert_test("alice" in game.game_state.defeated_players, "Player marked as defeated", "Alice should be in defeated players set")

def test_game_end_conditions():
    """Test game ending scenarios"""
    print("\n=== Testing Game End Conditions ===")
    
    players = ["alice", "bob", "charlie", "diana"]
    game.initialize_game(players)
    
    # Set up win scenario - only alice remains active
    game.game_state.defeated_players = {"bob", "charlie", "diana"}
    game.game_state.active_players = {"alice"}
    
    game_ended, message, winner = game.check_game_end()
    assert_test(game_ended, "Game ends with one player", message if not game_ended else "")
    assert_test(winner == "alice", "Correct winner identified", f"Expected alice, got {winner}")

def test_capture_chip_choice():
    """Test manual chip selection during capture"""
    print("\n=== Testing Capture Chip Choice ===")
    
    players = ["alice", "bob", "charlie", "diana"]
    game.initialize_game(players)
    
    # Set up a capture scenario
    game.game_state.piles = [["bob", "alice", "charlie", "diana"]]
    game.game_state.current_player = "alice"
    game.game_state.capture_in_progress = True
    game.game_state.capture_pile_index = 0
    game.game_state.capturing_player = "alice"
    
    initial_chips = len(game.game_state.player_chips["alice"])
    
    # Test choosing specific chip to kill
    success, msg = game.choose_chip_to_kill("alice", 1, "bob")
    assert_test(success, "Manual capture chip selection", msg if not success else "")
    
    # Verify alice got the remaining chips
    final_chips = len(game.game_state.player_chips["alice"])
    assert_test(final_chips > initial_chips, "Capturing player gets remaining chips", f"Had {initial_chips}, now has {final_chips}")

def test_invalid_actions():
    """Test various invalid action scenarios"""
    print("\n=== Testing Invalid Actions ===")
    
    players = ["alice", "bob", "charlie", "diana"]
    game.initialize_game(players)
    
    # Test wrong player trying to play (choose a player who is NOT current)
    current = game.game_state.current_player
    wrong_player = "alice" if current != "alice" else "bob" 
    success, msg = game.parse_and_execute_action(wrong_player, f"PLAY {wrong_player}")
    assert_test(not success, "Reject wrong player turn", "Should fail when wrong player tries to play")
    
    # Test playing chip player doesn't have
    current = game.game_state.current_player
    success, msg = game.parse_and_execute_action(current, "PLAY bob")
    assert_test(not success, "Reject unowned chip", "Should fail when playing chip not owned")
    
    # Test invalid pile number
    success, msg = game.parse_and_execute_action(current, f"PLAY {current} ON 99")
    assert_test(not success, "Reject invalid pile", "Should fail with invalid pile number")
    
    # Test malformed commands
    success, msg = game.parse_and_execute_action(current, "INVALID_COMMAND")
    assert_test(not success, "Reject invalid command", "Should fail with invalid command")

def test_pile_constraints():
    """Test next player choice constraints based on pile composition"""
    print("\n=== Testing Pile Constraints ===")
    
    players = ["alice", "bob", "charlie", "diana"]
    game.initialize_game(players)
    
    # Create pile with alice and bob chips
    game.game_state.piles = [["alice", "bob"]]
    game.game_state.current_player = "alice"
    
    # Alice should be able to choose charlie or diana (not in pile)
    eligible = []
    colors_in_pile = set(game.game_state.piles[0])
    for player in game.game_state.active_players:
        if player not in colors_in_pile:
            eligible.append(player)
    
    assert_test(len(eligible) == 2, "Correct eligible players identified", f"Expected 2 eligible players, got {len(eligible)}")
    
    # Test choosing eligible player
    if eligible:
        success, msg = game.choose_next_player("alice", eligible[0])
        assert_test(success, "Choose eligible player", msg if not success else "")
    
    # Test choosing ineligible player (should fail)
    game.game_state.current_player = "charlie"  # Reset for next test
    success, msg = game.choose_next_player("charlie", "alice")  # Alice is in pile
    assert_test(not success, "Reject ineligible player choice", "Should fail when choosing player represented in pile")

def test_comprehensive_game():
    """Run a more comprehensive game scenario"""
    print("\n=== Comprehensive Game Test ===")
    
    players = ["alice", "bob", "charlie", "diana"]
    game.initialize_game(players)
    
    # Use actual starting player and their chip color
    current_player = game.game_state.current_player
    
    actions = [
        f"PLAY {current_player}",
        "CHOOSE alice", 
        "PLAY alice ON 1",
        "CHOOSE bob",
        "PLAY bob",
        "CHOOSE diana", 
        "PLAY diana ON 2",
        "CHOOSE alice",
        "PLAY alice ON 1",  # Should trigger capture by alice
        "STATUS",
    ]
    
    all_successful = True
    
    for i, action in enumerate(actions):
        success, msg = game.parse_and_execute_action(current_player, action)
            
        if not success:
            all_successful = False
            assert_test(False, f"Comprehensive game step {i+1}", f"{action} failed: {msg}")
        else:
            if action.startswith("CHOOSE"):
                # Update current player to the chosen player
                chosen_player = action.split()[1]
                current_player = chosen_player
            elif action != "STATUS":
                # For other successful actions, current player might change
                current_player = game.game_state.current_player
    
    assert_test(all_successful, "Complete game scenario", "All actions in comprehensive test should succeed")

def run_all_tests():
    """Run all test functions"""
    global test_results
    test_results = []  # Reset results
    
    print("Testing So Long Sucker Game Engine")
    print("=" * 50)
    
    test_basic_gameplay()
    test_prisoner_management()
    test_rescue_mechanics()
    test_defeat_and_rebound()
    test_game_end_conditions()
    test_capture_chip_choice()
    test_invalid_actions()
    test_pile_constraints()
    test_comprehensive_game()
    
    # Print summary
    print("\n" + "=" * 50)
    passed = sum(1 for result in test_results if result['passed'])
    total = len(test_results)
    failed = total - passed
    
    print(f"TEST SUMMARY: {passed}/{total} tests passed")
    if failed > 0:
        print(f"FAILED TESTS ({failed}):")
        for result in test_results:
            if not result['passed']:
                print(f"  - {result['name']}: {result['description']}")
    else:
        print("🎉 ALL TESTS PASSED!")
    
    return failed == 0

if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)