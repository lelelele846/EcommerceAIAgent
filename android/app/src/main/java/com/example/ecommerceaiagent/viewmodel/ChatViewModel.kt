package com.example.ecommerceaiagent.viewmodel

import android.content.Context
import android.net.Uri
import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.ecommerceaiagent.model.MessageItem
import com.example.ecommerceaiagent.model.MessageItem.ContentBlock
import com.example.ecommerceaiagent.model.Product
import com.example.ecommerceaiagent.repository.ChatRepository
import com.example.ecommerceaiagent.utils.IntentRecognizer
import com.example.ecommerceaiagent.utils.ImageCompressor
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import java.io.File

class ChatViewModel : ViewModel() {
    private val _messages = MutableStateFlow<List<MessageItem>>(emptyList())
    val messages: StateFlow<List<MessageItem>> = _messages.asStateFlow()

    private val _isAiTyping = MutableStateFlow(false)
    val isAiTyping: StateFlow<Boolean> = _isAiTyping.asStateFlow()

    private val _currentTypingText = MutableStateFlow("")
    val currentTypingText: StateFlow<String> = _currentTypingText.asStateFlow()

    private val _scrollTick = MutableStateFlow(0)
    val scrollTick: StateFlow<Int> = _scrollTick.asStateFlow()

    private val _toastMessage = MutableStateFlow("")
    val toastMessage: StateFlow<String> = _toastMessage.asStateFlow()

    // 消息队列：用于排队处理用户消息
    private val messageQueue = Channel<String>(Channel.UNLIMITED)

    // 互斥锁：保证同一时间只有一个打字任务在执行
    private val typingMutex = Mutex()

    // 当前正在构建的AI消息的索引，-1表示没有正在构建的消息
    private var currentAiMessageIndex: Int = -1

    // 当前正在构建的内容块列表（用于收集服务器返回的数据）
    private var collectedBlocks = mutableListOf<ContentBlock>()
    private var collectedText = ""

    // 当前正在打字的消息索引
    private var typingMessageIndex: Int = -1

    private val chatRepository = ChatRepository()

    // 会话ID，用于标识当前对话
    private var _sessionId: String? = null
    val sessionId: String?
        get() {
            if (_sessionId == null) {
                _sessionId = java.util.UUID.randomUUID().toString()
            }
            return _sessionId
        }

    // 重置会话（用于切换会话时）
    fun resetSession() {
        _sessionId = null
        _messages.value = emptyList()
        val welcomeMessage = MessageItem.AiMessage(
            contentBlocks = listOf(ContentBlock.TextBlock("你好！我是 AI 智能购物助手，告诉我你想买什么，我来帮你找～")),
            timestamp = System.currentTimeMillis()
        )
        _messages.value = listOf(welcomeMessage)
    }

    // 检查 AI 是否正在处理（有 TypingIndicator 或正在打字）
    fun isAiBusy(): Boolean {
        return _messages.value.any { it is MessageItem.TypingIndicator } || _isAiTyping.value
    }

    fun clearToast() { _toastMessage.value = "" }

    init {
        val welcomeMessage = MessageItem.AiMessage(
            contentBlocks = listOf(ContentBlock.TextBlock("你好！我是 AI 智能购物助手，告诉我你想买什么，我来帮你找～")),
            timestamp = System.currentTimeMillis()
        )
        _messages.value = listOf(welcomeMessage)

        // 启动消息处理协程
        viewModelScope.launch(Dispatchers.IO) {
            for (userMessage in messageQueue) {
                processMessage(userMessage)
            }
        }
    }

    fun sendUserMessage(text: String) {
        if (isAiBusy()) return  // AI 正在回复，拦截
        viewModelScope.launch {
            // 添加用户消息
            val userMessage = MessageItem.UserMessage(
                text = text,
                timestamp = System.currentTimeMillis()
            )
            _messages.update { it + userMessage }

            // 使用IntentRecognizer识别用户意图
            val intent = IntentRecognizer.recognizeIntent(text)
            val intentResponse = IntentRecognizer.getIntentResponse(intent)

            if (intentResponse.isNotEmpty()) {
                // 如果是打招呼或随便逛逛，直接返回本地响应，不调用服务器
                val aiMessage = MessageItem.AiMessage(
                    contentBlocks = listOf(ContentBlock.TextBlock(intentResponse)),
                    timestamp = System.currentTimeMillis(),
                    isComplete = true
                )
                _messages.update { it + aiMessage }
                return@launch
            }

            // 加入队列处理
            messageQueue.send(text)
        }
    }

