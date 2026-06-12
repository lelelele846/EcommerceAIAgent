package com.example.ecommerceaiagent.model

sealed class MessageItem {
    data class UserMessage(
        val text: String,
        val timestamp: Long,
        val imageUri: String? = null,       // 图片本地URI (content:// 或 file://)
        val isVoiceMessage: Boolean = false  // 是否为语音消息
    ) : MessageItem()
    data class AiMessage(
        val contentBlocks: List<ContentBlock>,
        val timestamp: Long,
        val isComplete: Boolean = true,
        val isStreaming: Boolean = false,    // 流式写入中，末尾显示光标
    ) : MessageItem()
    object TypingIndicator : MessageItem()

    // 内容块：可以是文本、商品卡片、对比卡片或反问选项
    sealed class ContentBlock {
        data class TextBlock(val text: String) : ContentBlock()
        data class ProductBlock(val product: Product) : ContentBlock()
        data class ComparisonBlock(val products: List<Product>, val aiAnalysis: String) : ContentBlock()
        data class ClarificationBlock(val question: String, val options: List<String>) : ContentBlock()
    }
}