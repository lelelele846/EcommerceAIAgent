package com.example.ecommerceaiagent.ui

import android.Manifest
import android.content.pm.PackageManager
import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.StartOffset
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Send

import androidx.compose.material.icons.filled.VolumeOff
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import com.example.ecommerceaiagent.R
import com.example.ecommerceaiagent.model.MessageItem
import com.example.ecommerceaiagent.model.MessageItem.ContentBlock
import com.example.ecommerceaiagent.theme.*
import com.example.ecommerceaiagent.ui.components.ComparisonCard
import com.example.ecommerceaiagent.ui.components.ProductCardView
import com.example.ecommerceaiagent.utils.TtsManager
import com.example.ecommerceaiagent.viewmodel.ChatViewModel
import java.io.File

private val SUGGESTED_QUESTIONS = listOf(
    "推荐适合油皮的洗面奶",
    "200元以内的蓝牙耳机",
    "帮我推荐一双轻量跑鞋",
    "适合干皮的保湿面霜",
    "性价比高的降噪耳机",
    "适合夏天的防晒霜推荐"
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(chatViewModel: ChatViewModel = viewModel()) {
    val listState = rememberLazyListState()
    val context = LocalContext.current
    val focusManager = LocalFocusManager.current

    val messages by chatViewModel.messages.collectAsState()
    val isAiTyping by chatViewModel.isAiTyping.collectAsState()
    val scrollTick by chatViewModel.scrollTick.collectAsState()
    val isBusy = isAiTyping || messages.any { it is MessageItem.TypingIndicator }

    // ── TTS（文字转语音）──────────────────────────────────────
    var ttsEnabled by remember { mutableStateOf(false) }
    val ttsManager = remember { TtsManager(context) }
    DisposableEffect(Unit) {
        onDispose { ttsManager.shutdown() }
    }
    var lastSpokenText by remember { mutableStateOf("") }
    var prevLoading by remember { mutableStateOf(false) }

    // AI 回复完成后自动播报
    LaunchedEffect(isAiTyping) {
        if (prevLoading && !isAiTyping && ttsEnabled) {
            val lastMsg = messages.lastOrNull()
            if (lastMsg is MessageItem.AiMessage && lastMsg.isComplete) {
                val text = lastMsg.contentBlocks
                    .filterIsInstance<ContentBlock.TextBlock>()
                    .joinToString(" ") { it.text }
                val clean = stripMarkdown(text)
                if (clean.isNotBlank() && clean != lastSpokenText) {
                    ttsManager.speak(clean)
                    lastSpokenText = clean
                }
            }
        }
        prevLoading = isAiTyping
    }

    // 切换会话时重置，避免旧内容被误判"已播过"
    LaunchedEffect(chatViewModel.sessionId) {
        lastSpokenText = ""
    }

    // Toast 消息监听
    val toastMessage by chatViewModel.toastMessage.collectAsState()
    LaunchedEffect(toastMessage) {
        if (toastMessage.isNotEmpty()) {
            Toast.makeText(context, toastMessage, Toast.LENGTH_SHORT).show()
            chatViewModel.clearToast()
        }
    }

    var inputText by remember { mutableStateOf("") }
    var showBottomSheet by remember { mutableStateOf(false) }
    var cameraImageFile by remember { mutableStateOf<File?>(null) }
    var pendingImageUri by remember { mutableStateOf<Uri?>(null) }        // 待发送的相册图片
    var pendingCameraFile by remember { mutableStateOf<File?>(null) }     // 待发送的拍照图片
    var fullScreenImage by remember { mutableStateOf<String?>(null) }  // 全屏查看图片

    val showWelcome = messages.size <= 1 && !isAiTyping

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { perms ->
        if (!perms.all { it.value })
            Toast.makeText(context, "需要权限才能使用此功能", Toast.LENGTH_SHORT).show()
    }

    val latestBusy by rememberUpdatedState(isBusy)

    val imagePickerLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        if (uri != null) {
            pendingImageUri = uri
            pendingCameraFile = null
            inputText = ""  // 清空输入框，准备新消息
        }
    }

    val cameraLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.TakePicture()
    ) { success ->
        if (success) cameraImageFile?.let {
            pendingCameraFile = it
            pendingImageUri = null
            inputText = ""
        }
    }

    // 自动滚动：新卡片/组件出现时带动画滚动
    LaunchedEffect(scrollTick) {
        if (scrollTick > 0 && messages.isNotEmpty())
            listState.animateScrollToItem(messages.size - 1)
    }
    // 流式 token 逐字追加时即时跟滚（避免动画堆积卡顿）
    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.size - 1)
    }
    val lastStreamingText = (messages.lastOrNull() as? MessageItem.AiMessage)
        ?.takeIf { it.isStreaming && it.contentBlocks.isNotEmpty() }
        ?.contentBlocks?.filterIsInstance<ContentBlock.TextBlock>()?.lastOrNull()?.text
    LaunchedEffect(lastStreamingText) {
        if (!lastStreamingText.isNullOrEmpty())
            listState.scrollToItem(messages.size - 1)
    }

    fun launchCamera() {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED
        ) { permissionLauncher.launch(arrayOf(Manifest.permission.CAMERA)); return }
        try {
            val file = File(context.cacheDir, "photo_${System.currentTimeMillis()}.jpg")
            cameraImageFile = file
            cameraLauncher.launch(
                FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
            )
        } catch (e: Exception) {
            Toast.makeText(context, "无法启动相机", Toast.LENGTH_SHORT).show()
        }
    }

    fun sendMessage() {
        val hasText = inputText.isNotBlank()
        val hasImage = pendingImageUri != null || pendingCameraFile != null
        if (!hasText && !hasImage) return
        if (isBusy) {
            Toast.makeText(context, "AI还在说话哦，请先别打断它～", Toast.LENGTH_SHORT).show()
            return
        }
        // 带图片发送
        if (hasImage) {
            pendingImageUri?.let { chatViewModel.sendImageMessage(context, it, inputText) }
            pendingCameraFile?.let { chatViewModel.sendCameraImage(context, it, inputText) }
            pendingImageUri = null
            pendingCameraFile = null
        } else {
            chatViewModel.sendUserMessage(inputText)
        }
        inputText = ""
        focusManager.clearFocus()
    }

    // ── BottomSheet ──
    if (showBottomSheet) {
        ModalBottomSheet(
            onDismissRequest = { showBottomSheet = false },
            containerColor = Surface,
            shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp),
            dragHandle = null
        ) {
            Column(modifier = Modifier.padding(bottom = 48.dp)) {
                Box(
                    Modifier.padding(top = 12.dp, bottom = 20.dp).align(Alignment.CenterHorizontally)
                        .width(40.dp).height(5.dp).clip(RoundedCornerShape(3.dp)).background(Divider)
                )
                Text("选择功能", fontWeight = FontWeight.SemiBold, fontSize = 20.sp, color = TextPrimary, modifier = Modifier.padding(horizontal = 28.dp, vertical = 12.dp))

                Row(Modifier.fillMaxWidth().clickable { showBottomSheet = false; launchCamera() }.padding(horizontal = 28.dp, vertical = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(48.dp).clip(RoundedCornerShape(14.dp)).background(PrimaryContainer), contentAlignment = Alignment.Center) {
                        Icon(Icons.Default.Add, null, tint = Primary, modifier = Modifier.size(24.dp))
                    }
                    Spacer(Modifier.width(16.dp))
                    Column { Text("拍照找货", fontWeight = FontWeight.SemiBold, fontSize = 16.sp, color = TextPrimary); Text("拍摄实物，智能识别并推荐相似商品", fontSize = 13.sp, color = TextHint) }
                }

                HorizontalDivider(modifier = Modifier.padding(horizontal = 28.dp), color = Divider)

                Row(Modifier.fillMaxWidth().clickable { showBottomSheet = false; imagePickerLauncher.launch("image/*") }.padding(horizontal = 28.dp, vertical = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(48.dp).clip(RoundedCornerShape(14.dp)).background(Color(0xFFEEF2FF)), contentAlignment = Alignment.Center) {
                        Icon(Icons.Default.Add, null, tint = Color(0xFF6366F1), modifier = Modifier.size(24.dp))
                    }
                    Spacer(Modifier.width(16.dp))
                    Column { Text("上传图片", fontWeight = FontWeight.SemiBold, fontSize = 16.sp, color = TextPrimary); Text("从手机相册选择图片进行识别", fontSize = 13.sp, color = TextHint) }
                }
            }
        }
    }

    // ── 主布局 ──
    Box(modifier = Modifier.fillMaxSize().background(Background)) {
        Column(modifier = Modifier.fillMaxSize()) {
            TopBar(
                ttsEnabled = ttsEnabled,
                onTtsToggle = {
                    ttsEnabled = !ttsEnabled
                    if (!ttsEnabled) ttsManager.stop()
                },
            )
            Box(modifier = Modifier.weight(1f).fillMaxWidth()) {
                if (showWelcome) WelcomeScreen { chatViewModel.sendUserMessage(it) }
                else LazyColumn(
                    state = listState, modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 20.dp),
                    verticalArrangement = Arrangement.spacedBy(20.dp)
                ) {
                    itemsIndexed(messages, key = { index, _ -> index }) { _, msg ->
                        when (msg) {
                            is MessageItem.UserMessage -> UserBubble(msg, onImageClick = { fullScreenImage = it })
                            is MessageItem.AiMessage -> AiBubble(msg.contentBlocks, msg.isComplete, msg.isStreaming, onClarificationSelected = { chatViewModel.selectClarification(it) })
                            is MessageItem.StatusMessage -> StatusBubble(msg.message)
                            MessageItem.TypingIndicator -> TypingDots()
                        }
                    }
                }
            }

            // ── 待发送图片预览 ──
            val pendingImage = pendingImageUri ?: pendingCameraFile?.let { Uri.fromFile(it) }
            if (pendingImage != null) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(Color(0xFFF8F8F8))
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    AsyncImage(
                        model = pendingImage,
                        contentDescription = "待发送图片",
                        contentScale = ContentScale.Crop,
                        modifier = Modifier
                            .size(56.dp)
                            .clip(RoundedCornerShape(8.dp))
                    )
                    Spacer(Modifier.width(10.dp))
                    Text(
                        "图片已添加，可输入文字或直接发送",
                        fontSize = 13.sp,
                        color = TextHint,
                        modifier = Modifier.weight(1f)
                    )
                    IconButton(
                        onClick = {
                            pendingImageUri = null
                            pendingCameraFile = null
                        },
                        modifier = Modifier.size(32.dp)
                    ) {
                        Icon(Icons.Default.Close, "移除图片", tint = TextHint, modifier = Modifier.size(20.dp))
                    }
                }
            }

            val hasPendingImage = pendingImageUri != null || pendingCameraFile != null
            InputBar(
                inputText, { inputText = it }, { sendMessage() },
                onCameraClick = { showBottomSheet = true },
                isBusy = isBusy,
                hasPendingImage = hasPendingImage
            )
        }

        // ── 全屏图片查看 ──
        fullScreenImage?.let { imageUri ->
            FullScreenImageDialog(imageUri = imageUri, onDismiss = { fullScreenImage = null })
        }
    }
}

