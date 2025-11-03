#!/bin/bash

# Script to clean up zombie or hanging processes from benchmark runs
# Usage: cleanup_bm.sh [--force] [--exp-name EXP_NAME] [--yes]

FORCE=false
EXP_NAME=""
AUTO_YES=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --force)
      FORCE=true
      shift
      ;;
    --exp-name)
      EXP_NAME="$2"
      shift 2
      ;;
    --yes|-y)
      AUTO_YES=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--force] [--exp-name EXP_NAME] [--yes]"
      exit 1
      ;;
  esac
done

echo "=========================================="
echo "Benchmark Process Cleanup"
echo "=========================================="

# Arrays to store processes to kill
VLLM_PIDS=()
AGG_PIDS=()
ZOMBIE_PARENT_PIDS=()

# Find all vllm bench processes
VLLM_PIDS_RAW=$(pgrep -f "vllm bench serve" 2>/dev/null)
if [ -n "$VLLM_PIDS_RAW" ]; then
  while read -r pid; do
    VLLM_PIDS+=("$pid")
  done <<< "$VLLM_PIDS_RAW"
fi

# Find any Python processes that might be related to aggregation
if [ -n "$EXP_NAME" ]; then
  AGG_PIDS_RAW=$(pgrep -f "aggregate_results.py.*$EXP_NAME" 2>/dev/null)
  if [ -n "$AGG_PIDS_RAW" ]; then
    while read -r pid; do
      AGG_PIDS+=("$pid")
    done <<< "$AGG_PIDS_RAW"
  fi
fi

# Check for zombie processes and their parents
ZOMBIES=$(ps aux | awk '$8 ~ /^Z/ {print $2}' | head -20)
if [ -n "$ZOMBIES" ]; then
  while read -r pid; do
    if [ -n "$pid" ]; then
      PPID=$(ps -p $pid -o ppid= 2>/dev/null | tr -d ' ')
      if [ -n "$PPID" ] && [ "$PPID" != "1" ]; then
        # Check if we already have this parent PID
        if [[ ! " ${ZOMBIE_PARENT_PIDS[@]} " =~ " ${PPID} " ]]; then
          ZOMBIE_PARENT_PIDS+=("$PPID")
        fi
      fi
    fi
  done <<< "$ZOMBIES"
fi

