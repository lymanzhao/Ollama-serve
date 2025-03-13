from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
import httpx
import json
import uuid
import logging
import copy
from datetime import datetime
import asyncio

from config import OLLAMA_API_BASE_URL, VALID_API_KEYS


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("ollama-proxy")

# 创建FastAPI应用
app = FastAPI(title="Ollama API代理")



# 信任的客户端IP地址和会话（临时存储，无需认证的客户端）
TRUSTED_CLIENTS = {}  # 存储格式: {ip: {"expiry": timestamp, "user": user}}



# 智能处理请求体日志的函数
def format_body_for_log(body_obj):
    if not isinstance(body_obj, dict):
        return str(body_obj)
    
    # 创建深拷贝以避免修改原始对象
    log_body = copy.deepcopy(body_obj)
    
    # 智能处理messages数组
    if "messages" in log_body and isinstance(log_body["messages"], list):
        for msg in log_body["messages"]:
            if isinstance(msg, dict) and "content" in msg and isinstance(msg["content"], str):
                content = msg["content"]
                if len(content) > 100:  # 仅截断较长的content
                    msg["content"] = content[:50] + "..." + content[-20:]
    
    # 将处理后的对象转为格式化的JSON字符串
    return json.dumps(log_body, ensure_ascii=False, indent=2)

# 新增: 身份验证端点专门用于LangChain等客户端
@app.post("/auth")
async def authenticate(request: Request):
    request_id = str(uuid.uuid4())[:8]
    logger.info(f"[{request_id}] 收到身份验证请求")
    
    # 获取请求体
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    # 获取API密钥
    api_key = body.get("api_key") or request.headers.get("x-api-key") or request.headers.get("authorization")
    
    if api_key and api_key.startswith("Bearer "):
        api_key = api_key[7:]
    
    if not api_key:
        return Response(
            content=json.dumps({"error": "未提供API密钥"}),
            status_code=401,
            media_type="application/json"
        )
    
    if api_key not in VALID_API_KEYS:
        return Response(
            content=json.dumps({"error": "API密钥无效"}),
            status_code=403,
            media_type="application/json"
        )
    
    # 验证成功，将客户端IP添加到信任列表
    client_ip = request.client.host
    user = VALID_API_KEYS[api_key]
    
    # 设置信任状态，有效期1小时
    expiry = datetime.now().timestamp() + 3600
    TRUSTED_CLIENTS[client_ip] = {"expiry": expiry, "user": user}
    
    logger.info(f"[{request_id}] 客户端 {client_ip} 验证成功，用户: {user}")
    
    return {
        "status": "success",
        "message": "认证成功",
        "user": user,
        "expires_in": 3600  # 1小时
    }

