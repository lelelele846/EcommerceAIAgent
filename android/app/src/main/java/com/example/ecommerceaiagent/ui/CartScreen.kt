package com.example.ecommerceaiagent.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.example.ecommerceaiagent.model.CartItem
import com.example.ecommerceaiagent.viewmodel.CartViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CartScreen(
    sessionId: String,
    cartViewModel: CartViewModel,
    onBack: () -> Unit,
    onCheckout: () -> Unit = {}
) {
    val cart by cartViewModel.cartState.collectAsState()

    // 加载购物车
    androidx.compose.runtime.LaunchedEffect(sessionId) {
        cartViewModel.loadCart(sessionId)
    }

    Scaffold(
        topBar = {
            Surface(color = Color.White, shadowElevation = 1.dp) {
                Row(
                    Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 4.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, "返回", tint = Color(0xFF333333))
                    }
                    Text("购物车 (${cart.count})", fontSize = 18.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF333333))
                }
            }
        },
        bottomBar = {
            if (cart.items.isNotEmpty()) {
                Surface(
                    modifier = Modifier.fillMaxWidth().navigationBarsPadding(),
                    shadowElevation = 8.dp,
                    color = Color.White
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp, vertical = 12.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column {
                            Text("合计", fontSize = 13.sp, color = Color.Gray)
                            Text(
                                "¥${"%.2f".format(cart.total)}",
                                fontSize = 20.sp,
                                fontWeight = FontWeight.Bold,
                                color = Color(0xFFE53935)
                            )
                        }
                        Button(
                            onClick = onCheckout,
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.buttonColors(
                                containerColor = Color(0xFFFF7043)
                            )
                        ) {
                            Text("去结算", fontSize = 16.sp)
                        }
                    }
                }
            }
        }
    ) { padding ->
        if (cart.items.isEmpty()) {
            // 空态
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Icon(
                    Icons.Default.ShoppingCart,
                    contentDescription = null,
                    modifier = Modifier.size(64.dp),
                    tint = Color.LightGray
                )
                Spacer(Modifier.height(16.dp))
                Text(
                    "购物车是空的",
                    fontSize = 18.sp,
                    color = Color.Gray,
                    fontWeight = FontWeight.Medium
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    "对我说「加购物车」把商品放进来吧～",
                    fontSize = 14.sp,
                    color = Color.LightGray
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                contentPadding = PaddingValues(12.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                itemsIndexed(cart.items) { index, item ->
                    CartItemRow(
                        item = item,
                        onQuantityChange = { newQty ->
                            cartViewModel.updateQuantity(sessionId, index, newQty)
                        },
                        onDelete = {
                            cartViewModel.removeFromCart(sessionId, index)
                        }
                    )
                }
            }
        }
    }
}

@Composable
fun CartItemRow(
    item: CartItem,
    onQuantityChange: (Int) -> Unit,
    onDelete: () -> Unit
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        color = Color.White,
        shadowElevation = 1.dp
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // 商品图片
            AsyncImage(
                model = ImageRequest.Builder(
                    androidx.compose.ui.platform.LocalContext.current
                )
                    .data(item.image_url.ifBlank { null })
                    .crossfade(true)
                    .build(),
                contentDescription = item.name,
                modifier = Modifier
                    .size(72.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(Color(0xFFF5F5F5)),
                contentScale = ContentScale.Crop
            )

            Spacer(Modifier.width(12.dp))

            // 商品信息
            Column(modifier = Modifier.weight(1f)) {
                if (item.brand.isNotBlank()) {
                    Text(
                        item.brand,
                        fontSize = 12.sp,
                        color = Color.Gray
                    )
                }
                Text(
                    item.name,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Medium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "¥${"%.2f".format(item.price)}",
                        fontSize = 16.sp,
                        fontWeight = FontWeight.Bold,
                        color = Color(0xFFE53935)
                    )
                    Spacer(Modifier.width(12.dp))
                    // 数量步进器
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        IconButton(
                            onClick = { onQuantityChange(item.quantity - 1) },
                            modifier = Modifier.size(28.dp)
                        ) {
                            Icon(Icons.Default.Remove, "减", modifier = Modifier.size(16.dp))
                        }
                        Text(
                            "${item.quantity}",
                            fontSize = 14.sp,
                            fontWeight = FontWeight.Medium,
                            modifier = Modifier.padding(horizontal = 4.dp)
                        )
                        IconButton(
                            onClick = { onQuantityChange(item.quantity + 1) },
                            modifier = Modifier.size(28.dp)
                        ) {
                            Icon(Icons.Default.Add, "加", modifier = Modifier.size(16.dp))
                        }
                    }
                }
            }

            // 删除按钮
            IconButton(onClick = onDelete) {
                Icon(
                    Icons.Default.Delete,
                    "删除",
                    tint = Color.LightGray,
                    modifier = Modifier.size(22.dp)
                )
            }
        }
    }
}
