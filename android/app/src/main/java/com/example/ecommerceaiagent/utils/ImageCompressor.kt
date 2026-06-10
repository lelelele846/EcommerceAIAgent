package com.example.ecommerceaiagent.utils

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.net.Uri
import android.util.Log
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.InputStream

/**
 * 图片压缩工具类
 * 实现端侧等比缩放（800px上限）+ JPEG压缩（quality=80）
 */
object ImageCompressor {
    
    private const val MAX_WIDTH = 800
    private const val MAX_HEIGHT = 800
    private const val COMPRESS_QUALITY = 80
    
    /**
     * 将图片压缩为字节数组
     * @param context 上下文
     * @param uri 图片Uri
     * @return 压缩后的字节数组
     */
    fun compressToByteArray(context: Context, uri: Uri): ByteArray? {
        return try {
            val inputStream: InputStream? = context.contentResolver.openInputStream(uri)
            inputStream?.use {
                val bitmap = BitmapFactory.decodeStream(it)
                val compressedBitmap = resizeBitmap(bitmap)
                val outputStream = ByteArrayOutputStream()
                compressedBitmap.compress(Bitmap.CompressFormat.JPEG, COMPRESS_QUALITY, outputStream)
                outputStream.toByteArray()
            }
        } catch (e: Exception) {
            Log.e("ImageCompressor", "压缩图片为字节数组失败", e)
            null
        }
    }
    
    /**
     * 将图片文件压缩为字节数组
     * @param imageFile 原始图片文件
     * @return 压缩后的字节数组
     */
    fun compressFileToByteArray(imageFile: File): ByteArray? {
        return try {
            val bitmap = BitmapFactory.decodeFile(imageFile.absolutePath)
            val compressedBitmap = resizeBitmap(bitmap)
            val outputStream = ByteArrayOutputStream()
            compressedBitmap.compress(Bitmap.CompressFormat.JPEG, COMPRESS_QUALITY, outputStream)
            outputStream.toByteArray()
        } catch (e: Exception) {
            Log.e("ImageCompressor", "压缩图片文件为字节数组失败", e)
            null
        }
    }

    /**
     * 从Uri压缩图片并返回 Base64 字符串
     */
    fun compressToBase64(context: Context, uri: Uri): String? {
        val bytes = compressToByteArray(context, uri) ?: return null
        return android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)
    }

    /**
     * 从File压缩图片并返回 Base64 字符串
     */
    fun compressFileToBase64(imageFile: File): String? {
        val bytes = compressFileToByteArray(imageFile) ?: return null
        return android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)
    }

    /**
     * 等比缩放Bitmap
     */
    private fun resizeBitmap(bitmap: Bitmap): Bitmap {
        var width = bitmap.width
        var height = bitmap.height
        
        // 计算缩放比例，确保宽高都不超过MAX_WIDTH/MAX_HEIGHT
        val scale = if (width > height) {
            MAX_WIDTH.toFloat() / width
        } else {
            MAX_HEIGHT.toFloat() / height
        }
        
        // 如果不需要缩放，直接返回原图
        if (scale >= 1.0f) {
            return bitmap
        }
        
        // 计算新尺寸
        val newWidth = (width * scale).toInt()
        val newHeight = (height * scale).toInt()
        
        // 创建缩放后的Bitmap
        val matrix = Matrix()
        matrix.postScale(scale, scale)
        
        val resizedBitmap = Bitmap.createBitmap(bitmap, 0, 0, width, height, matrix, true)
        
        // 释放原始Bitmap
        if (bitmap != resizedBitmap) {
            bitmap.recycle()
        }
        
        return resizedBitmap
    }
}