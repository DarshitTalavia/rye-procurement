#!/usr/bin/env bash
# Run the meterless procurement agent on YOUR Claude login.
# Prereqs: `claude login` (Pro/Max) + `pip install -r requirements.txt`.
# Example: ./run.sh "I run a pub, about 200 m2, open 12pm to 11pm"
python3 agent.py "$@"
