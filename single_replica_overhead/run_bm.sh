#!/bin/bash

# Default values
BASE_URL="http://127.0.0.1:8000"

# Configurable parameters with defaults
EXP_NAME=""
BENCHMARK_TYPE="concurrency"
CONCURRENCY_LIST="all"
REQUEST_RATE_LIST="all"
INPUT_LEN=5000
OUTPUT_LEN=250
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
    -s|--smoke)
      SMOKE_TEST=true
      shift 1
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 -e|--exp-name RESULT_PATH [-t|--type concurrency|request-rate] [-c|--concurrency all|4,8,16,...] [-r|--request-rate all|1,2,4,...] [--itl INPUT_LEN] [--otl OUTPUT_LEN] [-u|--base-url URL] [-s|--smoke]"
      exit 1
      ;;
  esac
done

# Validate required parameters
if [ -z "$EXP_NAME" ]; then
  echo "Error: Experiment name is required"
  echo "Usage: $0 -e|--exp-name RESULT_PATH [-t|--type concurrency|request-rate] [-c|--concurrency all|4,8,16,...] [-r|--request-rate all|1,2,4,...] [--itl INPUT_LEN] [--otl OUTPUT_LEN] [-u|--base-url URL] [-s|--smoke]"
  exit 1
fi

# Get model information from the server
echo "=========================================="
echo "Fetching model information from ${BASE_URL}/v1/models"
echo "=========================================="

MODEL_RESPONSE=$(curl -s -X GET "${BASE_URL}/v1/models")
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
  
  curl -X POST "${BASE_URL}/v1/completions" \
    -H "Content-Type: application/json" \
    -d "{
      \"model\": \"${MODEL}\",
      \"prompt\": \"Hello, world!\",
      \"max_tokens\": 10,
      \"temperature\": 0
    }"
  
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
echo "  ${BENCHMARK_PARAM_NAME} Values: ${BENCHMARK_VALUES[@]}"
echo "  Input Length: ${INPUT_LEN}"
echo "  Output Length: ${OUTPUT_LEN}"
echo "=========================================="

# Loop through each benchmark value
for VALUE in "${BENCHMARK_VALUES[@]}"; do
  # Configure parameters based on benchmark type
  if [ "$BENCHMARK_TYPE" = "concurrency" ]; then
    NUM_PROMPTS=$((5 * VALUE))
    MAX_CONCURRENCY=$VALUE
    REQUEST_RATE=1000000000
  else
    NUM_PROMPTS=500
    MAX_CONCURRENCY=1000000000
    REQUEST_RATE=$VALUE
  fi
  
  # Generate file name based on benchmark type and value
  FILE_NAME="${FILE_PREFIX}${VALUE}.json"
  
  echo ""
  echo "=========================================="
  echo "Running benchmark:"
  echo "  ${BENCHMARK_PARAM_NAME}: ${VALUE}"
  echo "  Num Prompts: ${NUM_PROMPTS}"
  echo "  File: ${FILE_NAME}"
  echo "=========================================="
  
  mkdir -p "$EXP_NAME"
  
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
      --save-result --result-dir "$EXP_NAME" \
      --result-filename "$FILE_NAME"
  
  echo "Completed benchmark for ${BENCHMARK_PARAM_NAME,,} ${VALUE}"
done

echo ""
echo "=========================================="
echo "All benchmarks completed!"
echo "Results saved to: ${EXP_NAME}"
echo "=========================================="


