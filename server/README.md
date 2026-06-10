# Ecommerce AI Agent - Backend

基于 FastAPI + Chroma + RAG 的电商智能导购后端服务

## 环境要求

- Python 3.10+
- pip

## 安装依赖

```bash
cd server
pip install -r requirements.txt
```

## 配置环境变量

编辑 `.env` 文件：

```env
DOUBAO_API_KEY=your_api_key
DOUBAO_API_BASE=https://ark.cn-beijing.volces.com/api/v3/
DOUBAO_MODEL=ep-20260514111645-lmgt2
CHROMA_DB_PATH=./chroma_db
```

## 运行服务

```bash
python main.py
```

服务将在 http://localhost:8000 启动

## API 接口

### 1. 聊天接口（非流式）

**POST** `/api/chat`

请求体：
```json
{
  "message": "推荐一款适合油皮的洗面奶",
  "session_id": "optional-session-id"
}
```

### 2. 聊天接口（流式）

**POST** `/api/chat/stream`

返回 SSE 流式响应

### 3. 获取所有商品

**GET** `/api/products`

### 4. 获取单个商品

**GET** `/api/products/{product_id}`

## 项目结构

```
server/
├── main.py                 # FastAPI 入口
├── requirements.txt        # 依赖列表
├── .env                   # 环境变量
├── rag/
│   ├── retriever.py       # 向量检索模块
│   └── prompt.py          # Prompt 构建模块
├── services/
│   └── doubao_service.py  # 大模型服务
├── models/
│   └── schemas.py         # 数据模型
└── data/
    └── ecommerce_data.json # 商品数据
```