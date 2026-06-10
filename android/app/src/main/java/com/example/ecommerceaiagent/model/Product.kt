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
    val product_url: String = ""
)