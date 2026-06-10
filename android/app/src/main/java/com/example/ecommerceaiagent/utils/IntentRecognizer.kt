package com.example.ecommerceaiagent.utils

enum class UserIntent {
    GREETING,        // 打招呼
    CASUAL_BROWSE,   // 随便看看
    INQUIRY          // 一般询问（含购买意图，转发服务端处理）
}

object IntentRecognizer {

    // 检测打招呼意图
    private val greetingKeywords = listOf("你好", "您好", "嗨", "哈喽", "hi", "hello", "早上好", "晚上好", "下午好", "在吗", "有人吗")

    // 检测随便看看意图
    private val casualKeywords = listOf("看看", "浏览", "逛逛", "了解一下", "了解下", "随便看看", "随便逛逛", "有什么", "有哪些", "都有什么")

    fun recognizeIntent(text: String): UserIntent {
        val lowerText = text.toLowerCase()

        // 1. 检测打招呼意图
        for (keyword in greetingKeywords) {
            if (lowerText.contains(keyword)) {
                // 如果只是单纯打招呼，返回 GREETING
                if (text.length <= 10 || (text.length <= 20 && text.matches(Regex("[\\u4e00-\\u9fa5\\w\\s]+[！!。.?？]$")))) {
                    return UserIntent.GREETING
                }
            }
        }

        // 2. 检测随便看看意图
        for (keyword in casualKeywords) {
            if (lowerText.contains(keyword)) {
                return UserIntent.CASUAL_BROWSE
            }
        }

        // 默认返回一般询问（含商品搜索/推荐/对比等，转发服务端处理）
        return UserIntent.INQUIRY
    }

    fun getIntentResponse(intent: UserIntent): String {
        return when (intent) {
            UserIntent.GREETING -> {
                "你好呀！很高兴为你服务～请问有什么可以帮到你的吗？😊"
            }
            UserIntent.CASUAL_BROWSE -> {
                "好的呀！请问你想了解哪一类产品呢？比如数码产品、美妆护肤、食品零食等等？"
            }
            UserIntent.INQUIRY -> {
                ""
            }
        }
    }
}