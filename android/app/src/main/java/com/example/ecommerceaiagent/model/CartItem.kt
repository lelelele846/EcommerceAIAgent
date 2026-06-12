package com.example.ecommerceaiagent.model

/**
 * 购物车商品项和购物车状态。
 * CartState 从 REST API 和 SSE cart_update 事件反序列化。
 */
data class CartItem(
    val product_id: String = "",
    val name: String = "",
    val brand: String = "",
    val price: Double = 0.0,
    val quantity: Int = 1,
    val image_url: String = ""
)

data class CartState(
    val items: List<CartItem> = emptyList(),
    val total: Double = 0.0,
    val count: Int = 0,
    val action: String = ""   // "add" | "remove" | "update" | "clear" | "checkout" | "ordered"
)
