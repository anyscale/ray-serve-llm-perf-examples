from openai import OpenAI
from typing import List, Literal
from pydantic import BaseModel
import time
import numpy as np
import uuid

# Initialize client
client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="fake-key")
model = client.models.list().data[0].id

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

# response = client.chat.completions.create(
#     model="Qwen/Qwen3-0.6B",
#     messages=[{"role": "user", "content": "How are you? I want you to summarize this article: https://www.theguardian.com/world/2025/may/21/russia-ukraine-war-live-updates-putin-says-he-will-not-use-nuclear-weapons-as-ukraine-says-it-will-not-surrender-kyiv"}],
#     stream=False,
#     # max_tokens=128,
# )


# print(response)
# for chunk in response:
#     # if chunk.choices[0].delta.content is not None:
#     #     print(chunk.choices[0].delta.content, end="", flush=True)
#     if chunk.choices[0].text is not None:
#     print(chunk.choices[0].text, end="", flush=True)
