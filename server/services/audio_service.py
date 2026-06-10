import os
import asyncio
import aiohttp
import base64
import subprocess
import tempfile
from dotenv import load_dotenv

load_dotenv()

class AudioService:
    """语音服务 — 使用 Doubao-Seed 多模态原生音频能力"""

    def __init__(self):
        self.api_key = os.getenv("DOUBAO_API_KEY")
        self.base_url = os.getenv("DOUBAO_API_BASE", "https://ark.cn-beijing.volces.com/api/v3/")
        self.model = os.getenv("DOUBAO_MODEL", "ep-20260514111645-lmgt2")
        self.max_retries = 2
        self.retry_delay = 3

    def _convert_to_mp3(self, audio_data: bytes, source_ext: str) -> bytes:
        """
        使用 ffmpeg 将音频转为 mp3 格式
        豆包 input_audio 需要标准的 mp3 格式
        """
        try:
            with tempfile.NamedTemporaryFile(suffix=f".{source_ext}", delete=False) as infile:
                infile.write(audio_data)
                input_path = infile.name

            output_path = input_path + ".mp3"

            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-acodec", "libmp3lame", "-ab", "64k",
                "-ar", "16000", "-ac", "1",
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

            if result.returncode != 0:
                print(f"ffmpeg 转换失败: {result.stderr[:200]}")
                os.unlink(input_path)
                return audio_data

            with open(output_path, "rb") as f:
                mp3_data = f.read()

            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)

            print(f"音频转换: {len(audio_data)} bytes → {len(mp3_data)} bytes (mp3)")
            return mp3_data

        except FileNotFoundError:
            print("⚠️ ffmpeg 未安装，使用原始音频格式（可能不被豆包接受）")
            return audio_data
        except Exception as e:
            print(f"音频转换异常: {e}")
            return audio_data

    async def speech_to_text(self, audio_data: bytes, format: str = "wav") -> str:
        """
        语音转文字 — 使用 Doubao-Seed 多模态音频输入
        将音频转为 mp3 后作为 input_audio 发送给 chat/completions
        """
        url = f"{self.base_url}chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        source_ext = format.lower() if format else "m4a"
        converted_audio = await asyncio.to_thread(
            self._convert_to_mp3, audio_data, source_ext
        )

        audio_base64 = base64.b64encode(converted_audio).decode('utf-8')

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_base64,
                                "format": "mp3"
                            }
                        },
                        {
                            "type": "text",
                            "text": "请将这段语音内容转写为中文文字，只输出转写结果，不要加任何解释"
                        }
                    ]
                }
            ],
            "max_tokens": 500
        }

        for attempt in range(self.max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, headers=headers, json=payload) as response:
                        if response.status != 200:
                            error_body = await response.text()
                            print(f"ASR HTTP {response.status}: {error_body[:300]}")
                            if attempt < self.max_retries - 1:
                                await asyncio.sleep(self.retry_delay)
                                continue
                            return f"[ERROR] 语音识别服务返回错误 {response.status}"

                        data = await response.json()
                        content = data["choices"][0]["message"]["content"].strip()
                        return content

            except asyncio.TimeoutError:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                else:
                    return "[ERROR] 语音识别超时，请重试"
            except Exception as e:
                print(f"ASR异常: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                else:
                    return f"[ERROR] 语音识别失败: {str(e)}"

        return "[ERROR] 语音识别失败"

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
        
        # 根据 voice 参数选择不同的音色提示
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