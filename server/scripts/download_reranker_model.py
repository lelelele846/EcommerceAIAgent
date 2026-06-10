"""
下载 Reranker 模型到本地 HuggingFace 缓存。

用法：
    python download_reranker_model.py

首次运行从 HuggingFace 下载，之后 `local_files_only=True` 直接加载。
支持 HF 镜像和官方源自动 fallback。
"""
import os
import sys
import subprocess


# 可选的模型（按大小排列）
MODELS = {
    "base": "BAAI/bge-reranker-base",       # ~278MB，速度快
    "v2-m3": "BAAI/bge-reranker-v2-m3",     # ~1.2GB，多语言，当前默认
}

# 下载端点优先级
ENDPOINTS = [
    "https://huggingface.co",           # 官方（需科学上网）
    "https://hf-mirror.com",            # 国内镜像（可能不稳定）
]


def try_download(model_name: str, endpoint: str) -> bool:
    """尝试从指定 endpoint 下载模型"""
    env = os.environ.copy()
    env["HF_ENDPOINT"] = endpoint

    print(f"\n{'='*60}")
    print(f"下载模型: {model_name}")
    print(f"HF_ENDPOINT: {endpoint}")
    print(f"{'='*60}")

    code = (
        f"from sentence_transformers import CrossEncoder; "
        f"model = CrossEncoder('{model_name}'); "
        f"print(f'下载完成: {{model}}')"
    )

    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            timeout=600,  # 10 分钟超时
            capture_output=True,
            text=True,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"STDERR: {result.stderr[-500:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("下载超时（>10分钟）")
        return False
    except Exception as e:
        print(f"下载异常: {e}")
        return False


def main():
    model_name = os.getenv("RERANKER_MODEL", MODELS["base"])

    # 如果命令行传了参数，按 key 查找
    if len(sys.argv) > 1:
        key = sys.argv[1]
        model_name = MODELS.get(key, key)

    print(f"目标模型: {model_name}")

    for endpoint in ENDPOINTS:
        if try_download(model_name, endpoint):
            print(f"\n[OK] 模型已下载到本地缓存")
            print(f"     设置环境变量 RERANKER_MODEL={model_name} 后重启 server 即可")
            return 0

    print(f"\n[FAIL] 所有端点均下载失败")
    print(f"       请检查网络连接，或手动将模型文件放到:")
    print(f"       ~/.cache/huggingface/hub/models--{model_name.replace('/', '--')}/")
    return 1


if __name__ == "__main__":
    sys.exit(main())