// ═══════════════════════════════
// TopBar — 极简，无多余元素
// ═══════════════════════════════
@Composable
private fun TopBar(
    ttsEnabled: Boolean = false,
    onTtsToggle: () -> Unit = {},
) {
    Surface(color = Surface, shadowElevation = 0.dp) {
        Row(
            Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 20.dp, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Image(painterResource(R.drawable.ai_avatar), "AI", Modifier.size(38.dp).clip(CircleShape), contentScale = ContentScale.Crop)
            Spacer(Modifier.width(10.dp))
            Text("AI 购物助手", fontSize = 16.sp, fontWeight = FontWeight.Medium, color = TextPrimary)
            Spacer(Modifier.weight(1f))
            IconButton(onClick = onTtsToggle) {
                Icon(
                    if (ttsEnabled) Icons.Filled.VolumeUp
                    else Icons.Filled.VolumeOff,
                    contentDescription = if (ttsEnabled) "关闭语音播报" else "开启语音播报",
                    tint = if (ttsEnabled) Primary else TextHint,
                )
            }
        }
    }
}

// ═══════════════════════════════
// Welcome — 干净开场
// ═══════════════════════════════
@Composable
private fun WelcomeScreen(onQuestionClick: (String) -> Unit) {
    Column(
        Modifier.fillMaxSize().padding(horizontal = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Image(painterResource(R.drawable.ai_avatar), "AI", Modifier.size(88.dp).clip(CircleShape), contentScale = ContentScale.Crop)
        Spacer(Modifier.height(24.dp))
        Text("你好，想买点什么？", fontSize = 26.sp, fontWeight = FontWeight.Bold, color = TextPrimary, textAlign = TextAlign.Center)
        Spacer(Modifier.height(10.dp))
        Text("AI 智能购物助手，随时帮你找到心仪好物", fontSize = 15.sp, color = TextSecondary, textAlign = TextAlign.Center)
        Spacer(Modifier.height(44.dp))
        Text("试试这样问我", fontSize = 13.sp, fontWeight = FontWeight.Medium, color = TextHint, modifier = Modifier.fillMaxWidth(), letterSpacing = 1.sp)
        Spacer(Modifier.height(14.dp))

        SUGGESTED_QUESTIONS.chunked(2).forEach { row ->
            Row(Modifier.fillMaxWidth().padding(bottom = 10.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                row.forEach { q ->
                    Surface(
                        modifier = Modifier.weight(1f).clickable { onQuestionClick(q) },
                        color = Surface, shape = RoundedCornerShape(14.dp), shadowElevation = 1.dp
                    ) {
                        Row(Modifier.padding(horizontal = 16.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text(q, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = TextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                            Spacer(Modifier.width(6.dp))
                            Icon(Icons.Default.ArrowForward, null, tint = TextHint, modifier = Modifier.size(14.dp))
                        }
                    }
                }
                if (row.size < 2) Spacer(Modifier.weight(1f))
            }
        }
    }
}

// ═══════════════════════════════
// InputBar
// ═══════════════════════════════
@Composable
private fun InputBar(
    inputText: String, onInputChange: (String) -> Unit, onSend: () -> Unit,
    onCameraClick: () -> Unit,
    isBusy: Boolean = false,
    hasPendingImage: Boolean = false
) {
    val hasText = inputText.isNotBlank()
    val canSend = hasText || hasPendingImage

    Surface(color = Surface, shadowElevation = 8.dp) {
        Row(
            Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            // ── 左侧 [+] 按钮 ──
            IconButton(onClick = onCameraClick, modifier = Modifier.size(42.dp)) {
                Icon(Icons.Default.Add, "更多", tint = TextSecondary, modifier = Modifier.size(22.dp))
            }

            // ── 输入框 ──
            OutlinedTextField(
                value = inputText,
                onValueChange = onInputChange,
                modifier = Modifier.weight(1f),
                placeholder = { Text("说点什么...", color = TextHint, fontSize = 15.sp) },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Color.Transparent,
                    unfocusedBorderColor = Color.Transparent,
                    focusedContainerColor = InputBg,
                    unfocusedContainerColor = InputBg,
                ),
                shape = RoundedCornerShape(24.dp),
                textStyle = TextStyle(fontSize = 15.sp, color = TextPrimary),
                maxLines = 4,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { onSend() }),
            )

            // ── 发送按钮 ──
            IconButton(
                onClick = { onSend() },
                enabled = canSend,
                modifier = Modifier.size(42.dp),
            ) {
                Icon(
                    if (isBusy) Icons.Default.Close else Icons.Default.Send,
                    contentDescription = if (isBusy) "停止生成" else "发送",
                    tint = if (canSend) Primary else TextHint,
                    modifier = Modifier.size(22.dp)
                )
            }
        }
    }
}

// ═══════════════════════════════
// User Bubble — 深灰 (ChatGPT style)
// ═══════════════════════════════
@Composable
private fun UserBubble(msg: MessageItem.UserMessage, onImageClick: (String) -> Unit = {}) {
    val hasImage = msg.imageUri != null

    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.Bottom) {
        Surface(
            color = if (hasImage) Surface else UserBubble,
            shape = RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp, bottomStart = 18.dp, bottomEnd = 4.dp),
            shadowElevation = if (hasImage) 2.dp else 0.dp,
            modifier = Modifier.widthIn(max = 280.dp)
        ) {
            if (hasImage) {
                val uri = msg.imageUri ?: ""
                Column {
                    AsyncImage(model = uri, contentDescription = "查看大图",
                        contentScale = ContentScale.Crop,
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(max = 200.dp)
                            .clip(RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp, bottomStart = 0.dp, bottomEnd = 0.dp))
                            .clickable { onImageClick(uri) })
                    // 附带文字（如用户拍照后输入了描述）
                    if (msg.text.isNotBlank()) {
                        Text(
                            msg.text,
                            color = TextPrimary,
                            fontSize = 14.sp,
                            lineHeight = 20.sp,
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)
                        )
                    }
                }
            } else {
                Text(msg.text, color = Color.White, modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp), fontSize = 15.sp, lineHeight = 22.sp)
            }
        }
        if (!hasImage) {
            Spacer(Modifier.width(8.dp))
            Box(Modifier.size(30.dp).clip(CircleShape).background(Divider), contentAlignment = Alignment.Center) {
                Icon(Icons.Default.Person, null, tint = TextHint, modifier = Modifier.size(18.dp))
            }
        }
    }
}

