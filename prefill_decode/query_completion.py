from openai import OpenAI
from typing import List, Literal
from pydantic import BaseModel
import time
import numpy as np
import uuid
import argparse
import sys

def main(base_url: str = "http://127.0.0.1:8000", model_name: str = None):
    # Initialize client
    client = OpenAI(base_url=f"{base_url}/v1", api_key="fake-key")
    
    # Get model name - use provided name or fetch from server
    if model_name:
        model = model_name
    else:
        model = client.models.list().data[0].id
    
    print(f"Using base_url: {base_url}")
    print(f"Using model: {model}")
    print("-" * 50)
    
    # Request structured JSON output
    s = time.perf_counter()
    response = client.completions.create(
        model=model,
        prompt=f"Count: " + ", ".join([str(i) for i in range(1, 100)]) + ", ",
        stream=True,
        max_tokens=100,
        stream_options={"include_usage": True},
        temperature=0.0,
        extra_body={"ignore_eos": True}
    )
    
    is_first = True
    token_time_stamps = []
    
    for chunk in response:
        if chunk.choices and chunk.choices[0].text is not None:
            token = chunk.choices[0].text
            ts = time.perf_counter()
            
            token_time_stamps.append((token, (ts - s) * 1000))
            s = ts
            print(token, end="", flush=True)
        if chunk.usage is not None:
            print("\n total usage: ", chunk.usage)
    
    # from pprint import pprint
    # pprint(token_time_stamps)
    
    ttft = token_time_stamps[0][1]
    print("ttft: ", ttft)
    if len(token_time_stamps) > 1:
        mean_tpot = np.mean([tpot for _, tpot in token_time_stamps[1:]])
        std_tpot = np.std([tpot for _, tpot in token_time_stamps[1:]])
        # p99
        p99_tpot = np.percentile([tpot for _, tpot in token_time_stamps[1:]], 99)
    
        print("mean_tpot: ", mean_tpot)
        print("std_tpot: ", std_tpot)
        print("p99_tpot: ", p99_tpot)
    
    print("\n" + "=" * 50)
    print("Smoke test completed successfully!")
    print("=" * 50)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query completion test script")
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://127.0.0.1:8000",
        help="Base URL for the API (default: http://127.0.0.1:8000)"
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=None,
        help="Model name to use (default: auto-detect from server)"
    )
    
    args = parser.parse_args()
    
    try:
        main(base_url=args.base_url, model_name=args.model_name)
    except Exception as e:
        print(f"\n{'=' * 50}")
        print(f"ERROR: Smoke test failed!")
        print(f"{'=' * 50}")
        print(f"Error details: {e}")
        sys.exit(1)
