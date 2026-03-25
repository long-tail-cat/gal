import requests
import json

def chat_with_qwen_stream():
    api_key = "sk-b2a8ffe0caba48569e44741b3afb7a7e"
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    
    # 初始化对话历史
    messages = [
        {"role": "system", "content": "你是一个充满个性的 AI 助手。"}
    ]
    
    print("--- 已开启流式对话模式 (Qwen-Plus) ---")
    print("输入 'quit' 退出\n")

    while True:
        user_input = input("User: ").strip()
        if user_input.lower() in ['quit', 'exit']:
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        payload = {
            "model": "qwen-plus",
            "messages": messages,
            "stream": True  # 核心：开启流式输出
        }
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        try:
            # 开启 stream=True
            response = requests.post(url, headers=headers, json=payload, stream=True)
            
            if response.status_code == 200:
                print("AI: ", end="", flush=True)
                full_reply = ""
                
                # 遍历处理返回的数据行
                for line in response.iter_lines():
                    if line:
                        # 移除 "data: " 前缀
                        line_data = line.decode('utf-8')
                        if line_data.startswith("data: "):
                            line_data = line_data[6:]
                        
                        # 检查是否结束
                        if line_data.strip() == "[DONE]":
                            break
                        
                        try:
                            chunk = json.loads(line_data)
                            # 提取增量内容
                            delta = chunk['choices'][0]['delta'].get('content', '')
                            if delta:
                                print(delta, end="", flush=True)
                                full_reply += delta
                        except json.JSONDecodeError:
                            continue
                
                print("\n") # 换行
                # 将完整的回复存入历史，维持上下文
                messages.append({"role": "assistant", "content": full_reply})
            else:
                print(f"\n请求失败: {response.status_code}")
                
        except Exception as e:
            print(f"\n发生错误: {e}")

if __name__ == "__main__":
    chat_with_qwen_stream()