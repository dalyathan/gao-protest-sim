#!/bin/bash
# Play every case. Finished repeats are skipped, so re-running resumes where it stopped.
#   JOBS=3 bash run_all.sh          # games in parallel (default 3; use 1 to go one at a time)
#   SIM_BACKEND=cli bash run_all.sh # use your Claude subscription via `claude -p`
cd "$(dirname "$0")"
source .venv/bin/activate
JOBS=${JOBS:-3}
mkdir -p runs/logs
ls data/cases/*_packet.yaml | xargs -P "$JOBS" -I{} sh -c \
  'f={}; n=$(basename "$f" _packet.yaml); python run.py play "$f" --repeats 3 $EXTRA > "runs/logs/$n.log" 2>&1 && echo "done  $n" || echo "FAILED $n (see runs/logs/$n.log)"'
echo "DONE. Logs are in runs/"
