package pl.radiocharts.mobile

data class MetaResponse(
    val api_version: String = "",
    val radiocharts_version: String = "",
    val statuses: List<String> = emptyList(),
    val base_statuses: List<String> = emptyList(),
    val candidate_statuses: List<String> = emptyList(),
    val last_airplay_date: String? = null,
)


data class UpdateInfo(
    val available: Boolean = false,
    val latest_version_name: String? = null,
    val latest_version_code: Int = 0,
    val download_url: String? = null,
    val sha256: String? = null,
    val size_bytes: Long = 0,
    val git_sha: String? = null,
    val built_at: String? = null,
    val reason: String? = null,
)

data class Station(
    val station_id: Int,
    val name: String,
    val active: Int = 1,
)

data class SongRow(
    val song_id: Int,
    val artist: String = "",
    val title: String = "",
    val release_date: String? = null,
    val heard: Boolean = false,
    val status: String = "Nie słuchałem",
    val downloaded: Boolean = false,
    val note: String = "",
    val popularity: Double? = null,
    val familiarity: Double? = null,
    val momentum: Double? = null,
    val radio_reach: Double? = null,
    val airplay_spins_7d: Int? = null,
    val radio_presence: Double? = null,
    val avg_position: Double? = null,
    val RMF_pos: Int? = null,
    val RMF_weeks: Int? = null,
    val ZET_pos: Int? = null,
    val ZET_weeks: Int? = null,
    val ESKA_pos: Int? = null,
    val ESKA_weeks: Int? = null,
    val OLIA_pos: Int? = null,
    val OLIA_weeks: Int? = null,
    val OLIS_pos: Int? = null,
    val OLIS_weeks: Int? = null,
    val spins: Int? = null,
    val stations_count: Int? = null,
    val period_reach: Double? = null,
    val period_rotation: Double? = null,
    val period_radio_presence: Double? = null,
    val airplay_per_day: Double? = null,
    val airplay_per_station_day: Double? = null,
    val top_station: String? = null,
    val last_play: String? = null,
)

data class SongsResponse(
    val total: Int = 0,
    val offset: Int = 0,
    val limit: Int = 0,
    val start_date: String? = null,
    val end_date: String? = null,
    val reporting_stations: Int? = null,
    val items: List<SongRow> = emptyList(),
)

data class NotePatch(val heard: Boolean, val status: String, val downloaded: Boolean, val note: String)
data class PatchResponse(val ok: Boolean, val song: SongRow)

data class ChartPoint(val source: String, val chart_date: String, val chart_size: Int, val position: Int)
data class StationAirplay(val station: String, val spins: Int, val active_days: Int, val first_play: String?, val last_play: String?)
data class DailyAirplay(val play_date: String, val station: String, val spins: Int)
data class AirplayDetail(
    val total_spins: Int = 0,
    val stations_count: Int = 0,
    val first_play: String? = null,
    val last_play: String? = null,
    val start_date: String? = null,
    val end_date: String? = null,
    val days: Int = 0,
    val reporting_stations: Int = 0,
    val period_reach: Double = 0.0,
    val period_rotation: Double = 0.0,
    val period_radio_presence: Double = 0.0,
    val airplay_per_day: Double = 0.0,
    val airplay_per_station_day: Double = 0.0,
    val stations: List<StationAirplay> = emptyList(),
    val daily: List<DailyAirplay> = emptyList(),
)

data class ItunesResponse(val results: List<ItunesTrack> = emptyList())
data class ItunesTrack(val artistName: String = "", val trackName: String = "", val previewUrl: String? = null)
