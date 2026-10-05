package pl.radiocharts.mobile

import android.app.Activity
import android.content.Intent
import android.content.res.Configuration
import android.content.pm.ActivityInfo
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.PointerEventType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewModelScope
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneOffset

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { RadioChartsTheme { RadioChartsApp() } }
    }
}

private val Bg = Color(0xFF171B22)
private val CardBg = Color(0xFF222832)
private val Accent = Color(0xFF80CBC4)

@Composable fun RadioChartsTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = darkColorScheme(primary = Accent, background = Bg, surface = CardBg), content = content)
}

data class ListUiState(
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val error: String? = null,
    val meta: MetaResponse = MetaResponse(),
    val rows: List<SongRow> = emptyList(),
    val total: Int = 0,
    val search: String = "",
    val downloaded: String = "any",
    val sort: String = "popularity",
    val descending: Boolean = true,
    val statuses: Set<String> = emptySet(),
    val stations: List<Station> = emptyList(),
    val selectedStationIds: Set<Int> = emptySet(),
    val reportingStations: Int? = null,
    val savingSongIds: Set<Int> = emptySet(),
)

class ListVm(app: android.app.Application) : androidx.lifecycle.AndroidViewModel(app) {
    private val store = SettingsStore(app)
    private val _state = MutableStateFlow(ListUiState())
    val state: StateFlow<ListUiState> = _state
    private var modeDefaultsApplied = false

    suspend fun load(mode: String, start: String? = null, end: String? = null, append: Boolean = false) {
        var before = _state.value
        if (!modeDefaultsApplied) {
            modeDefaultsApplied = true
            if (mode == "airplay") {
                before = before.copy(sort = "spins", descending = true)
                _state.value = before
            }
        }
        _state.value = before.copy(loading = !append, loadingMore = append, error = null)
        try {
            val api = ApiProvider.api(store)
            val meta = if (before.meta.statuses.isEmpty()) api.meta() else before.meta
            val stations = if (mode == "airplay" && before.stations.isEmpty()) api.stations() else before.stations
            val offset = if (append) before.rows.size else 0
            val response = api.songs(
                mode = mode,
                search = before.search,
                statuses = before.statuses.toList(),
                downloaded = before.downloaded,
                sort = before.sort,
                descending = before.descending,
                start = start,
                end = end,
                stationIds = before.selectedStationIds.takeIf { it.isNotEmpty() }?.sorted()?.joinToString(","),
                limit = 120,
                offset = offset,
            )
            val rows = if (append) (before.rows + response.items).distinctBy { it.song_id } else response.items
            _state.value = _state.value.copy(
                loading = false,
                loadingMore = false,
                meta = meta,
                stations = stations,
                rows = rows,
                total = response.total,
                reportingStations = response.reporting_stations,
            )
        } catch (e: Exception) {
            _state.value = _state.value.copy(
                loading = false, loadingMore = false, error = e.message ?: e.javaClass.simpleName
            )
        }
    }

    fun setSearch(v: String) { _state.value = _state.value.copy(search = v) }
    fun setDownloaded(v: String) { _state.value = _state.value.copy(downloaded = v) }
    fun setSort(v: String, descending: Boolean) { _state.value = _state.value.copy(sort = v, descending = descending) }
    fun toggleDirection() { _state.value = _state.value.copy(descending = !_state.value.descending) }
    fun toggleStatus(v: String) {
        val selected = _state.value.statuses.toMutableSet()
        if (!selected.add(v)) selected.remove(v)
        _state.value = _state.value.copy(statuses = selected)
    }
    fun clearStatuses() { _state.value = _state.value.copy(statuses = emptySet()) }
    fun toggleStation(id: Int) {
        val selected = _state.value.selectedStationIds.toMutableSet()
        if (!selected.add(id)) selected.remove(id)
        _state.value = _state.value.copy(selectedStationIds = selected)
    }
    fun clearStations() { _state.value = _state.value.copy(selectedStationIds = emptySet()) }

    fun changeStatus(row: SongRow, newStatus: String) {
        if (row.status == newStatus || _state.value.savingSongIds.contains(row.song_id)) return
        val original = row
        _state.value = _state.value.copy(
            rows = _state.value.rows.map { if (it.song_id == row.song_id) it.copy(status = newStatus) else it },
            savingSongIds = _state.value.savingSongIds + row.song_id,
            error = null,
        )
        viewModelScope.launch {
            try {
                val updated = ApiProvider.api(store).patchSong(
                    row.song_id,
                    NotePatch(newStatus != "Nie słuchałem", newStatus, row.downloaded, row.note),
                ).song
                _state.value = _state.value.copy(
                    rows = _state.value.rows.map {
                        if (it.song_id == row.song_id) it.copy(
                            status = updated.status,
                            heard = updated.heard,
                            downloaded = updated.downloaded,
                            note = updated.note,
                        ) else it
                    },
                    savingSongIds = _state.value.savingSongIds - row.song_id,
                )
            } catch (e: Exception) {
                _state.value = _state.value.copy(
                    rows = _state.value.rows.map { if (it.song_id == row.song_id) original else it },
                    savingSongIds = _state.value.savingSongIds - row.song_id,
                    error = "Zmiana statusu: ${e.message ?: e.javaClass.simpleName}",
                )
            }
        }
    }
}

data class PreviewUiState(
    val loadingSongId: Int? = null,
    val playingSongId: Int? = null,
    val error: String? = null,
)

class PreviewPlayerVm(app: android.app.Application) : androidx.lifecycle.AndroidViewModel(app) {
    private val _state = MutableStateFlow(PreviewUiState())
    val state: StateFlow<PreviewUiState> = _state
    private var player: MediaPlayer? = null
    private var loadJob: Job? = null
    private var requestedSongId: Int? = null

    fun toggle(song: SongRow) {
        if (_state.value.playingSongId == song.song_id) {
            player?.pause()
            _state.value = _state.value.copy(playingSongId = null, loadingSongId = null)
            return
        }
        if (_state.value.loadingSongId == song.song_id) {
            loadJob?.cancel()
            requestedSongId = null
            _state.value = PreviewUiState()
            return
        }

        loadJob?.cancel()
        requestedSongId = song.song_id
        player?.release()
        player = null
        _state.value = PreviewUiState(loadingSongId = song.song_id)
        loadJob = viewModelScope.launch {
            try {
                val result = ApiProvider.itunes.search("${song.artist} ${song.title}")
                val previewUrl = result.results.firstOrNull { !it.previewUrl.isNullOrBlank() }?.previewUrl
                    ?: error("Brak podglądu 30 s")
                if (requestedSongId != song.song_id) return@launch
                val newPlayer = MediaPlayer().apply {
                    setAudioAttributes(
                        AudioAttributes.Builder().setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build()
                    )
                    setDataSource(previewUrl)
                    setOnPreparedListener { prepared ->
                        if (requestedSongId == song.song_id) {
                            prepared.start()
                            _state.value = PreviewUiState(playingSongId = song.song_id)
                        }
                    }
                    setOnCompletionListener {
                        if (requestedSongId == song.song_id) {
                            _state.value = PreviewUiState()
                        }
                    }
                    setOnErrorListener { _, _, _ ->
                        if (requestedSongId == song.song_id) {
                            _state.value = PreviewUiState(error = "Błąd odtwarzania")
                        }
                        true
                    }
                    prepareAsync()
                }
                player = newPlayer
            } catch (e: Exception) {
                if (requestedSongId == song.song_id) {
                    _state.value = PreviewUiState(error = e.message ?: e.javaClass.simpleName)
                }
            }
        }
    }

    override fun onCleared() {
        loadJob?.cancel()
        player?.release()
        player = null
        super.onCleared()
    }
}

