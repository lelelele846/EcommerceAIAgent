package com.example.ecommerceaiagent.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.ecommerceaiagent.model.CartState
import com.example.ecommerceaiagent.repository.CartRepository
import com.example.ecommerceaiagent.utils.AddressStorage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
private fun InfoRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, fontSize = 14.sp, color = Color.Gray)
        Text(value, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = Color(0xFF333333))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OrderFormScreen(
    sessionId: String,
    cart: CartState,
    onBack: () -> Unit,
    onOrderPlaced: () -> Unit
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val orange = Color(0xFFFF7043)

    // 步骤：confirm_items → fill_address → done
    var step by remember { mutableStateOf("confirm_items") }
    var orderId by remember { mutableStateOf<String?>(null) }
    var isSubmitting by remember { mutableStateOf(false) }
    var errorMsg by remember { mutableStateOf<String?>(null) }

    // 地址表单
    val savedAddresses = remember { AddressStorage.load(context) }
    var name by remember { mutableStateOf("") }
    var phone by remember { mutableStateOf("") }
    var address by remember { mutableStateOf("") }

    val fieldColors = OutlinedTextFieldDefaults.colors(
        focusedBorderColor = orange,
        unfocusedBorderColor = orange.copy(alpha = 0.4f),
        focusedLabelColor = orange,
        cursorColor = orange
    )

    fun submitOrder() {
        val addr = buildString {
            if (name.isNotBlank()) append(name)
            if (phone.isNotBlank()) { if (isNotEmpty()) append(" "); append(phone) }
            if (address.isNotBlank()) { if (isNotEmpty()) append("，"); append(address) }
        }
        if (addr.isBlank()) { errorMsg = "请填写收货信息"; return }
        isSubmitting = true
        scope.launch {
            val repo = CartRepository()
            val result = withContext(Dispatchers.IO) { repo.placeOrder(sessionId, addr) }
            isSubmitting = false
            if (result != null) {
                AddressStorage.save(context, name, phone, address)
                orderId = result.orderId
                step = "done"
            } else {
                errorMsg = "下单失败，请重试"
            }
        }
    }

    fun fillFromSaved(addr: AddressStorage.SavedAddress) {
        name = addr.name
        phone = addr.phone
        address = addr.address
    }

    if (step == "done" && orderId != null) {
        Column(
            Modifier.fillMaxSize().background(Color.White).statusBarsPadding()
        ) {
            // 顶部栏
            Surface(color = Color.White, shadowElevation = 1.dp) {
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    IconButton(onClick = onOrderPlaced) {
                        Icon(Icons.Default.ArrowBack, "返回", tint = Color(0xFF333333))
                    }
                    Text("订单详情", fontSize = 18.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF333333))
                }
            }

            // 成功标识
            Column(
                Modifier.weight(1f).fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Icon(Icons.Default.CheckCircle, null, tint = Color(0xFF16A34A), modifier = Modifier.size(72.dp))
                Spacer(Modifier.height(16.dp))
                Text("下单成功", fontSize = 22.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(24.dp))

                // 订单信息卡片
                Surface(Modifier.fillMaxWidth().padding(horizontal = 24.dp), shape = RoundedCornerShape(14.dp), color = Color(0xFFFAFAFA)) {
                    Column(Modifier.padding(20.dp)) {
                        InfoRow("订单编号", orderId ?: "")
                        HorizontalDivider(modifier = Modifier.padding(vertical = 10.dp), color = Color(0xFFEEEEEE))
                        InfoRow("订单状态", "已确认")
                        HorizontalDivider(modifier = Modifier.padding(vertical = 10.dp), color = Color(0xFFEEEEEE))
                        InfoRow("商品数量", "${cart.items.size} 件")
                        HorizontalDivider(modifier = Modifier.padding(vertical = 10.dp), color = Color(0xFFEEEEEE))
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("合计", fontSize = 15.sp, color = Color.Gray)
                            Text("¥${"%.2f".format(cart.total)}", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = Color(0xFFE53935))
                        }
                    }
                }

                Spacer(Modifier.height(24.dp))
                // 商品清单
                Surface(Modifier.fillMaxWidth().padding(horizontal = 24.dp), shape = RoundedCornerShape(14.dp), color = Color(0xFFFAFAFA)) {
                    Column(Modifier.padding(16.dp)) {
                        Text("商品清单", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Color(0xFF333333))
                        Spacer(Modifier.height(8.dp))
                        cart.items.forEach { item ->
                            Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                                Text("${item.name} x${item.quantity}", fontSize = 13.sp, modifier = Modifier.weight(1f), color = Color(0xFF666666))
                                Text("¥${"%.2f".format(item.price * item.quantity)}", fontSize = 13.sp)
                            }
                        }
                    }
                }
            }

            // 底部返回按钮
            Surface(Modifier.fillMaxWidth().navigationBarsPadding(), shadowElevation = 8.dp, color = Color.White) {
                Button(
                    onClick = onOrderPlaced,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp).height(48.dp),
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = orange)
                ) {
                    Text("返回继续购物", fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                }
            }
        }
        return
    }

    Scaffold(
        topBar = {
            Surface(color = Color.White, shadowElevation = 1.dp) {
                Row(
                    Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 4.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    IconButton(onClick = {
                        if (step == "fill_address") step = "confirm_items" else onBack()
                    }) {
                        Icon(Icons.Default.ArrowBack, "返回", tint = Color(0xFF333333))
                    }
                    Text(
                        if (step == "confirm_items") "确认订单" else "收货信息",
                        fontSize = 18.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF333333)
                    )
                }
            }
        }
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 12.dp)
        ) {
            if (step == "confirm_items") {
                Text("商品信息", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = Color(0xFF333333))
                Spacer(Modifier.height(12.dp))
                Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp), color = Color(0xFFFAFAFA)) {
                    Column(Modifier.padding(14.dp)) {
                        cart.items.forEachIndexed { i, item ->
                            Row(
                                Modifier.fillMaxWidth().padding(vertical = 6.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Column(Modifier.weight(1f)) {
                                    Text(item.name, fontSize = 15.sp, fontWeight = FontWeight.Medium)
                                    Text("x${item.quantity}", fontSize = 13.sp, color = Color.Gray)
                                }
                                Text(
                                    "¥${"%.2f".format(item.price * item.quantity)}",
                                    fontSize = 15.sp, fontWeight = FontWeight.SemiBold
                                )
                            }
                            if (i < cart.items.lastIndex) {
                                HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp), color = Color(0xFFEEEEEE))
                            }
                        }
                    }
                }

                Spacer(Modifier.height(16.dp))
                Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp), color = Color(0xFFFAFAFA)) {
                    Row(Modifier.fillMaxWidth().padding(14.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("合计", fontSize = 16.sp, fontWeight = FontWeight.Bold)
                        Text("¥${"%.2f".format(cart.total)}", fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Color(0xFFE53935))
                    }
                }

                Spacer(Modifier.height(24.dp))
                Button(
                    onClick = { step = "fill_address" },
                    modifier = Modifier.fillMaxWidth().height(50.dp),
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = orange)
                ) {
                    Text("确认无误，填写收货信息", fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                }
            } else {

                // 已保存地址卡片
                if (savedAddresses.isNotEmpty()) {
                    Text("历史地址", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = Color(0xFF333333))
                    Spacer(Modifier.height(10.dp))
                    savedAddresses.forEach { addr ->
                        Surface(
                            Modifier.fillMaxWidth().padding(vertical = 4.dp).clickable { fillFromSaved(addr) },
                            shape = RoundedCornerShape(10.dp),
                            color = if (addr.address == address) orange.copy(alpha = 0.1f) else Color(0xFFFAFAFA),
                            border = if (addr.address == address) androidx.compose.foundation.BorderStroke(1.dp, orange) else null
                        ) {
                            Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Default.LocationOn, null, tint = orange, modifier = Modifier.size(20.dp))
                                Spacer(Modifier.width(8.dp))
                                Text(addr.toLabel(), fontSize = 14.sp, modifier = Modifier.weight(1f), lineHeight = 20.sp)
                            }
                        }
                    }
                    Spacer(Modifier.height(16.dp))
                    Text("或填写新地址", fontSize = 14.sp, color = Color.Gray)
                    Spacer(Modifier.height(8.dp))
                } else {
                    Text("收货信息", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = Color(0xFF333333))
                    Spacer(Modifier.height(10.dp))
                }

                Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp), color = Color(0xFFFAFAFA)) {
                    Column(Modifier.padding(12.dp)) {
                        OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), singleLine = true,
                            shape = RoundedCornerShape(10.dp), colors = fieldColors,
                            label = { Text("收货人") },
                            textStyle = LocalTextStyle.current.copy(fontSize = 15.sp))
                        Spacer(Modifier.height(10.dp))
                        OutlinedTextField(phone, { phone = it }, Modifier.fillMaxWidth(), singleLine = true,
                            shape = RoundedCornerShape(10.dp), colors = fieldColors,
                            label = { Text("手机号") },
                            textStyle = LocalTextStyle.current.copy(fontSize = 15.sp))
                        Spacer(Modifier.height(10.dp))
                        OutlinedTextField(address, { address = it }, Modifier.fillMaxWidth(), minLines = 2,
                            shape = RoundedCornerShape(10.dp), colors = fieldColors,
                            label = { Text("详细地址") },
                            textStyle = LocalTextStyle.current.copy(fontSize = 15.sp))
                    }
                }

                if (errorMsg != null) {
                    Spacer(Modifier.height(12.dp))
                    Text(errorMsg!!, color = Color(0xFFDC2626), fontSize = 14.sp)
                }

                Spacer(Modifier.height(20.dp))
                Button(
                    onClick = { submitOrder() },
                    modifier = Modifier.fillMaxWidth().height(50.dp),
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = orange),
                    enabled = !isSubmitting
                ) {
                    if (isSubmitting) {
                        CircularProgressIndicator(color = Color.White, modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(8.dp))
                    }
                    Text("提交订单", fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                }

                Spacer(Modifier.height(16.dp))
            }
        }
    }
}
