package com.example.ecommerceaiagent.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.ecommerceaiagent.model.Product

/**
 * 商品对比卡片：表格形式展示 2-3 款商品在多维度上的对比
 */
@Composable
fun ComparisonCard(
    products: List<Product>,
    aiAnalysis: String = "",
    modifier: Modifier = Modifier
) {
    if (products.size < 2) return

    val scrollState = rememberScrollState()
    val accentColor = Color(0xFFFF5C5C)
    val tableBg = Color(0xFFFAFAFA)
    val headerBg = Color(0xFFF0F0F0)
    val highlightBg = Color(0xFFFFF5F5)

    Surface(
        modifier = modifier.fillMaxWidth(),
        color = Color.White,
        shape = RoundedCornerShape(14.dp),
        shadowElevation = 2.dp
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            // 标题
            Text(
                "📊 商品对比",
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold,
                color = Color(0xFF1A1A1A)
            )
            Spacer(Modifier.height(12.dp))

            // 表格容器（可横向滚动）
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(scrollState)
            ) {
                Column {
                    // ── 表头行 ──
                    Row(modifier = Modifier.fillMaxWidth()) {
                        // 维度列标题
                        Box(
                            modifier = Modifier
                                .width(70.dp)
                                .height(40.dp)
                                .background(headerBg),
                            contentAlignment = Alignment.Center
                        ) {
                            Text("", fontSize = 12.sp, fontWeight = FontWeight.Bold)
                        }
                        // 商品列标题
                        products.forEach { p ->
                            Box(
                                modifier = Modifier
                                    .width(110.dp)
                                    .height(40.dp)
                                    .background(headerBg),
                                contentAlignment = Alignment.Center
                            ) {
                                Text(
                                    p.name.take(8) + if (p.name.length > 8) "…" else "",
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Bold,
                                    color = Color(0xFF1A1A1A),
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis
                                )
                            }
                        }
                    }

                    // ── 价格行 ──
                    TableRow("价格", 70.dp, headerBg, products, 110.dp, tableBg) { p ->
                        Text(
                            if (p.price > 0) "¥${String.format("%.0f", p.price)}" else "暂无",
                            fontSize = 14.sp,
                            fontWeight = FontWeight.Bold,
                            color = accentColor
                        )
                    }

                    // ── 品牌行 ──
                    TableRow("品牌", 70.dp, headerBg, products, 110.dp, tableBg) { p ->
                        Text(
                            p.brand.ifEmpty { "-" },
                            fontSize = 12.sp,
                            color = Color(0xFF555555)
                        )
                    }

                    // ── 评分行 ──
                    TableRow("评分", 70.dp, headerBg, products, 110.dp, tableBg) { p ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("⭐", fontSize = 12.sp)
                            Spacer(Modifier.width(2.dp))
                            Text(
                                "${p.rating}",
                                fontSize = 13.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = Color(0xFFF59E0B)
                            )
                            Text(
                                " (${p.review_count})",
                                fontSize = 10.sp,
                                color = Color(0xFF999999)
                            )
                        }
                    }

                    // ── 描述行 ──
                    TableRow("特点", 70.dp, headerBg, products, 110.dp, tableBg) { p ->
                        Text(
                            p.description.take(50) + if (p.description.length > 50) "…" else "",
                            fontSize = 11.sp,
                            color = Color(0xFF666666),
                            maxLines = 3,
                            overflow = TextOverflow.Ellipsis
                        )
                    }
                }
            }

            // ── AI 分析文字 ──
            if (aiAnalysis.isNotEmpty()) {
                Spacer(Modifier.height(12.dp))
                Divider(color = Color(0xffeeeeee))
                Spacer(Modifier.height(10.dp))
                Text(
                    aiAnalysis,
                    fontSize = 14.sp,
                    color = Color(0xFF333333),
                    lineHeight = 22.sp
                )
            }
        }
    }
}

@Composable
private fun TableRow(
    label: String,
    labelWidth: androidx.compose.ui.unit.Dp,
    labelBg: Color,
    products: List<Product>,
    colWidth: androidx.compose.ui.unit.Dp,
    cellBg: Color,
    cellContent: @Composable (Product) -> Unit
) {
    Row(modifier = Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .width(labelWidth)
                .height(44.dp)
                .background(labelBg),
            contentAlignment = Alignment.CenterStart
        ) {
            Text(
                label,
                fontSize = 11.sp,
                fontWeight = FontWeight.Medium,
                color = Color(0xFF888888),
                modifier = Modifier.padding(start = 8.dp)
            )
        }
        products.forEachIndexed { i, p ->
            Box(
                modifier = Modifier
                    .width(colWidth)
                    .height(44.dp)
                    .background(if (i % 2 == 0) cellBg else Color.White),
                contentAlignment = Alignment.Center
            ) {
                cellContent(p)
            }
        }
    }
}
