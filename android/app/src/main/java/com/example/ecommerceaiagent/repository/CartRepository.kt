package com.example.ecommerceaiagent.repository

import com.example.ecommerceaiagent.model.CartItem
import com.example.ecommerceaiagent.model.CartState
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

/**
 * 购物车 Repository — REST API 调用。
 * 对话中的加购/删除等走 SSE，UI 按钮（加购按钮/数量步进器）走这里。
 */
class CartRepository {

    // 与 ChatRepository 共用 baseUrl（真机改为局域网 IP，模拟器用 10.0.2.2）
    private val baseUrl = "http://192.168.1.108:8080"

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private val gson = Gson()

    suspend fun getCart(sessionId: String): CartState? = withContext(Dispatchers.IO) {
        try {
            val req = Request.Builder().url("$baseUrl/api/cart/$sessionId").get().build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return@withContext null
                parseCartResponse(resp.body?.string() ?: return@withContext null)
            }
        } catch (e: Exception) {
            e.printStackTrace()
            null
        }
    }

    suspend fun addToCart(sessionId: String, productId: String, quantity: Int = 1): CartState? =
        withContext(Dispatchers.IO) {
            try {
                val json = """{"session_id":"$sessionId","product_id":"$productId","quantity":$quantity}"""
                val body = json.toRequestBody("application/json".toMediaType())
                val req = Request.Builder().url("$baseUrl/api/cart/add").post(body).build()
                client.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) return@withContext null
                    parseCartResponse(resp.body?.string() ?: return@withContext null)
                }
            } catch (e: Exception) {
                e.printStackTrace()
                null
            }
        }

    suspend fun removeFromCart(sessionId: String, index: Int): CartState? = withContext(Dispatchers.IO) {
        try {
            val req = Request.Builder().url("$baseUrl/api/cart/$sessionId/$index").delete().build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return@withContext null
                parseCartResponse(resp.body?.string() ?: return@withContext null)
            }
        } catch (e: Exception) {
            e.printStackTrace()
            null
        }
    }

    suspend fun updateQuantity(sessionId: String, index: Int, quantity: Int): CartState? =
        withContext(Dispatchers.IO) {
            try {
                val json = """{"session_id":"$sessionId","index":$index,"quantity":$quantity}"""
                val body = json.toRequestBody("application/json".toMediaType())
                val req = Request.Builder().url("$baseUrl/api/cart/$sessionId/$index").put(body).build()
                client.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) return@withContext null
                    parseCartResponse(resp.body?.string() ?: return@withContext null)
                }
            } catch (e: Exception) {
                e.printStackTrace()
                null
            }
        }


    private fun parseCartResponse(json: String): CartState {
        val obj = gson.fromJson(json, Map::class.java)
        val itemsRaw = obj["items"] as? List<*> ?: emptyList<Any>()
        val itemType = object : TypeToken<List<CartItem>>() {}.type
        val items: List<CartItem> = gson.fromJson(gson.toJson(itemsRaw), itemType)
        return CartState(
            items = items,
            total = (obj["total"] as? Number)?.toDouble() ?: 0.0,
            count = (obj["count"] as? Number)?.toInt() ?: 0,
            action = obj["action"] as? String ?: ""
        )
    }

    data class OrderResult(
        val orderId: String = "",
        val total: Double = 0.0,
        val status: String = ""
    )

    suspend fun placeOrder(sessionId: String, address: String): OrderResult? = withContext(Dispatchers.IO) {
        try {
            val json = """{"session_id":"$sessionId","address":"$address"}"""
            val body = json.toRequestBody("application/json".toMediaType())
            val req = Request.Builder().url("$baseUrl/api/cart/orders").post(body).build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return@withContext null
                val obj = gson.fromJson(resp.body?.string(), Map::class.java)
                OrderResult(
                    orderId = obj["order_id"] as? String ?: "",
                    total = (obj["total"] as? Number)?.toDouble() ?: 0.0,
                    status = obj["status"] as? String ?: ""
                )
            }
        } catch (e: Exception) {
            e.printStackTrace()
            null
        }
    }
}