// ═══════════════════════════════
// AI Bubble — 白底
// ═══════════════════════════════
@Composable
private fun AiBubble(blocks: List<ContentBlock>, isComplete: Boolean, isStreaming: Boolean = false, onClarificationSelected: (String) -> Unit = {}) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Start, verticalAlignment = Alignment.Top) {
        Image(painterResource(R.drawable.ai_avatar), "AI", Modifier.size(32.dp).clip(CircleShape), contentScale = ContentScale.Crop)
        Spacer(Modifier.width(10.dp))
        Surface(
            color = AiBubble, shadowElevation = 1.dp,
            shape = RoundedCornerShape(topStart = 4.dp, topEnd = 18.dp, bottomStart = 18.dp, bottomEnd = 18.dp),
            modifier = Modifier.widthIn(max = 320.dp)
        ) {
            Column(Modifier.padding(16.dp)) {
                blocks.forEachIndexed { i, block ->
                    when (block) {
                        is ContentBlock.TextBlock -> {
                            val cursor = if (i == blocks.size - 1 && isStreaming) "▌" else ""
                            val displayText = if (i == blocks.size - 1 && !isComplete) block.text + "▎" else block.text + cursor
                            Text(
                                text = parseMarkdown(displayText),
                                color = TextPrimary, fontSize = 15.sp, lineHeight = 24.sp
                            )
                        }
                        is ContentBlock.ProductBlock -> ProductCardView(product = block.product)
                        is ContentBlock.ComparisonBlock -> ComparisonCard(products = block.products, aiAnalysis = block.aiAnalysis)
                        is ContentBlock.ClarificationBlock -> ClarificationChips(
                            question = block.question,
                            options = block.options,
                            onSelected = { onClarificationSelected(it) }
                        )
                    }
                    // 智能间距：根据相邻 block 类型决定
                    if (i < blocks.size - 1) {
                        val next = blocks[i + 1]
                        val spacing = when {
                            // 推荐文字 → 商品卡片：同一单元紧贴
                            block is ContentBlock.TextBlock && next is ContentBlock.ProductBlock -> 4.dp
                            // 商品卡片 → 下一段推荐文字：不同商品分隔
                            block is ContentBlock.ProductBlock && next is ContentBlock.TextBlock -> 20.dp
                            // 商品卡片之间：紧贴
                            block is ContentBlock.ProductBlock && next is ContentBlock.ProductBlock -> 4.dp
                            // 对比卡片 → 后续文字
                            block is ContentBlock.ComparisonBlock && next is ContentBlock.TextBlock -> 20.dp
                            // 文字 → 对比卡片
                            block is ContentBlock.TextBlock && next is ContentBlock.ComparisonBlock -> 8.dp
                            // 默认标准间距
                            else -> 12.dp
                        }
                        Spacer(Modifier.height(spacing))
                    }
                }
                if (blocks.isEmpty() && !isComplete) Text("▎", color = TextPrimary, fontSize = 15.sp)
            }
        }
    }
}