@Composable fun RadioChartsApp() {
    val nav = rememberNavController()
    val context = LocalContext.current
    val store = remember { SettingsStore(context) }
    val scope = rememberCoroutineScope()
    val previewVm: PreviewPlayerVm = viewModel()
    var pendingUpdate by remember { mutableStateOf<UpdateInfo?>(null) }
    var updateStatus by remember { mutableStateOf("") }
    var updating by remember { mutableStateOf(false) }

    fun checkUpdates(manual: Boolean) {
        scope.launch {
            if (manual) updateStatus = "Sprawdzam aktualizacje…"
            try {
                val info = AppUpdater.check(store)
                if (info.available) {
                    pendingUpdate = info
                    updateStatus = "Dostępna wersja ${info.latest_version_name ?: info.latest_version_code}"
                } else if (manual) {
                    updateStatus = if (info.reason == "not_published") {
                        "Serwer nie ma jeszcze opublikowanego APK."
                    } else {
                        "Masz najnowszą wersję (${BuildConfig.VERSION_NAME})."
                    }
                }
            } catch (e: Exception) {
                if (manual) updateStatus = "Błąd sprawdzania aktualizacji: ${e.message ?: e.javaClass.simpleName}"
            }
        }
    }

    fun installUpdate(info: UpdateInfo) {
        scope.launch {
            updating = true
            updateStatus = "Pobieram RadioCharts ${info.latest_version_name ?: ""}…"
            try {
                val apk = AppUpdater.download(context, store, info)
                val installerStarted = AppUpdater.install(context, apk)
                updateStatus = if (installerStarted) {
                    "APK pobrane. Zatwierdź aktualizację w instalatorze Androida."
                } else {
                    "Włącz „Allow from this source” dla RadioCharts, wróć do aplikacji i kliknij Aktualizuj ponownie."
                }
            } catch (e: Exception) {
                updateStatus = "Błąd aktualizacji: ${e.message ?: e.javaClass.simpleName}"
            } finally {
                updating = false
            }
        }
    }

    LaunchedEffect(Unit) {
        kotlinx.coroutines.delay(1200)
        checkUpdates(manual = false)
    }

    val currentBackStackEntry by nav.currentBackStackEntryAsState()
    val chartOpen = currentBackStackEntry?.destination?.route?.startsWith("chart/") == true

    Scaffold(
        bottomBar = {
            if (!chartOpen) {
                NavigationBar {
                    val currentRoute = currentBackStackEntry?.destination?.route.orEmpty()
                    listOf("dashboard" to "Dashboard", "airplay" to "Emisje", "library" to "Baza", "emaus" to "Schedule", "settings" to "Ustawienia").forEach { (route,label) ->
                        NavigationBarItem(
                            selected=currentRoute == route,
                            onClick={nav.navigate(route){launchSingleTop=true}},
                            icon={Text(when(route){"dashboard"->"▦";"airplay"->"◉";"library"->"★";"emaus"->"E";else->"⚙"})},
                            label={Text(label,maxLines=1)}
                        )
                    }
                }
            }
        }
    ) { pad ->
        NavHost(navController = nav, startDestination = "dashboard", modifier = Modifier.padding(pad)) {
            composable("dashboard") { SongListScreen("dashboard", "Dashboard", nav::navigate, previewVm = previewVm) }
            composable("airplay") { SongListScreen("airplay", "Emisje", nav::navigate, withPeriod=true, previewVm = previewVm) }
            composable("library") { SongListScreen("library", "Baza", nav::navigate, withPeriod=true, previewVm = previewVm) }
            composable("emaus") { LocalRadioScreen(store) { sid -> nav.navigate("song/$sid") } }
            composable("settings") { SettingsScreen(updateStatus = updateStatus, onCheckUpdates = { checkUpdates(true) }) }
            composable("song/{id}", arguments=listOf(navArgument("id"){type=NavType.IntType})) { back ->
                SongScreen(back.arguments?.getInt("id") ?: 0, previewVm, nav::navigate)
            }
            composable(
                "chart/{id}/{source}",
                arguments=listOf(
                    navArgument("id"){type=NavType.IntType},
                    navArgument("source"){type=NavType.StringType},
                ),
            ) { back ->
                ToplistChartScreen(
                    id = back.arguments?.getInt("id") ?: 0,
                    source = Uri.decode(back.arguments?.getString("source").orEmpty()),
                    onBack = { nav.popBackStack() },
                )
            }
        }
    }

    pendingUpdate?.let { info ->
        AlertDialog(
            onDismissRequest = { if (!updating) pendingUpdate = null },
            title = { Text("Dostępna aktualizacja") },
            text = {
                Column {
                    Text("RadioCharts ${BuildConfig.VERSION_NAME} → ${info.latest_version_name ?: info.latest_version_code}")
                    if (info.size_bytes > 0) {
                        Text("Rozmiar: %.1f MB".format(info.size_bytes / 1024.0 / 1024.0), style = MaterialTheme.typography.bodySmall)
                    }
                    Text("APK zostanie pobrane z Twojego RadioCharts API przez LAN/Tailscale.", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
                }
            },
            confirmButton = {
                TextButton(enabled = !updating, onClick = { installUpdate(info) }) {
                    Text(if (updating) "Pobieram…" else "Aktualizuj")
                }
            },
            dismissButton = {
                TextButton(enabled = !updating, onClick = { pendingUpdate = null }) { Text("Później") }
            }
        )
    }
}

private fun androidStatusOrder(statuses: List<String>): List<String> = statuses.distinct()

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun SongListScreen(mode:String, title:String, navigate:(String)->Unit, withPeriod:Boolean=false, vm:ListVm=viewModel(key="list-$mode"), previewVm:PreviewPlayerVm) {
    val state by vm.state.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    var statusOpen by remember { mutableStateOf(false) }
    var stationOpen by remember { mutableStateOf(false) }
    var period by remember { mutableStateOf("7d") }
    var customStart by remember { mutableStateOf<LocalDate?>(null) }
    var customEnd by remember { mutableStateOf<LocalDate?>(null) }
    var showExactDates by remember { mutableStateOf(false) }

    fun presetRange(): Pair<LocalDate, LocalDate> {
        val end = LocalDate.now()
        val days = when(period){"1d"->1;"28d"->28;"90d"->90;else->7}
        return end.minusDays((days-1).toLong()) to end
    }
    fun effectiveRange(): Pair<LocalDate, LocalDate> {
        if (period == "custom" && customStart != null && customEnd != null) {
            return customStart!! to customEnd!!
        }
        return presetRange()
    }
    fun range(): Pair<String?,String?> {
        if (!withPeriod) return null to null
        val (start, end) = effectiveRange()
        return start.toString() to end.toString()
    }
    fun reload(append:Boolean=false) {
        scope.launch { val (s,e)=range(); vm.load(mode,s,e,append=append) }
    }
    LaunchedEffect(Unit) { val (s,e)=range(); vm.load(mode,s,e) }
    Column(Modifier.fillMaxSize().padding(horizontal=10.dp, vertical=6.dp)) {
        Row(verticalAlignment=Alignment.CenterVertically) {
            Text(title, style=MaterialTheme.typography.headlineSmall, fontWeight=FontWeight.Bold, modifier=Modifier.weight(1f))
            Text("${state.rows.size}/${state.total}", style=MaterialTheme.typography.labelMedium)
        }
        OutlinedTextField(
            value=state.search, onValueChange={vm.setSearch(it)}, label={Text("Szukaj wykonawcy / tytułu")},
            singleLine=true, modifier=Modifier.fillMaxWidth(),
            trailingIcon={ TextButton(onClick={reload()}) { Text("OK") } }
        )
        val (shownStart, shownEnd) = effectiveRange()
        Row(
            Modifier.fillMaxWidth().padding(top=2.dp).horizontalScroll(rememberScrollState()),
            horizontalArrangement=Arrangement.spacedBy(6.dp),
            verticalAlignment=Alignment.CenterVertically,
        ) {
            CompactFilterButton("Statusy${if(state.statuses.isEmpty())"" else " (${state.statuses.size})"}"){statusOpen=true}
            DownloadMenu(state.downloaded) { vm.setDownloaded(it); reload() }
            SortMenu(state.sort, withPeriod) { key, defaultDescending -> vm.setSort(key, defaultDescending); reload() }
            CompactFilterButton(if(state.descending) "↓" else "↑") { vm.toggleDirection(); reload() }
            if (withPeriod) {
                listOf("1d" to "1d","7d" to "7d","28d" to "28d","90d" to "3m").forEach { (k,l) ->
                    FilterChip(
                        selected=period==k,
                        onClick={period=k;showExactDates=false;reload()},
                        label={Text(l)},
                    )
                }
                CompactFilterButton(
                    "Daty ${shortDate(shownStart)}–${shortDate(shownEnd)}",
                    active = period == "custom" || showExactDates,
                ) { showExactDates = !showExactDates }
            }
            if (mode == "airplay") {
                val count = state.selectedStationIds.size
                CompactFilterButton(if(count == 0) "Stacje" else "Stacje ($count)") { stationOpen=true }
            }
        }
        if (withPeriod && showExactDates) {
            Row(Modifier.fillMaxWidth().padding(top=2.dp), horizontalArrangement=Arrangement.spacedBy(6.dp)) {
                DatePickerButton(
                    label = "Od",
                    value = shownStart,
                    modifier = Modifier.weight(1f),
                    onValue = { picked ->
                        val currentEnd = if (period == "custom") customEnd ?: shownEnd else shownEnd
                        customStart = picked
                        customEnd = if (picked > currentEnd) picked else currentEnd
                        period = "custom"
                        reload()
                    },
                )
                DatePickerButton(
                    label = "Do",
                    value = shownEnd,
                    modifier = Modifier.weight(1f),
                    onValue = { picked ->
                        val currentStart = if (period == "custom") customStart ?: shownStart else shownStart
                        customEnd = picked
                        customStart = if (picked < currentStart) picked else currentStart
                        period = "custom"
                        reload()
                    },
                )
            }
        }
        if (mode == "airplay") {
            state.reportingStations?.let { reporting ->
                Text("Raportujące: $reporting", style=MaterialTheme.typography.labelSmall, color=Color(0xFF98A2B3))
            }
        }
        if (state.loading || state.loadingMore) LinearProgressIndicator(Modifier.fillMaxWidth())
        state.error?.let { Text("Błąd: $it", color=MaterialTheme.colorScheme.error, modifier=Modifier.padding(8.dp)) }
        LazyColumn(verticalArrangement=Arrangement.spacedBy(6.dp), modifier=Modifier.fillMaxSize()) {
            items(state.rows, key={it.song_id}) { row ->
                SongCard(
                    s = row,
                    mode = mode,
                    statuses = state.meta.statuses,
                    savingStatus = state.savingSongIds.contains(row.song_id),
                    onStatusChange = { vm.changeStatus(row, it) },
                    previewVm = previewVm,
                    onClick = { navigate("song/${row.song_id}") },
                )
            }
            if (state.rows.size < state.total) {
                item {
                    OutlinedButton(
                        enabled=!state.loadingMore, onClick={reload(append=true)}, modifier=Modifier.fillMaxWidth().padding(vertical=6.dp)
                    ) { Text(if(state.loadingMore) "Ładuję…" else "Pokaż kolejne") }
                }
            }
        }
    }
    if (statusOpen) AlertDialog(
        onDismissRequest={statusOpen=false},
        confirmButton={TextButton(onClick={statusOpen=false;reload()}){Text("Zastosuj")}},
        dismissButton={TextButton(onClick={vm.clearStatuses()}){Text("Wyczyść")}},
        title={Text("Statusy")},
        text={LazyColumn(Modifier.heightIn(max=440.dp)){
            items(androidStatusOrder(state.meta.statuses)){st->Row(verticalAlignment=Alignment.CenterVertically){
                Checkbox(checked=state.statuses.contains(st),onCheckedChange={vm.toggleStatus(st)});Text(st)
            }}
        }}
    )
    if (stationOpen) AlertDialog(
        onDismissRequest={stationOpen=false},
        confirmButton={TextButton(onClick={stationOpen=false;reload()}){Text("Zastosuj")}},
        dismissButton={TextButton(onClick={vm.clearStations();stationOpen=false;reload()}){Text("Wszystkie")}},
        title={Text("Stacje radiowe")},
        text={Column(Modifier.heightIn(max=460.dp).verticalScroll(rememberScrollState())){
            state.stations.forEach{st->Row(verticalAlignment=Alignment.CenterVertically){
                Checkbox(checked=state.selectedStationIds.contains(st.station_id),onCheckedChange={vm.toggleStation(st.station_id)});Text(st.name)
            }}
        }}
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun DatePickerButton(label:String, value:LocalDate, modifier:Modifier=Modifier, onValue:(LocalDate)->Unit) {
    var open by remember { mutableStateOf(false) }
    OutlinedButton(
        onClick={open=true},
        modifier=modifier.heightIn(min=36.dp),
        contentPadding=PaddingValues(horizontal=8.dp, vertical=0.dp),
    ) { Text("$label ${value.dayOfMonth.toString().padStart(2, '0')}.${value.monthValue.toString().padStart(2, '0')}.${value.year}", maxLines=1, style=MaterialTheme.typography.labelMedium) }
    if (open) {
        val initialMillis = value.atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli()
        val pickerState = rememberDatePickerState(initialSelectedDateMillis = initialMillis)
        DatePickerDialog(
            onDismissRequest={open=false},
            confirmButton={
                TextButton(onClick={
                    pickerState.selectedDateMillis?.let { millis ->
                        onValue(Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC).toLocalDate())
                    }
                    open=false
                }) { Text("OK") }
            },
            dismissButton={TextButton(onClick={open=false}){Text("Anuluj")}},
        ) { DatePicker(state=pickerState) }
    }
}

private fun shortDate(value:LocalDate):String = "%02d.%02d".format(value.dayOfMonth, value.monthValue)

@Composable fun CompactFilterButton(text:String, active:Boolean=false, onClick:()->Unit) {
    OutlinedButton(
        onClick=onClick,
        contentPadding=PaddingValues(horizontal=10.dp, vertical=0.dp),
        modifier=Modifier.heightIn(min=34.dp),
        colors=if(active) ButtonDefaults.outlinedButtonColors(contentColor=Accent) else ButtonDefaults.outlinedButtonColors(),
    ) { Text(text,maxLines=1,style=MaterialTheme.typography.labelMedium) }
}

@Composable fun DownloadMenu(value:String,onValue:(String)->Unit){
    var open by remember{mutableStateOf(false)}
    Box{
        OutlinedButton(onClick={open=true},contentPadding=PaddingValues(horizontal=10.dp,vertical=0.dp),modifier=Modifier.heightIn(min=34.dp)){Text("Downloaded ${value.uppercase()}",style=MaterialTheme.typography.labelMedium)}
        DropdownMenu(expanded=open,onDismissRequest={open=false}){
            listOf("any","yes","no").forEach{DropdownMenuItem(text={Text(it.uppercase())},onClick={open=false;onValue(it)})}
        }
    }
}

data class SortChoice(val key:String, val label:String, val descending:Boolean)

private fun sortChoices(withPeriod:Boolean): List<SortChoice> {
    val common = listOf(
        SortChoice("popularity","Popularity",true),
        SortChoice("chart_score","Chart Score",true),
        SortChoice("momentum","Momentum",true),
        SortChoice("reach7","Zasięg 7d",true),
        SortChoice("spins7","Emisje 7d",true),
        SortChoice("radio_presence7","Radio Presence 7d",true),
        SortChoice("avg_position","Śr. pozycja",false),
        SortChoice("rmf","RMF",false),
        SortChoice("zet","ZET",false),
        SortChoice("olia","OLiA",false),
        SortChoice("olis","OLiS",false),
        SortChoice("eska","ESKA",false),
        SortChoice("artist","Wykonawca",false),
        SortChoice("title","Tytuł",false),
        SortChoice("status","Status",false),
    )
    if (!withPeriod) return common
    return listOf(
        SortChoice("spins","Emisje okres",true),
        SortChoice("stations","Liczba stacji",true),
        SortChoice("reach","Zasięg okres",true),
        SortChoice("rotation","Rotacja okres",true),
        SortChoice("radio_presence","Radio Presence okres",true),
        SortChoice("airplay_per_day","Emisje / dzień",true),
        SortChoice("last_play","Ostatnia emisja",true),
    ) + common
}

@Composable fun SortMenu(value:String,withPeriod:Boolean,onValue:(String,Boolean)->Unit){
    var open by remember{mutableStateOf(false)}
    Box{
        OutlinedButton(onClick={open=true},contentPadding=PaddingValues(horizontal=10.dp,vertical=0.dp),modifier=Modifier.heightIn(min=34.dp)){Text("Sort",style=MaterialTheme.typography.labelMedium)}
        DropdownMenu(expanded=open,onDismissRequest={open=false}){
            sortChoices(withPeriod).forEach{choice->
                DropdownMenuItem(
                    text={Text(choice.label + if(choice.descending) " ↓" else " ↑")},
                    onClick={open=false;onValue(choice.key,choice.descending)}
                )
            }
        }
    }
}

@Composable fun SongCard(
    s:SongRow,
    mode:String,
    statuses:List<String>,
    savingStatus:Boolean,
    onStatusChange:(String)->Unit,
    previewVm:PreviewPlayerVm,
    onClick:()->Unit,
) {
    Card(onClick=onClick, colors=CardDefaults.cardColors(containerColor=CardBg), modifier=Modifier.fillMaxWidth()) {
        Column(Modifier.padding(10.dp)) {
            Row {
                Column(Modifier.weight(1f)){
                    Text(s.artist,style=MaterialTheme.typography.labelMedium,color=Color(0xFFB5BDC9))
                    Text(s.title,fontWeight=FontWeight.SemiBold,maxLines=2,overflow=TextOverflow.Ellipsis)
                }
                Text(s.status,style=MaterialTheme.typography.labelSmall,color=Accent)
            }
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement=Arrangement.spacedBy(12.dp)) {
                MetricTiny("Pop",s.popularity?.let{"%.0f%%".format(it)}?:"—")
                MetricTiny("Chart",s.familiarity?.let{"%.0f%%".format(it)}?:"—")
                MetricTiny("Mom",s.momentum?.let{"%.0f%%".format(it)}?:"—")
                MetricTiny("R7",s.radio_reach?.let{"%.0f%%".format(it)}?:"—")
                MetricTiny("E7",(s.airplay_spins_7d?:0).toString())
                if(mode!="dashboard") MetricTiny("Em",(s.spins?:0).toString())
            }
            Row(Modifier.padding(top=5.dp), horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                ChartBadge("RMF",s.RMF_pos,s.RMF_weeks);ChartBadge("ZET",s.ZET_pos,s.ZET_weeks);ChartBadge("OLIA",s.OLIA_pos,s.OLIA_weeks);ChartBadge("OLIS",s.OLIS_pos,s.OLIS_weeks);ChartBadge("ESKA",s.ESKA_pos,s.ESKA_weeks)
            }
            Row(
                Modifier.fillMaxWidth().padding(top=7.dp),
                horizontalArrangement=Arrangement.spacedBy(7.dp),
                verticalAlignment=Alignment.CenterVertically,
            ) {
                PreviewButton(s, previewVm)
                SpotifyButton(s, compact = true)
                InlineStatusMenu(
                    value = s.status,
                    statuses = statuses,
                    enabled = !savingStatus,
                    modifier = Modifier.weight(1f),
                    onValue = onStatusChange,
                )
            }
        }
    }
}

@Composable fun StatusPickerDialog(
    value:String,
    statuses:List<String>,
    onDismiss:()->Unit,
    onValue:(String)->Unit,
) {
    AlertDialog(
        onDismissRequest=onDismiss,
        confirmButton={TextButton(onClick=onDismiss){Text("Anuluj")}},
        title={Text("Wybierz status")},
        text={
            LazyColumn(Modifier.heightIn(max=460.dp)) {
                items(androidStatusOrder(statuses)) { status ->
                    Row(
                        Modifier.fillMaxWidth().clickable{onValue(status)}.padding(vertical=10.dp, horizontal=4.dp),
                        verticalAlignment=Alignment.CenterVertically,
                    ) {
                        RadioButton(selected=status==value,onClick={onValue(status)})
                        Text(status,modifier=Modifier.padding(start=6.dp))
                    }
                }
            }
        },
    )
}

@Composable fun InlineStatusMenu(
    value:String,
    statuses:List<String>,
    enabled:Boolean,
    modifier:Modifier=Modifier,
    onValue:(String)->Unit,
) {
    var open by remember{mutableStateOf(false)}
    Box(modifier) {
        OutlinedButton(onClick={open=true},enabled=enabled,modifier=Modifier.fillMaxWidth()) {
            Text(if(enabled) value else "Zapisuję…",maxLines=1,overflow=TextOverflow.Ellipsis)
        }
    }
    if(open) {
        StatusPickerDialog(
            value=value,
            statuses=statuses,
            onDismiss={open=false},
            onValue={open=false;onValue(it)},
        )
    }
}

@Composable fun MetricTiny(label:String,value:String){Column{Text(label,style=MaterialTheme.typography.labelSmall,color=Color(0xFF98A2B3));Text(value,style=MaterialTheme.typography.bodyMedium,fontWeight=FontWeight.Bold)}}
@Composable fun ChartBadge(label:String,pos:Int?,weeks:Int?){Text(if(pos==null)"$label —" else "$label #$pos (${weeks?:0}w)",style=MaterialTheme.typography.labelSmall,color=Color(0xFFB5BDC9))}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun SongScreen(id:Int, previewVm:PreviewPlayerVm, navigate:(String)->Unit) {
    val context=LocalContext.current; val store=remember{SettingsStore(context)}; val scope=rememberCoroutineScope()
    var song by remember{id.let{mutableStateOf<SongRow?>(null)}};var charts by remember{mutableStateOf<List<ChartPoint>>(emptyList())};var air by remember{mutableStateOf<AirplayDetail?>(null)};var stations by remember{mutableStateOf<List<Station>>(emptyList())};var selectedStations by remember{mutableStateOf<Set<Int>>(emptySet())};var meta by remember{mutableStateOf(MetaResponse())};var error by remember{mutableStateOf<String?>(null)};var stationOpen by remember{mutableStateOf(false)};var period by remember{mutableStateOf("7d")};var savingNote by remember{mutableStateOf(false)};var savingState by remember{mutableStateOf(false)}
    suspend fun reloadAir(){try{val api=ApiProvider.api(store);val end=LocalDate.now();val days=when(period){"1d"->1;"28d"->28;"90d"->90;else->7};val ids=selectedStations.takeIf{it.isNotEmpty()}?.joinToString(",");air=api.airplay(id,end.minusDays((days-1).toLong()).toString(),end.toString(),ids)}catch(e:Exception){error=e.message}}
    LaunchedEffect(id){try{val api=ApiProvider.api(store);song=api.song(id);charts=api.charts(id);stations=api.stations();meta=api.meta();reloadAir()}catch(e:Exception){error=e.message}}
    val s=song
    if(s==null){Box(Modifier.fillMaxSize(),contentAlignment=Alignment.Center){if(error!=null)Text("Błąd: $error") else CircularProgressIndicator()};return}
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp)) {
        Text(s.artist,style=MaterialTheme.typography.titleMedium,color=Color(0xFFB5BDC9));Text(s.title,style=MaterialTheme.typography.headlineSmall,fontWeight=FontWeight.Bold)
        Row(Modifier.fillMaxWidth().padding(vertical=8.dp),horizontalArrangement=Arrangement.SpaceBetween){MetricTiny("Popularity",s.popularity?.let{"%.0f%%".format(it)}?:"—");MetricTiny("Chart Score",s.familiarity?.let{"%.0f%%".format(it)}?:"—");MetricTiny("Momentum",s.momentum?.let{"%.0f%%".format(it)}?:"—");MetricTiny("Zasięg 7d",s.radio_reach?.let{"%.0f%%".format(it)}?:"—");MetricTiny("Emisje 7d",(s.airplay_spins_7d?:0).toString())}
        Row(horizontalArrangement=Arrangement.spacedBy(8.dp)){PreviewButton(s, previewVm);SpotifyButton(s)}
        OutlinedButton(
            onClick={context.startActivity(Intent(Intent.ACTION_VIEW,Uri.parse("https://www.olis.pl/charts/oficjalna-lista-wyroznien")))},
            modifier=Modifier.fillMaxWidth(),
        ){Text("OLiS wyróżnienia ↗")}
        HorizontalDivider(Modifier.padding(vertical=8.dp))
        var dl by remember(s.song_id,s.downloaded){mutableStateOf(s.downloaded)};var status by remember(s.song_id,s.status){mutableStateOf(s.status)};var note by remember(s.song_id,s.note){mutableStateOf(s.note)}
        Row(verticalAlignment=Alignment.CenterVertically){
            Checkbox(checked=dl,onCheckedChange={newDl->
                if(!savingState){
                    dl=newDl
                    scope.launch{
                        savingState=true
                        try{
                            val updated=ApiProvider.api(store).patchSong(id,NotePatch(status != "Nie słuchałem",status,newDl,s.note)).song
                            song=updated;dl=updated.downloaded;status=updated.status
                        }catch(e:Exception){dl=s.downloaded;error=e.message}finally{savingState=false}
                    }
                }
            })
            Text("Downloaded")
            if(savingState) CircularProgressIndicator(Modifier.padding(start=8.dp).size(18.dp),strokeWidth=2.dp)
        }
        StatusMenu(status,meta.statuses){newStatus->
            if(!savingState && newStatus!=status){
                status=newStatus
                scope.launch{
                    savingState=true
                    try{
                        val updated=ApiProvider.api(store).patchSong(id,NotePatch(newStatus != "Nie słuchałem",newStatus,dl,s.note)).song
                        song=updated;status=updated.status;dl=updated.downloaded
                    }catch(e:Exception){status=s.status;error=e.message}finally{savingState=false}
                }
            }
        }
        OutlinedTextField(value=note,onValueChange={note=it},label={Text("Notatka")},modifier=Modifier.fillMaxWidth())
        Button(enabled=!savingNote && !savingState,onClick={scope.launch{savingNote=true;try{song=ApiProvider.api(store).patchSong(id,NotePatch(status != "Nie słuchałem",status,dl,note)).song}catch(e:Exception){error=e.message}finally{savingNote=false}}},modifier=Modifier.fillMaxWidth()){Text(if(savingNote)"Zapisuję…" else "Zapisz")}
        HorizontalDivider(Modifier.padding(vertical=8.dp))
        Text("Pozycje na listach",style=MaterialTheme.typography.titleMedium)
        val grouped=charts.groupBy{it.source}
        if(grouped.isEmpty()) {
            Text("Brak historii")
        } else {
            Row(
                modifier=Modifier.fillMaxWidth().clickable{navigate("chart/$id/__ALL__")}.padding(vertical=9.dp, horizontal=4.dp),
                verticalAlignment=Alignment.CenterVertically,
            ){
                Text(
                    "Wszystkie listy · ${grouped.size}",
                    modifier=Modifier.weight(1f),
                    fontWeight=FontWeight.SemiBold,
                )
                Text("Wspólny wykres ›",style=MaterialTheme.typography.labelMedium,color=Accent)
            }
            HorizontalDivider()
            grouped.forEach{(src,rawPts)->
                val pts=rawPts.sortedBy{it.chart_date}
                val last=pts.lastOrNull()
                val peak=pts.minOfOrNull{it.position}
                Row(
                    modifier=Modifier.fillMaxWidth().clickable{navigate("chart/$id/${Uri.encode(src)}")}.padding(vertical=8.dp, horizontal=4.dp),
                    verticalAlignment=Alignment.CenterVertically,
                ){
                    Text(
                        "$src: ${last?.position?.let{"#$it"}?:"—"} · peak ${peak?.let{"#$it"}?:"—"} · ${pts.size} notowań",
                        modifier=Modifier.weight(1f),
                    )
                    Text("Wykres ›",style=MaterialTheme.typography.labelMedium,color=Accent)
                }
                HorizontalDivider()
            }
        }
        HorizontalDivider(Modifier.padding(vertical=8.dp))
        Row(verticalAlignment=Alignment.CenterVertically){Text("Emisje radiowe",style=MaterialTheme.typography.titleMedium,modifier=Modifier.weight(1f));OutlinedButton(onClick={stationOpen=true}){Text(if(selectedStations.isEmpty())"Wszystkie stacje" else "Stacje: ${selectedStations.size}")}}
        Row(horizontalArrangement=Arrangement.spacedBy(6.dp)){listOf("1d" to "Dzisiaj","7d" to "7 dni","28d" to "28 dni","90d" to "3 mies.").forEach{(k,l)->FilterChip(selected=period==k,onClick={period=k;scope.launch{reloadAir()}},label={Text(l)})}}
        air?.let{a->Row(Modifier.fillMaxWidth().padding(vertical=6.dp),horizontalArrangement=Arrangement.SpaceBetween){MetricTiny("Emisje",a.total_spins.toString());MetricTiny("Zasięg","%.0f%%".format(a.period_reach));MetricTiny("Stacje","${a.stations_count}/${a.reporting_stations}");MetricTiny("/dzień","%.1f".format(a.airplay_per_day))};Text("Per stacja",style=MaterialTheme.typography.titleSmall);a.stations.forEach{Text("${it.station}: ${it.spins} · ${it.active_days} dni",modifier=Modifier.padding(vertical=2.dp))}}
        error?.let{Text("Błąd: $it",color=MaterialTheme.colorScheme.error)}
        Spacer(Modifier.height(80.dp))
    }
    if(stationOpen)AlertDialog(onDismissRequest={stationOpen=false},confirmButton={TextButton(onClick={stationOpen=false;scope.launch{reloadAir()}}){Text("Zastosuj")}},dismissButton={TextButton(onClick={selectedStations=emptySet()}){Text("Wszystkie")}},title={Text("Stacje")},text={Column(Modifier.heightIn(max=460.dp).verticalScroll(rememberScrollState())){stations.forEach{st->Row(verticalAlignment=Alignment.CenterVertically){Checkbox(checked=selectedStations.contains(st.station_id),onCheckedChange={val set=selectedStations.toMutableSet();if(it)set.add(st.station_id)else set.remove(st.station_id);selectedStations=set});Text(st.name)}}}})
}

