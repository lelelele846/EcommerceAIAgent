package com.example.ecommerceaiagent.repository

import android.content.Context
import android.util.Log
import com.example.ecommerceaiagent.model.*
import com.example.ecommerceaiagent.utils.ImageCompressor
import com.google.gson.Gson
import com.google.gson.JsonParser
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.mapNotNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.IOException
import java.io.InputStreamReader
import java.nio.charset.StandardCharsets
import java.util.UUID
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * 对话 Repository：
 *   - SSE 流式对话 → Flow<ChatMessage>（OkHttp EventSource + typed event parsing）
 *   - REST API 调用（商品详情、会话管理）
 */
class ChatRepository {

    private val sseClient = SseClient()
    private val gson = Gson()

    // HTTP 客户端 — SSE 流式请求也需要长超时（HyDE + reranker 首字节延迟较高）
    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)   // SSE 长连接，不设读超时
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private var sessionId: String? = null

    // ===== SSE 事件类型枚举 =====

    private enum class SseEventType(val value: String) {
        THINKING("thinking"),
        TOOL_PROGRESS("tool_progress"),
        TEXT_DELTA("text_delta"),
        PRODUCT_CARD("product_card"),
        PRODUCT_CARD_LIST("product_card_list"),
        COMPARISON_TABLE("comparison_table"),
        CLARIFICATION("clarification"),
        IMAGE_SEARCHING("image_searching"),
        ERROR("error"),
        DONE("done"),
        UNKNOWN("unknown");

        companion object {
            fun from(value: String): SseEventType =
                entries.find { it.value == value } ?: UNKNOWN
        }
    }

    // ===== 回调接口（保持向后兼容）=====

    interface ChatCallback {
        fun onMessageReceived(content: String)
        fun onProductReceived(product: Product)
        fun onRecognizedText(text: String) {}
        fun onComparisonReceived(products: List<Product>, aiAnalysis: String) {}
        fun onClarification(question: String, options: List<String>) {}
        fun onComplete()
        fun onError(error: String)
    }

    // ===== SSE Flow API（新架构，推荐使用）=====

    /**
     * 发起对话，返回 Flow<ChatMessage>。
     * text_delta 事件由 ViewModel 负责累积成流式文字气泡。
     */
    fun chatFlow(text: String, imageBase64: String? = null): Flow<ChatMessage> {
        if (sessionId == null) sessionId = UUID.randomUUID().toString()

        val baseUrl = "http://192.168.1.108:8080"
        val url = "$baseUrl/api/chat/stream"
        val escapedMessage = text.replace("\\", "\\\\").replace("\"", "\\\"")
        val imagePart = if (imageBase64 != null) """, "image_base64": "$imageBase64"""" else ""
        val json = """{"message": "$escapedMessage", "session_id": "$sessionId"$imagePart}"""

        return sseClient.stream(
            url = url,
            jsonBody = json,
            headers = mapOf("X-Session-ID" to sessionId!!),
        ).mapNotNull { (type, data) ->
            parseSseEvent(SseEventType.from(type), data)
        }
    }

    /** 拍照找货 SSE 流 */
    fun searchByImageFlow(imageBase64: String, caption: String = ""): Flow<ChatMessage> {
        if (sessionId == null) sessionId = UUID.randomUUID().toString()

        val baseUrl = "http://192.168.1.108:8080"
        val url = "$baseUrl/api/image/search"
        val escapedCaption = caption.replace("\\", "\\\\").replace("\"", "\\\"")
        val json = """{"image_base64": "$imageBase64", "caption": "$escapedCaption", "session_id": "$sessionId"}"""

        return sseClient.stream(
            url = url,
            jsonBody = json,
            headers = mapOf("X-Session-ID" to sessionId!!),
        ).mapNotNull { (type, data) ->
            parseSseEvent(SseEventType.from(type), data)
        }
    }

    // ===== 解析 SSE 事件 → ChatMessage =====

    private fun parseSseEvent(type: SseEventType, data: String): ChatMessage? {
        return try {
            when (type) {
                SseEventType.THINKING -> {
                    val json = JSONObject(data)
                    ChatMessage.AiStatus(json.optString("message", "正在思考..."))
                }
                SseEventType.TOOL_PROGRESS -> {
                    val json = JSONObject(data)
                    ChatMessage.AiStatus(json.optString("message", "检索中..."))
                }
                SseEventType.IMAGE_SEARCHING -> {
                    val json = JSONObject(data)
                    ChatMessage.AiStatus(json.optString("message", "正在分析图片..."))
                }
                SseEventType.TEXT_DELTA -> {
                    val json = JSONObject(data)
                    val text = json.optString("text", json.optString("content", ""))
                    if (text.isEmpty()) null else ChatMessage.AiText(text = text)
                }
                SseEventType.PRODUCT_CARD -> {
                    val json = JSONObject(data)
                    val productJson = json.optJSONObject("product") ?: json
                    ChatMessage.AiProductCard(product = parseProductFromJson(productJson))
                }
                SseEventType.PRODUCT_CARD_LIST -> {
                    val json = JSONObject(data)
                    val arr = json.optJSONArray("products") ?: JSONArray()
                    val products = (0 until arr.length()).map { i ->
                        parseProductFromJson(arr.getJSONObject(i))
                    }
                    val searchType = json.optString("search_type", "text")
                    ChatMessage.AiProductList(products, searchType)
                }
                SseEventType.COMPARISON_TABLE -> {
                    val json = JSONObject(data)
                    val arr = json.optJSONArray("products") ?: JSONArray()
                    val products = (0 until arr.length()).map { i ->
                        parseProductFromJson(arr.getJSONObject(i))
                    }
                    val dimsArr = json.optJSONArray("dimensions") ?: JSONArray()
                    val dims = (0 until dimsArr.length()).map { i ->
                        val dim = dimsArr.getJSONObject(i)
                        val vals = dim.optJSONArray("values") ?: JSONArray()
                        ComparisonDimension(
                            name = dim.optString("name", ""),
                            values = (0 until vals.length()).map { j -> vals.optString(j, "") }
                        )
                    }
                    ChatMessage.AiComparison(products, dims, json.optString("recommendation", ""))
                }
                SseEventType.CLARIFICATION -> {
                    val json = JSONObject(data)
                    val optsArr = json.optJSONArray("options") ?: JSONArray()
                    ChatMessage.AiClarification(
                        question = json.optString("question", ""),
                        options = (0 until optsArr.length()).map { i -> optsArr.optString(i, "") }
                    )
                }
                SseEventType.DONE -> {
                    val json = JSONObject(data)
                    ChatMessage.InternalDone(
                        agentState = json.optString("agent_state", "")
                    )
                }
                SseEventType.ERROR -> {
                    val json = JSONObject(data)
                    ChatMessage.AiError(
                        code = json.optString("code", "ERROR"),
                        message = json.optString("message", "未知错误"),
                    )
                }
                SseEventType.UNKNOWN -> {
                    // 兼容无 type 字段但包含完整商品字段的 SSE 事件
                    val json = JSONObject(data)
                    if (json.has("id") && json.has("name") && json.has("price")) {
                        ChatMessage.AiProductCard(product = parseProductFromJson(json))
                    } else {
                        val content = json.optString("content", "")
                        if (content.isNotEmpty()) ChatMessage.AiText(text = content) else null
                    }
                }
            }
        } catch (e: Exception) {
            Log.e("ChatRepository", "解析 SSE 事件失败 type=${type.value}: $data", e)
            null
        }
    }

    private fun parseProductFromJson(json: JSONObject): Product {
        return Product(
            id = json.optString("id", ""),
            name = json.optString("name", json.optString("title", "")),
            brand = json.optString("brand", ""),
            category = json.optString("category", ""),
            price = json.optDouble("price", json.optDouble("base_price", 0.0)),
            image_url = json.optString("image_url", ""),
            rating = json.optDouble("rating", 0.0),
            review_count = json.optInt("review_count", 0),
            description = json.optString("description", json.optString("marketing_description", "")),
            product_url = json.optString("product_url", ""),
        )
    }

    // ===== 旧回调 API（保持兼容）=====

    /** 发送文字消息（旧接口，委托到 Flow API） */
    fun sendMessage(message: String, callback: ChatCallback) {
        sendChatRequest(message, null, callback)
    }

    /** 发送图片消息（旧接口） */
    fun sendImageMessage(imageBase64: String, caption: String, callback: ChatCallback) {
        sendChatRequest(caption, imageBase64, callback)
    }

    /** 统一请求入口：文字 + 可选图片 base64 → /api/chat/stream */
    private fun sendChatRequest(message: String, imageBase64: String?, callback: ChatCallback) {
        if (sessionId == null) sessionId = UUID.randomUUID().toString()

        val baseUrl = "http://192.168.1.108:8080"
        val url = "$baseUrl/api/chat/stream"
        val escapedMessage = message.replace("\\", "\\\\").replace("\"", "\\\"")
        val imagePart = if (imageBase64 != null) """, "image_base64": "$imageBase64"""" else ""
        val json = """{"message": "$escapedMessage", "session_id": "$sessionId"$imagePart}"""

        val request = Request.Builder()
            .url(url)
            .header("Accept", "text/event-stream")
            .header("X-Session-ID", sessionId!!)
            .post(json.toRequestBody("application/json; charset=utf-8".toMediaType()))
            .build()

        httpClient.newCall(request).enqueue(object : okhttp3.Callback {
            override fun onFailure(call: okhttp3.Call, e: IOException) {
                callback.onError("连接服务器失败：${e.message}")
            }

            override fun onResponse(call: okhttp3.Call, response: okhttp3.Response) {
                response.use {
                    if (!response.isSuccessful) {
                        callback.onError("服务器响应失败：${response.code}")
                        return
                    }

                    val inputStream = response.body?.byteStream() ?: return
                    val reader = BufferedReader(InputStreamReader(inputStream, StandardCharsets.UTF_8))

                    try {
                        var line: String?
                        val buffer = StringBuilder()

                        line = reader.readLine()
                        while (line != null) {
                            if (line.startsWith("data: ")) {
                                val jsonStr = line.substring(6)
                                try {
                                    val jsonObject = JSONObject(jsonStr)
                                    val type = jsonObject.optString("type", "")

                                    when (type) {
                                        "content" -> {
                                            val content = jsonObject.optString("content", "")
                                            if (content.isNotEmpty()) callback.onMessageReceived(content)
                                        }
                                        "product_card" -> {
                                            val productJson = jsonObject.optJSONObject("product")
                                            if (productJson != null) callback.onProductReceived(parseProductFromJson(productJson))
                                        }
                                        "start" -> {
                                            val productsArray = jsonObject.optJSONArray("products")
                                            if (productsArray != null) {
                                                for (i in 0 until productsArray.length()) {
                                                    // 缓存但不立即发送
                                                }
                                            }
                                        }
                                        "comparison" -> {
                                            val productsArray = jsonObject.optJSONArray("products")
                                            val aiAnalysis = jsonObject.optString("ai_analysis", "")
                                            if (productsArray != null) {
                                                val products = mutableListOf<Product>()
                                                for (i in 0 until productsArray.length()) {
                                                    products.add(parseProductFromJson(productsArray.getJSONObject(i)))
                                                }
                                                callback.onComparisonReceived(products, aiAnalysis)
                                            }
                                        }
                                        "clarification" -> {
                                            val question = jsonObject.optString("question", "")
                                            val optsArr = jsonObject.optJSONArray("options")
                                            val opts = mutableListOf<String>()
                                            if (optsArr != null) {
                                                for (i in 0 until optsArr.length()) opts.add(optsArr.optString(i, ""))
                                            }
                                            callback.onClarification(question, opts)
                                        }
                                        "end" -> { /* onComplete 在循环结束后统一调用，避免重复 */ }
                                        "error" -> {
                                            val errorMsg = jsonObject.optString("message", "未知错误")
                                            callback.onError(errorMsg)
                                        }
                                        else -> {
                                            if (jsonObject.has("id") && jsonObject.has("name") && jsonObject.has("price")) {
                                                callback.onProductReceived(parseProductFromJson(jsonObject))
                                            } else {
                                                val content = jsonObject.optString("content", "")
                                                if (content.isNotEmpty()) callback.onMessageReceived(content)
                                            }
                                        }
                                    }
                                } catch (e: Exception) {
                                    Log.e("ChatRepository", "解析JSON失败: $jsonStr", e)
                                    if (jsonStr.contains("[商品卡片")) callback.onMessageReceived(jsonStr)
                                    else callback.onMessageReceived(jsonStr)
                                }
                            }
                            line = reader.readLine()
                        }
                        callback.onComplete()
                    } catch (e: Exception) {
                        Log.e("ChatRepository", "解析响应失败", e)
                        callback.onError("解析响应失败：${e.message}")
                    } finally {
                        reader.close()
                    }
                }
            }
        })
    }

    /** 发送语音消息（保持不变） */
    fun sendVoiceMessage(context: Context, audioFile: File, callback: ChatCallback) {
        if (sessionId == null) sessionId = UUID.randomUUID().toString()

        val baseUrl = "http://192.168.1.108:8080"
        val url = "$baseUrl/api/speech/recognize"

        val requestBody = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("file", audioFile.name, audioFile.asRequestBody("audio/mpeg".toMediaType()))
            .build()

        val request = Request.Builder()
            .url(url)
            .header("X-Session-ID", sessionId!!)
            .post(requestBody)
            .build()

        httpClient.newCall(request).enqueue(object : okhttp3.Callback {
            override fun onFailure(call: okhttp3.Call, e: IOException) {
                callback.onError("语音识别失败：${e.message}")
            }
            override fun onResponse(call: okhttp3.Call, response: okhttp3.Response) {
                response.use {
                    if (!response.isSuccessful) {
                        callback.onError("服务器响应失败：${response.code}")
                        return
                    }
                    try {
                        val responseBody = response.body?.string() ?: ""
                        val jsonObject = JSONObject(responseBody)
                        val recognizedText = jsonObject.optString("recognized_text", "")
                        val replyText = jsonObject.optString("reply_text", "")
                        val productsArray = jsonObject.optJSONArray("products")
                        if (recognizedText.isNotEmpty()) callback.onRecognizedText(recognizedText)
                        if (replyText.isNotEmpty()) callback.onMessageReceived(replyText)
                        if (productsArray != null) {
                            for (i in 0 until productsArray.length()) {
                                callback.onProductReceived(parseProductFromJson(productsArray.getJSONObject(i)))
                            }
                        }
                        callback.onComplete()
                    } catch (e: Exception) {
                        Log.e("ChatRepository", "解析语音响应失败", e)
                        callback.onError("解析响应失败：${e.message}")
                    }
                }
            }
        })
    }

    fun clearSession() { sessionId = null }
}
