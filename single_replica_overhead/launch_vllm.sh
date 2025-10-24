
vllm serve openai/gpt-oss-120b \
    --tensor-parallel-size 4 \
    --host 0.0.0.0 \
    --port 8000 \
    --disable-log-requests \
    --disable-uvicorn-access-log \
    --kv-cache-dtype "fp8" 