@Composable fun ToplistChartScreen(id:Int, source:String, onBack:()->Unit) {
    val context=LocalContext.current
    val configuration=LocalConfiguration.current
    val activity=context as? Activity
    val store=remember{SettingsStore(context)}
    val allSources=source=="__ALL__"
    var song by remember{mutableStateOf<SongRow?>(null)}
    var points by remember{mutableStateOf<List<ChartPoint>>(emptyList())}
    var loading by remember{mutableStateOf(true)}
    var error by remember{mutableStateOf<String?>(null)}
    var forcedLandscape by remember{mutableStateOf(false)}

    fun leaveChart() {
        activity?.requestedOrientation=ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
        onBack()
    }

    BackHandler { leaveChart() }
    LaunchedEffect(Unit) {
        // Keep the orientation the user is already using. With system auto-rotate
        // enabled the chart follows the phone; the button below can force landscape
        // even when the device is portrait-locked.
        activity?.requestedOrientation=ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
    }
    LaunchedEffect(id,source) {
        loading=true
        error=null
        try {
            val api=ApiProvider.api(store)
            song=api.song(id)
            val all=api.charts(id).sortedBy{it.chart_date}
            points=if(allSources) all else all.filter{it.source==source}
        } catch(e:Exception) {
            error=e.message ?: e.javaClass.simpleName
        } finally {
            loading=false
        }
    }

    val s=song
    Column(Modifier.fillMaxSize().padding(horizontal=12.dp,vertical=8.dp)) {
        Row(verticalAlignment=Alignment.CenterVertically) {
            OutlinedButton(onClick={ leaveChart() }){Text("‹ Wróć")}
            OutlinedButton(
                onClick={
                    if(forcedLandscape || configuration.orientation==Configuration.ORIENTATION_LANDSCAPE) {
                        forcedLandscape=false
                        activity?.requestedOrientation=ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
                    } else {
                        forcedLandscape=true
                        activity?.requestedOrientation=ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
                    }
                },
                modifier=Modifier.padding(start=6.dp),
            ){
                Text(if(forcedLandscape || configuration.orientation==Configuration.ORIENTATION_LANDSCAPE) "↕ Auto" else "⟳ Poziomo")
            }
            Column(Modifier.padding(start=10.dp).weight(1f)) {
                Text(if(allSources) "Wszystkie listy" else source,style=MaterialTheme.typography.titleLarge,fontWeight=FontWeight.Bold)
                Text(
                    if(s==null) "Toplisty" else "${s.artist} — ${s.title}",
                    style=MaterialTheme.typography.bodyMedium,
                    color=Color(0xFFB5BDC9),
                    maxLines=1,
                    overflow=TextOverflow.Ellipsis,
                )
            }
        }
        if(loading) {
            LinearProgressIndicator(Modifier.fillMaxWidth().padding(top=8.dp))
            return@Column
        }
        error?.let {
            Text("Błąd: $it",color=MaterialTheme.colorScheme.error,modifier=Modifier.padding(top=12.dp))
            return@Column
        }
        if(points.isEmpty()) {
            Box(Modifier.fillMaxSize(),contentAlignment=Alignment.Center){Text(if(allSources) "Brak historii toplist" else "Brak historii dla $source")}
            return@Column
        }

        val latest=points.maxByOrNull{it.chart_date}!!
        val peak=points.minOf{it.position}
        val peakPoint=points.filter{it.position==peak}.minByOrNull{it.chart_date}!!
        val sources=points.map{it.source}.distinct()
        Row(Modifier.fillMaxWidth().padding(vertical=6.dp).horizontalScroll(rememberScrollState()),horizontalArrangement=Arrangement.spacedBy(24.dp)) {
            if(allSources) {
                MetricTiny("Listy",sources.size.toString())
                MetricTiny("Punkty",points.size.toString())
                MetricTiny("Peak ${peakPoint.source}","#$peak · ${shortChartDate(peakPoint.chart_date)}")
            } else {
                MetricTiny("Ostatnia","#${latest.position}")
                MetricTiny("Peak","#$peak · ${shortChartDate(peakPoint.chart_date)}")
                MetricTiny("Notowania",points.size.toString())
            }
            MetricTiny("Zakres","${shortChartDate(points.minBy{it.chart_date}.chart_date)} – ${shortChartDate(points.maxBy{it.chart_date}.chart_date)}")
        }
        if(allSources) {
            Row(
                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(bottom=3.dp),
                horizontalArrangement=Arrangement.spacedBy(14.dp),
            ) {
                sources.forEachIndexed { index,src ->
                    Text("● $src",color=toplistSeriesColor(index),style=MaterialTheme.typography.labelMedium)
                }
            }
        }
        ToplistLineChart(points=points,modifier=Modifier.fillMaxWidth().weight(1f))
    }
}