# Total count of processes to kill
TOTAL_TO_KILL=$((${#VLLM_PIDS[@]} + ${#AGG_PIDS[@]} + ${#ZOMBIE_PARENT_PIDS[@]}))

if [ $TOTAL_TO_KILL -eq 0 ]; then
  echo "No processes found to clean up."
  exit 0
fi

# Display processes found
echo ""
echo "Processes found to kill:"
echo "----------------------------------------"

if [ ${#VLLM_PIDS[@]} -gt 0 ]; then
  echo ""
  echo "vllm bench processes (${#VLLM_PIDS[@]}):"
  printf "%-8s %-8s %-12s %-10s %s\n" "PID" "PPID" "RUNTIME" "MEMORY" "COMMAND"
  printf "%-8s %-8s %-12s %-10s %s\n" "---" "----" "-------" "------" "-------"
  for pid in "${VLLM_PIDS[@]}"; do
    if kill -0 $pid 2>/dev/null; then
      ps -p $pid -o pid=,ppid=,etime=,rss=,cmd= --no-headers 2>/dev/null | while read p ppid etime rss cmd; do
        # Convert RSS from KB to MB
        mem_mb=$((rss / 1024))
        # Truncate command if too long
        cmd_short="${cmd:0:60}"
        if [ ${#cmd} -gt 60 ]; then
          cmd_short="${cmd_short}..."
        fi
        printf "%-8s %-8s %-12s %-10s %s\n" "$p" "$ppid" "$etime" "${mem_mb}MB" "$cmd_short"
      done
    fi
  done
fi

if [ ${#AGG_PIDS[@]} -gt 0 ]; then
  echo ""
  echo "Aggregation processes (${#AGG_PIDS[@]}):"
  printf "%-8s %-8s %-12s %-10s %s\n" "PID" "PPID" "RUNTIME" "MEMORY" "COMMAND"
  printf "%-8s %-8s %-12s %-10s %s\n" "---" "----" "-------" "------" "-------"
  for pid in "${AGG_PIDS[@]}"; do
    if kill -0 $pid 2>/dev/null; then
      ps -p $pid -o pid=,ppid=,etime=,rss=,cmd= --no-headers 2>/dev/null | while read p ppid etime rss cmd; do
        mem_mb=$((rss / 1024))
        cmd_short="${cmd:0:60}"
        if [ ${#cmd} -gt 60 ]; then
          cmd_short="${cmd_short}..."
        fi
        printf "%-8s %-8s %-12s %-10s %s\n" "$p" "$ppid" "$etime" "${mem_mb}MB" "$cmd_short"
      done
    fi
  done
fi

if [ ${#ZOMBIE_PARENT_PIDS[@]} -gt 0 ]; then
  echo ""
  echo "Zombie parent processes (${#ZOMBIE_PARENT_PIDS[@]}):"
  echo "  Note: These will be killed to clean up zombie processes"
  printf "%-8s %-8s %-12s %-10s %s\n" "PID" "PPID" "RUNTIME" "MEMORY" "COMMAND"
  printf "%-8s %-8s %-12s %-10s %s\n" "---" "----" "-------" "------" "-------"
  for pid in "${ZOMBIE_PARENT_PIDS[@]}"; do
    if kill -0 $pid 2>/dev/null; then
      ps -p $pid -o pid=,ppid=,etime=,rss=,cmd= --no-headers 2>/dev/null | while read p ppid etime rss cmd; do
        mem_mb=$((rss / 1024))
        cmd_short="${cmd:0:60}"
        if [ ${#cmd} -gt 60 ]; then
          cmd_short="${cmd_short}..."
        fi
        printf "%-8s %-8s %-12s %-10s %s\n" "$p" "$ppid" "$etime" "${mem_mb}MB" "$cmd_short"
      done
    fi
  done
fi

echo ""
echo "----------------------------------------"
echo "Total processes to kill: $TOTAL_TO_KILL"
echo "----------------------------------------"

# Ask for confirmation unless force or auto-yes
if [ "$FORCE" = true ] || [ "$AUTO_YES" = true ]; then
  CONFIRM="y"
else
  echo ""
  read -p "Do you want to kill these processes? [y/N]: " CONFIRM
fi

if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
  echo "Aborted. No processes were killed."
  exit 0
fi

# Kill processes
echo ""
echo "Killing processes..."

# Kill vllm bench processes
if [ ${#VLLM_PIDS[@]} -gt 0 ]; then
  echo "  Killing ${#VLLM_PIDS[@]} vllm bench process(es)..."
  for pid in "${VLLM_PIDS[@]}"; do
    if kill -0 $pid 2>/dev/null; then
      kill $pid 2>/dev/null
    fi
  done
  
  # Wait a bit for graceful shutdown
  sleep 2
  
  # Force kill if still running
  for pid in "${VLLM_PIDS[@]}"; do
    if kill -0 $pid 2>/dev/null; then
      echo "    Force killing PID $pid"
      kill -9 $pid 2>/dev/null
    fi
  done
fi

# Kill aggregation processes
if [ ${#AGG_PIDS[@]} -gt 0 ]; then
  echo "  Killing ${#AGG_PIDS[@]} aggregation process(es)..."
  for pid in "${AGG_PIDS[@]}"; do
    if kill -0 $pid 2>/dev/null; then
      kill -9 $pid 2>/dev/null
    fi
  done
fi

# Kill zombie parent processes
if [ ${#ZOMBIE_PARENT_PIDS[@]} -gt 0 ]; then
  echo "  Killing ${#ZOMBIE_PARENT_PIDS[@]} zombie parent process(es)..."
  for pid in "${ZOMBIE_PARENT_PIDS[@]}"; do
    if kill -0 $pid 2>/dev/null; then
      kill -9 $pid 2>/dev/null
    fi
  done
fi

sleep 1

# Summary
echo ""
echo "=========================================="
echo "Cleanup completed."
echo ""
echo "Remaining processes:"
REMAINING_VLLM=$(pgrep -f "vllm bench serve" 2>/dev/null)
if [ -n "$REMAINING_VLLM" ]; then
  REMAINING_COUNT=$(echo $REMAINING_VLLM | wc -w)
  echo "  vllm bench: $REMAINING_COUNT process(es) still running"
  echo "    PIDs: $REMAINING_VLLM"
else
  echo "  vllm bench: No processes found"
fi

REMAINING_AGG=$(pgrep -f "aggregate_results.py" 2>/dev/null)
if [ -n "$REMAINING_AGG" ]; then
  REMAINING_COUNT=$(echo $REMAINING_AGG | wc -w)
  echo "  aggregation: $REMAINING_COUNT process(es) still running"
  echo "    PIDs: $REMAINING_AGG"
fi
echo "=========================================="