// ═══════════════════════════════
// Status Bubble — 思考/检索状态（替换式，带动画圆点）
// ═══════════════════════════════
@Composable
private fun StatusBubble(message: String) {
    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
        Surface(
            shape = RoundedCornerShape(topStart = 4.dp, topEnd = 16.dp, bottomStart = 16.dp, bottomEnd = 16.dp),
            color = AiBubble,
            shadowElevation = 2.dp,
            border = BorderStroke(1.dp, Divider),
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(5.dp),
            ) {
                val transition = rememberInfiniteTransition(label = "typing")
                repeat(3) { i ->
                    val scale by transition.animateFloat(
                        initialValue = 0.5f,
                        targetValue = 1f,
                        animationSpec = infiniteRepeatable(
                            animation = tween(500, delayMillis = i * 160, easing = FastOutSlowInEasing),
                            repeatMode = RepeatMode.Reverse,
                        ),
                        label = "dot_$i",
                    )
                    Box(
                        modifier = Modifier
                            .size(7.dp)
                            .graphicsLayer { scaleX = scale; scaleY = scale }
                            .clip(CircleShape)
                            .background(Primary.copy(alpha = 0.4f + 0.6f * scale)),
                    )
                }
                Spacer(Modifier.width(6.dp))
                Text(
                    message,
                    style = TextStyle(fontSize = 13.sp, color = TextSecondary),
                )
            }
        }
    }
}