private fun shortChartDate(raw:String):String {
    return runCatching {
        val d=LocalDate.parse(raw.take(10))
        "${d.dayOfMonth.toString().padStart(2,'0')}.${d.monthValue.toString().padStart(2,'0')}.${d.year}"
    }.getOrDefault(raw.take(10))
}

private val ToplistSeriesColors=listOf(
    Accent,
    Color(0xFFFFB74D),
    Color(0xFF64B5F6),
    Color(0xFFE57373),
    Color(0xFFBA68C8),
    Color(0xFFAED581),
    Color(0xFFFF8A65),
    Color(0xFF4DD0E1),
)
private fun toplistSeriesColor(index:Int)=ToplistSeriesColors[index % ToplistSeriesColors.size]

private fun chartOffset(
    point:ChartPoint,
    dateIndex:Map<String,Int>,
    dateCount:Int,
    maxRank:Int,
    width:Float,
    height:Float,
):Offset {
    val idx=dateIndex[point.chart_date] ?: 0
    val x=if(dateCount<=1) width/2f else width*idx.toFloat()/(dateCount-1).toFloat()
    val y=height*(point.position-1).toFloat()/(maxRank-1).toFloat()
    return Offset(x,y)
}

@Composable fun ToplistLineChart(points:List<ChartPoint>, modifier:Modifier=Modifier) {
    val maxRank=(points.maxOfOrNull{maxOf(it.chart_size,it.position)} ?: 20).coerceAtLeast(2)
    val middleRank=((maxRank+1)/2).coerceAtLeast(2)
    val dates=points.map{it.chart_date}.distinct().sorted()
    val dateIndex=dates.withIndex().associate{it.value to it.index}
    val sources=points.map{it.source}.distinct()
    val bySource=points.groupBy{it.source}.mapValues{(_,pts)->pts.sortedBy{it.chart_date}}
    var selectedDate by remember(points){mutableStateOf<String?>(null)}
    val selectedPoints=selectedDate?.let { d ->
        points.filter{it.chart_date==d}.sortedBy { p ->
            val i=sources.indexOf(p.source)
            if(i<0) Int.MAX_VALUE else i
        }
    }.orEmpty()

    Row(modifier.padding(top=2.dp,bottom=4.dp)) {
        Column(
            Modifier.width(42.dp).fillMaxHeight().padding(bottom=24.dp),
            verticalArrangement=Arrangement.SpaceBetween,
            horizontalAlignment=Alignment.End,
        ) {
            Text("#1",style=MaterialTheme.typography.labelSmall)
            Text("#$middleRank",style=MaterialTheme.typography.labelSmall)
            Text("#$maxRank",style=MaterialTheme.typography.labelSmall)
        }
        Column(Modifier.fillMaxSize().padding(start=7.dp)) {
            Box(Modifier.fillMaxWidth().weight(1f)) {
                Canvas(
                    Modifier.fillMaxSize().pointerInput(points,dates,maxRank) {
                        awaitPointerEventScope {
                            while(true) {
                                val event=awaitPointerEvent()
                                if(event.type==PointerEventType.Move || event.type==PointerEventType.Press) {
                                    val pos=event.changes.firstOrNull()?.position ?: continue
                                    val w=size.width.toFloat().coerceAtLeast(1f)
                                    if(dates.isNotEmpty()) {
                                        val raw=((pos.x.coerceIn(0f,w)/w)*(dates.size-1).coerceAtLeast(0).toFloat())
                                        val idx=(raw+0.5f).toInt().coerceIn(0,dates.lastIndex)
                                        selectedDate=dates[idx]
                                    }
                                }
                            }
                        }
                    }
                ) {
                    val w=size.width
                    val h=size.height
                    val grid=Color.White.copy(alpha=0.12f)
                    listOf(0f,0.25f,0.5f,0.75f,1f).forEach { ratio ->
                        val y=h*ratio
                        drawLine(grid,Offset(0f,y),Offset(w,y),strokeWidth=1f)
                    }
                    sources.forEachIndexed { sourceIndex,src ->
                        val color=toplistSeriesColor(sourceIndex)
                        val srcPoints=bySource[src].orEmpty()
                        if(srcPoints.isNotEmpty()) {
                            val path=Path()
                            srcPoints.forEachIndexed { index,p ->
                                val o=chartOffset(p,dateIndex,dates.size,maxRank,w,h)
                                if(index==0) path.moveTo(o.x,o.y) else path.lineTo(o.x,o.y)
                            }
                            drawPath(path,color,style=Stroke(width=3.5f))
                            srcPoints.forEach { p ->
                                val o=chartOffset(p,dateIndex,dates.size,maxRank,w,h)
                                drawCircle(color,radius=4.5f,center=o)
                            }
                        }
                    }
                    selectedDate?.let { d ->
                        val idx=dateIndex[d] ?: 0
                        val x=if(dates.size<=1) w/2f else w*idx.toFloat()/(dates.size-1).toFloat()
                        drawLine(Color.White.copy(alpha=0.42f),Offset(x,0f),Offset(x,h),strokeWidth=1.5f)
                        selectedPoints.forEach { p ->
                            val o=chartOffset(p,dateIndex,dates.size,maxRank,w,h)
                            drawCircle(Color.White,radius=8f,center=o,style=Stroke(width=2.5f))
                        }
                    }
                }
                selectedDate?.let { d ->
                    Surface(
                        modifier=Modifier.align(Alignment.TopEnd).padding(8.dp),
                        shape=MaterialTheme.shapes.small,
                        tonalElevation=5.dp,
                    ) {
                        Column(Modifier.padding(horizontal=10.dp,vertical=7.dp)) {
                            Text(shortChartDate(d),style=MaterialTheme.typography.labelLarge,fontWeight=FontWeight.Bold)
                            selectedPoints.forEach { p ->
                                Text(
                                    "${p.source}  #${p.position}",
                                    style=MaterialTheme.typography.labelMedium,
                                    color=toplistSeriesColor(sources.indexOf(p.source).coerceAtLeast(0)),
                                )
                            }
                        }
                    }
                }
            }
            val middleDate=dates[dates.size/2]
            Row(Modifier.fillMaxWidth().height(24.dp),horizontalArrangement=Arrangement.SpaceBetween) {
                Text(shortChartDate(dates.first()),style=MaterialTheme.typography.labelSmall)
                if(dates.size>2) Text(shortChartDate(middleDate),style=MaterialTheme.typography.labelSmall)
                Text(shortChartDate(dates.last()),style=MaterialTheme.typography.labelSmall)
            }
            Text(
                "Najedź lub dotknij daty: pionowa linia zaznaczy wszystkie punkty toplist z tego dnia.",
                style=MaterialTheme.typography.labelSmall,
                color=Color(0xFFB5BDC9),
                modifier=Modifier.padding(top=2.dp),
            )
        }
    }
}

