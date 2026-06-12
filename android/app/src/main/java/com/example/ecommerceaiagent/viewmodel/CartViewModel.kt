package com.example.ecommerceaiagent.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.ecommerceaiagent.model.CartItem
import com.example.ecommerceaiagent.model.CartState
import com.example.ecommerceaiagent.repository.CartRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class CartViewModel : ViewModel() {

    private val _cartState = MutableStateFlow(CartState())
    val cartState: StateFlow<CartState> = _cartState.asStateFlow()

    private val _toastMessage = MutableStateFlow<String?>(null)
    val toastMessage: StateFlow<String?> = _toastMessage.asStateFlow()

    private val repo = CartRepository()

    fun updateFromSse(items: List<CartItem>, total: Double, count: Int, action: String) {
        _cartState.value = CartState(items = items, total = total, count = count, action = action)
        when (action) {
            "add" -> _toastMessage.value = "已加入购物车"
            "remove" -> _toastMessage.value = "已从购物车移除"
            "clear" -> _toastMessage.value = "购物车已清空"
            "ordered" -> _toastMessage.value = "下单成功！"
        }
    }

    fun clearToast() { _toastMessage.value = null }

    fun loadCart(sessionId: String) {
        viewModelScope.launch(Dispatchers.IO) {
            repo.getCart(sessionId)?.let { _cartState.value = it }
        }
    }

    fun addToCart(sessionId: String, productId: String) {
        viewModelScope.launch(Dispatchers.IO) {
            repo.addToCart(sessionId, productId)?.let {
                _cartState.value = it
                _toastMessage.value = "已加入购物车"
            }
        }
    }

    fun removeFromCart(sessionId: String, index: Int) {
        viewModelScope.launch(Dispatchers.IO) {
            repo.removeFromCart(sessionId, index)?.let {
                _cartState.value = it
                _toastMessage.value = "已从购物车移除"
            }
        }
    }

    fun updateQuantity(sessionId: String, index: Int, quantity: Int) {
        viewModelScope.launch(Dispatchers.IO) {
            if (quantity <= 0) {
                repo.removeFromCart(sessionId, index)?.let { _cartState.value = it }
            } else {
                repo.updateQuantity(sessionId, index, quantity)?.let { _cartState.value = it }
            }
        }
    }
}
