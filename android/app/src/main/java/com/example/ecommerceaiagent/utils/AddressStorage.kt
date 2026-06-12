package com.example.ecommerceaiagent.utils

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * 收货地址本地存储 — SharedPreferences 持久化。
 * 用户提交过的地址自动保存，下次可直接点选。
 */
object AddressStorage {

    private const val PREFS_NAME = "address_prefs"
    private const val KEY_ADDRESSES = "saved_addresses"
    private const val MAX_SAVED = 5

    data class SavedAddress(
        val name: String = "",
        val phone: String = "",
        val address: String = ""
    ) {
        fun toLabel(): String {
            val parts = mutableListOf<String>()
            if (name.isNotBlank()) parts.add(name)
            if (phone.isNotBlank()) parts.add(phone)
            if (parts.isEmpty()) return address
            return "${parts.joinToString(" ")}，$address"
        }
    }

    fun save(context: Context, name: String, phone: String, address: String) {
        if (address.isBlank()) return
        val existing = load(context).toMutableList()
        // 去重：相同地址不重复保存
        existing.removeAll { it.address == address && it.name == name }
        existing.add(0, SavedAddress(name, phone, address))
        if (existing.size > MAX_SAVED) existing.removeAt(existing.lastIndex)
        val arr = JSONArray()
        existing.forEach { addr ->
            arr.put(JSONObject().apply {
                put("name", addr.name)
                put("phone", addr.phone)
                put("address", addr.address)
            })
        }
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit().putString(KEY_ADDRESSES, arr.toString()).apply()
    }

    fun load(context: Context): List<SavedAddress> {
        val json = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(KEY_ADDRESSES, null) ?: return emptyList()
        val arr = try { JSONArray(json) } catch (_: Exception) { return emptyList() }
        val result = mutableListOf<SavedAddress>()
        for (i in 0 until arr.length()) {
            val obj = arr.getJSONObject(i)
            result.add(SavedAddress(
                name = obj.optString("name", ""),
                phone = obj.optString("phone", ""),
                address = obj.optString("address", "")
            ))
        }
        return result
    }
}
