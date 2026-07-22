#!/bin/bash
# Add --hints to a client to include strategy hints (strategy-hints.md) in that
# player's initial prompt, e.g. to compare hinted vs. unhinted players:
#   python client.py anthropic jim --hints &
python client.py anthropic jim --hints &\
python client.py anthropic jack --hints &\
python client.py anthropic janet --hints &\
python client.py anthropic josie --hints