@Composable fun StatusMenu(value:String, statuses:List<String>,onValue:(String)->Unit){
    var open by remember{mutableStateOf(false)}
    OutlinedButton(onClick={open=true},modifier=Modifier.fillMaxWidth()){Text("Status: $value")}
    if(open) {
        StatusPickerDialog(
            value=value,
            statuses=statuses,
            onDismiss={open=false},
            onValue={open=false;onValue(it)},
        )
    }
}
@Composable fun SpotifyButton(s:SongRow, compact:Boolean=false){
    val context=LocalContext.current
    OutlinedButton(
        onClick={
            val q=Uri.encode("${s.artist} ${s.title}")
            context.startActivity(Intent(Intent.ACTION_VIEW,Uri.parse("https://open.spotify.com/search/$q")))
        },
        modifier=if(compact) Modifier.heightIn(min=36.dp) else Modifier,
        contentPadding=if(compact) PaddingValues(horizontal=9.dp, vertical=0.dp) else ButtonDefaults.ContentPadding,
    ){Text(if(compact) "Spotify" else "Spotify ↗",maxLines=1,style=if(compact) MaterialTheme.typography.labelMedium else MaterialTheme.typography.labelLarge)}
}
@Composable fun PreviewButton(s:SongRow, previewVm:PreviewPlayerVm) {
    val preview by previewVm.state.collectAsStateWithLifecycle()
    val loading = preview.loadingSongId == s.song_id
    val playing = preview.playingSongId == s.song_id
    OutlinedButton(onClick={previewVm.toggle(s)}) {
        Text(when {
            loading -> "Szukam…"
            playing -> "⏸ 30s"
            else -> "▶ 30s"
        })
    }
}


