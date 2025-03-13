# Ollama API Proxy User Guide

## Introduction
Ollama lacks API key security authentication, which is a serious issue, but we don't want to build a complex HTTP server just for simple Ollama usage. Therefore, I've written a lightweight forwarding server using FastAPI. This is a very lightweight application, and if you need SQL database integration, you can also modify the configuration file to incorporate Python ORM frameworks like peewee to directly use database tables.

Ollama-serve as API Proxy is a lightweight middleware designed to add API key authentication functionality to the native Ollama service. This project addresses the issue that Ollama's official implementation does not provide API key verification, allowing you to deploy Ollama services more securely and prevent unauthorized access.

## Problems Solved

1. **Lack of Security**: Ollama's official service does not provide an API key authentication mechanism, allowing anyone who knows the API endpoint to access your Ollama service.
2. **Multi-user Support**: Cannot differentiate access and usage between different users.
3. **Access Control**: No way to restrict who can access your Ollama service.

## Core Features

1. **API Key Authentication**: All requests require a valid API key to access the Ollama service.
2. **Multi-user Support**: Supports multiple API keys, each associated with a specific user.
3. **Session Management**: Uses an IP-based trust system to reduce the need for repeated authentication.
4. **Client Integration**: Provides a friendly authentication mechanism specifically for clients.
5. **Logging**: Detailed logging of all requests and responses for monitoring and troubleshooting.
6. **Streaming Response Support**: Fully supports Ollama's streaming response functionality.
7. **Health Check**: Provides health check endpoints to monitor the status of both the proxy service and the backend Ollama service.

## Installation and Configuration

### 1. Requirements

- Python 3.8+
- Ollama service installed and running

### 2. Install Dependencies

```bash
pip install fastapi uvicorn httpx
```

### 3. Configuration File

Create a `config.py` file and set your API keys and Ollama API address:

```python
# Set API keys
VALID_API_KEYS = {
    "api-20250312000101": "user1",
    "api-20250312000202": "user2",
}

# Ollama API address
OLLAMA_API_BASE_URL = "http://localhost:11434"
```

### 4. Start the Service

```bash
python "ollama serve.py"
```

By default, the service will run on http://localhost:8000 and forward requests to `OLLAMA_API_BASE_URL`.

## Usage

### 1. Direct API Key Usage

You can provide the API key in several ways:

- **Request Header**: `X-API-Key: your-api-key`
- **Authorization Header**: `Authorization: Bearer your-api-key` or `Authorization: your-api-key`
- **URL Query Parameter**: `?api_key=your-api-key`
- **Request Body**: Include `"api_key": "your-api-key"` in the JSON request body

Example (using curl):

```bash
curl -X POST "http://localhost:8000/api/chat" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: api-20250312000101" \
  -d '{"model": "qwen2.5:72b", "messages": [{"role": "user", "content": "Hello"}], "stream": true}'
```

### 2. Using Client（LangChain）

Clients need to call the `/auth` endpoint first for authentication, then send normal requests:

```python
from langchain_ollama import ChatOllama
from langchain.schema import HumanMessage, SystemMessage
import requests

# First authenticate
def authenticate():
    api_key = "api-20250312000101"
    auth_url = "http://localhost:8000/auth"
    
    response = requests.post(
        auth_url,
        json={"api_key": api_key},
        headers={"Content-Type": "application/json"}
    )
    
    if response.status_code == 200:
        print("Authentication successful:", response.json())
        return True
    else:
        print(f"Authentication failed: {response.status_code}", response.text)
        return False

# Set up ChatOllama model
def setup_model():
    chat_model = ChatOllama(
        base_url="http://localhost:8000",
        model="qwen2.5:72b",
        max_retries=3,
        streaming=True,
    )
    return chat_model

# Main program
def main():
    # Authenticate first
    if not authenticate():
        print("Authentication failed, cannot continue.")
        return
    
    # Set up model
    chat_model = setup_model()
    
    # Send messages
    messages = [
        SystemMessage(content="You are a helpful AI assistant."),
        HumanMessage(content="Please introduce yourself")
    ]
    
    # Use streaming response
    for chunk in chat_model.stream(messages):
        print(chunk.content, end="", flush=True)

if __name__ == "__main__":
    main()
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Returns API information |
| `/auth` | POST | Authentication endpoint specifically for clients |
| `/health` | GET | Health check endpoint |
| `/{path}` | * | Proxies all Ollama API requests, requires API key |

## Security Considerations

1. **API Key Management**: Keep your API keys secure and rotate them regularly for enhanced security.
2. **Network Security**: Consider restricting access to the proxy service through firewalls or other network protection measures.
3. **HTTPS**: In production environments, it's recommended to use HTTPS to encrypt communications.

## Logging

The proxy service logs all requests and responses in detail, with the following format:

```
2025-03-13 10:15:23 - INFO - [a1b2c3d4] Processing request: POST api/chat
2025-03-13 10:15:23 - INFO - [a1b2c3d4] Request headers: {'content-type': 'application/json', 'user-agent': 'langchain'}
2025-03-13 10:15:23 - INFO - [a1b2c3d4] API key from request header(x-api-key): api-****0101
2025-03-13 10:15:23 - INFO - [a1b2c3d4] Authentication passed, user: user1
2025-03-13 10:15:23 - INFO - [a1b2c3d4] Forwarding request: POST http://localhost:11434/api/chat
2025-03-13 10:15:25 - INFO - [a1b2c3d4] Ollama response status: 200 (duration: 2.15s)
```

## Common Issues

1. **Issue**: Authentication fails with "Invalid API key"
   **Solution**: Check that your API key is correct and that it has been added to the `VALID_API_KEYS` dictionary in `config.py`.

2. **Issue**: Cannot connect to Ollama service
   **Solution**: Ensure the Ollama service is running and verify that the `OLLAMA_API_BASE_URL` setting in `config.py` is correct.

3. **Issue**: client cannot connect
   **Solution**: Make sure to call the `/auth` endpoint for authentication first, then use the client to send requests.

## Summary

Ollama API Proxy adds necessary API key authentication functionality to the native Ollama service, allowing you to securely deploy and share your Ollama service. With simple configuration and deployment, you can easily manage access permissions for different users and get more detailed request logging.
