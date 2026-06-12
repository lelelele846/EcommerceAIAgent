package com.example.ecommerceaiagent.model

/** 下单成功事件（SSE order_confirmed → 触发成功页） */
data class OrderConfirmed(
    val orderId: String,
    val items: List<CartItem>,
    val total: Double,
    val count: Int
)
