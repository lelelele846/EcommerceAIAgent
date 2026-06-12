"""
语音合成服务 — 将文字转换为自然语音输出。

实现方式：
    - 调用 Doubao-Seed 多模态语音合成能力
    - 支持三种音色选择：温柔女性、沉稳男性、可爱儿童
    - 自动处理重试逻辑（最多2次，间隔3秒）
    - 支持两种响应格式：直接二进制音频或 base64 编码

应用场景：
    - AI 回复自动朗读，打造语音导购体验
    - 商品描述语音播报，方便视障用户
"""
import os
import asyncio
import aiohttp
import base64
from dotenv import load_dotenv

load_dotenv()

class AudioService:
    """语音合成服务 — 将文字转换为自然语音输出"""

    def __init__(self):
        self.api_key = os.getenv("DOUBAO_API_KEY")
        self.base_url = os.getenv("DOUBAO_API_BASE", "https://ark.cn-beijing.volces.com/api/v3/")
        self.model = os.getenv("DOUBAO_MODEL", "ep-20260514111645-lmgt2")
        self.max_retries = 2
        self.retry_delay = 3

    async def text_to_speech(self, text: str, voice: str = "female") -> bytes:
        """
        TTS 语音合成 — 使用 Doubao-Seed 多模态语音合成能力
        
        参数:
            text: 要合成的文本
            voice: 声音类型 (female/male/child)
        
        返回:
            MP3 音频数据（bytes）
        """
        url = f"{self.base_url}chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        voice_prompt = {
            "female": "温柔女性声音",
            "male": "沉稳男性声音",
            "child": "可爱儿童声音"
        }.get(voice, "温柔女性声音")
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"请用{voice_prompt}将以下文本合成语音，只返回音频数据，不要加任何解释：\n{text}"
                        }
                    ]
                }
            ],
            "max_tokens": 1024,
            "response_format": "audio"
        }
        
        for attempt in range(self.max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=60)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, headers=headers, json=payload) as response:
                        if response.status != 200:
                            error_body = await response.text()
                            print(f"TTS HTTP {response.status}: {error_body[:300]}")
                            if attempt < self.max_retries - 1:
                                await asyncio.sleep(self.retry_delay)
                                continue
                            return b""
                        
                        # 检查响应类型
                        content_type = response.headers.get("Content-Type", "")
                        if content_type.startswith("audio/"):
                            # 直接返回二进制音频数据
                            audio_data = await response.read()
                            return audio_data
                        else:
                            # 尝试解析 JSON 响应（某些模型可能返回 base64 编码的音频）
                            data = await response.json()
                            if "audio" in data:
                                audio_base64 = data["audio"]
                                return base64.b64decode(audio_base64)
                            elif "choices" in data and len(data["choices"]) > 0:
                                content = data["choices"][0]["message"].get("content", "")
                                if content:
                                    # 尝试解析 base64 音频
                                    try:
                                        return base64.b64decode(content)
                                    except:
                                        print(f"TTS 返回非音频内容: {content[:100]}")
                        
                        print("TTS 响应不包含有效音频数据")
                        return b""
                        
            except asyncio.TimeoutError:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                else:
                    return b""
            except Exception as e:
                print(f"TTS异常: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                else:
                    return b""
        
        return b""