# EcommerceAIAgent — 多模态电商智能导购 AI Agent

> 基于 RAG 的多模态电商智能导购 AI Agent，支持自然语言对话、拍照找货、语音交互、流式推荐

---

## 目录

1. [项目简介](#1-项目简介)
2. [系统架构](#2-系统架构)
3. [技术栈](#3-技术栈)
4. [目录结构](#4-目录结构)
5. [配置说明](#5-配置说明)
6. [快速开始](#6-快速开始)
7. [使用说明](#7-使用说明)
8. [核心实现](#8-核心实现)
9. [亮点与创新](#9-亮点与创新)

---

## 1. 项目简介

EcommerceAIAgent 是一个面向电商场景的智能导购 AI Agent，将传统"展示型广告"升级为"交互型导购"。用户通过自然语言、拍照或语音与 Agent 对话，实现从浏览兴趣到购买决策的全链路深度连接。

**已实现能力：**

| 类别 | 能力 |
|------|------|
| 对话理解 | 多轮上下文管理、主动反问澄清（Slot-filling）、意图识别路由、状态机驱动 |
| 检索 | 向量 + BM25 + 属性匹配三路混合检索、RRF 融合、Cross-Encoder 精排、HyDE 查询增强 |
| 复杂场景 | 否定语义反选、多商品对比、场景化组合推荐、跨类目检索、Query 分解 |
| 购物闭环 | 对话式加购、购物车管理、商品追问 |
| 多模态 | 拍照找货（VLM + 向量双路径）、语音输入（ASR）、TTS 语音播报 |
| 工程 | 检索结果缓存、设备级会话隔离、SQLite 持久化、流式 SSE 推送 |

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
│  │          编排层（Agent）             │ │
│  │  意图分类（规则快路由 + LLM 兜底）   │ │
│  │  状态机路由（3 状态转移表）          │ │
│  │  3 个子 Agent：                     │ │
│  │    search / compare / scene         │ │
│  └─────────────────┬───────────────────┘ │
│  ┌─────────────────▼───────────────────┐ │
│  │          能力层（RAG）               │ │
│  │  混合检索（向量 + BM25 + 属性匹配）  │ │
│  │  RRF 融合 → Cross-Encoder 精排      │ │
│  │  HyDE 查询增强 · Query 分解         │ │
│  │  Self-RAG 相关性校验                │ │
│  └─────────────────┬───────────────────┘ │
│  ┌─────────────────▼───────────────────┐ │
│  │          模型层（豆包 API）           │ │
│  │  文本生成  Doubao-Seed-2.0-lite      │ │
│  │  向量化    Doubao-embedding-vision   │ │
│  │  视觉理解  Doubao 多模态 VLM         │ │
│  │  语音      Doubao 语音识别/合成      │ │
│  └─────────────────┬───────────────────┘ │
│  ┌─────────────────▼───────────────────┐ │
│  │          存储层                      │ │
│  │  Chroma（向量库）· SQLite（关系库）  │ │
│  │  内存缓存（检索结果）                │ │
│  └─────────────────────────────────────┘ │
└──────────────────────────────────────────┘
```

### 2.2 一次对话的完整数据流

```
用户输入（文字 / 图片 / 语音）
    │
    ▼
意图分类 → 规则快路由（~3ms，覆盖 ~70% 查询）
    │         │ 规则无法判定 → LLM 兜底
    │         ▼
    ├── 状态机路由（BROWSING / COMPARING / SCENE_PLANNING）
    │
    ▼
子 Agent 构造检索 Query + 过滤条件
    │
    ▼
HybridRetriever: 向量检索 ‖ BM25 检索 ‖ 属性匹配 → RRF 融合 → Cross-Encoder 精排
    │
    ▼
LLM 注入商品资料 + System Prompt → 流式生成
    │
    ▼
SSE 事件流: thinking / text_delta / product_card / comparison_table /
            clarification / image_searching / done
    │
    ▼
Android 客户端逐事件渲染: 流式文字气泡 / 商品卡片 / 对比表格 / 反问选项
```

---

## 3. 技术栈

### 后端

| 层次 | 技术选型 | 版本 |
|------|---------|------|
| Web 框架 | FastAPI + Uvicorn | 0.110.0 / 0.28.0 |
| 大语言模型 | Doubao-Seed-2.0-lite（豆包 API，兼容 OpenAI SDK） | — |
| Embedding | Doubao-embedding-vision（文本 + 图像同空间 2048 维） | — |
| 本地 Embedding | all-MiniLM-L6-v2（SentenceTransformers，384 维） | 2.6.1 |
| 向量库 | Chroma | 0.4.24 |
| 关系数据库 | SQLite（WAL 模式，线程安全） | — |
| Reranker | BGE-Reranker-Base（Cross-Encoder，自动下载） | — |
| BM25 | rank-bm25 + jieba 中文分词 | ≥0.2.2 |
| 数据校验 | Pydantic v2 | 2.6.1 |
| 异步 IO | aiohttp / httpx | — |
| 重试机制 | tenacity（指数退避） | 8.2.3 |

### 客户端（Android）

| 层次 | 技术选型 |
|------|---------|
| 语言 | Kotlin |
| UI 框架 | Jetpack Compose（Material 3） |
| 架构 | MVVM + Repository Pattern |
| 异步 | Kotlin Coroutines + StateFlow |
| 网络 | OkHttp 4.11（SSE 长连接 + REST） |
| 图片加载 | Coil Compose 2.4.0 |
| 多模态 | Android CameraX / ActivityResult API / TextToSpeech |
| 序列化 | Gson 2.10.1 |
| 导航 | Compose 内嵌导航（单 Activity） |
| 最低 SDK | API 24（Android 7.0） |

---

## 4. 目录结构

```
EcommerceAIAgent/
├── server/                              # Python 后端
│   ├── main.py                          # FastAPI 应用入口 + 启动初始化
│   ├── requirements.txt                 # Python 依赖清单
│   ├── .env                             # 环境变量（API Key、模型配置）
│   │
│   ├── agent/                           # Agent 编排层
│   │   ├── __init__.py                  # Agent 初始化 + 依赖注入
│   │   ├── state_machine.py             # 3 状态转移表（BROWSING/COMPARING/SCENE_PLANNING）
│   │   ├── search_agent.py              # 单品搜索推荐 + Slot-filling 渐进反问
│   │   ├── compare_agent.py             # 多商品对比（识别→检索→提维度→组表）
│   │   └── scene_agent.py               # 场景化组合推荐（规划 + 主题导航）
│   │
│   ├── rag/                             # RAG 检索层
│   │   ├── retriever.py                 # 混合检索主入口：向量+BM25+属性 RRF 融合 + 精排 + 缓存
│   │   ├── chroma_client.py             # ChromaDB 共享客户端单例
│   │   ├── hyde.py                      # HyDE 查询增强（短查询生成假设文档）
│   │   ├── query_decomposer.py          # 复杂 Query 分解（含触发词检测）
│   │   ├── keyword_retriever.py         # 属性匹配检索（品牌/类目/标题加权打分）
│   │   ├── product_graph.py             # 商品关系图谱（同品牌/同品类/互补推荐）
│   │   ├── relevance_checker.py         # Self-RAG 相关性校验（LLM 逐商品评判）
│   │   ├── reranker.py                  # BGE Cross-Encoder 精排（自动下载，优雅降级）
│   │   └── prompt.py                    # Prompt 构建器（人设/记忆/偏好/情感/输出格式）
│   │
│   ├── services/                        # 业务服务层
│   │   ├── doubao_service.py            # 豆包 API 封装（流式/非流式/多轮/3次重试）
│   │   ├── session_manager.py           # 会话管理（内存 + DB 恢复，14 类偏好追踪）
│   │   ├── feedback_manager.py          # 用户反馈管理（评分/改进建议）
│   │   ├── audio_service.py             # 语音识别（ASR）+ 语音合成（TTS）
│   │   ├── image_service.py             # 图像分析 + 视觉检索（VLM + Embedding 双路径）
│   │   └── summary_generator.py         # 会话摘要生成（LLM + 规则兜底）
│   │
│   ├── routers/                         # API 路由层
│   │   ├── __init__.py                  # 路由导出
│   │   ├── chat.py                      # /api/chat + /api/chat/stream（SSE 流式对话）
│   │   ├── products.py                  # /api/products（商品查询）
│   │   ├── session.py                   # /api/session（会话 CRUD + 历史）
│   │   ├── feedback.py                  # /api/feedback（用户反馈）
│   │   └── multimodal.py                # 多模态接口（语音识别/合成、拍照找货、语音对话）
│   │
│   ├── models/                          # 数据模型
│   │   ├── schemas.py                   # Pydantic 模型（Product/ChatRequest/Session 等）
│   │   └── events.py                    # SSE 事件定义（11 种事件类型 + 工厂函数）
│   │
│   ├── db/                              # 数据库层
│   │   ├── __init__.py                  # DB 包标记
│   │   └── relational.py                # SQLite 持久化（sessions + messages 表）
│   │
│   ├── utils/                           # 工具模块
│   │   ├── __init__.py                  # 工具导出
│   │   ├── category_detector.py         # 关键词类目检测（10 大类目，支持跨类目）
│   │   ├── price_parser.py              # 价格范围自然语言解析
│   │   ├── product_repo.py              # 商品数据访问层（单例，100 件商品）
│   │   ├── product_card_parser.py       # 流式商品卡片解析（双检测：标记 + 标题匹配）
│   │   ├── position_resolver.py         # 位置指代消解（"第一个"/"这个"→商品 ID）
│   │   └── query_analyzer.py            # 查询分析（模糊度检测 + 偏好提取 + 品牌库）
│   │
│   ├── data/ecommerce_agent_dataset/    # 商品数据集
│   │   ├── 1_美妆护肤/                   # 25 件美妆护肤商品（JSON + 图片）
│   │   ├── 2_数码电子/                   # 25 件数码电子商品
│   │   ├── 3_服饰运动/                   # 25 件服饰运动商品
│   │   ├── 4_食品饮料/                   # 25 件食品饮料商品
│   │   └── all_products.json            # 聚合商品数据
│   │
│   ├── chroma_db/                       # ChromaDB 向量持久化目录
│   ├── eval/                            # 评估
│   │   └── test_queries.json            # 10 条测试查询（覆盖全部类目）
│   └── app.db                           # SQLite 数据库文件
│
├── android/                             # Android 客户端
│   └── app/src/main/java/com/example/ecommerceaiagent/
│       ├── MainActivity.kt              # 应用入口（EdgeToEdge + Compose + 崩溃防护）
│       ├── model/
│       │   ├── Product.kt               # 商品数据类
│       │   ├── ChatMessage.kt           # SSE 事件密封类（8 种消息类型）
│       │   └── MessageItem.kt           # UI 消息模型（含 ContentBlock 子类型）
│       ├── viewmodel/
│       │   └── ChatViewModel.kt         # 对话状态管理（StateFlow + 消息队列 + 打字特效）
│       ├── repository/
│       │   ├── ChatRepository.kt        # HTTP/SSE 网络层（事件解析 + 文件上传）
│       │   └── SseClient.kt             # OkHttp EventSource → Kotlin Flow 桥接
│       ├── ui/
│       │   ├── ChatScreen.kt            # 主对话页（流式渲染/商品卡片/反问选项/全屏图片）
│       │   └── components/
│       │       ├── ProductCard.kt        # 商品卡片组件
│       │       └── ComparisonCard.kt     # 对比表格组件
│       ├── theme/
│       │   ├── Color.kt                 # 色彩系统（Indigo 主色调）
│       │   └── Theme.kt                 # Material 3 主题 + 字体
│       └── utils/
│           ├── ImageCompressor.kt        # 图片压缩（800px + JPEG 80% + Base64）
│           └── TtsManager.kt             # TTS 语音播报管理
│
└── README.md
```

---

## 5. 配置说明

### 5.1 环境变量

在 `server/.env` 中配置，所有配置通过环境变量注入，**不需要改代码**。

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DOUBAO_API_KEY` | **必填** | 豆包文本模型 API 密钥 |
| `DOUBAO_API_BASE` | `https://ark.cn-beijing.volces.com/api/v3/` | 豆包 API 地址 |
| `DOUBAO_MODEL` | **必填** | 主模型 Endpoint ID（如 `ep-xxx-lmgt2`） |
| `DOUBAO_EMBEDDING_VISION_MODEL` | **必填** | 多模态 Embedding 模型 Endpoint ID |
| `DOUBAO_EMBEDDING_VISION_API_KEY` | **必填** | 多模态模型 API 密钥（可与文本模型不同） |
| `CHROMA_DB_PATH` | `./chroma_db` | ChromaDB 向量库持久化路径 |
| `SERVER_BASE_URL` | 自动检测 | 服务端公网地址（用于生成图片 URL） |
| `HF_ENDPOINT` | `https://hf-mirror.com` | HuggingFace 镜像（国内加速） |
| `HF_HUB_DISABLE_SYMLINKS` | `1` | 禁用 HF 符号链接（Windows 兼容） |

### 5.2 `.env` 示例

```env
DOUBAO_API_KEY=your_text_api_key
DOUBAO_API_BASE=https://ark.cn-beijing.volces.com/api/v3/
DOUBAO_MODEL=ep-20260514111645-lmgt2
DOUBAO_EMBEDDING_VISION_MODEL=ep-20260610152946-zwtkf
DOUBAO_EMBEDDING_VISION_API_KEY=your_vision_api_key
CHROMA_DB_PATH=./chroma_db
SERVER_BASE_URL=http://192.168.1.108:8080
HF_ENDPOINT=https://hf-mirror.com
HF_HUB_DISABLE_SYMLINKS=1
```

---

## 6. 快速开始

### 6.1 后端启动

```bash
# 1. 进入后端目录
cd server

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
# 编辑 .env，填入 DOUBAO_API_KEY、DOUBAO_MODEL 等必填项

# 4. 启动服务
python main.py
```

服务启动后监听 `http://localhost:8080`。

**验证启动：**
```bash
curl http://localhost:8080/health
# 返回 {"status": "ok"} 即为成功
```

### 6.2 客户端运行

1. 打开 Android Studio
2. 导入 `android/` 目录
3. 确认 Android SDK 已安装（API 24+）
4. 修改 `ChatRepository.kt` 中的 `baseUrl` 为后端实际地址
5. 连接设备或启动模拟器，点击 Run

> **注意**：模拟器中 `10.0.2.2` 指向宿主机 `localhost`；真机需使用局域网 IP。

### 6.3 首次运行说明

- ChromaDB 向量库首次启动时自动初始化（基于 `all-MiniLM-L6-v2` 本地模型）
- BGE-Reranker 模型首次使用时自动从 HuggingFace 下载（约 1GB）
- 商品数据位于 `server/data/ecommerce_agent_dataset/`，启动时自动加载
- 无需手动建索引，向量化在首次检索时自动完成

---

## 7. 使用说明

### 基础场景

**单轮模糊推荐：**
> 推荐一款适合油皮的洗面奶

**条件筛选：**
> 200 元以下的蓝牙耳机有哪些？

**跨类目推荐：**
> 想要推荐露营的零食和衣服

### 进阶场景

**多轮追问与细化：**
> 帮我推荐跑鞋
> （Agent 反问预算/场景后继续）→ 要轻量的，预算 500 以内

**多商品对比：**
> 帮我对比一下刚才推荐的那几款面霜

**Agent 主动反问：**
> 推荐一款手机
> （Agent 会主动询问使用场景、预算、品牌偏好，逐步锁定需求）

### 高级场景

**反选 / 排除约束：**
> 推荐防晒霜，不要含酒精、不要日系品牌

**场景化组合推荐：**
> 下周去三亚度假，帮我搭配一套防晒和穿搭方案

**购物车全链路：**
> 把第一款加入购物车
> 查看购物车 → 修改数量 → 删除商品

### 多模态场景

**拍照找货：**
> 点击输入框旁的 [+] 按钮，拍照或上传商品图片，Agent 自动检索相似商品

**语音输入：**
> 点击系统键盘麦克风，说出购物需求（Android 系统键盘原生支持）

**语音播报：**
> AI 回复完成后自动朗读，可通过顶栏音量图标开关

---

## 8. 核心实现

### 8.1 分层 Agent 编排 + 状态机驱动

系统采用 **3 个子 Agent** 的分层架构，通过显式状态机约束会话流转。

**意图识别：两层快路由**

```
用户输入
    │
    ├─① 规则快速通道：匹配购物车/对比/场景/推荐等关键词 → 毫秒级判定
    │   覆盖约 70% 电商常见意图，跳过 LLM 调用
    │
    └─② LLM 兜底：仅在规则无法判定的语义模糊场景调用
```

**状态机（3 状态）**

```
BROWSING（浏览/搜索） ←→  COMPARING（对比）
    │                        │
    └── SCENE_PLANNING（场景规划）
```

每个状态明确约束允许的 Agent 和意图跳转，防止对话在错误时机跳转。

**3 个子 Agent 职责：**

| Agent | 负责 |
|-------|------|
| `search_agent` | 单品搜索 + Slot-filling 渐进反问 + 互补推荐 |
| `compare_agent` | 多商品对比（四步法：识别→并行检索→提维度→组表→流式理由） |
| `scene_agent` | 场景化组合规划 + 多主题导航 |

**渐进反问（Slot-filling）**

`search_agent` 内置反问决策：当候选商品 > 3 个且尚未充分锁定需求时，依次询问：

1. **动态 SKU 属性**：从候选商品中提取有区分力的属性选项（如颜色/尺码/容量）
2. **类目关键维度**：按品类预设维度询问（手机类询问"用途/品牌/预算"，运动鞋询问"场景/性别/价位"）
3. **兜底**：直接出卡

### 8.2 混合检索 + RRF 融合 + Cross-Encoder 精排

**Chunking 策略**

每条商品数据切分为多类 chunk，独立向量化：

| Chunk 类型 | 内容 | 适合命中 |
|-----------|------|---------|
| `title_attrs` | 标题 + 品牌 + 类目 + 价格 | 精确品名/品牌检索 |
| `description` | 营销描述、卖点文案 | 功效/适用人群/场景 |
| `faq` | 官方问答 | 具体功效/成分/规格 |
| `review` | 用户评价 | 真实体验/口碑 |

**三路并行召回**

```
用户 Query
    │
    ├─① 向量检索（Chroma）：语义相似度，召回 top_k×2 个 chunk
    │   Query → all-MiniLM-L6-v2 / Doubao-embedding-vision → 向量
    │
    ├─② BM25 检索（rank-bm25）：关键词精确匹配，召回 top_k×2 个 chunk
    │   Query → jieba 分词 → 同义词扩展 → IDF 打分
    │
    └─③ 属性匹配：品牌/类目/子类目/标题加权打分
        结构化字段精确匹配，补充语义检索盲区
```

**RRF（Reciprocal Rank Fusion）融合**

三路检索分数量纲不同，RRF 只依赖排名进行融合：

```
score(d) = Σ 1 / (k + rank_i(d))，k=60
```

**Cross-Encoder 精排**

1. RRF 融合后按 `product_id` 聚合 chunk 结果
2. 构造商品代表文本：`"商品:{标题}\n{最高分 chunk 内容}"`
3. 送入 `BGE-Reranker-Base`（Cross-Encoder），与 Query 交互打分
4. 按精排分数重新排列取 top_k

BGE 模型不可用时自动降级，确保服务可用性。

**检索增强技术**

- **HyDE（Hypothetical Document Embeddings）**：短查询（≤20 字）时，LLM 先想象理想商品描述，用想象文档的向量替代原始 Query 向量检索
- **Query 分解**：含"和/与/还/也/同时"等连接词的复合查询，LLM 拆成 2-3 个子查询分别检索后合并
- **Self-RAG 相关性校验**：LLM 逐商品评判检索结果与 Query 的相关性，过滤不相关商品（保留最少 3 件）
- **多维度偏好加权**：品牌偏好（+0.3）、价格范围（+0.2）、肤质匹配（+0.2）、口味偏好（+0.2）等

### 8.3 防幻觉设计

推荐、对比、追问场景中，商品的价格、标题、SKU、图片等结构化数据**全部直接从数据库查询**，LLM 只生成文字说明。System Prompt 明确约束：

- 严格基于检索到的商品资料回答
- 对比表中资料未提及的属性填"—"，绝不臆造
- 不编造优惠、库存、成分等未经核实的信息

### 8.4 多模态能力

**拍照找货（双路径）**

```
端侧拍照/相册选图
    → 等比缩放（800px 上限）+ JPEG 压缩（quality=80）
    → Base64 编码
    → 后端双路径并行：
       ├─ VLM 路径：Doubao 多模态 VLM 识别物体属性 → 文本 RAG 检索
       └─ Embedding 路径：Doubao-embedding-vision 图像向量化 → 向量检索
    → 返回视觉相似商品
```

**语音输入（ASR）**

集成系统键盘语音输入，Android 各主流机型（包括国产定制系统）均原生支持，无需引入第三方 ASR SDK。语音转文字后进入与普通文字消息相同的处理链路。

**TTS 语音播报**

流式回复结束后，自动将 AI 文字内容通过 Android `TextToSpeech` 朗读。去除 Markdown 符号避免噪音播报；记录上次播报内容防止重复朗读。

### 8.5 Prompt 工程

`prompt.py` 构建多层次的 System Prompt：

| 层次 | 内容 |
|------|------|
| 人设 | "小豆"，AI 闺蜜兼购物助手，温暖活泼风格 |
| 记忆 | 会话摘要 + 用户长期偏好（14 类：肤质/运动类型/口味/风格等） |
| 历史 | 最近 10 轮对话 |
| 上下文 | 上次展示商品列表（支持"200 以内"等约束追问） |
| 情感感知 | 13 种情绪检测，自适应调整回复语气 |
| 模式感知 | 目的性购物 vs 闲逛浏览，调整推荐策略 |
| 生活事件 | 提取旅行/工作压力/健身计划等，关联商品推荐 |
| 格式约束 | 商品卡片标记规范、禁止编造信息 |

### 8.6 客户端流式渲染

`SseClient` 基于 OkHttp EventSource 将 SSE 回调桥接为 Kotlin `Flow`，`ChatViewModel` 订阅并按事件类型分发：

- `text_delta`：追加到当前流式气泡，触发滚动跟随
- `thinking`：替换顶部状态提示（"正在思考..."）
- `product_card`：紧跟相关文字插入商品卡片
- `comparison_table`：渲染横向滚动对比表格
- `clarification`：渲染流式反问选项按钮（FlowRow 布局）
- `done`：结束流式状态，触发 TTS 播报

支持打字特效（30ms/字）、流式文字与商品卡片交替渲染、历史会话重建。

---

## 9. 亮点与创新

### 亮点一：工程化抗幻觉——"数据-文本分离" + 规则快路由

**与同类方案的差异：**

同类方案通常让 LLM 一步生成含价格、参数、推荐理由的完整回复，容易产生编造信息。

本系统将回复内容严格分为两类：
- **结构化数据**（价格、SKU、标题、图片）：全部从数据库直接查询，LLM 无法干预
- **自然语言内容**（推荐理由、对比分析、场景说明）：LLM 基于已核实的资料生成

对比场景尤为典型：维度提取用 LLM，但每个维度值必须来自商品原文，缺失填"—"不臆造。意图识别采用**规则快路由优先**，常见电商意图毫秒级判定无需调用 LLM，从路由层就降低了幻觉风险。

### 亮点二：三路混合检索 + HyDE + Self-RAG——多层次检索增强

**与同类方案的差异：**

同类 RAG 方案常见问题：单一向量检索对精确关键词不敏感；向量 + BM25 直接加权需要手动调参。

本系统的多层次设计：
- **三路召回**：向量 + BM25 + 属性匹配并行，RRF 融合规避量纲差异
- **HyDE 增强**：短查询自动生成假设文档，显著提升模糊查询的召回质量
- **Self-RAG 校验**：LLM 逐商品评判相关性，过滤噪声，保障精排输入质量
- **Query 分解**：复合查询自动拆分，支持跨类目检索
- **商品关系图谱**：同品牌/同品类/互补商品关联，支持追加推荐

### 亮点三：渐进式 Slot-filling 反问——多轮对话主动收敛需求

`search_agent` 的三层反问决策实现了"先收敛再推荐"的交互模式：
1. 动态提取候选商品有区分力的 SKU 属性供用户选择
2. 按品类预设维度逐层细化
3. 充分收敛后才出卡，避免无效推荐

用户的反问答复通过 `pending` 机制确定性解析（不经 LLM），点击即可精准识别；同时提供"直接帮我搜"按钮随时退出反问。

### 亮点四：多模态全链路——从拍照到语音的完整交互闭环

- **拍照找货**：VLM + Embedding 双路径并行，自动选择最优方案
- **语音输入**：零第三方依赖，系统键盘原生语音
- **TTS 播报**：智能去 Markdown + 防重复播报
- **流式渲染**：SSE 事件流驱动，文字/卡片/表格/反问选项交替实时渲染
- 多模态输入与对话搜索复用同一 SSE 事件链路，非功能堆砌