    /**
     * 发送语音消息
     */
    fun sendVoiceMessage(context: Context, audioFile: File) {
        if (isAiBusy()) return  // AI 正在回复，拦截
        viewModelScope.launch {
            // 添加用户消息（语音 — 先显示"语音消息"占位）
            val userMessage = MessageItem.UserMessage(
                text = "语音消息",
                timestamp = System.currentTimeMillis(),
                isVoiceMessage = true
            )
            _messages.update { it + userMessage }

            // 添加TypingIndicator
            _messages.update { it + MessageItem.TypingIndicator }

            try {
                // 调用语音识别API
                chatRepository.sendVoiceMessage(context, audioFile, object : ChatRepository.ChatCallback {
                    override fun onRecognizedText(text: String) {
                        // 识别成功 → 把用户气泡从"语音消息"更新为识别出的文字
                        viewModelScope.launch(Dispatchers.Main) {
                            _messages.update { messages ->
                                messages.toMutableList().apply {
                                    // 找到用户语音消息并更新为文字消息
                                    val idx = indexOfLast { it is MessageItem.UserMessage && it.isVoiceMessage }
                                    if (idx >= 0) {
                                        this[idx] = MessageItem.UserMessage(
                                            text = text,
                                            timestamp = System.currentTimeMillis(),
                                            isVoiceMessage = false
                                        )
                                    }
                                }
                            }
                        }
                    }

                    override fun onMessageReceived(content: String) {
                        viewModelScope.launch(Dispatchers.Main) {
                            collectedText += content
                        }
                    }

                    override fun onProductReceived(product: Product) {
                        viewModelScope.launch(Dispatchers.Main) {
                            if (collectedText.isNotEmpty()) {
                                collectedBlocks.add(ContentBlock.TextBlock(collectedText))
                                collectedText = ""
                            }
                            collectedBlocks.add(ContentBlock.ProductBlock(product))
                        }
                    }

                    override fun onComplete() {
                        viewModelScope.launch(Dispatchers.Main) {
                            if (collectedText.isNotEmpty()) {
                                collectedBlocks.add(ContentBlock.TextBlock(collectedText))
                                collectedText = ""
                            }
                            
                            // 移除TypingIndicator
                            _messages.update { messages ->
                                messages.toMutableList().apply {
                                    removeLast()
                                }
                            }
                            
                            // 添加AI回复
                            if (collectedBlocks.isNotEmpty()) {
                                val aiMessage = MessageItem.AiMessage(
                                    contentBlocks = collectedBlocks.toList(),
                                    timestamp = System.currentTimeMillis(),
                                    isComplete = true
                                )
                                _messages.update { it + aiMessage }
                            }
                            
                            collectedBlocks.clear()
                        }
                    }

                    override fun onError(error: String) {
                        viewModelScope.launch(Dispatchers.Main) {
                            // 移除TypingIndicator
                            _messages.update { messages ->
                                messages.toMutableList().apply {
                                    removeLast()
                                }
                            }
                            
                            val errorMessage = MessageItem.AiMessage(
                                contentBlocks = listOf(ContentBlock.TextBlock("语音识别失败：$error")),
                                timestamp = System.currentTimeMillis(),
                                isComplete = true
                            )
                            _messages.update { it + errorMessage }
                        }
                    }
                })
            } catch (e: Exception) {
                Log.e("ChatViewModel", "语音消息发送失败", e)
                // 移除TypingIndicator
                _messages.update { messages ->
                    messages.toMutableList().apply {
                        removeLast()
                    }
                }
                
                val errorMessage = MessageItem.AiMessage(
                    contentBlocks = listOf(ContentBlock.TextBlock("语音消息发送失败：${e.message}")),
                    timestamp = System.currentTimeMillis(),
                    isComplete = true
                )
                _messages.update { it + errorMessage }
            }
        }
    }