// ═══════════════════════════════
// Typing
// ═══════════════════════════════
@Composable
private fun TypingDots() {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Start, verticalAlignment = Alignment.Bottom) {
        Image(painterResource(R.drawable.ai_avatar), "AI", Modifier.size(32.dp).clip(CircleShape), contentScale = ContentScale.Crop)
        Spacer(Modifier.width(10.dp))
        Surface(color = AiBubble, shadowElevation = 1.dp, shape = RoundedCornerShape(topStart = 4.dp, topEnd = 18.dp, bottomStart = 18.dp, bottomEnd = 18.dp)) {
            Row(Modifier.padding(horizontal = 20.dp, vertical = 14.dp), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                Dot(6.dp, 0); Dot(6.dp, 200); Dot(6.dp, 400)
            }
        }
    }
}

@Composable
private fun Dot(size: androidx.compose.ui.unit.Dp, delay: Int) {
    val t = rememberInfiniteTransition(label = "d_$delay")
    val a by t.animateFloat(0.3f, 1f, infiniteRepeatable(tween(600, easing = LinearEasing), initialStartOffset = StartOffset(delay)), label = "a")
    val s by t.animateFloat(0.8f, 1.2f, infiniteRepeatable(tween(600, easing = LinearEasing), initialStartOffset = StartOffset(delay)), label = "s")
    Box(Modifier.size(size).scale(s).clip(CircleShape).background(TextHint.copy(alpha = a)))
}