# 代理所有Ollama API请求
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_ollama(path: str, request: Request):
    # 为每个请求分配唯一ID
    request_id = str(uuid.uuid4())[:8]
    start_time = datetime.now()
    
    logger.info(f"[{request_id}] 开始处理请求: {request.method} {path}")
    
    # 获取原始请求体
    body_bytes = await request.body()
    modified_body = body_bytes
    
    # 记录原始请求信息
    headers_log = {k: v for k, v in request.headers.items() 
                  if k.lower() not in ('authorization', 'x-api-key')}
    logger.info(f"[{request_id}] 请求头: {headers_log}")
    
    # 检查是否是来自LangChain的请求
    user_agent = request.headers.get("user-agent", "")
    is_langchain = "langchain" in user_agent.lower()
    client_ip = request.client.host
    
    if is_langchain:
        logger.info(f"[{request_id}] 检测到来自LangChain的请求")
    
    # 解析请求体（如果是JSON）
    body_obj = None
    if request.headers.get("content-type") == "application/json":
        try:
            body_obj = json.loads(body_bytes)
            
            # 使用智能格式化函数记录请求体
            formatted_body = format_body_for_log(body_obj)
            logger.info(f"[{request_id}] JSON请求体:\n{formatted_body}")
        except Exception as e:
            logger.error(f"[{request_id}] 解析JSON时出错: {str(e)}")
    
    # 检查IP是否在信任列表中（用于LangChain等客户端）
    if client_ip in TRUSTED_CLIENTS:
        client_info = TRUSTED_CLIENTS[client_ip]
        current_time = datetime.now().timestamp()
        
        if current_time <= client_info["expiry"]:
            user = client_info["user"]
            logger.info(f"[{request_id}] 客户端IP {client_ip} 已通过预认证，用户: {user}")
            
            # 更新过期时间（每次请求延长会话）
            TRUSTED_CLIENTS[client_ip]["expiry"] = current_time + 3600
            
            # 构建完整URL
            url = f"{OLLAMA_API_BASE_URL}/{path}"
            
            # 获取请求头，但移除一些不需要转发的头
            headers = dict(request.headers)
            headers.pop("host", None)
            headers.pop("connection", None)
            
            # 移除所有可能包含API密钥的头
            for key in list(headers.keys()):
                if key.lower() in ["x-api-key", "authorization"]:
                    headers.pop(key, None)
            
            # 设置代理标识
            headers["X-Proxy-By"] = "OllamaAPIProxy"
            headers["X-Proxy-User"] = user
            headers["X-Proxy-Request-ID"] = request_id
            
            # 直接转发请求
            return await forward_request(request_id, request.method, url, headers, modified_body, body_obj, start_time)
    
    # 从多个来源尝试获取API密钥
    api_key = None
    api_key_source = None
    
    # 1. 从请求头获取
    if not api_key:
        for header in ['x-api-key', 'X-API-Key']:
            if header in request.headers:
                api_key = request.headers[header]
                api_key_source = f"请求头({header})"
                break
    
    # 从Authorization头获取API密钥
    if not api_key:
        for header in ['authorization', 'Authorization']:
            if header in request.headers:
                auth_value = request.headers[header]
                # 不管有没有Bearer前缀，都尝试提取API密钥
                if auth_value.startswith("Bearer "):
                    api_key = auth_value[7:]
                else:
                    # 没有Bearer前缀时，使用整个值作为API密钥
                    api_key = auth_value
                
                api_key_source = f"Authorization头"
                logger.info(f"[{request_id}] 尝试从Authorization头获取API密钥: {auth_value[:4]}***")
                break
    
    # 3. 从查询参数获取
    if not api_key and "api_key" in request.query_params:
        api_key = request.query_params["api_key"]
        api_key_source = "URL查询参数"
    
    # 4. 从请求体JSON获取
    if not api_key and isinstance(body_obj, dict) and "api_key" in body_obj:
        api_key = body_obj["api_key"]
        api_key_source = "JSON请求体"
        
        # 从请求体中移除API密钥
        body_copy = body_obj.copy()
        body_copy.pop("api_key")
        # 更新请求体
        modified_body = json.dumps(body_copy).encode()
    
    # 验证API密钥
    if not api_key:
        # 特殊处理LangChain客户端，给出友好提示
        if is_langchain:
            logger.warning(f"[{request_id}] 来自LangChain的请求未提供API密钥")
            return Response(
                content=json.dumps({
                    "error": "未提供API密钥。LangChain客户端请先调用/auth端点进行认证。"
                }),
                status_code=401,
                media_type="application/json"
            )
        else:
            logger.warning(f"[{request_id}] 未找到API密钥，请求被拒绝")
            return Response(
                content=json.dumps({"error": "未提供API密钥"}),
                status_code=401,
                media_type="application/json"
            )
    
    # 屏蔽日志中的完整API密钥
    masked_key = api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:] if len(api_key) > 8 else "****"
    logger.info(f"[{request_id}] 从{api_key_source}获取API密钥: {masked_key}")
    
    if api_key not in VALID_API_KEYS:
        logger.warning(f"[{request_id}] 无效的API密钥: {masked_key}")
        return Response(
            content=json.dumps({"error": "API密钥无效"}),
            status_code=403,
            media_type="application/json"
        )
    
    user = VALID_API_KEYS[api_key]
    logger.info(f"[{request_id}] 验证通过，用户: {user}")
    
    # 如果是有效的API密钥，也将该IP加入信任列表（便于后续请求）
    if is_langchain or request.headers.get("user-agent", "").startswith("ollama-python"):
        expiry = datetime.now().timestamp() + 3600  # 1小时
        TRUSTED_CLIENTS[client_ip] = {"expiry": expiry, "user": user}
        logger.info(f"[{request_id}] 将客户端IP {client_ip} 添加到信任列表")
    
    # 构建完整URL
    url = f"{OLLAMA_API_BASE_URL}/{path}"
    
    # 获取请求头，但移除一些不需要转发的头
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("connection", None)
    
    # 移除所有可能包含API密钥的头
    for key in list(headers.keys()):
        if key.lower() in ["x-api-key", "authorization"]:
            headers.pop(key, None)
    
    # 设置代理标识
    headers["X-Proxy-By"] = "OllamaAPIProxy"
    headers["X-Proxy-User"] = user
    headers["X-Proxy-Request-ID"] = request_id
    
    logger.info(f"[{request_id}] 转发请求: {request.method} {url}")
    
    return await forward_request(request_id, request.method, url, headers, modified_body, body_obj, start_time)

