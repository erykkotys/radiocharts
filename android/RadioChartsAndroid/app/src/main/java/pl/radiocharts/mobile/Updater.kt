package pl.radiocharts.mobile

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest

object AppUpdater {
    suspend fun check(store: SettingsStore): UpdateInfo =
        ApiProvider.api(store).androidUpdate(BuildConfig.VERSION_CODE)

    suspend fun download(context: Context, store: SettingsStore, info: UpdateInfo): File = withContext(Dispatchers.IO) {
        val body = ApiProvider.api(store).downloadApk()
        val dir = File(context.cacheDir, "updates").apply { mkdirs() }
        val file = File(dir, "RadioCharts-${info.latest_version_name ?: info.latest_version_code}.apk")
        val digest = MessageDigest.getInstance("SHA-256")
        body.byteStream().use { input ->
            file.outputStream().use { output ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    output.write(buffer, 0, count)
                    digest.update(buffer, 0, count)
                }
            }
        }
        val actual = digest.digest().joinToString("") { "%02x".format(it) }
        val expected = info.sha256?.lowercase()?.trim().orEmpty()
        if (expected.length == 64 && actual != expected) {
            file.delete()
            error("Błędna suma SHA-256 pobranego APK")
        }
        file
    }

    /** Returns true when the package installer was launched. False means Android opened
     * the one-time 'Install unknown apps' permission screen for RadioCharts instead. */
    fun install(context: Context, apk: File): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !context.packageManager.canRequestPackageInstalls()) {
            val intent = Intent(
                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:${context.packageName}")
            ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
            return false
        }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", apk)
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
        return true
    }
}