// ═══════════════════════════════
// Markdown 解析 — 支持 **加粗**
// ═══════════════════════════════
private fun parseMarkdown(text: String): androidx.compose.ui.text.AnnotatedString {
    return buildAnnotatedString {
        var i = 0
        while (i < text.length) {
            val boldStart = text.indexOf("**", i)
            if (boldStart == -1) {
                // 没有更多加粗标记，追加剩余文本
                append(text.substring(i))
                break
            }
            // 追加加粗标记前的普通文本
            if (boldStart > i) {
                append(text.substring(i, boldStart))
            }
            // 查找结束标记
            val boldEnd = text.indexOf("**", boldStart + 2)
            if (boldEnd == -1) {
                // 没有闭合标记，按普通文本处理
                append(text.substring(boldStart))
                break
            }
            // 追加加粗文本
            withStyle(SpanStyle(fontWeight = FontWeight.Bold)) {
                append(text.substring(boldStart + 2, boldEnd))
            }
            i = boldEnd + 2
        }
    }
}

// ═══════════════════════════════
// Clarification Chips — 可点击反问选项（参考 RAGent）
// ═══════════════════════════════
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ClarificationChips(question: String, options: List<String>, onSelected: (String) -> Unit) {
    Column {
        if (question.isNotBlank()) {
            Text(
                question,
                color = TextPrimary,
                fontSize = 14.sp,
                lineHeight = 22.sp,
                modifier = Modifier.padding(bottom = 10.dp)
            )
        }
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            options.forEach { option ->
                Surface(
                    modifier = Modifier
                        .clip(RoundedCornerShape(20.dp))
                        .clickable { onSelected(option) },
                    shape = RoundedCornerShape(20.dp),
                    color = Surface,
                    border = BorderStroke(1.dp, Primary.copy(alpha = 0.4f)),
                ) {
                    Text(
                        option,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 9.dp),
                        style = TextStyle(fontSize = 14.sp),
                        color = Primary,
                        fontWeight = FontWeight.Medium,
                    )
                }
            }
        }
    }
}