async def forward_request(request_id, method, url, headers, body, body_obj, start_time):
    # 检查是否是流式请求
    is_stream_request = False
    if isinstance(body_obj, dict) and body_obj.get("stream") is True:
        is_stream_request = True
        logger.info(f"[{request_id}] 检测到流式请求")
    
    if is_stream_request:
        # 对于流式请求，使用流式响应处理
        async def stream_response():
            start_stream_time = datetime.now()
            try:
                # 在生成器内部创建客户端，确保在整个流式过程中客户端保持活动状态
                async with httpx.AsyncClient() as client:
                    async with client.stream(
                        method=method,
                        url=url,
                        headers=headers,
                        content=body,
                        timeout=600.0
                    ) as response:
                        # 首先验证响应状态
                        if response.status_code != 200:
                            # 如果响应非200，返回错误信息
                            error_content = await response.read()
                            yield error_content
                            logger.error(f"[{request_id}] Ollama流式响应错误: {response.status_code}")
                            return
                        
                        # 逐块转发响应
                        async for chunk in response.aiter_bytes():
                            yield chunk
            
            except Exception as e:
                logger.error(f"[{request_id}] 流式处理错误: {str(e)}")
                yield json.dumps({"error": f"流式处理错误: {str(e)}"}).encode()
            
            finally:
                # 计算流式处理总时间
                stream_duration = (datetime.now() - start_stream_time).total_seconds()
                logger.info(f"[{request_id}] 流式响应完成 (耗时: {stream_duration:.2f}秒)")
        
        # 创建流式响应对象
        # 保持原始内容类型，通常是application/json
        content_type = "application/json"
        if "content-type" in headers:
            content_type = headers["content-type"]
        
        resp_headers = {
            "X-Proxy-Request-ID": request_id,
            "Content-Type": content_type
        }
        
        return StreamingResponse(
            stream_response(),
            headers=resp_headers
        )
    else:
        # 非流式请求处理
        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    content=body,
                    timeout=600.0
                )
                
                # 计算请求处理时间
                duration = (datetime.now() - start_time).total_seconds()
                
                # 记录响应信息
                logger.info(f"[{request_id}] Ollama响应状态码: {response.status_code} (耗时: {duration:.2f}秒)")
                
                # 构造响应
                resp_headers = dict(response.headers)
                resp_headers["X-Proxy-Request-ID"] = request_id
                resp_headers["X-Proxy-Time"] = f"{duration:.2f}s"
                
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=resp_headers,
                )
        except httpx.TimeoutException:
            logger.error(f"[{request_id}] 请求超时 (已等待{(datetime.now() - start_time).total_seconds():.2f}秒)")
            return Response(
                content=json.dumps({"error": "请求Ollama服务器超时"}),
                status_code=504,
                media_type="application/json"
            )
        except Exception as e:
            logger.error(f"[{request_id}] 代理请求失败: {str(e)}")
            return Response(
                content=json.dumps({"error": f"代理请求失败: {str(e)}"}),
                status_code=500,
                media_type="application/json"
            )

# 添加健康检查端点
@app.get("/health")
async def health_check():
    request_id = str(uuid.uuid4())[:8]
    logger.info(f"[{request_id}] 健康检查")
    
    # 检查Ollama服务是否在线
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{OLLAMA_API_BASE_URL}/api/tags", timeout=5.0)
            if response.status_code == 200:
                return {
                    "status": "ok",
                    "message": "Ollama代理服务器和Ollama服务都正常运行",
                    "ollama_status": "online",
                    "request_id": request_id
                }
            else:
                return {
                    "status": "warning",
                    "message": f"Ollama代理服务器正常，但Ollama服务返回了异常状态码: {response.status_code}",
                    "ollama_status": "warning",
                    "request_id": request_id
                }
    except Exception as e:
        return {
            "status": "warning",
            "message": f"Ollama代理服务器正常，但无法连接到Ollama服务: {str(e)}",
            "ollama_status": "offline",
            "request_id": request_id
        }

@app.get("/")
async def root():
    return {
        "name": "Ollama API代理",
        "version": "1.0.0",
        "description": "Ollama API的身份验证代理",
        "endpoints": {
            "/": "API信息",
            "/health": "健康检查",
            "/auth": "LangChain客户端专用身份验证端点",
            "/{path}": "代理所有Ollama API请求，需要API密钥"
        }
    }

if __name__ == "__main__":
    import uvicorn
    logger.info(f"启动Ollama代理服务器在端口8401，转发到{OLLAMA_API_BASE_URL}")
    logger.info(f"有效的API密钥数量: {len(VALID_API_KEYS)}")
    uvicorn.run(app, host="0.0.0.0", port=8000)