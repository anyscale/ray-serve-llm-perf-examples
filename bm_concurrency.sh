#!/bin/bash

# Default values
export MODEL="openai/gpt-oss-120b"
export SERVED_MODEL_NAME="gptoss"
BASE_URL="http://127.0.0.1:8000"

# Configurable parameters with defaults
EXP_NAME="default_exp"
CONCURRENCY_LIST="all"
INPUT_LEN=8000
OUTPUT_LEN=1000
MODE="mixed"
SMOKE_TEST=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    -e|--exp-name)
      EXP_NAME="$2"
      shift 2
      ;;
    -c|--concurrency)
      CONCURRENCY_LIST="$2"
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
    -m|--served-model-name)
      SERVED_MODEL_NAME="$2"
      shift 2
      ;;
    --mode)
      MODE="$2"
      shift 2
      ;;
    -s|--smoke)
      SMOKE_TEST=true
      shift 1
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [-e|--exp-name NAME] [-c|--concurrency all|32,64,128,...] [--itl INPUT_LEN] [--otl OUTPUT_LEN] [-u|--base-url URL] [-m|--served-model-name NAME] [--mode prefill-only|decode-only|mixed] [-s|--smoke]"
      exit 1
      ;;
  esac
done

# If smoke test is requested, run query_completion.py and exit
if [ "$SMOKE_TEST" = true ]; then
  echo "=========================================="
  echo "Running Smoke Test"
  echo "  Base URL: ${BASE_URL}"
  echo "  Served Model Name: ${SERVED_MODEL_NAME}"
  echo "=========================================="
  echo ""
  
  # Get the directory where this script is located
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  
  python "$SCRIPT_DIR/query_completion.py" --base-url "$BASE_URL" --model-name "$SERVED_MODEL_NAME"
  exit $?
fi

# Validate and configure mode
case "$MODE" in
  prefill-only)
    EFFECTIVE_OTL=1
    PREFIX_LEN=0
    SUFFIX_LEN=$INPUT_LEN
    ;;
  decode-only)
    EFFECTIVE_OTL=$OUTPUT_LEN
    PREFIX_LEN=$INPUT_LEN
    SUFFIX_LEN=0
    ;;
  mixed)
    EFFECTIVE_OTL=$OUTPUT_LEN
    PREFIX_LEN=0
    SUFFIX_LEN=$INPUT_LEN
    ;;
  *)
    echo "Error: Invalid mode '$MODE'"
    echo "Valid modes: prefill-only, decode-only, mixed"
    exit 1
    ;;
esac

# Handle concurrency values
if [ "$CONCURRENCY_LIST" = "all" ]; then
  CONCURRENCIES=(4 8 16 32 48 64)
else
  IFS=',' read -ra CONCURRENCIES <<< "$CONCURRENCY_LIST"
fi

# Replace slashes in SERVED_MODEL_NAME for directory naming
SERVED_MODEL_NAME_SAFE=${SERVED_MODEL_NAME//\//--}

# Create auto-generated suffix with all parameters
AUTO_GEN="${SERVED_MODEL_NAME_SAFE}_itl${INPUT_LEN}_otl${OUTPUT_LEN}_${MODE}"
RESULT_BASE_DIR="bm_results/${AUTO_GEN}_${EXP_NAME}"

echo "=========================================="
echo "Experiment Configuration:"
echo "  Experiment Name: ${EXP_NAME}"
echo "  Model: ${MODEL}"
echo "  Served Model Name: ${SERVED_MODEL_NAME}"
echo "  Base URL: ${BASE_URL}"
echo "  Mode: ${MODE}"
echo "  Concurrencies: ${CONCURRENCIES[@]}"
echo "  Input Length: ${INPUT_LEN}"
echo "  Output Length: ${OUTPUT_LEN}"
echo "  Effective Output Length: ${EFFECTIVE_OTL}"
echo "  Prefix Length: ${PREFIX_LEN}"
echo "  Suffix Length: ${SUFFIX_LEN}"
echo "  Result Directory: ${RESULT_BASE_DIR}"
echo "=========================================="

# Loop through each concurrency level
for CONCURRENCY in "${CONCURRENCIES[@]}"; do
  NUM_PROMPTS=$((5 * CONCURRENCY))
  
  # Generate file name based on concurrency
  FILE_NAME="conc${CONCURRENCY}.json"
  
  echo ""
  echo "=========================================="
  echo "Running benchmark:"
  echo "  Concurrency: ${CONCURRENCY}"
  echo "  File: ${FILE_NAME}"
  echo "=========================================="
  
  mkdir -p "$RESULT_BASE_DIR"
  
  # vllm bench serve \
  #     --model $MODEL \
  #     --served-model-name $SERVED_MODEL_NAME \
  #     --backend vllm \
  #     --base-url $BASE_URL \
  #     --ignore-eos \
  #     --num-prompts $NUM_PROMPTS \
  #     --max-concurrency $CONCURRENCY \
  #     --request-rate 1000000000 \
  #     --dataset-name random \
  #     --random-input-len $INPUT_LEN \
  #     --random-output-len $OUTPUT_LEN \
  #     --save-result --result-dir "$RESULT_BASE_DIR" \
  #     --result-filename "$FILE_NAME"

  vllm bench serve \
      --model $MODEL \
      --served-model-name $SERVED_MODEL_NAME \
      --backend vllm \
      --base-url $BASE_URL \
      --ignore-eos \
      --num-prompts $NUM_PROMPTS \
      --max-concurrency $CONCURRENCY \
      --request-rate 1000000000 \
      --dataset-name prefix_repetition \
      --prefix-repetition-prefix-len $PREFIX_LEN \
      --prefix-repetition-suffix-len $SUFFIX_LEN \
      --prefix-repetition-num-prefixes 1 \
      --prefix-repetition-output-len $EFFECTIVE_OTL \
      --save-result --result-dir "$RESULT_BASE_DIR" \
      --result-filename "$FILE_NAME"
  
  echo "Completed benchmark for concurrency ${CONCURRENCY}"
done

echo ""
echo "=========================================="
echo "All benchmarks completed!"
echo "Results saved to: ${RESULT_BASE_DIR}"
echo "=========================================="

