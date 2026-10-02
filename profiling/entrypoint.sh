#!/bin/bash

# Persistent results directory (mounted from host project folder)
LOG_DIR="/home/muruga/workspace/GalleryClassifier/profiling/results"
mkdir -p "$LOG_DIR"

# Find the next auto-increment number for the log file
NEXT_NUM=1
for file in "$LOG_DIR"/result_*_*.log; do
    if [ -f "$file" ]; then
        NUM=$(basename "$file" | cut -d'_' -f2)
        if [[ "$NUM" =~ ^[0-9]+$ ]] && [ "$NUM" -ge "$NEXT_NUM" ]; then
            NEXT_NUM=$((NUM + 1))
        fi
    fi
done

# Format: result_<number>_<time>.log
CURRENT_TIME=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/result_${NEXT_NUM}_${CURRENT_TIME}.log"
export PROFILING_LOG_FILE="$LOG_FILE"

echo "Logging profiling data to $LOG_FILE"
echo "Timestamp, CPU(%), RAM(MB)" > "$LOG_FILE"

# Start the uvicorn server in the background
# Make sure 'server:app' matches your actual FastAPI instance in server.py
uvicorn server:app --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

# Profiling loop - continues as long as the uvicorn server is running
while kill -0 $UVICORN_PID 2>/dev/null; do
    # Calculate total CPU and RAM(MB) usage of all processes in the container
    STATS=$(ps -eo %cpu,rss | tail -n +2 | awk '{cpu+=$1; ram+=$2} END {printf "%.1f, %.1f", cpu, ram/1024}')
    
    TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
    echo "$TIMESTAMP, $STATS" >> "$LOG_FILE"
    sleep 1 # Logs every 1 second
done