@Composable fun LocalRadioScreen(store: SettingsStore, onSong: (Int) -> Unit) {
    var tab by remember { mutableStateOf(0) }
    val tabs = listOf("Scheduled", "ETM", "Played", "Porównanie", "Utwory", "Import")
    Column(Modifier.fillMaxSize()) {
        ScrollableTabRow(selectedTabIndex = tab, edgePadding = 8.dp) {
            tabs.forEachIndexed { index, label ->
                Tab(selected = tab == index, onClick = { tab = index }, text = { Text(label, maxLines = 1) })
            }
        }
        when (tab) {
            0 -> LocalRadioTimeline(store, "schedule", onSong)
            1 -> LocalRadioEtm(store)
            2 -> LocalRadioTimeline(store, "played", onSong)
            3 -> LocalRadioCompare(store, onSong)
            4 -> LocalRadioSongs(store)
            else -> LocalRadioImport(store)
        }
    }
}

@Composable private fun LocalRadioDateHourControls(
    dates: List<String>,
    selectedDate: String,
    selectedHour: Int,
    onDate: (String) -> Unit,
    onHour: (Int) -> Unit,
) {
    var dateOpen by remember { mutableStateOf(false) }
    var hourOpen by remember { mutableStateOf(false) }
    Row(Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Box(Modifier.weight(1f)) {
            OutlinedButton(onClick = { dateOpen = true }, modifier = Modifier.fillMaxWidth()) {
                Text(selectedDate.ifBlank { "Dzień" }, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            DropdownMenu(expanded = dateOpen, onDismissRequest = { dateOpen = false }) {
                dates.reversed().take(45).forEach { d ->
                    DropdownMenuItem(text = { Text(d) }, onClick = { dateOpen = false; onDate(d) })
                }
            }
        }
        Box(Modifier.width(138.dp)) {
            OutlinedButton(onClick = { hourOpen = true }, modifier = Modifier.fillMaxWidth()) {
                Text("%02d:00–%02d:59+".format(selectedHour, selectedHour))
            }
            DropdownMenu(expanded = hourOpen, onDismissRequest = { hourOpen = false }) {
                (0..23).forEach { h ->
                    DropdownMenuItem(text = { Text("%02d:00–%02d:59+".format(h, h)) }, onClick = { hourOpen = false; onHour(h) })
                }
            }
        }
    }
}

@Composable private fun LocalHourJumpBar(selectedHour: Int, onHour: (Int) -> Unit) {
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 10.dp, vertical = 2.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        (0..23).forEach { h ->
            OutlinedButton(
                onClick = { onHour(h) },
                modifier = Modifier.heightIn(min = 32.dp),
                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp),
                colors = ButtonDefaults.outlinedButtonColors(
                    containerColor = if (h == selectedHour) MaterialTheme.colorScheme.primary.copy(alpha = .16f) else Color.Transparent
                ),
            ) { Text("%02d".format(h), style = MaterialTheme.typography.labelSmall) }
        }
    }
}

private fun localRadioDefaultDate(kind: String, dates: List<String>): String {
    if (dates.isEmpty()) return ""
    val today = LocalDate.now().toString()
    return if (kind == "schedule") {
        dates.firstOrNull { it >= today } ?: dates.last()
    } else {
        dates.lastOrNull { it <= today } ?: dates.last()
    }
}

@Composable private fun LocalRadioTimeline(store: SettingsStore, kind: String, onSong: (Int) -> Unit) {
    var dates by remember(kind) { mutableStateOf<List<String>>(emptyList()) }
    var day by remember(kind) { mutableStateOf("") }
    var hour by remember(kind) { mutableStateOf(LocalTime.now().hour) }
    var rows by remember(kind) { mutableStateOf<List<LocalRadioEvent>>(emptyList()) }
    var loading by remember(kind) { mutableStateOf(true) }
    var error by remember(kind) { mutableStateOf("") }

    suspend fun loadDates() {
        try {
            val result = ApiProvider.api(store).localRadioDates(kind)
            dates = result
            if (day.isBlank() || day !in result) day = localRadioDefaultDate(kind, result)
        } catch (e: Exception) { error = e.message ?: e.javaClass.simpleName }
    }
    suspend fun loadRows(showLoading: Boolean = true) {
        if (day.isBlank()) return
        if (showLoading) loading = true
        error = ""
        try { rows = ApiProvider.api(store).localRadioEvents(kind, day, hour, continuity = true) }
        catch (e: Exception) { error = e.message ?: e.javaClass.simpleName }
        finally { if (showLoading) loading = false }
    }
    LaunchedEffect(kind) { loadDates() }
    LaunchedEffect(day, hour, kind) {
        if (day.isBlank()) return@LaunchedEffect
        loadRows(true)
        if (kind == "played") {
            while (true) {
                delay(15_000)
                loadRows(false)
            }
        }
    }

    val groups = remember(rows) {
        buildList<List<LocalRadioEvent>> {
            var traffic = mutableListOf<LocalRadioEvent>()
            fun flush() {
                if (traffic.isNotEmpty()) { add(traffic.toList()); traffic = mutableListOf() }
            }
            rows.forEach { row ->
                if (row.event_type == "traffic") traffic.add(row)
                else { flush(); add(listOf(row)) }
            }
            flush()
        }
    }

    Column(Modifier.fillMaxSize()) {
        LocalRadioDateHourControls(dates, day, hour, { day = it }, { hour = it })
        LocalHourJumpBar(hour) { hour = it }
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 2.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(if (kind == "schedule") "Scheduled" else "Played", fontWeight = FontWeight.Bold)
            Text("${rows.size} elementów", style = MaterialTheme.typography.bodySmall)
        }
        if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (error.isNotBlank()) Text("Błąd: $error", color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(12.dp))
        if (!loading && rows.isEmpty() && error.isBlank()) Text("Brak elementów dla tej godziny.", modifier = Modifier.padding(16.dp))
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(8.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            itemsIndexed(groups, key = { index, group -> "${kind}_${group.firstOrNull()?.id ?: index}_$index" }) { _, group ->
                if (group.size > 1 && group.all { it.event_type == "traffic" }) {
                    LocalRadioTrafficBlock(group, kind, onSong)
                } else {
                    LocalRadioEventCard(group.first(), kind, onSong)
                }
            }
        }
    }
}

private fun localRadioTextColor(row: LocalRadioEvent): Color = when (row.event_type) {
    "song" -> Color(0xFFF4F4F5)
    "traffic" -> Color(0xFFFF5D5D)
    "etm" -> Color(0xFF69D6FF)
    "toh" -> Color(0xFFFF79C6)
    else -> Color(0xFFF4CF57)
}

