import os
import asyncio
import aiohttp
import json
from dotenv import load_dotenv

load_dotenv()

class DoubaoService:
    def __init__(self):
        self.api_key = os.getenv("DOUBAO_API_KEY")
        self.base_url = os.getenv("DOUBAO_API_BASE", "https://ark.cn-beijing.volces.com/api/v3/")
        self.model = os.getenv("DOUBAO_MODEL", "ep-20260514111645-lmgt2")
        self.fast_model = os.getenv("DOUBAO_FAST_MODEL", "")
        self.max_retries = 3
        self.retry_delay = 5

    # ══════════════════════════════════════════════════════════════
    # 带对话历史的方法（核心：让 LLM 看到上下文）
    # ══════════════════════════════════════════════════════════════

    async def chat_with_history(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        use_fast_model: bool = False,
    ) -> str:
        """
        非流式调用 — 支持完整 multi-turn 对话历史。
        messages 格式: [{"role": "system", "content": "..."},
                       {"role": "user", "content": "..."},
                       {"role": "assistant", "content": "..."}, ...]
        """
        url = f"{self.base_url}chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        model = (self.fast_model if use_fast_model and self.fast_model else self.model)

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        for attempt in range(self.max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=120)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, headers=headers, json=payload) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            raise Exception(f"API request failed: {error_text}")
                        data = await response.json()
                        return data["choices"][0]["message"]["content"]
            except asyncio.TimeoutError:
                if attempt < self.max_retries - 1:
                    print(f"请求超时，正在重试 ({attempt + 1}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    raise Exception("请求超时，已达到最大重试次数")
            except Exception as e:
                if attempt < self.max_retries - 1:
                    print(f"请求失败: {str(e)}，正在重试 ({attempt + 1}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    raise

    async def stream_with_history(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ):
        """
        流式调用 — 支持完整 multi-turn 对话历史。
        messages 格式同上，yield 文本 token。
        """
        url = f"{self.base_url}chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        for attempt in range(self.max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=180)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, headers=headers, json=payload) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            if attempt < self.max_retries - 1:
                                print(f"流式请求失败: {error_text}，正在重试 ({attempt + 1}/{self.max_retries})...")
                                await asyncio.sleep(self.retry_delay * (attempt + 1))
                                continue
                            yield f"Error: {error_text}"
                            return

                        buffer = ""
                        async for line in response.content:
                            try:
                                text = line.decode('utf-8')
                                buffer += text
                                while '\n' in buffer:
                                    line_str, buffer = buffer.split('\n', 1)
                                    line_str = line_str.strip()
                                    if not line_str or not line_str.startswith('data: '):
                                        continue
                                    data_str = line_str[6:]
                                    if data_str.strip() == '[DONE]':
                                        return
                                    try:
                                        data = json.loads(data_str)
                                        if "choices" in data and len(data["choices"]) > 0:
                                            delta = data["choices"][0].get("delta", {})
                                            if "content" in delta:
                                                yield delta["content"]
                                    except json.JSONDecodeError:
                                        continue
                            except UnicodeDecodeError:
                                continue
                return
            except asyncio.TimeoutError:
                if attempt < self.max_retries - 1:
                    print(f"流式请求超时，正在重试 ({attempt + 1}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    yield "Error: 请求超时，已达到最大重试次数"
            except Exception as e:
                if attempt < self.max_retries - 1:
                    print(f"流式请求失败: {str(e)}，正在重试 ({attempt + 1}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    yield f"Error: {str(e)}"

    # ══════════════════════════════════════════════════════════════
    # 原有单条 prompt 方法（向后兼容）
    # ══════════════════════════════════════════════════════════════

    async def generate_response(self, prompt: str) -> str:
        url = f"{self.base_url}chat/completions"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.7,
            "max_tokens": 2048
        }
        
        for attempt in range(self.max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=120)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, headers=headers, json=payload) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            raise Exception(f"API request failed: {error_text}")
                        
                        data = await response.json()
                        return data["choices"][0]["message"]["content"]
            except asyncio.TimeoutError:
                if attempt < self.max_retries - 1:
                    print(f"请求超时，正在重试 ({attempt + 1}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    raise Exception("请求超时，已达到最大重试次数")
            except Exception as e:
                if attempt < self.max_retries - 1:
                    print(f"请求失败: {str(e)}，正在重试 ({attempt + 1}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    raise
    
    async def stream_response(self, prompt: str):
        url = f"{self.base_url}chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.3,   # 🔧 降低温度 0.7→0.3，让推荐类 prompt 更遵循指令
            "max_tokens": 2048,
            "stream": True
        }
        
        for attempt in range(self.max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=180)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, headers=headers, json=payload) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            if attempt < self.max_retries - 1:
                                print(f"流式请求失败: {error_text}，正在重试 ({attempt + 1}/{self.max_retries})...")
                                await asyncio.sleep(self.retry_delay * (attempt + 1))
                                continue
                            yield f"Error: {error_text}"
                            return
                        
                        # 使用 text mode 而不是 binary mode
                        buffer = ""
                        async for line in response.content:
                            try:
                                # 尝试解码
                                text = line.decode('utf-8')
                                buffer += text
                                
                                # 处理完整的数据行
                                while '\n' in buffer:
                                    line, buffer = buffer.split('\n', 1)
                                    line = line.strip()
                                    if not line or not line.startswith('data: '):
                                        continue
                                    
                                    data_str = line[6:]
                                    if data_str.strip() == '[DONE]':
                                        return
                                    
                                    try:
                                        data = json.loads(data_str)
                                        if "choices" in data and len(data["choices"]) > 0:
                                            delta = data["choices"][0].get("delta", {})
                                            if "content" in delta:
                                                yield delta["content"]
                                    except json.JSONDecodeError:
                                        continue
                            except UnicodeDecodeError:
                                # 忽略无法解码的部分
                                continue
                return
            except asyncio.TimeoutError:
                if attempt < self.max_retries - 1:
                    print(f"流式请求超时，正在重试 ({attempt + 1}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    yield "Error: 请求超时，已达到最大重试次数"
            except Exception as e:
                if attempt < self.max_retries - 1:
                    print(f"流式请求失败: {str(e)}，正在重试 ({attempt + 1}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    yield f"Error: {str(e)}"