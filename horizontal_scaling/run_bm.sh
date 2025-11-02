#!/bin/bash

# Cleanup function for signal handling
cleanup() {
  echo ""
  echo "=========================================="
  echo "Interrupted! Cleaning up processes..."
  echo "=========================================="
  
  # Kill all background benchmark processes
  if [ ${#PIDS[@]} -gt 0 ]; then
    echo "Stopping benchmark processes..."
    for PID in "${PIDS[@]}"; do
      if kill -0 $PID 2>/dev/null; then
        echo "  Stopping PID: $PID"
        kill $PID 2>/dev/null
      fi
    done
    
    # Wait a bit for graceful shutdown
    sleep 2
    
    # Force kill if still running
    for PID in "${PIDS[@]}"; do
      if kill -0 $PID 2>/dev/null; then
        echo "  Force killing PID: $PID"
        kill -9 $PID 2>/dev/null
      fi
    done
  fi
  
  # Kill any remaining vllm bench processes
  VLLM_PIDS=$(pgrep -f "vllm bench serve" 2>/dev/null)
  if [ -n "$VLLM_PIDS" ]; then
    echo "Cleaning up remaining vllm bench processes..."
    echo "$VLLM_PIDS" | xargs -r kill -9 2>/dev/null
  fi
  
  echo ""
  echo "Cleanup completed. You may need to run cleanup_bm.sh --force if processes persist."
  echo "=========================================="
  exit 130
}

# Initialize PIDS array for cleanup function
PIDS=()

# Set up signal handlers
trap cleanup SIGINT SIGTERM

# Default values - use OPENAI_API_URL env var if set, otherwise default
BASE_URL="${OPENAI_API_URL:-http://127.0.0.1:8000}"

# Configurable parameters with defaults
EXP_NAME=""
BENCHMARK_TYPE="concurrency"
CONCURRENCY_LIST="all"
REQUEST_RATE_LIST="all"
INPUT_LEN=5000
OUTPUT_LEN=250
NUM_RUNS=1
SMOKE_TEST=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    -e|--exp-name)
      EXP_NAME="$2"
      shift 2
      ;;
    -t|--type)
      BENCHMARK_TYPE="$2"
      shift 2
      ;;
    -c|--concurrency)
      CONCURRENCY_LIST="$2"
      shift 2
      ;;
    -r|--request-rate)
      REQUEST_RATE_LIST="$2"
      shift 2
      ;;
    --itl)
      INPUT_LEN="$2"
      shift 2
      ;;
    --otl)
      OUTPUT_LEN="$2"
      shift 2
      ;;
    -u|--base-url)
      BASE_URL="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: $0 -e|--exp-name RESULT_PATH [OPTIONS]"
      echo ""
      echo "Required:"
      echo "  -e, --exp-name RESULT_PATH    Experiment name (result directory path)"
      echo ""
      echo "Optional:"
      echo "  -t, --type TYPE               Benchmark type: concurrency (default) or request-rate"
      echo "  -c, --concurrency VALUES      Comma-separated concurrency values or 'all' (default: all)"
      echo "  -r, --request-rate VALUES      Comma-separated request rate values or 'all' (default: all)"
      echo "  --itl INPUT_LEN               Input token length (default: 5000)"
      echo "  --otl OUTPUT_LEN               Output token length (default: 250)"
      echo "  -u, --base-url URL            Base URL (overrides OPENAI_API_URL env var)"
      echo "  -s, --scaling-factor N        Number of parallel benchmark runs (default: 1)"
      echo "  --smoke                       Run smoke test only"
      echo ""
      echo "Environment Variables:"
      echo "  OPENAI_API_URL                 Base URL for the API (default: http://127.0.0.1:8000)"
      echo "  OPENAI_API_KEY                 API key for authentication (optional)"
      echo ""
      exit 0
      ;;
    -s|--scaling-factor)
      NUM_RUNS="$2"
      shift 2
      ;;
    --smoke)
      SMOKE_TEST=true
      shift 1
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 -e|--exp-name RESULT_PATH [-t|--type concurrency|request-rate] [-c|--concurrency all|4,8,16,...] [-r|--request-rate all|1,2,4,...] [--itl INPUT_LEN] [--otl OUTPUT_LEN] [-u|--base-url URL] [-s|--scaling-factor N] [--smoke]"
      exit 1
      ;;
  esac
