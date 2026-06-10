package com.example.ecommerceaiagent.model

import android.graphics.Bitmap

/**
 * SSE 事件对应的内部消息类型（与 UI 层的 MessageItem 解耦）。
 *
 * Repository 将原始 SSE 事件解析为此 sealed class，
 * ViewModel 收集后按类型分发到 ChatUiState 的 messages 列表（MessageItem）。
 *
 * 对应 SSE 事件类型：
 *   text_delta      → AiText        — 流式文字增量
 *   thinking        → AiStatus      — 思考状态（替换顶部的"正在思考..."）
 *   tool_progress   → AiStatus      — 工具进度（如"正在检索商品..."）
 *   product_card    → AiProductCard — 单张商品卡片
 *   product_card_list → AiProductList — 横滑商品列表
 *   comparison_table → AiComparison — 商品对比表格
 *   clarification   → AiClarification — Agent 反问 + 选项按钮
 *   done            → InternalDone — 本轮回复结束（不显示）
 *   error           → AiError — 错误提示
 */
sealed class ChatMessage {
    /** 用户发送的文字/图片消息 */
    data class User(val text: String, val bitmap: Bitmap? = null) : ChatMessage()

    /** AI 流式文字增量，isStreaming=true 时末尾显示光标 */
    data class AiText(val text: String, val isStreaming: Boolean = false) : ChatMessage()

    /** 加载/思考/工具进度状态（替换式，不累积） */
    data class AiStatus(val message: String) : ChatMessage()

    /** 单张商品卡片 */
    data class AiProductCard(val product: Product) : ChatMessage()

    /** 横滑商品列表（HorizontalPager） */
    data class AiProductList(val products: List<Product>, val searchType: String = "text") : ChatMessage()

    /** 多商品对比表格 */
    data class AiComparison(val products: List<Product>, val dimensions: List<ComparisonDimension>, val recommendation: String = "") : ChatMessage()

    /** Agent 反问 + 选项按钮（FlowRow 自适应布局） */
    data class AiClarification(val question: String, val options: List<String>) : ChatMessage()

    /** 错误提示 */
    data class AiError(val code: String, val message: String) : ChatMessage()

    // ── 内部事件（不加入消息列表，由 ViewModel 处理）──

    /** 本轮回复结束（更新 agentState） */
    data class InternalDone(val agentState: String = "") : ChatMessage()
}

/** 对比表格维度 */
data class ComparisonDimension(
    val name: String,
    val values: List<String>,
)
