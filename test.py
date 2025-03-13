from langchain_ollama import ChatOllama
from langchain.schema import HumanMessage, SystemMessage
import requests
import sys

# 首先进行认证
def authenticate():
    api_key = "api-20250312000101"
    auth_url = "http://127.0.0.1:8000/auth"
    
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
def setup_qwen_model():
    # 简化配置，删除多余的认证信息
    chat_model = ChatOllama(
        base_url="http://127.0.0.1:8000",
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
    chat_model = setup_qwen_model()
    
    # 发送消息
    messages = [
        SystemMessage(content="你是一个有用的AI助手。"),
        HumanMessage(content="请介绍一下自己")
    ]
    
    print("发送消息中...\n")
    print("AI助手回复:\n", end="")
    
    # 使用stream()方法而不是invoke()来获取流式响应
    full_response = ""
    for chunk in chat_model.stream(messages):
        chunk_text = chunk.content
        full_response += chunk_text
        print(chunk_text, end="", flush=True)  # 实时打印每个文本块
    
    print("\n\n完整回复已保存")
    
    # 如果需要，可以在这里使用完整回复做进一步处理
    # print(f"完整回复:\n{full_response}")

if __name__ == "__main__":
    main()