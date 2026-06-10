package com.example.ecommerceaiagent

import android.os.Bundle
import android.util.Log
import android.view.MotionEvent
import android.view.Window
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import com.example.ecommerceaiagent.theme.EcommerceAITheme
import com.example.ecommerceaiagent.theme.Background
import com.example.ecommerceaiagent.ui.ChatScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            EcommerceAITheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = Background
                ) {
                    ChatScreen()
                }
            }
        }

        // 修复 Compose 已知 bug (b/277938898)：
        // 在 Window.Callback 层拦截所有 ACTION_HOVER_* 事件，
        // 阻止其进入 AndroidComposeView，避免异步 Handler 回调中抛出
        // "The ACTION_HOVER_EXIT event was not cleared."
        // 注意：dispatchGenericMotionEvent 的 try-catch 抓不到异常，
        // 因为 sendHoverExitEvent 通过 handler.post 异步执行。
        wrapWindowCallbackForHoverCrash()
    }

    private fun wrapWindowCallbackForHoverCrash() {
        val original = window.callback ?: return
        window.callback = object : Window.Callback by original {
            override fun dispatchGenericMotionEvent(event: MotionEvent?): Boolean {
                if (event != null) {
                    val action = event.action
                    if (action == MotionEvent.ACTION_HOVER_ENTER
                        || action == MotionEvent.ACTION_HOVER_EXIT
                        || action == MotionEvent.ACTION_HOVER_MOVE
                    ) {
                        // 拦截 hover 事件，不传给 ComposeView
                        return true
                    }
                }
                return try {
                    original.dispatchGenericMotionEvent(event)
                } catch (e: IllegalStateException) {
                    if (e.message?.contains("ACTION_HOVER_EXIT") == true) {
                        Log.w("MainActivity", "已拦截 Compose hover 崩溃(兜底)", e)
                        false
                    } else throw e
                }
            }
        }
    }
}