@Composable private fun LocalRadioTrafficBlock(rows: List<LocalRadioEvent>, kind: String, onSong: (Int) -> Unit) {
    var open by remember(rows.firstOrNull()?.id) { mutableStateOf(false) }
    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color(0xFF1B0F12))) {
        Column {
            Row(
                Modifier.fillMaxWidth().clickable { open = !open }.padding(horizontal = 12.dp, vertical = 9.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(if (open) "−" else "+", color = Color(0xFFFF5D5D), fontWeight = FontWeight.Bold, modifier = Modifier.width(24.dp))
                Text("REKLAMA/AUTOPROMOCJA", color = Color(0xFFFF5D5D), fontWeight = FontWeight.Bold)
                Spacer(Modifier.weight(1f))
                Text("${rows.size} poz.", color = Color(0xFFFF8C8C), style = MaterialTheme.typography.labelSmall)
            }
            if (open) {
                rows.forEach { LocalRadioEventCard(it, kind, onSong) }
            }
        }
    }
}

@Composable private fun LocalRadioEventCard(row: LocalRadioEvent, kind: String, onSong: (Int) -> Unit) {
    val current = kind == "played" && (row.display_phase == "current" || row.zetta_status_code in listOf(-3, 2, 9))
    val past = kind == "played" && row.display_phase == "played_past" && !current
    val future = kind == "played" && row.display_phase == "future_schedule"
    val toh = row.event_type == "toh"
    val main = if (toh) {
        "Top of the hour"
    } else {
        listOf(row.artist, row.title).filter { it.isNotBlank() }.joinToString(" — ").ifBlank { row.category.ifBlank { row.event_type } }
    }
    val categoryCode = row.category_code.ifBlank {
        when (row.event_type) {
            "etm" -> row.title.substringAfterLast("_").uppercase()
            "show" -> "AUD"
            "toh" -> "TOH"
            else -> row.category.substringBefore("/").ifBlank { row.event_type.uppercase() }
        }
    }
    val metadata = buildList {
        if (row.mood.isNotBlank()) add("Mood ${row.mood}")
        if (row.opener.isNotBlank()) add("Opener ${row.opener}")
        if (row.texture_open.isNotBlank()) add("T.Open ${row.texture_open}")
        if (row.texture_close.isNotBlank()) add("T.Close ${row.texture_close}")
        if (row.event_type == "etm" && row.etm_delta_raw.isNotBlank()) add("gap ${row.etm_delta_raw}")
        if (future) add("Scheduled — jeszcze nie zagrano")
        else if (kind == "played" && row.zetta_status.isNotBlank()) add(row.zetta_status)
    }.joinToString(" · ")
    val timing = buildList {
        if (row.runtime_raw.isNotBlank()) add("runtime ${row.runtime_raw}")
        if (kind == "played" && !future && row.played_raw.isNotBlank()) add("zagrano ${row.played_raw}")
    }.joinToString(" · ")

    var modifier = Modifier.fillMaxWidth()
    if (row.event_type == "song" && row.song_id != null) {
        modifier = modifier.pointerInput(row.song_id) {
            detectTapGestures(onDoubleTap = { onSong(row.song_id) })
        }
    }
    val container = when {
        toh -> Color(0xFF2A1526)
        current -> Color(0xFF10231A)
        future -> Color(0xFF1A2028)
        else -> CardBg
    }
    val baseColor = localRadioTextColor(row)
    val titleColor = if (past) baseColor.copy(alpha = .62f) else baseColor
    Card(modifier, colors = CardDefaults.cardColors(containerColor = container)) {
        Row(Modifier.fillMaxWidth().padding(10.dp), verticalAlignment = Alignment.Top) {
            Text(row.air_time_raw, style = MaterialTheme.typography.labelMedium, modifier = Modifier.width(78.dp), color = if (current) Color(0xFF7EE29D) else titleColor, fontStyle = if (past) FontStyle.Italic else FontStyle.Normal)
            Text(categoryCode, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold, modifier = Modifier.width(62.dp), color = titleColor, fontStyle = if (past) FontStyle.Italic else FontStyle.Normal)
            Column(Modifier.weight(1f)) {
                Text(main, fontWeight = if (row.event_type in listOf("etm", "toh") || current) FontWeight.Bold else FontWeight.Medium, fontStyle = if (past) FontStyle.Italic else FontStyle.Normal, color = titleColor, maxLines = 2, overflow = TextOverflow.Ellipsis)
                if (metadata.isNotBlank()) Text(metadata, style = MaterialTheme.typography.labelSmall, color = titleColor.copy(alpha = .72f), fontStyle = if (past) FontStyle.Italic else FontStyle.Normal)
                if (timing.isNotBlank()) Text(timing, style = MaterialTheme.typography.labelSmall, color = if (kind == "played" && !future) Color(0xFF9FE0B2).copy(alpha = if (past) .62f else 1f) else MaterialTheme.colorScheme.onSurfaceVariant, fontStyle = if (past) FontStyle.Italic else FontStyle.Normal)
                if (row.event_type == "song" && row.song_id != null) Text("Dwuklik: karta utworu", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary.copy(alpha = if (past) .62f else 1f))
                if (current && (row.runtime_seconds ?: 0.0) > 0.0) {
                    val ratio = ((row.played_seconds ?: 0.0) / (row.runtime_seconds ?: 1.0)).toFloat().coerceIn(0f, 1f)
                    Box(Modifier.fillMaxWidth().padding(top = 6.dp).height(4.dp).background(Color(0xFF26342B))) {
                        Box(Modifier.fillMaxWidth(ratio).fillMaxHeight().background(Color(0xFF45C878)))
                    }
                }
            }
        }
    }
}

@Composable private fun LocalRadioEtm(store: SettingsStore) {
    var dates by remember { mutableStateOf<List<String>>(emptyList()) }
    var day by remember { mutableStateOf("") }
    var ignoreResets by remember { mutableStateOf(true) }
    var mode by remember { mutableStateOf("Hard + Soft") }
    var rows by remember { mutableStateOf<List<LocalRadioEvent>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf("") }
    var dateOpen by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        try {
            dates = ApiProvider.api(store).localRadioDates("schedule")
            day = localRadioDefaultDate("schedule", dates)
        } catch (e: Exception) { error = e.message ?: e.javaClass.simpleName; loading = false }
    }
    LaunchedEffect(day, ignoreResets) {
        if (day.isBlank()) return@LaunchedEffect
        loading = true; error = ""
        try {
            rows = ApiProvider.api(store).localRadioEvents("schedule", day, null, continuity = false, ignoreResets = ignoreResets)
                .filter { row -> row.event_type == "etm" && (row.category_code.equals("HARD", true) || row.category_code.equals("SOFT", true) || row.title.contains("Hard", true) || row.title.contains("Soft", true)) }
        } catch (e: Exception) { error = e.message ?: e.javaClass.simpleName }
        finally { loading = false }
    }
    val visible = rows.filter { row ->
        mode == "Hard + Soft" || row.category_code.equals(mode, true) || row.title.contains(mode, true)
    }

    Column(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 8.dp)) {
            OutlinedButton(onClick = { dateOpen = true }, modifier = Modifier.fillMaxWidth()) { Text(day.ifBlank { "Dzień" }) }
            DropdownMenu(expanded = dateOpen, onDismissRequest = { dateOpen = false }) {
                dates.reversed().take(45).forEach { d ->
                    DropdownMenuItem(text = { Text(d) }, onClick = { dateOpen = false; day = d })
                }
            }
        }
        Row(Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = mode == "Hard + Soft", onClick = { mode = "Hard + Soft" }, label = { Text("Hard + Soft") })
            FilterChip(selected = mode == "Hard", onClick = { mode = "Hard" }, label = { Text("Hard") })
            FilterChip(selected = mode == "Soft", onClick = { mode = "Soft" }, label = { Text("Soft") })
            Spacer(Modifier.weight(1f))
            Text("Ignoruj resety", style = MaterialTheme.typography.labelSmall)
            Switch(checked = ignoreResets, onCheckedChange = { ignoreResets = it })
        }
        if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (error.isNotBlank()) Text("Błąd: $error", color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(12.dp))
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(visible, key = { "etm_${it.id}" }) { row ->
                Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color(0xFF111821))) {
                    Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(row.air_time_raw.take(5), color = Color(0xFFC6CFDB), fontWeight = FontWeight.Bold, modifier = Modifier.width(64.dp))
                        Text(row.category_code.ifBlank { row.title.substringAfterLast("_").uppercase() }, color = Color(0xFF69D6FF), fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                        Text(row.etm_delta_raw.ifBlank { "—" }, color = Color.White, fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
    }
}

@Composable private fun LocalRadioCompare(store: SettingsStore, onSong: (Int) -> Unit) {
    var dates by remember { mutableStateOf<List<String>>(emptyList()) }
    var day by remember { mutableStateOf("") }
    var hour by remember { mutableStateOf(LocalTime.now().hour) }
    var result by remember { mutableStateOf<LocalRadioCompareResponse?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        try {
            val a = ApiProvider.api(store).localRadioDates("schedule")
            val b = ApiProvider.api(store).localRadioDates("played")
            dates = (a + b).distinct().sorted()
            day = localRadioDefaultDate("played", dates)
        } catch (e: Exception) { error = e.message ?: e.javaClass.simpleName; loading = false }
    }
    LaunchedEffect(day, hour) {
        if (day.isBlank()) return@LaunchedEffect
        loading = true; error = ""
        try { result = ApiProvider.api(store).localRadioCompare(day, hour) }
        catch (e: Exception) { error = e.message ?: e.javaClass.simpleName }
        finally { loading = false }
    }

    val groups = remember(result?.rows) {
        buildList<List<LocalRadioCompareRow>> {
            var traffic = mutableListOf<LocalRadioCompareRow>()
            fun flush() { if (traffic.isNotEmpty()) { add(traffic.toList()); traffic = mutableListOf() } }
            (result?.rows ?: emptyList()).forEach { row ->
                if (row.event_type == "traffic") traffic.add(row) else { flush(); add(listOf(row)) }
            }
            flush()
        }
    }

    Column(Modifier.fillMaxSize()) {
        LocalRadioDateHourControls(dates, day, hour, { day = it }, { hour = it })
        LocalHourJumpBar(hour) { hour = it }
        val r = result
        if (r != null) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 4.dp), horizontalArrangement = Arrangement.SpaceEvenly) {
                MetricTiny("Cutoff", r.scheduled.toString())
                MetricTiny("Zagrane", r.played_actual.toString())
                MetricTiny("Oczekuje", r.waiting.toString())
                MetricTiny("Różnice", r.differences.toString())
            }
        }
        if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (error.isNotBlank()) Text("Błąd: $error", color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(12.dp))
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            itemsIndexed(groups, key = { index, group -> "cmp_${group.firstOrNull()?.scheduled_time}_${group.firstOrNull()?.played_time}_$index" }) { _, group ->
                if (group.size > 1 && group.all { it.event_type == "traffic" }) {
                    LocalRadioCompareTrafficBlock(group, onSong)
                } else {
                    LocalRadioCompareCard(group.first(), onSong)
                }
            }
        }
    }
}

