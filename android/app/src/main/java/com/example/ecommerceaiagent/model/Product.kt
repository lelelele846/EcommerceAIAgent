package com.example.ecommerceaiagent.model

data class Product(
    val id: String = "",
    val name: String = "",
    val brand: String = "",
    val category: String = "",
    val price: Double = 0.0,
    val image_url: String = "",
    val rating: Double = 0.0,
    val review_count: Int = 0,
    val description: String = "",
    val product_url: String = "",
    val skus: List<Sku> = emptyList(),
    val faq: List<FaqItem> = emptyList(),
    val reviews: List<ReviewItem> = emptyList()
)

data class Sku(
    val sku_id: String = "",
    val properties: Map<String, String> = emptyMap(),
    val price: Double = 0.0
)

data class FaqItem(
    val question: String = "",
    val answer: String = ""
)

data class ReviewItem(
    val nickname: String = "",
    val rating: Int = 0,
    val content: String = ""
)