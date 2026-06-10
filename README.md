# EcommerceAIAgent — 多模态电商智能导购 AI Agent

> 基于 RAG 的多模态电商智能导购 AI Agent，支持拍照找货、语音交互、智能推荐

---

## 目录

1. [项目简介](#1-项目简介)
2. [系统架构](#2-系统架构)
3. [技术栈](#3-技术栈)
4. [目录结构](#4-目录结构)
5. [配置说明](#5-配置说明)
6. [快速开始](#6-快速开始)
7. [使用说明](#7-使用说明)
8. [核心功能](#8-核心功能)
9. [开发说明](#9-开发说明)

---

## 1. 项目简介

EcommerceAIAgent 是一个面向电商场景的智能导购 AI Agent，将传统"展示型广告"升级为"交互型导购"。用户通过自然语言、拍照或语音与 Agent 对话，实现从浏览兴趣到购买决策的全链路深度连接。

**已实现能力：**

| 类别 | 能力 |
|------|------|
| 对话理解 | 多轮上下文管理、意图识别路由 |
| 检索 | 向量 + BM25 混合检索、RRF 融合 |
| 多模态 | 拍照找货、语音输入（ASR）、TTS 语音播报 |
| 购物闭环 | 对话式加购、购物车管理 |

---

## 2. 系统架构

### 2.1 整体分层

```
┌──────────────────────────────────────────┐
│          Android 客户端（Kotlin）          │
│  Jetpack Compose UI · MVVM · SSE 流式渲染  │
└───────────────────┬──────────────────────┘
                    │ HTTP / SSE（结构化事件流）
┌───────────────────▼──────────────────────┐
│              后端（Python FastAPI）        │
│                                          │
│  ┌─────────────────────────────────────┐ │
│  │          业务层                      │ │
│  │  Chat Router · Multimodal API       │ │
│  └─────────────────┬───────────────────┘ │
│  ┌─────────────────▼───────────────────┐ │
│  │          RAG 检索层                  │ │
│  │  混合检索（向量 + BM25）· RRF 融合   │ │
│  │  Query 扩展 · 同义词词典            │ │
│  └─────────────────┬───────────────────┘ │
│  ┌─────────────────▼───────────────────┐ │
│  │          模型层（豆包 API）           │ │
│  │  文本生成  Doubao-Seed-2.0-lite      │ │
│  │  向量化    Doubao-embedding-vision   │ │
│  └─────────────────┬───────────────────┘ │
│  ┌─────────────────▼───────────────────┐ │
│  │          存储层                      │ │
│  │  Chroma（向量库）· SQLite（关系库）  │ │
│  └─────────────────────────────────────┘ │
└──────────────────────────────────────────┘
```

---

## 3. 技术栈

### 后端

| 层次 | 技术选型 | 版本 |
|------|---------|------|
| Web 框架 | FastAPI + Uvicorn | 0.115.0+ |
| 大语言模型 | Doubao-Seed-2.0-lite（豆包 API） | — |
| Embedding | Doubao-embedding-vision（文本+图像） | — |
| 向量库 | Chroma | 0.5.18+ |
| 关系数据库 | SQLite | — |
| BM25 | rank-bm25 + jieba 中文分词 | — |
| 数据校验 | Pydantic v2 | 2.9.2+ |
| 异步 IO | httpx | — |

### 客户端（Android）

| 层次 | 技术选型 |
|------|---------|
| 语言 | Kotlin |
| UI 框架 | Jetpack Compose（Material 3） |
| 架构 | MVVM + Repository Pattern |
| 异步 | Kotlin Coroutines + StateFlow |
| 网络 | OkHttp（SSE 长连接 + REST） |
| 图片加载 | Coil Compose |
| 多模态 | Android CameraX / ActivityResult API / TextToSpeech |
| 序列化 | Gson |
| 最低 SDK | API 24（Android 7.0） |

---

## 4. 目录结构

```
EcommerceAIAgent/
├── server/                          # Python 后端
│   ├── main.py                      # FastAPI 应用入口
│   ├── requirements.txt             # 依赖清单
│   ├── routers/                     # API 路由
│   │   ├── chat.py                  # 会话、流式对话接口
│   │   └── multimodal.py            # 多模态接口（语音/图像）
│   ├── services/                    # 业务服务
│   │   ├── doubao_service.py        # 豆包 API 封装
│   │   ├── image_service.py         # 图像检索服务
│   │   └── audio_service.py         # 语音服务
│   ├── rag/                         # RAG 检索模块
│   │   ├── retriever.py             # 混合检索器
│   │   └── product_repo.py          # 商品仓库
│   ├── models/                      # 数据模型
│   │   └── events.py                # SSE 事件定义
│   └── data/                        # 商品数据
│
├── android/                         # Android 客户端
│   └── app/src/main/java/com/example/ecommerceaiagent/
│       ├── MainActivity.kt          # 应用入口
│       ├── ui/
│       │   ├── ChatScreen.kt        # 主对话页面
│       │   └── theme/               # Material 3 主题
│       ├── viewmodel/
│       │   └── ChatViewModel.kt     # 对话状态管理
│       ├── repository/
│       │   └── ChatRepository.kt    # 数据访问层
│       ├── model/                   # 数据模型
│       └── utils/
│           ├── ImageCompressor.kt   # 图片压缩工具
│           └── TtsManager.kt        # TTS 语音管理
└── README.md
```

---

## 5. 配置说明

### 5.1 环境变量配置

在 `server/` 目录下创建 `.env` 文件：

```env
# 豆包 API 配置（必填）
DOUBAO_API_KEY=your_api_key_here
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3/
DOUBAO_MODEL=your_model_endpoint
DOUBAO_EMBEDDING_MODEL=Doubao-embedding-vision

# 应用配置
ENVIRONMENT=development
PORT=8080
```

### 5.2 配置项说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DOUBAO_API_KEY` | 必填 | 豆包 API 密钥 |
| `DOUBAO_BASE_URL` | `https://ark.cn-beijing.volces.com/api/v3/` | 豆包 API 地址 |
| `DOUBAO_MODEL` | 必填 | 主模型 Endpoint ID |
| `DOUBAO_EMBEDDING_MODEL` | `Doubao-embedding-vision` | 向量化模型 |
| `ENVIRONMENT` | `development` | 运行环境 |
| `PORT` | `8080` | 服务端口 |

---

## 6. 快速开始

### 6.1 后端启动

```bash
# 进入后端目录
cd server

# 安装依赖
pip install -r requirements.txt

# 设置环境变量（Windows）
set DOUBAO_API_KEY=your_api_key

# 启动服务
python main.py
```

服务启动后监听 `http://localhost:8080`

### 6.2 客户端运行

1. 打开 Android Studio
2. 导入 `android/` 目录下的项目
3. 确保 Android SDK 已安装（API 24+）
4. 连接设备或启动模拟器
5. 点击 "Run" 按钮运行

> **注意**：客户端默认连接 `http://192.168.1.108:8080`，请根据实际后端地址修改 `ChatRepository.kt` 中的 `baseUrl`。

---

## 7. 使用说明

### 基础场景

**单轮模糊推荐：**
> 推荐一款适合油皮的洗面奶

**条件筛选：**
> 200 元以下的蓝牙耳机有哪些？

### 多模态场景

**拍照找货：**
> 点击相机图标，拍摄或上传商品图片，Agent 自动检索相似商品

**语音输入：**
> 点击麦克风图标，说出购物需求（系统键盘原生支持）

**语音播报：**
> AI 回复完成后自动朗读，可通过音量图标开关

---

## 8. 核心功能

### 8.1 多模态交互

**拍照找货流程：**
```
端侧拍照/相册选图
    → 等比缩放（800px 上限）+ JPEG 压缩（quality=80）
    → Base64 编码
    → 后端 Doubao-embedding-vision 图像向量化
    → 向量检索 product_images collection
    → 返回视觉相似商品
```

**语音输入（STT）：**
- 集成系统键盘语音输入
- Android 各主流机型原生支持，零额外依赖
- 语音转文字后进入与普通文字消息相同的处理链路

**TTS 语音播报：**
- 流式回复结束后自动朗读
- 去除 Markdown 符号避免噪音播报
- 记录上次播报内容防止重复朗读

### 8.2 混合检索

- **向量检索**：基于 Chroma 向量库，语义相似度匹配
- **BM25 检索**：关键词精确匹配，支持同义词扩展
- **RRF 融合**：将向量检索与 BM25 检索结果融合，提升召回率

### 8.3 对话管理

- **流式响应**：支持 SSE 实时推送，打字机效果
- **上下文维护**：多轮对话记忆，理解用户意图
- **意图识别**：支持加购、对比、推荐等多种意图

---

## 9. 开发说明

### 9.1 代码规范

- **后端**：遵循 PEP 8 规范，使用 `black` 格式化
- **前端**：遵循 Kotlin 官方编码规范

### 9.2 测试

```bash
# 后端测试
cd server
python -m pytest tests/

# 客户端测试
在 Android Studio 中运行单元测试
```

### 9.3 部署

**生产环境部署建议：**
1. 使用 Gunicorn + Uvicorn 部署后端
2. 配置 Nginx 反向代理
3. 使用 HTTPS 加密传输
4. 配置日志监控

---

## License

MIT License