@Composable private fun LocalRadioCompareTrafficBlock(rows: List<LocalRadioCompareRow>, onSong: (Int) -> Unit) {
    var open by remember(rows.firstOrNull()?.scheduled_time, rows.firstOrNull()?.played_time) { mutableStateOf(false) }
    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color(0xFF1B0F12))) {
        Column {
            Row(Modifier.fillMaxWidth().clickable { open = !open }.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(if (open) "−" else "+", color = Color(0xFFFF5D5D), fontWeight = FontWeight.Bold, modifier = Modifier.width(24.dp))
                Text("REKLAMA/AUTOPROMOCJA", color = Color(0xFFFF5D5D), fontWeight = FontWeight.Bold)
                Spacer(Modifier.weight(1f))
                Text("${rows.size} poz.", color = Color(0xFFFF8C8C), style = MaterialTheme.typography.labelSmall)
            }
            if (open) rows.forEach { LocalRadioCompareCard(it, onSong) }
        }
    }
}

@Composable private fun LocalRadioCompareCard(row: LocalRadioCompareRow, onSong: (Int) -> Unit) {
    val waiting = row.status == "Oczekuje"
    val eventColor = when (row.event_type) {
        "song" -> Color(0xFFF4F4F5)
        "traffic" -> Color(0xFFFF5D5D)
        "etm" -> Color(0xFF69D6FF)
        "toh" -> Color(0xFFFF79C6)
        else -> Color(0xFFF4CF57)
    }
    val statusColor = when {
        waiting -> MaterialTheme.colorScheme.onSurfaceVariant
        row.status == "OK" -> Color(0xFF45C878)
        else -> MaterialTheme.colorScheme.error
    }
    var modifier = Modifier.fillMaxWidth()
    if (row.event_type == "song" && row.song_id != null) {
        modifier = modifier.pointerInput(row.song_id) { detectTapGestures(onDoubleTap = { onSong(row.song_id) }) }
    }
    Card(modifier) {
        Column(Modifier.padding(10.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(row.status, color = statusColor, fontWeight = FontWeight.Bold)
                Text(listOf(row.scheduled_time, row.played_time).filter { it.isNotBlank() }.joinToString(" → "), style = MaterialTheme.typography.labelSmall)
            }
            Text(listOf(row.artist, row.title).filter { it.isNotBlank() }.joinToString(" — ").ifBlank { row.category }, color = eventColor, maxLines = 2, overflow = TextOverflow.Ellipsis)
            val details = listOf(row.start_delta.takeIf { it.isNotBlank() }?.let { "Δ $it" }, row.runtime_cut.takeIf { it.isNotBlank() }?.let { "runtime $it" }, row.note.takeIf { it.isNotBlank() }).filterNotNull().joinToString(" · ")
            if (details.isNotBlank()) Text(details, style = MaterialTheme.typography.labelSmall)
            if (row.event_type == "song" && row.song_id != null) Text("Dwuklik: karta utworu", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
        }
    }
}

@Composable private fun LocalRadioSongs(store: SettingsStore) {
    var kind by remember { mutableStateOf("played") }
    var rows by remember { mutableStateOf<List<LocalRadioSongStat>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf("") }
    LaunchedEffect(kind) {
        loading = true; error = ""
        try { rows = ApiProvider.api(store).localRadioSongStats(kind) }
        catch (e: Exception) { error = e.message ?: e.javaClass.simpleName }
        finally { loading = false }
    }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = kind == "played", onClick = { kind = "played" }, label = { Text("Played") })
            FilterChip(selected = kind == "schedule", onClick = { kind = "schedule" }, label = { Text("Scheduled") })
            Spacer(Modifier.weight(1f)); Text("${rows.size} utworów", style = MaterialTheme.typography.bodySmall, modifier = Modifier.align(Alignment.CenterVertically))
        }
        if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (error.isNotBlank()) Text("Błąd: $error", color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(12.dp))
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(8.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            items(rows.take(500)) { row ->
                Card(Modifier.fillMaxWidth()) {
                    Row(Modifier.fillMaxWidth().padding(10.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                        Column(Modifier.weight(1f)) {
                            Text("${row.artist} — ${row.title}", fontWeight = FontWeight.Medium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            Text("${row.category} · dni ${row.days_with_play} · średnio ${row.per_calendar_day}/dzień", style = MaterialTheme.typography.labelSmall)
                        }
                        Text(row.plays.toString(), fontWeight = FontWeight.Bold, modifier = Modifier.padding(start = 10.dp))
                    }
                }
            }
        }
    }
}

@Composable private fun LocalRadioImport(store: SettingsStore) {
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf("") }
    fun run(label: String, block: suspend () -> Map<String, Any?>) {
        if (busy) return
        scope.launch {
            busy = true; result = "$label…"
            result = try { "$label: ${block().entries.joinToString(" · ") { "${it.key}=${it.value}" }}" }
            catch (e: Exception) { "Błąd: ${e.message ?: e.javaClass.simpleName}" }
            finally { busy = false }
        }
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Zetta2GO", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text("Te przyciski uruchamiają synchronizację na serwerze RadioCharts. Login i hasło pozostają zapisane po stronie serwera.", style = MaterialTheme.typography.bodySmall)
        Button(onClick = { run("Test Zetta2GO") { ApiProvider.api(store).zettaTest() } }, enabled = !busy, modifier = Modifier.fillMaxWidth()) { Text("Test Zetta2GO") }
        OutlinedButton(onClick = { run("Played live") { ApiProvider.api(store).zettaLive() } }, enabled = !busy, modifier = Modifier.fillMaxWidth()) { Text("Odśwież Played teraz") }
        OutlinedButton(onClick = { run("Scheduled") { ApiProvider.api(store).zettaSchedule() } }, enabled = !busy, modifier = Modifier.fillMaxWidth()) { Text("Odśwież przyszłe Scheduled") }
        if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (result.isNotBlank()) Text(result, style = MaterialTheme.typography.bodySmall)
        HorizontalDivider(Modifier.padding(vertical = 6.dp))
        Text("Ręczny import plików GSelector zostaje w wersji webowej — Android obsługuje bieżący Zetta2GO i podgląd danych.", style = MaterialTheme.typography.bodySmall)
    }
}

@Composable fun SettingsScreen(updateStatus:String,onCheckUpdates:()->Unit){
    val context=LocalContext.current
    val store=remember{SettingsStore(context)}
    val scope=rememberCoroutineScope()
    var url by remember{mutableStateOf(store.serverUrl)}
    var token by remember{mutableStateOf(store.token)}
    var result by remember{mutableStateOf("")}
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(14.dp)){
        Text("Połączenie",style=MaterialTheme.typography.headlineSmall,fontWeight=FontWeight.Bold)
        Text("Włącz Tailscale na telefonie i wpisz Tailscale IP lub nazwę MagicDNS serwera z portem 8502. Niczego nie trzeba wystawiać do Internetu.",style=MaterialTheme.typography.bodySmall,modifier=Modifier.padding(vertical=8.dp))
        OutlinedTextField(url,{url=it},label={Text("API URL")},placeholder={Text("http://100.x.y.z:8502/")},modifier=Modifier.fillMaxWidth())
        OutlinedTextField(token,{token=it},label={Text("API token (opcjonalny)")},modifier=Modifier.fillMaxWidth())
        Button(onClick={store.serverUrl=url;store.token=token;ApiProvider.invalidate();scope.launch{result=try{ApiProvider.api(store).health();"Połączenie OK"}catch(e:Exception){"Błąd: ${e.message}"}}},modifier=Modifier.fillMaxWidth().padding(top=8.dp)){Text("Zapisz i sprawdź")}
        if(result.isNotBlank())Text(result,modifier=Modifier.padding(top=8.dp))
        Text("Domyślnie: http://192.168.1.10:8502/",style=MaterialTheme.typography.labelSmall,modifier=Modifier.padding(top=12.dp))
        HorizontalDivider(Modifier.padding(vertical=16.dp))
        Text("Aktualizacje",style=MaterialTheme.typography.titleMedium,fontWeight=FontWeight.Bold)
        Text("Zainstalowana wersja: ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",style=MaterialTheme.typography.bodySmall,modifier=Modifier.padding(vertical=6.dp))
        OutlinedButton(onClick=onCheckUpdates,modifier=Modifier.fillMaxWidth()){Text("Sprawdź aktualizacje")}
        if(updateStatus.isNotBlank())Text(updateStatus,style=MaterialTheme.typography.bodySmall,modifier=Modifier.padding(top=8.dp))
    }
}