    /**
     * 发送图片消息（从相册选择），将图片压缩为 base64 → SSE chat stream
     */
    fun sendImageMessage(context: Context, imageUri: Uri, caption: String = "") {
        if (isAiBusy()) return
        viewModelScope.launch(Dispatchers.IO) {
            // 压缩并转 base64
            val base64 = ImageCompressor.compressToBase64(context, imageUri) ?: run {
                withContext(Dispatchers.Main) {
                    Log.e("ChatViewModel", "图片压缩失败")
                    _toastMessage.value = "图片处理失败，请重试"
                }
                return@launch
            }

            withContext(Dispatchers.Main) {
                // 添加用户消息
                val userMessage = MessageItem.UserMessage(
                    text = caption,
                    timestamp = System.currentTimeMillis(),
                    imageUri = imageUri.toString()
                )
                _messages.update { it + userMessage + MessageItem.TypingIndicator }

                // SSE 流式发送
                streamImageSearch(base64, caption)
            }
        }
    }

    /**
     * 发送拍照图片
     */
    fun sendCameraImage(context: Context, imageFile: File, caption: String = "") {
        if (isAiBusy()) return
        viewModelScope.launch(Dispatchers.IO) {
            // 检查文件是否真实存在（部分国产 ROM 相机不写文件到 FileProvider URI）
            if (!imageFile.exists() || imageFile.length() == 0L) {
                withContext(Dispatchers.Main) {
                    Log.e("ChatViewModel", "拍照文件不存在或为空: ${imageFile.absolutePath}")
                    _toastMessage.value = "拍照失败，请重新拍照"
                }
                return@launch
            }
            val base64 = ImageCompressor.compressFileToBase64(imageFile) ?: run {
                withContext(Dispatchers.Main) {
                    Log.e("ChatViewModel", "图片压缩失败")
                    _toastMessage.value = "图片处理失败，请重试"
                }
                return@launch
            }

            withContext(Dispatchers.Main) {
                val userMessage = MessageItem.UserMessage(
                    text = caption,
                    timestamp = System.currentTimeMillis(),
                    imageUri = imageFile.toURI().toString()
                )
                _messages.update { it + userMessage + MessageItem.TypingIndicator }

                streamImageSearch(base64, caption)
            }
        }
    }

    /** 统一的图片 SSE 流处理 */
    private fun streamImageSearch(imageBase64: String, caption: String) {
        Log.d("ChatViewModel", "[streamImageSearch] 开始发送图片, caption=$caption")
        viewModelScope.launch {
            chatRepository.sendImageMessage(imageBase64, caption, object : ChatRepository.ChatCallback {
                override fun onMessageReceived(content: String) {
                    Log.d("ChatViewModel", "[streamImageSearch] onMessageReceived: ${content.take(60)}")
                    collectedText += content
                }

                override fun onProductReceived(product: Product) {
                    Log.d("ChatViewModel", "[streamImageSearch] onProductReceived: ${product.name}")
                    if (collectedText.isNotEmpty()) {
                        collectedBlocks.add(ContentBlock.TextBlock(collectedText))
                        collectedText = ""
                    }
                    collectedBlocks.add(ContentBlock.ProductBlock(product))
                }

                override fun onComplete() {
                    Log.d("ChatViewModel", "[streamImageSearch] onComplete, collectedText='${collectedText.take(40)}', blocks=${collectedBlocks.size}")
                    viewModelScope.launch(Dispatchers.Main) {
                        finishAiMessage()
                    }
                }

                override fun onError(error: String) {
                    Log.e("ChatViewModel", "[streamImageSearch] onError: $error")
                    viewModelScope.launch(Dispatchers.Main) {
                        finishAiMessage()
                        _toastMessage.value = "图片搜索失败: $error"
                    }
                }
            })
        }
    }

