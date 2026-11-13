#!/bin/bash
# THE pre-registered test. Run ONCE, after the system is frozen (see docs/REVIEW_2026-11-12.md).
# Plays every test case two ways and scores both against GAO's real rulings:
#   game   = multi-agent game on the real path (file/defend/continue), counsel argues the filed grounds
#   single = one agent, one call per case, same information GAO had
#   SIM_BACKEND=cli JOBS=2 bash run_test.sh
cd "$(dirname "$0")"
source .venv/bin/activate
JOBS=${JOBS:-2}; REPEATS=${REPEATS:-3}
mkdir -p runs/logs
ls data/cases_test/*_packet.yaml | xargs -P "$JOBS" -I{} sh -c '
  f={}; n=$(basename "$f" _packet.yaml)
  python run.py play "$f" --real-path --repeats '"$REPEATS"' > "runs/logs/test_game_$n.log" 2>&1 || echo "FAILED game $n"
  python run.py single "$f" --repeats '"$REPEATS"' > "runs/logs/test_single_$n.log" 2>&1 || echo "FAILED single $n"
  echo "done $n"'
python scripts/analyze_runs.py
