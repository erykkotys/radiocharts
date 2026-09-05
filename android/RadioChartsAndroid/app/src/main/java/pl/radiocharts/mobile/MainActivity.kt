package pl.radiocharts.mobile

import android.content.Intent
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewModelScope
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDate
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
                    NotePatch(row.heard, newStatus, row.downloaded, row.note),
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

    Scaffold(
        bottomBar = {
            NavigationBar {
                listOf("dashboard" to "Dashboard", "airplay" to "Emisje", "library" to "Baza", "settings" to "Ustawienia").forEach { (route,label) ->
                    NavigationBarItem(selected=false, onClick={nav.navigate(route){launchSingleTop=true}}, icon={Text(when(route){"dashboard"->"▦";"airplay"->"◉";"library"->"★";else->"⚙"})}, label={Text(label)})
                }
            }
        }
    ) { pad ->
        NavHost(navController = nav, startDestination = "dashboard", modifier = Modifier.padding(pad)) {
            composable("dashboard") { SongListScreen("dashboard", "Dashboard", nav::navigate, previewVm = previewVm) }
            composable("airplay") { SongListScreen("airplay", "Emisje", nav::navigate, withPeriod=true, previewVm = previewVm) }
            composable("library") { SongListScreen("library", "Baza", nav::navigate, withPeriod=true, previewVm = previewVm) }
            composable("settings") { SettingsScreen(updateStatus = updateStatus, onCheckUpdates = { checkUpdates(true) }) }
            composable("song/{id}", arguments=listOf(navArgument("id"){type=NavType.IntType})) { back -> SongScreen(back.arguments?.getInt("id") ?: 0, previewVm) }
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

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun SongListScreen(mode:String, title:String, navigate:(String)->Unit, withPeriod:Boolean=false, vm:ListVm=viewModel(key="list-$mode"), previewVm:PreviewPlayerVm) {
    val state by vm.state.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    var statusOpen by remember { mutableStateOf(false) }
    var stationOpen by remember { mutableStateOf(false) }
    var period by remember { mutableStateOf("7d") }
    var customStart by remember { mutableStateOf<LocalDate?>(null) }
    var customEnd by remember { mutableStateOf<LocalDate?>(null) }

    fun presetRange(): Pair<LocalDate, LocalDate> {
        val end = LocalDate.now()
        val days = when(period){"28d"->28;"90d"->90;else->7}
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
            singleLine=true, modifier=Modifier.fillMaxWidth()
        )
        Row(Modifier.fillMaxWidth(), horizontalArrangement=Arrangement.spacedBy(6.dp)) {
            Box(Modifier.weight(1f)) { FilterButton("Statusy${if(state.statuses.isEmpty())"" else " (${state.statuses.size})"}"){statusOpen=true} }
            DownloadMenu(state.downloaded) { vm.setDownloaded(it); reload() }
            SortMenu(state.sort, withPeriod) { key, defaultDescending -> vm.setSort(key, defaultDescending); reload() }
            OutlinedButton(onClick={vm.toggleDirection();reload()}, contentPadding=PaddingValues(horizontal=13.dp)) {
                Text(if(state.descending) "↓" else "↑")
            }
        }
        if (withPeriod) {
            Row(horizontalArrangement=Arrangement.spacedBy(6.dp), modifier=Modifier.padding(top=4.dp)) {
                listOf("7d" to "7 dni","28d" to "28 dni","90d" to "3 mies.").forEach { (k,l) ->
                    FilterChip(selected=period==k,onClick={period=k;reload()},label={Text(l)})
                }
            }
            val (shownStart, shownEnd) = effectiveRange()
            Row(Modifier.fillMaxWidth(), horizontalArrangement=Arrangement.spacedBy(6.dp)) {
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
            if (period == "custom") {
                Text("Własny zakres", style=MaterialTheme.typography.labelSmall, color=Accent)
            }
        }
        if (mode == "airplay") {
            OutlinedButton(
                onClick={stationOpen=true},
                modifier=Modifier.fillMaxWidth().padding(top=4.dp),
            ) {
                val count = state.selectedStationIds.size
                Text(if(count == 0) "Stacje: wszystkie" else "Stacje: $count wybranych")
            }
            state.reportingStations?.let { reporting ->
                Text("Raportujące w tym zakresie: $reporting", style=MaterialTheme.typography.labelSmall, color=Color(0xFF98A2B3))
            }
        }
        Button(onClick={reload()}, modifier=Modifier.fillMaxWidth().padding(vertical=4.dp)) { Text("Odśwież / zastosuj filtry") }
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
        text={Column(Modifier.heightIn(max=440.dp).verticalScroll(rememberScrollState())){
            state.meta.statuses.forEach{st->Row(verticalAlignment=Alignment.CenterVertically){
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
        modifier=modifier,
        contentPadding=PaddingValues(horizontal=8.dp),
    ) { Text("$label: $value", maxLines=1, style=MaterialTheme.typography.labelMedium) }
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

@Composable fun FilterButton(text:String,onClick:()->Unit){OutlinedButton(onClick=onClick,modifier=Modifier.fillMaxWidth()){Text(text,maxLines=1,overflow=TextOverflow.Ellipsis)}}
@Composable fun DownloadMenu(value:String,onValue:(String)->Unit){
    var open by remember{mutableStateOf(false)}
    Box{
        OutlinedButton(onClick={open=true}){Text("DL: ${value.uppercase()}")}
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
        OutlinedButton(onClick={open=true},contentPadding=PaddingValues(horizontal=12.dp)){Text("Sort")}
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
        DropdownMenu(expanded=open,onDismissRequest={open=false}) {
            statuses.forEach { status ->
                DropdownMenuItem(text={Text(status)},onClick={open=false;onValue(status)})
            }
        }
    }
}

@Composable fun MetricTiny(label:String,value:String){Column{Text(label,style=MaterialTheme.typography.labelSmall,color=Color(0xFF98A2B3));Text(value,style=MaterialTheme.typography.bodyMedium,fontWeight=FontWeight.Bold)}}
@Composable fun ChartBadge(label:String,pos:Int?,weeks:Int?){Text(if(pos==null)"$label —" else "$label #$pos (${weeks?:0}w)",style=MaterialTheme.typography.labelSmall,color=Color(0xFFB5BDC9))}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun SongScreen(id:Int, previewVm:PreviewPlayerVm) {
    val context=LocalContext.current; val store=remember{SettingsStore(context)}; val scope=rememberCoroutineScope()
    var song by remember{id.let{mutableStateOf<SongRow?>(null)}};var charts by remember{mutableStateOf<List<ChartPoint>>(emptyList())};var air by remember{mutableStateOf<AirplayDetail?>(null)};var stations by remember{mutableStateOf<List<Station>>(emptyList())};var selectedStations by remember{mutableStateOf<Set<Int>>(emptySet())};var meta by remember{mutableStateOf(MetaResponse())};var error by remember{mutableStateOf<String?>(null)};var stationOpen by remember{mutableStateOf(false)};var period by remember{mutableStateOf("28d")};var saving by remember{mutableStateOf(false)}
    suspend fun reloadAir(){try{val api=ApiProvider.api(store);val end=LocalDate.now();val days=when(period){"7d"->7;"90d"->90;else->28};val ids=selectedStations.takeIf{it.isNotEmpty()}?.joinToString(",");air=api.airplay(id,end.minusDays((days-1).toLong()).toString(),end.toString(),ids)}catch(e:Exception){error=e.message}}
    LaunchedEffect(id){try{val api=ApiProvider.api(store);song=api.song(id);charts=api.charts(id);stations=api.stations();meta=api.meta();reloadAir()}catch(e:Exception){error=e.message}}
    val s=song
    if(s==null){Box(Modifier.fillMaxSize(),contentAlignment=Alignment.Center){if(error!=null)Text("Błąd: $error") else CircularProgressIndicator()};return}
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp)) {
        Text(s.artist,style=MaterialTheme.typography.titleMedium,color=Color(0xFFB5BDC9));Text(s.title,style=MaterialTheme.typography.headlineSmall,fontWeight=FontWeight.Bold)
        Row(Modifier.fillMaxWidth().padding(vertical=8.dp),horizontalArrangement=Arrangement.SpaceBetween){MetricTiny("Popularity",s.popularity?.let{"%.0f%%".format(it)}?:"—");MetricTiny("Chart Score",s.familiarity?.let{"%.0f%%".format(it)}?:"—");MetricTiny("Momentum",s.momentum?.let{"%.0f%%".format(it)}?:"—");MetricTiny("Zasięg 7d",s.radio_reach?.let{"%.0f%%".format(it)}?:"—");MetricTiny("Emisje 7d",(s.airplay_spins_7d?:0).toString())}
        Row(horizontalArrangement=Arrangement.spacedBy(8.dp)){PreviewButton(s, previewVm);SpotifyButton(s)}
        HorizontalDivider(Modifier.padding(vertical=8.dp))
        var heard by remember(s.song_id,s.heard){mutableStateOf(s.heard)};var dl by remember(s.song_id,s.downloaded){mutableStateOf(s.downloaded)};var status by remember(s.song_id,s.status){mutableStateOf(s.status)};var note by remember(s.song_id,s.note){mutableStateOf(s.note)}
        Row(verticalAlignment=Alignment.CenterVertically){Checkbox(heard,{heard=it});Text("Przesłuchany");Checkbox(dl,{dl=it});Text("DL")}
        StatusMenu(status,meta.statuses){status=it}
        OutlinedTextField(value=note,onValueChange={note=it},label={Text("Notatka")},modifier=Modifier.fillMaxWidth())
        Button(enabled=!saving,onClick={scope.launch{saving=true;try{song=ApiProvider.api(store).patchSong(id,NotePatch(heard,status,dl,note)).song}catch(e:Exception){error=e.message}finally{saving=false}}},modifier=Modifier.fillMaxWidth()){Text(if(saving)"Zapisuję…" else "Zapisz")}
        HorizontalDivider(Modifier.padding(vertical=8.dp))
        Text("Pozycje na listach",style=MaterialTheme.typography.titleMedium)
        val grouped=charts.groupBy{it.source};if(grouped.isEmpty())Text("Brak historii") else grouped.forEach{(src,pts)->val last=pts.lastOrNull();val peak=pts.minOfOrNull{it.position};Text("$src: ${last?.position?.let{"#$it"}?:"—"} · peak ${peak?.let{"#$it"}?:"—"} · ${pts.size} notowań",modifier=Modifier.padding(vertical=2.dp))}
        HorizontalDivider(Modifier.padding(vertical=8.dp))
        Row(verticalAlignment=Alignment.CenterVertically){Text("Emisje radiowe",style=MaterialTheme.typography.titleMedium,modifier=Modifier.weight(1f));OutlinedButton(onClick={stationOpen=true}){Text(if(selectedStations.isEmpty())"Wszystkie stacje" else "Stacje: ${selectedStations.size}")}}
        Row(horizontalArrangement=Arrangement.spacedBy(6.dp)){listOf("7d" to "7 dni","28d" to "28 dni","90d" to "3 mies.").forEach{(k,l)->FilterChip(selected=period==k,onClick={period=k;scope.launch{reloadAir()}},label={Text(l)})}}
        air?.let{a->Row(Modifier.fillMaxWidth().padding(vertical=6.dp),horizontalArrangement=Arrangement.SpaceBetween){MetricTiny("Emisje",a.total_spins.toString());MetricTiny("Zasięg","%.0f%%".format(a.period_reach));MetricTiny("Stacje","${a.stations_count}/${a.reporting_stations}");MetricTiny("/dzień","%.1f".format(a.airplay_per_day))};Text("Per stacja",style=MaterialTheme.typography.titleSmall);a.stations.forEach{Text("${it.station}: ${it.spins} · ${it.active_days} dni",modifier=Modifier.padding(vertical=2.dp))}}
        error?.let{Text("Błąd: $it",color=MaterialTheme.colorScheme.error)}
        Spacer(Modifier.height(80.dp))
    }
    if(stationOpen)AlertDialog(onDismissRequest={stationOpen=false},confirmButton={TextButton(onClick={stationOpen=false;scope.launch{reloadAir()}}){Text("Zastosuj")}},dismissButton={TextButton(onClick={selectedStations=emptySet()}){Text("Wszystkie")}},title={Text("Stacje")},text={Column(Modifier.heightIn(max=460.dp).verticalScroll(rememberScrollState())){stations.forEach{st->Row(verticalAlignment=Alignment.CenterVertically){Checkbox(checked=selectedStations.contains(st.station_id),onCheckedChange={val set=selectedStations.toMutableSet();if(it)set.add(st.station_id)else set.remove(st.station_id);selectedStations=set});Text(st.name)}}}})
}

@Composable fun StatusMenu(value:String, statuses:List<String>,onValue:(String)->Unit){var open by remember{mutableStateOf(false)};Box{OutlinedButton(onClick={open=true},modifier=Modifier.fillMaxWidth()){Text("Status: $value")};DropdownMenu(expanded=open,onDismissRequest={open=false}){statuses.forEach{DropdownMenuItem(text={Text(it)},onClick={open=false;onValue(it)})}}}}
@Composable fun SpotifyButton(s:SongRow){val context=LocalContext.current;OutlinedButton(onClick={val q=Uri.encode("${s.artist} ${s.title}");context.startActivity(Intent(Intent.ACTION_VIEW,Uri.parse("https://open.spotify.com/search/$q")))}){Text("Spotify ↗")}}
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
