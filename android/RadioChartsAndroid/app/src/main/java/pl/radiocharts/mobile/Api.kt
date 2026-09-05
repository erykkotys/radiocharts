package pl.radiocharts.mobile

import android.content.Context
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.*

interface RadioChartsApi {
    @GET("api/v1/health") suspend fun health(): Map<String, Any?>
    @GET("api/v1/meta") suspend fun meta(): MetaResponse
    @GET("api/v1/stations") suspend fun stations(@Query("active_only") activeOnly: Boolean = true): List<Station>

    @GET("api/v1/songs")
    suspend fun songs(
        @Query("mode") mode: String,
        @Query("search") search: String = "",
        @Query("statuses") statuses: List<String> = emptyList(),
        @Query("downloaded") downloaded: String = "any",
        @Query("sort") sort: String = "popularity",
        @Query("descending") descending: Boolean = true,
        @Query("start") start: String? = null,
        @Query("end") end: String? = null,
        @Query("station_ids") stationIds: String? = null,
        @Query("limit") limit: Int = 300,
    ): SongsResponse

    @GET("api/v1/songs/{id}") suspend fun song(@Path("id") id: Int): SongRow
    @PATCH("api/v1/songs/{id}") suspend fun patchSong(@Path("id") id: Int, @Body body: NotePatch): PatchResponse
    @GET("api/v1/songs/{id}/charts") suspend fun charts(@Path("id") id: Int): List<ChartPoint>
    @GET("api/v1/songs/{id}/airplay")
    suspend fun airplay(
        @Path("id") id: Int,
        @Query("start") start: String? = null,
        @Query("end") end: String? = null,
        @Query("station_ids") stationIds: String? = null,
    ): AirplayDetail
}

interface ItunesApi {
    @GET("search") suspend fun search(
        @Query("term") term: String,
        @Query("country") country: String = "PL",
        @Query("media") media: String = "music",
        @Query("entity") entity: String = "song",
        @Query("limit") limit: Int = 5,
    ): ItunesResponse
}

class SettingsStore(context: Context) {
    private val prefs = context.getSharedPreferences("radiocharts", Context.MODE_PRIVATE)
    var serverUrl: String
        get() = prefs.getString("server_url", "http://192.168.1.10:8502/") ?: "http://192.168.1.10:8502/"
        set(value) { prefs.edit().putString("server_url", normalizeUrl(value)).apply() }
    var token: String
        get() = prefs.getString("token", "") ?: ""
        set(value) { prefs.edit().putString("token", value.trim()).apply() }
    private fun normalizeUrl(raw: String): String {
        val value = raw.trim().ifBlank { "http://192.168.1.10:8502/" }
        return if (value.endsWith("/")) value else "$value/"
    }
}

object ApiProvider {
    @Volatile private var cachedKey: String? = null
    @Volatile private var cached: RadioChartsApi? = null

    fun api(store: SettingsStore): RadioChartsApi {
        val key = store.serverUrl + "|" + store.token
        if (cachedKey == key && cached != null) return cached!!
        synchronized(this) {
            if (cachedKey == key && cached != null) return cached!!
            val logging = HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BASIC }
            val auth = Interceptor { chain ->
                val builder = chain.request().newBuilder()
                if (store.token.isNotBlank()) builder.header("Authorization", "Bearer ${store.token}")
                chain.proceed(builder.build())
            }
            val client = OkHttpClient.Builder().addInterceptor(auth).addInterceptor(logging).build()
            val api = Retrofit.Builder().baseUrl(store.serverUrl).client(client)
                .addConverterFactory(GsonConverterFactory.create()).build().create(RadioChartsApi::class.java)
            cachedKey = key; cached = api
            return api
        }
    }

    val itunes: ItunesApi by lazy {
        Retrofit.Builder().baseUrl("https://itunes.apple.com/")
            .addConverterFactory(GsonConverterFactory.create()).build().create(ItunesApi::class.java)
    }

    fun invalidate() { cachedKey = null; cached = null }
}
