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
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.time.LocalDate

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
    val error: String? = null,
    val meta: MetaResponse = MetaResponse(),
    val rows: List<SongRow> = emptyList(),
    val total: Int = 0,
    val search: String = "",
    val downloaded: String = "any",
    val sort: String = "popularity",
    val statuses: Set<String> = emptySet(),
)

class ListVm(app: android.app.Application) : androidx.lifecycle.AndroidViewModel(app) {
    private val store = SettingsStore(app)
    private val _state = MutableStateFlow(ListUiState())
    val state: StateFlow<ListUiState> = _state
    suspend fun load(mode: String, start: String? = null, end: String? = null) {
        _state.value = _state.value.copy(loading = true, error = null)
        try {
            val api = ApiProvider.api(store)
            val meta = if (_state.value.meta.statuses.isEmpty()) api.meta() else _state.value.meta
            val response = api.songs(mode, _state.value.search, _state.value.statuses.toList(), _state.value.downloaded, _state.value.sort, true, start, end)
            _state.value = _state.value.copy(loading = false, meta = meta, rows = response.items, total = response.total)
        } catch (e: Exception) {
            _state.value = _state.value.copy(loading = false, error = e.message ?: e.javaClass.simpleName)
        }
    }
    fun setSearch(v: String) { _state.value = _state.value.copy(search = v) }
    fun setDownloaded(v: String) { _state.value = _state.value.copy(downloaded = v) }
    fun setSort(v: String) { _state.value = _state.value.copy(sort = v) }
    fun toggleStatus(v: String) { val s=_state.value.statuses.toMutableSet(); if(!s.add(v))s.remove(v); _state.value=_state.value.copy(statuses=s) }
    fun clearStatuses() { _state.value = _state.value.copy(statuses = emptySet()) }
}

