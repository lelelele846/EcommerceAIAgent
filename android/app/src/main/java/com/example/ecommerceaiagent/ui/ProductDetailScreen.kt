package com.example.ecommerceaiagent.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.example.ecommerceaiagent.model.Product

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductDetailScreen(
    product: Product,
    onBack: () -> Unit,
    onAddToCart: (Product) -> Unit,
    onBuyNow: (Product) -> Unit
) {
    val orange = Color(0xFFFF7043)
    val scrollState = rememberScrollState()

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
                    Text(product.name, fontSize = 17.sp, fontWeight = FontWeight.SemiBold,
                        color = Color(0xFF333333), maxLines = 1, overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f))
                }
            }
        },
        bottomBar = {
            Surface(Modifier.fillMaxWidth().navigationBarsPadding(), shadowElevation = 8.dp, color = Color.White) {
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column(Modifier.weight(1f)) {
                        Text("¥${"%.2f".format(product.price)}", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color(0xFFE53935))
                        if (product.brand.isNotEmpty()) Text(product.brand, fontSize = 12.sp, color = Color.Gray)
                    }
                    OutlinedButton(
                        onClick = { onAddToCart(product) },
                        shape = RoundedCornerShape(10.dp),
                        border = androidx.compose.foundation.BorderStroke(1.dp, orange)
                    ) {
                        Text("加入购物车", color = orange, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                    }
                    Button(
                        onClick = { onBuyNow(product) },
                        shape = RoundedCornerShape(10.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = orange)
                    ) {
                        Text("立即下单", fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                    }
                }
            }
        }
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).verticalScroll(scrollState)) {
            AsyncImage(
                model = ImageRequest.Builder(androidx.compose.ui.platform.LocalContext.current)
                    .data(product.image_url).crossfade(true).build(),
                contentDescription = product.name,
                modifier = Modifier.fillMaxWidth().aspectRatio(1f).background(Color(0xFFF5F5F5)),
                contentScale = ContentScale.Crop
            )
            Column(Modifier.padding(16.dp)) {
                if (product.brand.isNotEmpty()) {
                    Text(product.brand, fontSize = 13.sp, color = Color.Gray)
                    Spacer(Modifier.height(4.dp))
                }
                Text(product.name, fontSize = 18.sp, fontWeight = FontWeight.Bold, lineHeight = 26.sp)
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.Star, null, tint = Color(0xFFF59E0B), modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("${product.rating}", fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.width(4.dp))
                    Text("(${product.review_count} 评价)", fontSize = 13.sp, color = Color.Gray)
                }
            }

            if (product.description.isNotBlank()) {
                Spacer(Modifier.height(12.dp))
                Text(product.description, fontSize = 14.sp, color = Color(0xFF555555),
                    lineHeight = 24.sp, modifier = Modifier.padding(horizontal = 16.dp))
            }

            Spacer(Modifier.height(16.dp))
            HorizontalDivider(modifier = Modifier.padding(horizontal = 16.dp))
            Spacer(Modifier.height(8.dp))

            Text("用户评价", fontSize = 17.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))

            if (product.reviews.isEmpty()) {
                Text("暂无评价", fontSize = 14.sp, color = Color.Gray, modifier = Modifier.padding(horizontal = 16.dp))
            } else {
                Column(Modifier.padding(horizontal = 16.dp)) {
                    product.reviews.forEach { review ->
                        Surface(
                            Modifier.fillMaxWidth().padding(vertical = 4.dp),
                            shape = RoundedCornerShape(10.dp),
                            color = Color(0xFFFAFAFA)
                        ) {
                            Column(Modifier.padding(14.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(review.nickname, fontSize = 14.sp, fontWeight = FontWeight.Medium)
                                    Spacer(Modifier.width(8.dp))
                                    repeat(review.rating) {
                                        Icon(Icons.Default.Star, null,
                                            tint = Color(0xFFF59E0B), modifier = Modifier.size(13.dp))
                                    }
                                }
                                Spacer(Modifier.height(6.dp))
                                Text(review.content, fontSize = 13.sp, color = Color(0xFF666666), lineHeight = 20.sp)
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.height(80.dp))
        }
    }
}
