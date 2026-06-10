package com.example.ecommerceaiagent.repository

import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * 基于 OkHttp EventSource 的 SSE 客户端，将回调桥接为 Kotlin Flow。
 *
 * 相比原始 newCall().enqueue() 手动逐行解析的优势：
 *   - OkHttp 原生 SSE 解析，自动处理断线重连
 *   - callbackFlow 桥接为 Flow，与 ViewModel 的协程模型天然融合
 *   - 每个元素是 Pair(eventType, dataJson)，由上层 Repository 负责解析业务含义
 *   - readTimeout(0) 保证 SSE 长连接不超时断开
 */
class SseClient {

    // SSE 连接需要长超时，读取超时设为 0（无限）
    private val okHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    /**
     * 发起 SSE 流式请求。
     *
     * @param url  SSE 端点地址
     * @param jsonBody  POST 请求体（JSON 字符串）
     * @param headers  额外请求头（如 X-Session-ID）
     * @return Flow<Pair<eventType, dataJson>> 每个 SSE 事件的类型和 JSON 数据
     */
    fun stream(
        url: String,
        jsonBody: String,
        headers: Map<String, String> = emptyMap(),
    ): Flow<Pair<String, String>> = callbackFlow {
        val body = jsonBody.toRequestBody("application/json; charset=utf-8".toMediaType())
        val requestBuilder = Request.Builder()
            .url(url)
            .post(body)
            .header("Accept", "text/event-stream")
            .header("Cache-Control", "no-cache")

        headers.forEach { (key, value) -> requestBuilder.header(key, value) }

        val request = requestBuilder.build()

        val eventSource = EventSources.createFactory(okHttpClient)
            .newEventSource(request, object : EventSourceListener() {
                override fun onEvent(
                    eventSource: EventSource,
                    id: String?,
                    type: String?,
                    data: String,
                ) {
                    val t = type ?: return
                    trySend(Pair(t, data))
                }

                override fun onFailure(
                    eventSource: EventSource,
                    t: Throwable?,
                    response: Response?,
                ) {
                    val error = t ?: IOException("SSE 连接失败: HTTP ${response?.code}")
                    close(error)
                }

                override fun onClosed(eventSource: EventSource) {
                    close()
                }
            })

        awaitClose { eventSource.cancel() }
    }
}
