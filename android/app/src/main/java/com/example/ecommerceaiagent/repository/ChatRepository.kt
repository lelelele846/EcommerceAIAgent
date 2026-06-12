package com.example.ecommerceaiagent.repository

import android.content.Context
import android.util.Log
import com.example.ecommerceaiagent.model.*
import com.example.ecommerceaiagent.model.CartItem
import com.google.gson.Gson
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
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

    private val gson = Gson()

    // HTTP 客户端 — SSE 流式请求也需要长超时（HyDE + reranker 首字节延迟较高）
    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)   // SSE 长连接，不设读超时
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private var sessionId: String? = null

    fun setSessionId(id: String) { sessionId = id }
    fun getSessionId(): String {
        if (sessionId == null) sessionId = UUID.randomUUID().toString()
        return sessionId!!
    }



    // ===== 回调接口（保持向后兼容）=====

    interface ChatCallback {
        fun onMessageReceived(content: String)
        fun onProductReceived(product: Product)
        fun onComparisonReceived(products: List<Product>, aiAnalysis: String) {}
        fun onClarification(question: String, options: List<String>) {}
        fun onCartUpdate(items: List<CartItem>, total: Double, count: Int, action: String) {}
        fun onOrderConfirmed(orderId: String, items: List<CartItem>, total: Double) {}
        fun onComplete()
        fun onError(error: String)
    }


    /**
     * 发起对话，返回 Flow<ChatMessage>。
     * text_delta 事件由 ViewModel 负责累积成流式文字气泡。
     */

    // ===== 解析 SSE 事件 → ChatMessage =====


    private fun parseProductFromJson(json: JSONObject): Product {
        val reviewsArr = json.optJSONArray("reviews")
        val reviews = if (reviewsArr != null) {
            (0 until reviewsArr.length()).map { i ->
                val r = reviewsArr.getJSONObject(i)
                ReviewItem(nickname = r.optString("nickname"), rating = r.optInt("rating"), content = r.optString("content"))
            }
        } else emptyList()
        val faqArr = json.optJSONArray("faq")
        val faq = if (faqArr != null) {
            (0 until faqArr.length()).map { i ->
                val f = faqArr.getJSONObject(i)
                FaqItem(question = f.optString("question"), answer = f.optString("answer"))
            }
        } else emptyList()
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
            reviews = reviews,
            faq = faq,
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
                                        "cart_update" -> {
                                            val itemsArr = jsonObject.optJSONArray("items") ?: JSONArray()
                                            val items = (0 until itemsArr.length()).map { i ->
                                                val obj = itemsArr.getJSONObject(i)
                                                CartItem(product_id = obj.optString("product_id"), name = obj.optString("name"),
                                                    brand = obj.optString("brand"), price = obj.optDouble("price"),
                                                    quantity = obj.optInt("quantity", 1), image_url = obj.optString("image_url"))
                                            }
                                            callback.onCartUpdate(items, jsonObject.optDouble("total"), jsonObject.optInt("count"), jsonObject.optString("action"))
                                        }
                                        "order_confirmed" -> {
                                            val itemsArr = jsonObject.optJSONArray("items") ?: JSONArray()
                                            val items = (0 until itemsArr.length()).map { i ->
                                                val obj = itemsArr.getJSONObject(i)
                                                CartItem(product_id = obj.optString("product_id"), name = obj.optString("name"),
                                                    brand = obj.optString("brand"), price = obj.optDouble("price"),
                                                    quantity = obj.optInt("quantity", 1), image_url = obj.optString("image_url"))
                                            }
                                            callback.onOrderConfirmed(jsonObject.optString("order_id"), items, jsonObject.optDouble("total"))
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
}