@Composable fun RadioChartsApp() {
    val nav = rememberNavController()
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
            composable("dashboard") { SongListScreen("dashboard", "Dashboard", nav::navigate) }
            composable("airplay") { SongListScreen("airplay", "Emisje", nav::navigate, withPeriod=true) }
            composable("library") { SongListScreen("library", "Baza", nav::navigate, withPeriod=true) }
            composable("settings") { SettingsScreen() }
            composable("song/{id}", arguments=listOf(navArgument("id"){type=NavType.IntType})) { back -> SongScreen(back.arguments?.getInt("id") ?: 0) }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun SongListScreen(mode:String, title:String, navigate:(String)->Unit, withPeriod:Boolean=false, vm:ListVm=viewModel(key="list-$mode")) {
    val state by vm.state.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    var statusOpen by remember { mutableStateOf(false) }
    var period by remember { mutableStateOf("7d") }
    fun range(): Pair<String?,String?> {
        if (!withPeriod) return null to null
        val end = LocalDate.now(); val days = when(period){"28d"->28;"90d"->90;else->7}; return end.minusDays((days-1).toLong()).toString() to end.toString()
    }
    LaunchedEffect(Unit) { val (s,e)=range(); vm.load(mode,s,e) }
    Column(Modifier.fillMaxSize().padding(horizontal=10.dp, vertical=6.dp)) {
        Row(verticalAlignment=Alignment.CenterVertically) {
            Text(title, style=MaterialTheme.typography.headlineSmall, fontWeight=FontWeight.Bold, modifier=Modifier.weight(1f))
            Text("${state.rows.size}/${state.total}", style=MaterialTheme.typography.labelMedium)
        }
        OutlinedTextField(value=state.search, onValueChange={vm.setSearch(it)}, label={Text("Szukaj wykonawcy / tytułu")}, singleLine=true, modifier=Modifier.fillMaxWidth())
        Row(Modifier.fillMaxWidth(), horizontalArrangement=Arrangement.spacedBy(6.dp)) {
            Box(Modifier.weight(1f)) { FilterButton("Statusy${if(state.statuses.isEmpty())"" else " (${state.statuses.size})"}"){statusOpen=true} }
            DownloadMenu(state.downloaded) { vm.setDownloaded(it); scope.launch { val(s,e)=range();vm.load(mode,s,e) } }
            SortMenu(state.sort) { vm.setSort(it); scope.launch { val(s,e)=range();vm.load(mode,s,e) } }
        }
        if (withPeriod) Row(horizontalArrangement=Arrangement.spacedBy(6.dp), modifier=Modifier.padding(top=4.dp)) {
            listOf("7d" to "7 dni","28d" to "28 dni","90d" to "3 mies.").forEach { (k,l) -> FilterChip(selected=period==k,onClick={period=k;scope.launch{val(s,e)=range();vm.load(mode,s,e)}},label={Text(l)}) }
        }
        Button(onClick={scope.launch{val(s,e)=range();vm.load(mode,s,e)}}, modifier=Modifier.fillMaxWidth().padding(vertical=4.dp)) { Text("Odśwież / zastosuj filtry") }
        if (state.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
        state.error?.let { Text("Błąd: $it", color=MaterialTheme.colorScheme.error, modifier=Modifier.padding(8.dp)) }
        LazyColumn(verticalArrangement=Arrangement.spacedBy(6.dp), modifier=Modifier.fillMaxSize()) {
            items(state.rows, key={it.song_id}) { row -> SongCard(row, mode) { navigate("song/${row.song_id}") } }
        }
    }
    if (statusOpen) AlertDialog(onDismissRequest={statusOpen=false}, confirmButton={TextButton(onClick={statusOpen=false;scope.launch{val(s,e)=range();vm.load(mode,s,e)}}){Text("Zastosuj")}}, dismissButton={TextButton(onClick={vm.clearStatuses()}){Text("Wyczyść")}}, title={Text("Statusy")}, text={Column(Modifier.heightIn(max=440.dp).verticalScroll(rememberScrollState())){state.meta.statuses.forEach{st->Row(verticalAlignment=Alignment.CenterVertically){Checkbox(checked=state.statuses.contains(st),onCheckedChange={vm.toggleStatus(st)});Text(st)}}}})
}

@Composable fun FilterButton(text:String,onClick:()->Unit){OutlinedButton(onClick=onClick,modifier=Modifier.fillMaxWidth()){Text(text,maxLines=1,overflow=TextOverflow.Ellipsis)}}
@Composable fun DownloadMenu(value:String,onValue:(String)->Unit){var open by remember{mutableStateOf(false)};Box{OutlinedButton(onClick={open=true}){Text("DL: ${value.uppercase()}")};DropdownMenu(expanded=open,onDismissRequest={open=false}){listOf("any","yes","no").forEach{DropdownMenuItem(text={Text(it.uppercase())},onClick={open=false;onValue(it)})}}}}
@Composable fun SortMenu(value:String,onValue:(String)->Unit){var open by remember{mutableStateOf(false)};Box{OutlinedButton(onClick={open=true}){Text("Sort")};DropdownMenu(expanded=open,onDismissRequest={open=false}){listOf("popularity" to "Popularity","chart_score" to "Chart Score","momentum" to "Momentum","reach7" to "Zasięg 7d","spins7" to "Emisje 7d","spins" to "Emisje okres").forEach{(k,l)->DropdownMenuItem(text={Text(l)},onClick={open=false;onValue(k)})}}}}

@Composable fun SongCard(s:SongRow, mode:String, onClick:()->Unit) {
    Card(onClick=onClick, colors=CardDefaults.cardColors(containerColor=CardBg), modifier=Modifier.fillMaxWidth()) {
        Column(Modifier.padding(10.dp)) {
            Row { Column(Modifier.weight(1f)){Text(s.artist,style=MaterialTheme.typography.labelMedium,color=Color(0xFFB5BDC9));Text(s.title,fontWeight=FontWeight.SemiBold,maxLines=2,overflow=TextOverflow.Ellipsis)};Text(s.status,style=MaterialTheme.typography.labelSmall,color=Accent) }
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
        }
    }
}
@Composable fun MetricTiny(label:String,value:String){Column{Text(label,style=MaterialTheme.typography.labelSmall,color=Color(0xFF98A2B3));Text(value,style=MaterialTheme.typography.bodyMedium,fontWeight=FontWeight.Bold)}}
@Composable fun ChartBadge(label:String,pos:Int?,weeks:Int?){Text(if(pos==null)"$label —" else "$label #$pos (${weeks?:0}w)",style=MaterialTheme.typography.labelSmall,color=Color(0xFFB5BDC9))}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun SongScreen(id:Int) {
    val context=LocalContext.current; val store=remember{SettingsStore(context)}; val scope=rememberCoroutineScope()
    var song by remember{id.let{mutableStateOf<SongRow?>(null)}};var charts by remember{mutableStateOf<List<ChartPoint>>(emptyList())};var air by remember{mutableStateOf<AirplayDetail?>(null)};var stations by remember{mutableStateOf<List<Station>>(emptyList())};var selectedStations by remember{mutableStateOf<Set<Int>>(emptySet())};var meta by remember{mutableStateOf(MetaResponse())};var error by remember{mutableStateOf<String?>(null)};var stationOpen by remember{mutableStateOf(false)};var period by remember{mutableStateOf("28d")};var saving by remember{mutableStateOf(false)}
    suspend fun reloadAir(){try{val api=ApiProvider.api(store);val end=LocalDate.now();val days=when(period){"7d"->7;"90d"->90;else->28};val ids=selectedStations.takeIf{it.isNotEmpty()}?.joinToString(",");air=api.airplay(id,end.minusDays((days-1).toLong()).toString(),end.toString(),ids)}catch(e:Exception){error=e.message}}
    LaunchedEffect(id){try{val api=ApiProvider.api(store);song=api.song(id);charts=api.charts(id);stations=api.stations();meta=api.meta();reloadAir()}catch(e:Exception){error=e.message}}
    val s=song
    if(s==null){Box(Modifier.fillMaxSize(),contentAlignment=Alignment.Center){if(error!=null)Text("Błąd: $error") else CircularProgressIndicator()};return}
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp)) {
        Text(s.artist,style=MaterialTheme.typography.titleMedium,color=Color(0xFFB5BDC9));Text(s.title,style=MaterialTheme.typography.headlineSmall,fontWeight=FontWeight.Bold)
        Row(Modifier.fillMaxWidth().padding(vertical=8.dp),horizontalArrangement=Arrangement.SpaceBetween){MetricTiny("Popularity",s.popularity?.let{"%.0f%%".format(it)}?:"—");MetricTiny("Chart Score",s.familiarity?.let{"%.0f%%".format(it)}?:"—");MetricTiny("Momentum",s.momentum?.let{"%.0f%%".format(it)}?:"—");MetricTiny("Zasięg 7d",s.radio_reach?.let{"%.0f%%".format(it)}?:"—");MetricTiny("Emisje 7d",(s.airplay_spins_7d?:0).toString())}
        Row(horizontalArrangement=Arrangement.spacedBy(8.dp)){PreviewButton(s);SpotifyButton(s)}
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
@Composable fun PreviewButton(s:SongRow){val scope=rememberCoroutineScope();var player by remember{mutableStateOf<MediaPlayer?>(null)};var loading by remember{mutableStateOf(false)};DisposableEffect(Unit){onDispose{player?.release()}};OutlinedButton(onClick={scope.launch{if(player?.isPlaying==true){player?.pause();return@launch};loading=true;try{val r=ApiProvider.itunes.search("${s.artist} ${s.title}");val p=r.results.firstOrNull{!it.previewUrl.isNullOrBlank()}?.previewUrl;if(p!=null){player?.release();player=MediaPlayer().apply{setAudioAttributes(AudioAttributes.Builder().setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build());setDataSource(p);prepare();start()}}}catch(_:Exception){}finally{loading=false}}}){Text(if(loading)"Szukam…" else "▶ 30s")}}

@Composable fun SettingsScreen(){val context=LocalContext.current;val store=remember{SettingsStore(context)};val scope=rememberCoroutineScope();var url by remember{mutableStateOf(store.serverUrl)};var token by remember{mutableStateOf(store.token)};var result by remember{mutableStateOf("")};Column(Modifier.fillMaxSize().padding(14.dp)){Text("Połączenie",style=MaterialTheme.typography.headlineSmall,fontWeight=FontWeight.Bold);Text("Włącz Tailscale na telefonie i wpisz Tailscale IP lub nazwę MagicDNS serwera z portem 8502. Niczego nie trzeba wystawiać do Internetu.",style=MaterialTheme.typography.bodySmall,modifier=Modifier.padding(vertical=8.dp));OutlinedTextField(url,{url=it},label={Text("API URL")},placeholder={Text("http://100.x.y.z:8502/")},modifier=Modifier.fillMaxWidth());OutlinedTextField(token,{token=it},label={Text("API token (opcjonalny)")},modifier=Modifier.fillMaxWidth());Button(onClick={store.serverUrl=url;store.token=token;ApiProvider.invalidate();scope.launch{result=try{ApiProvider.api(store).health();"Połączenie OK"}catch(e:Exception){"Błąd: ${e.message}"}}},modifier=Modifier.fillMaxWidth().padding(top=8.dp)){Text("Zapisz i sprawdź")};if(result.isNotBlank())Text(result,modifier=Modifier.padding(top=8.dp));Text("Domyślnie: http://192.168.1.10:8502/",style=MaterialTheme.typography.labelSmall,modifier=Modifier.padding(top=12.dp))}}