// ═══════════════════════════════
// Product Carousel — 横滑商品卡片（HorizontalPager）
// ═══════════════════════════════
@OptIn(ExperimentalLayoutApi::class, ExperimentalFoundationApi::class)
@Composable

// ═══════════════════════════════
// 全屏图片查看 Dialog
// ═══════════════════════════════
@Composable
private fun FullScreenImageDialog(imageUri: String, onDismiss: () -> Unit) {
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false)
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black.copy(alpha = 0.95f))
                .clickable { onDismiss() },
            contentAlignment = Alignment.Center
        ) {
            AsyncImage(
                model = imageUri,
                contentDescription = "查看大图",
                contentScale = ContentScale.Fit,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp)
            )
            // 关闭按钮
            IconButton(
                onClick = onDismiss,
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(16.dp)
                    .size(40.dp)
                    .clip(CircleShape)
                    .background(Color.White.copy(alpha = 0.2f))
            ) {
                Icon(Icons.Default.Close, "关闭", tint = Color.White, modifier = Modifier.size(24.dp))
            }
        }
    }
}

/** 朗读前去掉 Markdown 符号，避免读出"星星加粗星星"之类 */
private fun stripMarkdown(text: String): String = text
    .replace(Regex("#{1,6}\\s+"), "")
    .replace(Regex("\\*{1,2}(.*?)\\*{1,2}"), "$1")
    .replace(Regex("`([^`]*)`"), "$1")
    .replace(Regex("^[-*>]\\s+", RegexOption.MULTILINE), "")
    .replace(Regex("^\\d+\\.\\s+", RegexOption.MULTILINE), "")
    .replace("---", "")
    .replace("▌", "")
    .replace("**", "")
    .trim()
