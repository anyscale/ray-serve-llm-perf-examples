export MODEL="openai/gpt-oss-120b"
export SERVED_MODEL_NAME="gptoss"
# export SERVED_MODEL_NAME=$MODEL

BASE_URL="http://127.0.0.1:8000"
echo "BASE_URL=${BASE_URL}"

# BASE_URLS=("http://10.65.82.25:30002" "http://10.65.82.25:30003" "http://10.65.82.25:30009" "http://10.65.82.25:30006" "http://10.65.82.25:30008" "http://10.65.82.25:30004" "http://10.65.82.25:30000" "http://10.65.82.25:30010" "http://10.65.82.25:30005" "http://10.65.82.25:30001" "http://10.65.82.25:30007" "http://10.65.82.25:30011")
# echo "BASE_URLS=${BASE_URLS[@]}"

CONCURRENCY=256
REQUEST_RATE=$((CONCURRENCY / 32))
if [ "$REQUEST_RATE" -lt 1 ]; then
  REQUEST_RATE=1
fi
INPUT_LEN=10000
OUTPUT_LEN=500

EXPERIMENT_NAME=u${CONCURRENCY}-rr${REQUEST_RATE}
FILE_NAME=${EXPERIMENT_NAME}.json
# RESULT_DIR=bm_results/$SERVED_MODEL_NAME/4ptp1-2dtp2
RESULT_DIR=bm_results/$SERVED_MODEL_NAME/4ptp1-2dtp2-debug/

echo "Running experiment ${EXPERIMENT_NAME}"

mkdir -p $RESULT_DIR

vllm bench serve \
    --model $MODEL \
    --served-model-name $SERVED_MODEL_NAME \
    --backend vllm \
    --base-url $BASE_URL \
    --ignore-eos \
    --num-prompts $((2 * CONCURRENCY)) \
    --max-concurrency $CONCURRENCY \
    --request-rate $REQUEST_RATE \
    --dataset-name random \
    --random-input-len $INPUT_LEN \
    --random-output-len $OUTPUT_LEN \
    --save-result --result-dir $RESULT_DIR \
    --result-filename $FILE_NAME