done

# Validate required parameters
if [ -z "$EXP_NAME" ]; then
  echo "Error: Experiment name is required"
  echo "Usage: $0 -e|--exp-name RESULT_PATH [-t|--type concurrency|request-rate] [-c|--concurrency all|4,8,16,...] [-r|--request-rate all|1,2,4,...] [--itl INPUT_LEN] [--otl OUTPUT_LEN] [-u|--base-url URL] [-s|--scaling-factor N] [--smoke]"
  exit 1
fi

# Get model information from the server
echo "=========================================="
echo "Fetching model information from ${BASE_URL}/v1/models"
echo "=========================================="

# Build curl command with optional API key
CURL_CMD="curl -s -X GET"
if [ -n "$OPENAI_API_KEY" ]; then
  CURL_CMD="$CURL_CMD -H \"Authorization: Bearer $OPENAI_API_KEY\""
  echo "Using OPENAI_API_KEY for authentication"
fi
CURL_CMD="$CURL_CMD \"${BASE_URL}/v1/models\""

MODEL_RESPONSE=$(eval $CURL_CMD)
if [ $? -ne 0 ]; then
  echo "Error: Failed to fetch model information from ${BASE_URL}/v1/models"
  exit 1
fi

# Extract the model ID from the response
MODEL=$(echo "$MODEL_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
if [ -z "$MODEL" ]; then
  echo "Error: Could not extract model ID from response"
  echo "Response: $MODEL_RESPONSE"
  exit 1
fi

echo "Detected model: ${MODEL}"
echo ""

# If smoke test is requested, run a simple curl test and exit
if [ "$SMOKE_TEST" = true ]; then
  echo "=========================================="
  echo "Running Smoke Test"
  echo "  Base URL: ${BASE_URL}"
  echo "  Model: ${MODEL}"
  echo "=========================================="
  echo ""
  
  # Build curl command with optional API key
  SMOKE_CURL_CMD="curl -X POST \"${BASE_URL}/v1/completions\" -H \"Content-Type: application/json\""
  if [ -n "$OPENAI_API_KEY" ]; then
    SMOKE_CURL_CMD="$SMOKE_CURL_CMD -H \"Authorization: Bearer $OPENAI_API_KEY\""
  fi
  SMOKE_CURL_CMD="$SMOKE_CURL_CMD -d '{\"model\": \"${MODEL}\", \"prompt\": \"Hello, world!\", \"max_tokens\": 10, \"temperature\": 0}'"
  
  eval $SMOKE_CURL_CMD
  
  echo ""
  echo "Smoke test completed"
  exit $?
fi

# Validate and configure benchmark type
case "$BENCHMARK_TYPE" in
  concurrency)
    if [ "$CONCURRENCY_LIST" = "all" ]; then
      BENCHMARK_VALUES=(4 8 16 32 48 64 128)
    else
      IFS=',' read -ra BENCHMARK_VALUES <<< "$CONCURRENCY_LIST"
    fi
    BENCHMARK_PARAM_NAME="Concurrency"
    FILE_PREFIX="conc"
    ;;
  request-rate)
    if [ "$REQUEST_RATE_LIST" = "all" ]; then
      BENCHMARK_VALUES=(1 2 3 4 5 6 7 8 9 10)
    else
      IFS=',' read -ra BENCHMARK_VALUES <<< "$REQUEST_RATE_LIST"
    fi
    BENCHMARK_PARAM_NAME="Request Rate"
    FILE_PREFIX="rr"
    ;;
  *)
    echo "Error: Invalid benchmark type '$BENCHMARK_TYPE'"
    echo "Valid types: concurrency, request-rate"
    exit 1
    ;;
esac

