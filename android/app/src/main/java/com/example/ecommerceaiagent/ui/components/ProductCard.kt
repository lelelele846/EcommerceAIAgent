package com.example.ecommerceaiagent.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.example.ecommerceaiagent.model.Product
import com.example.ecommerceaiagent.theme.*

@Composable
fun ProductCardView(
    product: Product,
    onClick: (() -> Unit)? = null,
    onAddToCart: ((Product) -> Unit)? = null,
) {
    Surface(
        modifier = Modifier.fillMaxWidth().clickable { onClick?.invoke() },
        color = Background,
        shape = RoundedCornerShape(14.dp),
        shadowElevation = 1.dp
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(
                    color = Color(0xFFF2F2F2),
                    shape = RoundedCornerShape(10.dp),
                    modifier = Modifier.size(76.dp)
                ) {
                    if (product.image_url.isNotEmpty()) {
                        AsyncImage(model = product.image_url, contentDescription = product.name,
                            contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                    } else {
                        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                            Text(product.brand.take(2).ifEmpty { "商" }, fontSize = 18.sp,
                                fontWeight = FontWeight.Bold, color = Color(0xFFCCCCCC))
                        }
                    }
                }
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    if (product.brand.isNotEmpty()) {
                        Text(product.brand, fontSize = 11.sp, color = TextHint, fontWeight = FontWeight.Medium, letterSpacing = 0.5.sp)
                        Spacer(Modifier.height(3.dp))
                    }
                    Text(product.name, fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
                        color = TextPrimary, maxLines = 2, overflow = TextOverflow.Ellipsis, lineHeight = 21.sp)
                    Spacer(Modifier.height(6.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.Star, null, tint = Color(0xFFF59E0B), modifier = Modifier.size(14.dp))
                        Spacer(Modifier.width(3.dp))
                        Text("${product.rating}", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = TextPrimary)
                        Spacer(Modifier.width(3.dp))
                        Text("(${product.review_count})", fontSize = 11.sp, color = TextHint)
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                Text(if (product.price > 0) "¥${String.format("%.2f", product.price)}" else "价格待定",
                    fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color(0xFFDC2626))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    val orange = Color(0xFFFF7043)
                    val orangeLight = Color(0xFFFFF0E6)
                    if (onAddToCart != null) {
                        Surface(
                            color = orange,
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier.clickable { onAddToCart(product) }
                        ) {
                            Text("加购", fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                                color = Color.White,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 7.dp))
                        }
                    }
                    Surface(color = orangeLight, shape = RoundedCornerShape(8.dp)) {
                        Text("查看详情", fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                            color = orange,
                            modifier = Modifier.padding(horizontal = 14.dp, vertical = 7.dp))
                    }
                }
            }
        }
    }
}
