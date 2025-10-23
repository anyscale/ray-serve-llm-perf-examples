"""
Simple client for testing the Ray Serve LLM service.
Makes a single request to the service and times the response.
"""

import requests
import time
import json

def make_request(url="http://127.0.0.1:8000"):
    """Make a single chat completion request and time it."""
    
    # Same payload as the concurrent client
    payload = {
        "model": "model",
        "messages": [
            {
                "role": "user", 
                "content": "Hello!"
            }
        ],
        "max_tokens": 50,
        "temperature": 0.7
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    endpoint = f"{url}/v1/chat/completions"
    
    print(f"Sending request to {endpoint}...")
    
    # Time the request
    start_time = time.time()
    print(f"[DEBUG] SENDING REQUEST at {start_time}")
    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=6000)
        end_time = time.time()
        
        response_time = end_time - start_time
        
        if response.status_code == 200:
            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = result.get("usage", {})
            
            print(f"\n✅ Success!")
            print(f"Response time: {response_time:.3f} seconds")
            print(f"Content: {content}")
            print(f"Usage: {usage}")
            
        else:
            print(f"\n❌ Error!")
            print(f"HTTP Status: {response.status_code}")
            print(f"Response time: {response_time:.3f} seconds")
            print(f"Error: {response.text}")
            
    except requests.exceptions.RequestException as e:
        end_time = time.time()
        response_time = end_time - start_time
        print(f"\n❌ Request failed!")
        print(f"Response time: {response_time:.3f} seconds")
        print(f"Error: {e}")

if __name__ == "__main__":
    make_request()