echo "=========================================="
echo "Experiment Configuration:"
echo "  Result Path: ${EXP_NAME}"
echo "  Benchmark Type: ${BENCHMARK_TYPE}"
echo "  Model: ${MODEL}"
echo "  Base URL: ${BASE_URL}"
echo "  Number of Runs: ${NUM_RUNS}"
echo "  ${BENCHMARK_PARAM_NAME} Values: ${BENCHMARK_VALUES[@]}"
echo "  Input Length: ${INPUT_LEN}"
echo "  Output Length: ${OUTPUT_LEN}"
echo "=========================================="

# Function to run all benchmarks for a single run number
run_benchmark_suite() {
  local RUN_NUM=$1
  local PART_DIR="${EXP_NAME}/part${RUN_NUM}"
  
  echo "[Run ${RUN_NUM}] Starting benchmark suite"
  echo "[Run ${RUN_NUM}] Results will be saved to: ${PART_DIR}"
  
  # Loop through each benchmark value
  for VALUE in "${BENCHMARK_VALUES[@]}"; do
    # Configure parameters based on benchmark type
    if [ "$BENCHMARK_TYPE" = "concurrency" ]; then
      NUM_PROMPTS=$((10 * VALUE))
      MAX_CONCURRENCY=$VALUE
      REQUEST_RATE=1000000000
    else
      NUM_PROMPTS=500
      MAX_CONCURRENCY=1000000000
      REQUEST_RATE=$VALUE
    fi
    
    # Generate file name based on benchmark type and value
    FILE_NAME="${FILE_PREFIX}${VALUE}.json"
    
    echo "[Run ${RUN_NUM}] Running benchmark: ${BENCHMARK_PARAM_NAME}=${VALUE}, File=${FILE_NAME}"
    
    mkdir -p "$PART_DIR"
    
    vllm bench serve \
        --model $MODEL \
        --backend vllm \
        --base-url $BASE_URL \
        --ignore-eos \
        --num-prompts $NUM_PROMPTS \
        --max-concurrency $MAX_CONCURRENCY \
        --request-rate $REQUEST_RATE \
        --dataset-name random \
        --random-input-len $INPUT_LEN \
        --random-output-len $OUTPUT_LEN \
        --save-result --result-dir "$PART_DIR" \
        --result-filename "$FILE_NAME"
    
    echo "[Run ${RUN_NUM}] Completed benchmark for ${BENCHMARK_PARAM_NAME,,} ${VALUE}"
  done
  
  echo "[Run ${RUN_NUM}] Completed all benchmarks"
}

# Launch all runs in parallel
echo ""
echo "=========================================="
echo "Launching ${NUM_RUNS} parallel benchmark runs"
echo "=========================================="
echo "Note: Press Ctrl+C to interrupt and cleanup processes"

for RUN_NUM in $(seq 1 $NUM_RUNS); do
  run_benchmark_suite $RUN_NUM &
  PIDS+=($!)
  echo "Launched Run ${RUN_NUM} (PID: ${PIDS[-1]})"
done

# Wait for all background jobs to complete
echo ""
echo "Waiting for all ${NUM_RUNS} runs to complete..."
for PID in "${PIDS[@]}"; do
  wait $PID
  if [ $? -eq 0 ]; then
    echo "Run completed successfully (PID: $PID)"
  else
    echo "Run failed (PID: $PID)"
  fi
done

echo ""
echo "=========================================="
echo "All benchmarks completed!"
echo "Results saved to: ${EXP_NAME}"
echo "  Part directories: part1, part2, ..., part${NUM_RUNS}"
echo "=========================================="

# Aggregate results from all parts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGGREGATE_SCRIPT="${SCRIPT_DIR}/aggregate_results.py"

if [ -f "$AGGREGATE_SCRIPT" ]; then
  echo ""
  python3 "$AGGREGATE_SCRIPT" "$EXP_NAME"
else
  echo ""
  echo "Warning: Aggregation script not found at ${AGGREGATE_SCRIPT}"
  echo "Skipping result aggregation."
fi
