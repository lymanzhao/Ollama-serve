# Ollama API 代理使用说明文档

## 项目简介

Ollama 缺少api-key安全认证，这是一个很严重的问题，但我们又不想为了简单使用Ollama搭建一个非常复杂的http服务器，所以我用Fastapi写了一个简单的转发服务器，是非常轻量的应用，如果你需要sql数据库，也可以修改配置文件接入python ORM框架比如peewee等，直接用数据库表。

Ollama API 代理是一个轻量级中间件，用于为原生 Ollama 服务添加 API 密钥认证功能。该项目解决了 Ollama 官方不提供 API 密钥验证的问题，使您可以更安全地部署 Ollama 服务并防止未授权访问。

## 解决的问题

1. **安全性缺失**：Ollama 官方服务不提供 API 密钥认证机制，任何知道 API 端点的人都可以访问您的 Ollama 服务。
2. **多用户支持**：无法区分不同用户的访问和使用情况。
3. **访问控制**：无法限制谁可以访问您的 Ollama 服务。

## 核心功能

1. **API 密钥认证**：所有请求都需要有效的 API 密钥才能访问 Ollama 服务。
2. **多用户支持**：支持多个 API 密钥，每个密钥关联到特定用户。
3. **会话管理**：使用基于 IP 的信任系统，减少重复认证的需求。
4. **LangChain**： LangChain 进验证可使用。
5. **日志记录**：详细记录所有请求和响应，便于监控和排查问题。
6. **流式响应支持**：完全支持 Ollama 的流式响应功能。
7. **健康检查**：提供健康检查端点来监控代理服务和后端 Ollama 服务的状态。

## 安装和配置

### 1. 环境要求

- Python 3.8+
- 已安装并运行的 Ollama 服务

### 2. 安装依赖

```bash
pip install fastapi uvicorn httpx
```

### 3. 配置文件

创建 `config.py` 文件并设置您的 API 密钥和 Ollama API 地址：

```python
# 设置API密钥
VALID_API_KEYS = {
    "api-20250312000101": "user1",
    "api-20250312000202": "user2",
}

# Ollama API地址
OLLAMA_API_BASE_URL = "http://localhost:11434"
```

### 4. 启动服务

```bash
python "ollama serve.py"
```

默认情况下，服务将在 http://localhost:8000 上运行，并将请求转发到 `OLLAMA_API_BASE_URL`。

## 使用方法

### 1. 直接使用 API 密钥

您可以通过多种方式提供 API 密钥：

- **请求头**：`X-API-Key: your-api-key`
- **Authorization 头**：`Authorization: Bearer your-api-key` 或 `Authorization: your-api-key`
- **URL 查询参数**：`?api_key=your-api-key`
- **请求体**：在 JSON 请求体中包含 `"api_key": "your-api-key"`

示例（使用 curl）：

```bash
curl -X POST "http://localhost:8000/api/chat" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: api-20250312000101" \
  -d '{"model": "qwen2.5:72b", "messages": [{"role": "user", "content": "你好"}], "stream": true}'
```

### 2. 使用 LangChain 客户端

LangChain 客户端需要先调用 `/auth` 端点进行认证，然后再发送正常请求：

```python
from langchain_ollama import ChatOllama
from langchain.schema import HumanMessage, SystemMessage
import requests

# 首先进行认证
def authenticate():
    api_key = "api-20250312000101"
    auth_url = "http://localhost:8000/auth"
    
    response = requests.post(
        auth_url,
        json={"api_key": api_key},
        headers={"Content-Type": "application/json"}
    )
    
    if response.status_code == 200:
        print("认证成功:", response.json())
        return True
    else:
        print(f"认证失败: {response.status_code}", response.text)
        return False

# 设置ChatOllama模型
def setup_model():
    chat_model = ChatOllama(
        base_url="http://localhost:8000",
        model="qwen2.5:72b",
        max_retries=3,
        streaming=True,
    )
    return chat_model

# 主程序
def main():
    # 先认证
    if not authenticate():
        print("认证失败，无法继续。")
        return
    
    # 设置模型
    chat_model = setup_model()
    
    # 发送消息
    messages = [
        SystemMessage(content="你是一个有用的AI助手。"),
        HumanMessage(content="请介绍一下自己")
    ]
    
    # 使用流式响应
    for chunk in chat_model.stream(messages):
        print(chunk.content, end="", flush=True)

if __name__ == "__main__":
    main()
```

## API 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/` | GET | 返回 API 信息 |
| `/auth` | POST | LangChain 客户端专用身份验证端点 |
| `/health` | GET | 健康检查端点 |
| `/{path}` | * | 代理所有 Ollama API 请求，需要 API 密钥 |

## 安全注意事项

1. **API 密钥管理**：请妥善保管您的 API 密钥，定期更换以提高安全性。
2. **网络安全**：考虑通过防火墙或其他网络防护措施限制对代理服务的访问。
3. **HTTPS**：在生产环境中，建议使用 HTTPS 加密通信。

## 日志记录

代理服务会详细记录所有请求和响应，日志格式如下：

```
2025-03-13 10:15:23 - INFO - [a1b2c3d4] 开始处理请求: POST api/chat
2025-03-13 10:15:23 - INFO - [a1b2c3d4] 请求头: {'content-type': 'application/json', 'user-agent': 'langchain'}
2025-03-13 10:15:23 - INFO - [a1b2c3d4] 从请求头(x-api-key)获取API密钥: api-****0101
2025-03-13 10:15:23 - INFO - [a1b2c3d4] 验证通过，用户: user1
2025-03-13 10:15:23 - INFO - [a1b2c3d4] 转发请求: POST http://localhost:11434/api/chat
2025-03-13 10:15:25 - INFO - [a1b2c3d4] Ollama响应状态码: 200 (耗时: 2.15秒)
```

## 常见问题

1. **问题**：认证失败，提示"API密钥无效"
   **解决方案**：检查您的 API 密钥是否正确，并确认它已添加到 `config.py` 中的 `VALID_API_KEYS` 字典。

2. **问题**：无法连接到 Ollama 服务
   **解决方案**：确保 Ollama 服务正在运行，并检查 `config.py` 中的 `OLLAMA_API_BASE_URL` 设置是否正确。

3. **问题**：LangChain 客户端无法连接
   **解决方案**：确保先调用 `/auth` 端点进行认证，然后再使用 LangChain 客户端发送请求。

## 总结

Ollama API 代理为原生 Ollama 服务添加了必要的 API 密钥认证功能，使您可以安全地部署并共享您的 Ollama 服务。通过简单的配置和部署，您可以轻松管理不同用户的访问权限，并获得更详细的请求日志记录。