    /** 图片搜索结束：移除 TypingIndicator → 构建最终 AI 消息 */
    private fun finishAiMessage() {
        Log.d("ChatViewModel", "[finishAiMessage] collectedText='${collectedText.take(50)}', blocks=${collectedBlocks.size}, messages=${_messages.value.size}")
        // 追加剩余文本
        if (collectedText.isNotEmpty()) {
            collectedBlocks.add(ContentBlock.TextBlock(collectedText))
            collectedText = ""
        }
        // 移除 TypingIndicator
        _messages.update { messages ->
            messages.toMutableList().apply {
                if (isNotEmpty() && last() is MessageItem.TypingIndicator) {
                    removeLast()
                }
            }
        }
        // 构建 AI 消息
        if (collectedBlocks.isNotEmpty()) {
            val aiMessage = MessageItem.AiMessage(
                contentBlocks = collectedBlocks.toList(),
                timestamp = System.currentTimeMillis(),
                isComplete = true
            )
            _messages.update { it + aiMessage }
            Log.d("ChatViewModel", "[finishAiMessage] AiMessage 已添加: ${aiMessage.contentBlocks.firstOrNull()?.let {
                if (it is ContentBlock.TextBlock) it.text.take(50) else it::class.simpleName
            }}")
        } else {
            Log.w("ChatViewModel", "[finishAiMessage] collectedBlocks 为空，未创建 AiMessage")
        }
        collectedBlocks.clear()
    }

    private suspend fun processMessage(userMessage: String) = withContext(Dispatchers.Main) {
        typingMutex.lock()
        try {
            // 1. 添加TypingIndicator
            val typingIndicatorIndex = _messages.value.size
            _messages.update { it + MessageItem.TypingIndicator }

            // 2. 收集服务器响应
            collectedBlocks.clear()
            collectedText = ""
            currentAiMessageIndex = -1

            // 使用CompletableDeferred等待服务器响应完成
            val responseDeferred = CompletableDeferred<Unit>()

            chatRepository.sendMessage(userMessage, object : ChatRepository.ChatCallback {
                override fun onMessageReceived(content: String) {
                    viewModelScope.launch(Dispatchers.Main) {
                        collectedText += content
                    }
                }

                override fun onProductReceived(product: Product) {
                    viewModelScope.launch(Dispatchers.Main) {
                        // 如果有未完成的文本，先添加文本块
                        if (collectedText.isNotEmpty()) {
                            collectedBlocks.add(ContentBlock.TextBlock(collectedText))
                            collectedText = ""
                        }
                        // 添加商品块
                        collectedBlocks.add(ContentBlock.ProductBlock(product))
                    }
                }

                override fun onComparisonReceived(products: List<Product>, aiAnalysis: String) {
                    viewModelScope.launch(Dispatchers.Main) {
                        // 对比卡片作为一个独立块
                        if (collectedText.isNotEmpty()) {
                            collectedBlocks.add(ContentBlock.TextBlock(collectedText))
                            collectedText = ""
                        }
                        collectedBlocks.add(ContentBlock.ComparisonBlock(products, aiAnalysis))
                    }
                }

                override fun onClarification(question: String, options: List<String>) {
                    viewModelScope.launch(Dispatchers.Main) {
                        // 🆕 改为 ClarificationBlock（可点击按钮），不再拼成纯文本
                        if (collectedText.isNotEmpty()) {
                            collectedBlocks.add(ContentBlock.TextBlock(collectedText))
                            collectedText = ""
                        }
                        collectedBlocks.add(ContentBlock.ClarificationBlock(question, options))
                    }
                }

                override fun onComplete() {
                    viewModelScope.launch(Dispatchers.Main) {
                        // 添加最后剩余的文本
                        if (collectedText.isNotEmpty()) {
                            collectedBlocks.add(ContentBlock.TextBlock(collectedText))
                            collectedText = ""
                        }
                        responseDeferred.complete(Unit)
                    }
                }

                override fun onError(error: String) {
                    viewModelScope.launch(Dispatchers.Main) {
                        collectedBlocks.add(ContentBlock.TextBlock("很抱歉，服务器出现问题：$error"))
                        responseDeferred.complete(Unit)
                    }
                }
            })

            // 等待服务器响应完成
            responseDeferred.await()

            // 3. 移除TypingIndicator
            _messages.update { messages ->
                messages.toMutableList().apply {
                    if (typingIndicatorIndex < size) {
                        removeAt(typingIndicatorIndex)
                    }
                }
            }

            // 4. 创建AI消息框架
            typingMessageIndex = _messages.value.size
            _messages.update {
                it + MessageItem.AiMessage(
                    contentBlocks = emptyList(),
                    timestamp = System.currentTimeMillis(),
                    isComplete = false
                )
            }

            // 5. 启动打字机效果
            _isAiTyping.value = true
            _currentTypingText.value = ""

            // 逐块处理
            for (block in collectedBlocks) {
                when (block) {
                    is ContentBlock.TextBlock -> {
                        // 逐字显示文本
                        for (char in block.text.toCharArray()) {
                            _currentTypingText.value += char
                            updateTypingMessage()
                            delay(30) // 每隔30ms输出一个字符
                        }
                    }
                    is ContentBlock.ProductBlock -> {
                        // 添加商品块，文本清空
                        _currentTypingText.value = ""
                        updateTypingMessage(withProduct = block.product)
                    }
                    is ContentBlock.ComparisonBlock -> {
                        // 对比卡片立即显示
                        _currentTypingText.value = ""
                        updateTypingMessage(withComparison = block)
                    }
                    is ContentBlock.ClarificationBlock -> {
                        // 🆕 反问选项块 — 立即显示为可点击按钮
                        _currentTypingText.value = ""
                        updateTypingMessage(withClarification = block)
                    }
                }
            }

            // 6. 打字完成
            _isAiTyping.value = false
            _currentTypingText.value = ""

            // 复制一份内容块，避免后续清空影响已设置的消息
            val finalBlocks = collectedBlocks.toList()

            // 标记消息为完成
            _messages.update { messages ->
                messages.toMutableList().apply {
                    if (typingMessageIndex < size) {
                        this[typingMessageIndex] = MessageItem.AiMessage(
                            contentBlocks = finalBlocks,
                            timestamp = System.currentTimeMillis(),
                            isComplete = true
                        )
                    }
                }
            }

            typingMessageIndex = -1
            collectedBlocks.clear()

        } finally {
            typingMutex.unlock()
        }
    }

    private fun updateTypingMessage(
        withProduct: Product? = null,
        withComparison: ContentBlock.ComparisonBlock? = null,
        withClarification: ContentBlock.ClarificationBlock? = null,
    ) {
        if (typingMessageIndex < 0 || typingMessageIndex >= _messages.value.size) return

        _messages.update { messages ->
            messages.toMutableList().apply {
                val currentMsg = this[typingMessageIndex] as? MessageItem.AiMessage
                val currentBlocks = currentMsg?.contentBlocks?.toMutableList() ?: mutableListOf()
                // 保留消息创建时的时间戳，避免每次更新都改变 hashCode
                val originalTimestamp = currentMsg?.timestamp ?: System.currentTimeMillis()

                if (withComparison != null) {
                    currentBlocks.add(withComparison)
                } else if (withClarification != null) {
                    currentBlocks.add(withClarification)
                } else if (withProduct != null) {
                    currentBlocks.add(ContentBlock.ProductBlock(withProduct))
                } else if (_currentTypingText.value.isNotEmpty()) {
                    if (currentBlocks.isNotEmpty() && currentBlocks.last() is ContentBlock.TextBlock) {
                        currentBlocks.removeLast()
                    }
                    currentBlocks.add(ContentBlock.TextBlock(_currentTypingText.value))
                }

                this[typingMessageIndex] = MessageItem.AiMessage(
                    contentBlocks = currentBlocks,
                    timestamp = originalTimestamp,
                    isComplete = false
                )
            }
        }
    }

    /** 🆕 用户点击反问选项 → 作为用户消息发送 */
    fun selectClarification(option: String) {
        sendUserMessage(option)
    }

    override fun onCleared() {
        super.onCleared()
        messageQueue.close()
    }

    // ── 增强方法（RAGent 模式）──

    /** 添加/替换状态气泡：只在消息列表末尾保留一条，新状态替换旧状态 */
    private fun addStatus(msg: String) {
        _messages.update { messages ->
            val idx = messages.indexOfLast { it is MessageItem.StatusMessage }
            if (idx >= 0) {
                messages.toMutableList().apply { set(idx, MessageItem.StatusMessage(msg)) }
            } else {
                messages + MessageItem.StatusMessage(msg)
            }
        }
        _scrollTick.value += 1
    }

    private fun replaceOrAddStatus(messages: List<MessageItem>, status: MessageItem.StatusMessage): List<MessageItem> {
        val idx = messages.indexOfLast { it is MessageItem.StatusMessage }
        return if (idx >= 0) messages.toMutableList().apply { set(idx, status) }
        else messages + status
    }

    /** 将流式文字气泡锁定（isStreaming = false），准备在其后添加卡片/选项等组件 */
    private fun finalizeStreamingText(messages: List<MessageItem>): List<MessageItem> =
        messages.map { msg ->
            if (msg is MessageItem.AiMessage && !msg.isComplete) msg.copy(isComplete = true, isStreaming = false)
            else msg
        }
}