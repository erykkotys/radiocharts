const state = {
  unlocked: false,
  viewOnly: false,
  selectedDate: new Date(),
  report: null,
  shows: [],
  premiereSlots: [],
  repeats: [],
  additionalFilePatterns: [],
  productionWatchFolders: [],
  productionBrowseIndex: null,
  ftpSourcePatterns: [],
  browserPath: "",
  browserRoot: "media",
  browserFavoritesMode: false,
  browserFavoriteBase: null,
  browserMode: "file",
  newFolderParent: null,
  browserSort: (() => { try { return localStorage.getItem("browserSort") || "name"; } catch (_) { return "name"; } })(),
  listenBrowserRoot: "media",
  listenBrowserPath: "",
  listenFavoritesMode: false,
  listenFavoriteBase: null,
  listenBrowserSort: (() => { try { return localStorage.getItem("listenBrowserSort") || "name"; } catch (_) { return "name"; } })(),
  fileFavorites: [],
  renameFileContext: null,
  previewTimer: null,
  importWarningTimer: null,
  importWarningKey: null,
  notificationSettings: { recipients: [], rules: [] },
  fileMaintenanceSettings: {},
  windowsPathSettings: { mappings: {} },
  deliverySettings: {},
  zettaSettings: {},
  googleFlowId: null,
  googleCalendars: [],
  calendarDate: new Date(),
  calendarRange: (() => { try { return Number(localStorage.getItem("calendarRange")) || (window.innerWidth <= 760 ? 3 : 7); } catch (_) { return window.innerWidth <= 760 ? 3 : 7; } })(),
  calendar: { events: [], connected: false, calendar_access: false, configured: false, writable: false, calendar_name: "" },
  calendarLoaded: false,
  calendarAutoScrolled: false,
  calendarLoading: false,
  calendarLoadId: 0,
  playedDate: new Date(),
  played: { items: [], configured: false, last_sync: null, sync_error: "" },
  playedFilter: "all",
  playedTimer: null,
  playedProgressTimer: null,
  playedLoadId: 0,
  spyDate: new Date(),
  spyFiles: [],
  ftpTasks: null,
  timetable: { entries: [], items: [], shows: [] },
  timetableUnlocked: false,
  timetableDay: new Date().getDay() === 0 ? 6 : new Date().getDay() - 1,
  timetableRange: (() => { try { return Number(localStorage.getItem("timetableRange")) || (window.innerWidth <= 760 ? 1 : 7); } catch (_) { return window.innerWidth <= 760 ? 1 : 7; } })(),
  timetableDensity: (() => { try { return localStorage.getItem("timetableDensity") || "compact"; } catch (_) { return "compact"; } })(),
  timetableZoom: (() => { try { return Number(localStorage.getItem("timetableZoom")) || 60; } catch (_) { return 60; } })(),
  timetableViewportHeight: (() => { try { return Number(localStorage.getItem("timetableViewportHeight")) || 72; } catch (_) { return 72; } })(),
  timetableWide: (() => { try { return localStorage.getItem("timetableWide") === "true"; } catch (_) { return false; } })(),
  timetableFullscreenFallback: false,
  timetableLayers: (() => {
    const defaults = ["shows", "ads", "presenter", "weather", "news", "branding", "transmission", "other"];
    try {
      const saved = JSON.parse(localStorage.getItem("timetableLayers") || "null");
      return new Set(Array.isArray(saved) ? saved : defaults);
    } catch (_) { return new Set(defaults); }
  })(),
  timetableDraggedId: null,
  timetableDragCopy: false,
  timetableBulkEntryId: null,
  timetableBulkMinutes: new Set(),
  timetableBulkDays: new Set(),
  audioContext: null,
  reportSort: (() => { try { return localStorage.getItem("reportSort") || "name"; } catch (_) { return "name"; } })(),
  substituteItem: null,
  substituteSources: [],
};

const TIMETABLE_WEEKDAYS = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"];
const FILE_ROOTS = [
  { key: "media", label: "AUDYCJE" },
  { key: "archive", label: "Archiwum" },
  { key: "emaus", label: "Emaus" },
  { key: "emaus_contact", label: "Emaus Kontakt" },
];
const audioMetadataQueue = [];
let activeAudioMetadataRequests = 0;
const AUDIO_METADATA_CONCURRENCY = 2;

function fileRootLabel(root) {
  if (root === "favorites") return "Ulubione";
  return FILE_ROOTS.find(item => item.key === root)?.label || root;
}

function productionFolderSource(value) {
  if (value && typeof value === "object") {
    return {
      root: value.root || "media",
      path: value.path || "",
      auto_delete: Boolean(value.auto_delete),
    };
  }
  return { root: "media", path: String(value || ""), auto_delete: false };
}

function productionFolderValue(source) {
  return source.root === "media" && !source.auto_delete
    ? source.path
    : { root: source.root, path: source.path, auto_delete: Boolean(source.auto_delete) };
}

function openProductionFolder(source) {
  const folder = productionFolderSource(source);
  state.productionViewSource = folder;
  openBrowser("production-view");
}

function scheduleBrowserDuration(row, root, path) {
  const target = row.querySelector(".browser-file-duration");
  if (!target) return;
  audioMetadataQueue.push({ target, root, path });
  pumpAudioMetadataQueue();
}

function pumpAudioMetadataQueue() {
  while (activeAudioMetadataRequests < AUDIO_METADATA_CONCURRENCY && audioMetadataQueue.length) {
    const job = audioMetadataQueue.shift();
    if (!job.target.isConnected) continue;
    activeAudioMetadataRequests += 1;
    api(`/api/files/metadata?root=${encodeURIComponent(job.root)}&path=${encodeURIComponent(job.path)}`)
      .then(result => {
        if (job.target.isConnected) job.target.textContent = result.duration || "—";
      })
      .catch(() => {
        if (job.target.isConnected) job.target.textContent = "—";
      })
      .finally(() => {
        activeAudioMetadataRequests -= 1;
        pumpAudioMetadataQueue();
      });
  }
}
const TIMETABLE_LAYERS = [
  { key: "shows", label: "Audycje" },
  { key: "ads", label: "Reklamy" },
  { key: "presenter", label: "Wejścia" },
  { key: "weather", label: "Pogoda" },
  { key: "news", label: "Serwisy" },
  { key: "branding", label: "Oprawa" },
  { key: "transmission", label: "Transmisje" },
  { key: "other", label: "Inne" },
  { key: "music", label: "Muzyka (przyszłościowo)" },
];

if (![1, 3, 7].includes(state.timetableRange)) state.timetableRange = 7;
if (![1, 3, 7].includes(state.calendarRange)) state.calendarRange = window.innerWidth <= 760 ? 3 : 7;
if (!["compact", "full"].includes(state.timetableDensity)) state.timetableDensity = "compact";
if (!Number.isFinite(state.timetableZoom) || state.timetableZoom < 36 || state.timetableZoom > 144) state.timetableZoom = 60;
if (!Number.isFinite(state.timetableViewportHeight) || state.timetableViewportHeight < 45 || state.timetableViewportHeight > 95) state.timetableViewportHeight = 72;

const queryParams = new URLSearchParams(location.search);
const urlTheme = queryParams.get("theme");
if (urlTheme === "dark") document.documentElement.classList.add("dark");
if (urlTheme === "light") document.documentElement.classList.remove("dark");

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];

function openModal(dialog) {
  lockPageScroll();
  dialog.showModal();
  dialog.scrollTop = 0;
  requestAnimationFrame(() => { dialog.scrollTop = 0; });
}

function openFileBrowserDialog() {
  const dialog = $("#fileDialog");
  lockPageScroll();
  dialog.showModal();
  document.body.classList.add("file-dialog-open");
  dialog.scrollTop = 0;
  requestAnimationFrame(() => { dialog.scrollTop = 0; });
}

function lockPageScroll() {
  if (document.body.classList.contains("modal-scroll-locked")) return;
  const scrollY = window.scrollY;
  document.body.dataset.modalScrollY = String(scrollY);
  document.body.style.top = `-${scrollY}px`;
  document.body.classList.add("modal-scroll-locked");
}

function unlockPageScrollWhenIdle() {
  requestAnimationFrame(() => {
    if (document.querySelector("dialog[open]")) return;
    const scrollY = Number(document.body.dataset.modalScrollY || 0);
    document.body.classList.remove("modal-scroll-locked");
    document.body.style.top = "";
    delete document.body.dataset.modalScrollY;
    window.scrollTo(0, scrollY);
  });
}

// Delegacja działa nawet wtedy, gdy późniejsza inicjalizacja interfejsu napotka błąd.
document.addEventListener("click", event => {
  const button = event.target.closest?.("[data-close-dialog]");
  if (!button) return;
  const dialog = document.getElementById(button.dataset.closeDialog);
  if (dialog?.open) dialog.close();
});

async function api(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const response = await fetch(url, { credentials: "same-origin", ...options, headers });
  let payload = null;
  try { payload = await response.json(); } catch (_) { /* empty response */ }
  if (!response.ok) throw new Error(payload?.detail || `Błąd HTTP ${response.status}`);
  return payload;
}

function localIso(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function dateFromIso(value) {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day, 12);
}

function formatDate(date) {
  return new Intl.DateTimeFormat("pl-PL", { day: "2-digit", month: "long", year: "numeric" }).format(date);
}

function isoWeekNumber(date) {
  const target = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const weekday = (target.getUTCDay() + 6) % 7;
  target.setUTCDate(target.getUTCDate() - weekday + 3);
  const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
  const firstWeekday = (firstThursday.getUTCDay() + 6) % 7;
  firstThursday.setUTCDate(firstThursday.getUTCDate() - firstWeekday + 3);
  return 1 + Math.round((target - firstThursday) / 604800000);
}

function capitalizeFirst(value) {
  if (!value) return "";
  return value.charAt(0).toLocaleUpperCase("pl-PL") + value.slice(1);
}

function durationLimitLabel(minutes) {
  const seconds = Math.max(0, Math.round(Number(minutes || 0) * 60));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function updateVersionBadge() {
  const serverVersion = document.querySelector('meta[name="app-version"]')?.content || "?";
  const androidVersion = queryParams.get("android");
  $("#headerVersion").textContent = androidVersion
    ? `Serwer v${serverVersion} • APK v${androidVersion}`
    : `Serwer v${serverVersion}`;
}

function toast(message, duration = 2800) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove("show"), duration);
}

function isAndroidClient() {
  return Boolean(queryParams.get("android")) || /Android/i.test(navigator.userAgent);
}

function mappedWindowsPath(root, path = "") {
  const base = String(state.windowsPathSettings?.mappings?.[root] || "").replace(/[\\/]+$/, "");
  const relative = String(path || "").replaceAll("/", "\\").replace(/^\\+/, "");
  return base && relative ? `${base}\\${relative}` : base;
}

async function copyWindowsPath(root, path) {
  const windowsPath = mappedWindowsPath(root, path);
  if (!windowsPath) {
    toast("Nie skonfigurowano ścieżki Windows dla tego źródła", 6000);
    return;
  }
  try {
    await navigator.clipboard.writeText(windowsPath);
  } catch (_) {
    const input = document.createElement("textarea");
    input.value = windowsPath;
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.append(input);
    input.select();
    document.execCommand("copy");
    input.remove();
  }
  toast("Skopiowano ścieżkę. Wklej ją do Explorera lub Win+R.", 5000);
}

function windowsPathToFileUrl(path) {
  if (!path?.startsWith("\\\\")) return "";
  return `file://${path.slice(2).split("\\").map(encodeURIComponent).join("/")}`;
}

function prepareBrowserFileDrag(element, root, entry) {
  if (!entry || isAndroidClient()) return;
  element.draggable = true;
  element.title = "Przeciągnij plik do Nuendo, Sound Forge, Explorera albo na Pulpit";
  element.addEventListener("dragstart", event => {
    const downloadUrl = new URL(
      `/api/files/download?root=${encodeURIComponent(root)}&path=${encodeURIComponent(entry.path)}`,
      window.location.href,
    ).href;
    const fileUrl = windowsPathToFileUrl(entry.windows_path || "");
    const safeName = entry.name.replaceAll(":", "_");
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setData("DownloadURL", `application/octet-stream:${safeName}:${downloadUrl}`);
    if (fileUrl) event.dataTransfer.setData("text/uri-list", fileUrl);
    event.dataTransfer.setData("text/plain", entry.windows_path || downloadUrl);
  });
}

function showError(selector, error) {
  const element = $(selector);
  element.textContent = error instanceof Error ? error.message : String(error);
  element.classList.remove("hidden");
}

function clearError(selector) { $(selector).classList.add("hidden"); }

function switchView(name) {
  $$(".view").forEach(view => view.classList.toggle("active", view.id === `${name}View`));
  $$(".nav-button").forEach(button => button.classList.toggle("active", button.dataset.view === name));
  document.body.classList.toggle("timetable-wide-mode", name === "timetable" && state.timetableWide);
  document.body.classList.toggle("calendar-wide-mode", name === "calendar");
  setPlayedPolling(name === "played");
  if (name === "shows") loadShows();
  else if (name === "timetable") loadTimetable();
  else if (name === "calendar") loadCalendar();
  else if (name === "played") loadPlayed();
  else if (name === "ftp") loadFtpTasks();
  else if (name === "spy") {
    loadSpy();
    if (state.listenFavoritesMode) showListenFavorites();
    else loadListenBrowser(state.listenBrowserPath);
  }
  else loadReport();
}

const VIEW_NAMES = new Set(["checker", "shows", "timetable", "calendar", "played", "ftp", "spy"]);

function viewFromLocation() {
  const name = location.hash.replace(/^#/, "");
  return VIEW_NAMES.has(name) ? name : "checker";
}

function formatLocalDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("pl-PL", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(date);
}

const CALENDAR_TIMEZONE = "Europe/Warsaw";
const CALENDAR_HOUR_HEIGHT = 68;
const CALENDAR_WEEKDAYS_SHORT = ["pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz."];

function addCalendarDays(date, days) {
  const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate(), 12);
  copy.setDate(copy.getDate() + days);
  return copy;
}

function calendarRangeStart() {
  const date = new Date(state.calendarDate.getFullYear(), state.calendarDate.getMonth(), state.calendarDate.getDate(), 12);
  if (state.calendarRange !== 7) return date;
  const mondayOffset = (date.getDay() + 6) % 7;
  date.setDate(date.getDate() - mondayOffset);
  return date;
}

function calendarVisibleDates() {
  const start = calendarRangeStart();
  return Array.from({ length: state.calendarRange }, (_, index) => addCalendarDays(start, index));
}

function calendarDateRangeLabel(dates) {
  if (!dates.length) return "—";
  if (dates.length === 1) return capitalizeFirst(formatDate(dates[0]));
  const first = dates[0];
  const last = dates.at(-1);
  const sameMonth = first.getMonth() === last.getMonth() && first.getFullYear() === last.getFullYear();
  if (sameMonth) {
    const monthYear = new Intl.DateTimeFormat("pl-PL", { month: "long", year: "numeric" }).format(last);
    return `${first.getDate()}–${last.getDate()} ${monthYear}`;
  }
  const short = date => new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "short", year: "numeric" }).format(date);
  return `${short(first)} – ${short(last)}`;
}

function calendarZonedParts(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const result = {};
  new Intl.DateTimeFormat("en-CA", {
    timeZone: CALENDAR_TIMEZONE,
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(date).forEach(part => {
    if (part.type !== "literal") result[part.type] = part.value;
  });
  return {
    date: `${result.year}-${result.month}-${result.day}`,
    time: `${result.hour}:${result.minute}`,
    minutes: Number(result.hour) * 60 + Number(result.minute),
  };
}

function calendarMinutesLabel(minutes) {
  const safe = Math.max(0, Math.min(1440, Math.round(minutes)));
  const hour = Math.floor(safe / 60) % 24;
  const minute = safe % 60;
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function updateCalendarControls() {
  const dates = calendarVisibleDates();
  $("#calendarDate").value = localIso(state.calendarDate);
  $("#calendarRangeLabel").textContent = calendarDateRangeLabel(dates);
  $("#calendarTimezoneLabel").textContent = `${CALENDAR_TIMEZONE} · format 24h`;
  $$("#calendarRange [data-range]").forEach(button => {
    button.classList.toggle("active", Number(button.dataset.range) === state.calendarRange);
  });
}

function updateCalendarAccessUi() {
  const calendar = state.calendar || {};
  const editable = Boolean(state.unlocked && calendar.configured && calendar.writable);
  const hint = $("#calendarEditHint");
  if (!calendar.configured) hint.textContent = "Skonfiguruj Kalendarz Google w Ustawieniach.";
  else if (!calendar.writable) hint.textContent = "Ten kalendarz jest tylko do odczytu.";
  else if (!state.unlocked) hint.textContent = "Odblokuj kłódkę, aby zmieniać grafik.";
  else hint.textContent = "Edycja aktywna — kliknij wydarzenie albo wolne miejsce.";
  hint.classList.toggle("editable", editable);
  $("#addCalendarEvent").classList.toggle("hidden", !editable);
  $("#calendarReadonlyNotice").classList.toggle("hidden", !calendar.configured || calendar.writable);
}

async function loadCalendar(preserveScroll = false) {
  const loadId = ++state.calendarLoadId;
  state.calendarLoading = true;
  updateCalendarControls();
  clearError("#calendarError");
  const shell = $("#calendarShell");
  const previousScroll = preserveScroll ? shell.scrollTop : null;
  $("#calendarRefresh").disabled = true;
  $("#calendarBoard").classList.add("loading");
  $("#calendarBoard").textContent = "Ładowanie Grafiku…";
  try {
    const dates = calendarVisibleDates();
    const start = localIso(dates[0]);
    const end = localIso(addCalendarDays(dates.at(-1), 1));
    const result = await api(`/api/calendar/events?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
    if (loadId !== state.calendarLoadId) return;
    state.calendar = result;
    state.calendarLoaded = true;
    $("#calendarName").textContent = result.calendar_name || "Kalendarz Google";
    const needsSetup = !result.connected || !result.calendar_access || !result.configured;
    $("#calendarSetupNotice").classList.toggle("hidden", !needsSetup);
    if (!result.connected) $("#calendarSetupText").textContent = "Połącz konto Google w Ustawieniach.";
    else if (!result.calendar_access) $("#calendarSetupText").textContent = "Połącz konto Google ponownie, aby nadać dostęp do Kalendarza.";
    else if (!result.configured) $("#calendarSetupText").textContent = "Wybierz kalendarz Grafiku w Ustawieniach.";
    renderCalendar();
    updateCalendarAccessUi();
    if (previousScroll !== null) shell.scrollTop = previousScroll;
    else if (!state.calendarAutoScrolled && result.configured) {
      requestAnimationFrame(() => { shell.scrollTop = 8 * CALENDAR_HOUR_HEIGHT; });
      state.calendarAutoScrolled = true;
    }
  } catch (error) {
    if (loadId !== state.calendarLoadId) return;
    state.calendar.events = [];
    state.calendarLoaded = false;
    $("#calendarBoard").classList.remove("loading");
    $("#calendarBoard").replaceChildren();
    showError("#calendarError", error);
  } finally {
    if (loadId === state.calendarLoadId) {
      state.calendarLoading = false;
      $("#calendarRefresh").disabled = false;
    }
  }
}

function calendarTimedSegments(events, dateIso) {
  const segments = [];
  events.filter(event => !event.all_day).forEach(event => {
    const start = calendarZonedParts(event.start);
    const end = calendarZonedParts(event.end);
    if (!start || !end || dateIso < start.date || dateIso > end.date) return;
    let startMinutes = dateIso === start.date ? start.minutes : 0;
    let endMinutes = dateIso === end.date ? end.minutes : 1440;
    if (end.date !== start.date && dateIso === end.date && end.minutes === 0) return;
    if (endMinutes <= startMinutes) return;
    segments.push({ event, start: startMinutes, end: endMinutes, column: 0, columns: 1 });
  });
  segments.sort((a, b) => a.start - b.start || b.end - a.end);
  let group = [];
  let groupEnd = -1;
  const finishGroup = () => {
    if (!group.length) return;
    const columnEnds = [];
    group.forEach(segment => {
      let column = columnEnds.findIndex(end => end <= segment.start);
      if (column < 0) column = columnEnds.length;
      columnEnds[column] = segment.end;
      segment.column = column;
    });
    const count = Math.max(1, columnEnds.length);
    group.forEach(segment => segment.columns = count);
    group = [];
  };
  segments.forEach(segment => {
    if (group.length && segment.start >= groupEnd) finishGroup();
    group.push(segment);
    groupEnd = Math.max(groupEnd, segment.end);
  });
  finishGroup();
  return segments;
}

function calendarEventButton(event, segment = null) {
  const button = document.createElement("button");
  button.type = "button";
  if (!segment) {
    button.className = "calendar-all-day-event";
    button.textContent = event.title;
    button.title = event.title;
  } else {
    button.className = "calendar-event";
    const duration = segment.end - segment.start;
    if (duration <= 30) button.classList.add("short");
    const width = 100 / segment.columns;
    button.style.left = `calc(${segment.column * width}% + 2px)`;
    button.style.width = `calc(${width}% - 4px)`;
    button.style.top = `${segment.start / 60 * CALENDAR_HOUR_HEIGHT + 1}px`;
    button.style.height = `${Math.max(17, duration / 60 * CALENDAR_HOUR_HEIGHT - 2)}px`;
    const time = document.createElement("span");
    time.className = "calendar-event-time";
    time.textContent = `${calendarMinutesLabel(segment.start)}–${calendarMinutesLabel(segment.end)}`;
    const title = document.createElement("strong");
    title.className = "calendar-event-title";
    title.textContent = event.title;
    button.append(time, title);
    if (event.location) {
      const location = document.createElement("small");
      location.className = "calendar-event-location";
      location.textContent = event.location;
      button.append(location);
    }
    button.title = `${time.textContent} · ${event.title}${event.location ? ` · ${event.location}` : ""}`;
  }
  button.addEventListener("click", clickEvent => {
    clickEvent.stopPropagation();
    openCalendarEventDialog(event);
  });
  return button;
}

function renderCalendar() {
  const board = $("#calendarBoard");
  board.classList.remove("loading");
  board.replaceChildren();
  const dates = calendarVisibleDates();
  const events = state.calendar.events || [];
  board.style.setProperty("--calendar-days", String(dates.length));
  const mobileMinWidth = dates.length === 7 ? 1120 : dates.length === 3 ? 690 : 0;
  board.style.setProperty("--calendar-mobile-min-width", mobileMinWidth ? `${mobileMinWidth}px` : "0px");

  if (!state.calendar.configured) {
    const empty = document.createElement("div");
    empty.className = "calendar-empty";
    empty.textContent = "Po skonfigurowaniu konta i wybraniu kalendarza pojawi się tutaj Grafik.";
    board.append(empty);
    return;
  }

  const header = document.createElement("div");
  header.className = "calendar-grid-row calendar-header";
  const corner = document.createElement("div");
  corner.className = "calendar-time-corner";
  corner.textContent = "24h";
  header.append(corner);
  const todayIso = localIso(new Date());
  dates.forEach(date => {
    const heading = document.createElement("div");
    heading.className = "calendar-day-heading";
    if (localIso(date) === todayIso) heading.classList.add("today");
    const weekday = document.createElement("span");
    weekday.textContent = CALENDAR_WEEKDAYS_SHORT[(date.getDay() + 6) % 7];
    const day = document.createElement("strong");
    day.textContent = String(date.getDate());
    heading.append(weekday, day);
    header.append(heading);
  });

  const allDay = document.createElement("div");
  allDay.className = "calendar-grid-row calendar-all-day-row";
  const allDayLabel = document.createElement("div");
  allDayLabel.className = "calendar-all-day-label";
  allDayLabel.textContent = "cały dzień";
  allDay.append(allDayLabel);
  dates.forEach(date => {
    const iso = localIso(date);
    const cell = document.createElement("div");
    cell.className = "calendar-all-day-cell";
    events.filter(event => event.all_day && iso >= event.start_date && iso <= event.end_date)
      .forEach(event => cell.append(calendarEventButton(event)));
    if (state.unlocked && state.calendar.writable) {
      cell.addEventListener("dblclick", () => openCalendarEventDialog(null, { date: iso, allDay: true }));
    }
    allDay.append(cell);
  });

  const body = document.createElement("div");
  body.className = "calendar-grid-row calendar-grid-body";
  const axis = document.createElement("div");
  axis.className = "calendar-time-axis";
  for (let hour = 0; hour < 24; hour += 1) {
    const label = document.createElement("span");
    label.className = "calendar-hour-label";
    label.style.top = `${hour * CALENDAR_HOUR_HEIGHT}px`;
    label.textContent = `${String(hour).padStart(2, "0")}:00`;
    axis.append(label);
  }
  body.append(axis);
  dates.forEach(date => {
    const iso = localIso(date);
    const column = document.createElement("div");
    column.className = "calendar-day-column";
    if (iso === todayIso) column.classList.add("today");
    if (state.unlocked && state.calendar.writable) column.classList.add("calendar-editable");
    calendarTimedSegments(events, iso).forEach(segment => column.append(calendarEventButton(segment.event, segment)));
    if (iso === todayIso) {
      const now = new Date();
      const parts = calendarZonedParts(now.toISOString());
      if (parts) {
        const line = document.createElement("div");
        line.className = "calendar-now-line";
        line.style.top = `${parts.minutes / 60 * CALENDAR_HOUR_HEIGHT}px`;
        column.append(line);
      }
    }
    column.addEventListener("click", clickEvent => {
      if (!state.unlocked || !state.calendar.writable || clickEvent.target !== column) return;
      const rect = column.getBoundingClientRect();
      const rawMinutes = (clickEvent.clientY - rect.top) / CALENDAR_HOUR_HEIGHT * 60;
      const startMinutes = Math.max(0, Math.min(1425, Math.round(rawMinutes / 15) * 15));
      const endMinutes = Math.min(1440, startMinutes + 60);
      const endDate = endMinutes === 1440 ? localIso(addCalendarDays(date, 1)) : iso;
      openCalendarEventDialog(null, {
        date: iso,
        startTime: calendarMinutesLabel(startMinutes),
        endDate,
        endTime: endMinutes === 1440 ? "00:00" : calendarMinutesLabel(endMinutes),
      });
    });
    body.append(column);
  });
  board.append(header, allDay, body);
}

function calendarTimeForInput(value) {
  const parts = calendarZonedParts(value);
  return parts?.time || "";
}

function normalizeCalendarTimeInput(input) {
  const value = input.value.trim();
  if (/^\d{3,4}$/.test(value)) input.value = `${value.slice(0, -2).padStart(2, "0")}:${value.slice(-2)}`;
}

function openCalendarEventDialog(event = null, defaults = {}) {
  const dialog = $("#calendarEventDialog");
  const editing = Boolean(event?.id);
  const readOnly = !state.unlocked || !state.calendar.writable;
  const startParts = editing && !event.all_day ? calendarZonedParts(event.start) : null;
  const endParts = editing && !event.all_day ? calendarZonedParts(event.end) : null;
  const defaultDate = defaults.date || localIso(state.calendarDate);
  $("#calendarEventDialogTitle").textContent = editing ? event.title : "Dodaj wydarzenie";
  $("#calendarEventId").value = event?.id || "";
  $("#calendarEventTitle").value = event?.title || "";
  $("#calendarEventAllDay").checked = Boolean(event?.all_day || defaults.allDay);
  $("#calendarEventStartDate").value = event?.start_date || startParts?.date || defaultDate;
  $("#calendarEventEndDate").value = event?.end_date || endParts?.date || defaults.endDate || defaultDate;
  $("#calendarEventStartTime").value = startParts?.time || defaults.startTime || "08:00";
  $("#calendarEventEndTime").value = endParts?.time || defaults.endTime || "09:00";
  $("#calendarEventLocation").value = event?.location || "";
  $("#calendarEventDescription").value = event?.description || "";
  const googleLink = $("#calendarEventGoogleLink");
  googleLink.href = event?.html_link || "#";
  googleLink.classList.toggle("hidden", !event?.html_link);
  dialog.classList.toggle("view-only", readOnly);
  dialog.querySelectorAll("input:not([type='hidden']), textarea").forEach(input => input.disabled = readOnly);
  $("#saveCalendarEvent").classList.toggle("hidden", readOnly);
  $("#deleteCalendarEvent").classList.toggle("hidden", readOnly || !editing);
  updateCalendarEventTimeFields();
  clearError("#calendarEventError");
  openModal(dialog);
  if (!readOnly && !editing) setTimeout(() => $("#calendarEventTitle").focus(), 40);
}

function updateCalendarEventTimeFields() {
  const allDay = $("#calendarEventAllDay").checked;
  $$("#calendarEventForm .calendar-time-field").forEach(field => field.classList.toggle("hidden", allDay));
  $("#calendarEventStartTime").required = !allDay;
  $("#calendarEventEndTime").required = !allDay;
}

function calendarEventPayload() {
  normalizeCalendarTimeInput($("#calendarEventStartTime"));
  normalizeCalendarTimeInput($("#calendarEventEndTime"));
  return {
    title: $("#calendarEventTitle").value,
    all_day: $("#calendarEventAllDay").checked,
    start_date: $("#calendarEventStartDate").value,
    start_time: $("#calendarEventStartTime").value,
    end_date: $("#calendarEventEndDate").value,
    end_time: $("#calendarEventEndTime").value,
    location: $("#calendarEventLocation").value,
    description: $("#calendarEventDescription").value,
  };
}

async function saveCalendarEvent(event) {
  event.preventDefault();
  clearError("#calendarEventError");
  const button = $("#saveCalendarEvent");
  const eventId = $("#calendarEventId").value;
  button.disabled = true;
  button.textContent = "Zapisuję…";
  try {
    await api(eventId ? `/api/calendar/events/${encodeURIComponent(eventId)}` : "/api/calendar/events", {
      method: eventId ? "PATCH" : "POST",
      body: JSON.stringify(calendarEventPayload()),
    });
    $("#calendarEventDialog").close();
    await loadCalendar(true);
    toast(eventId ? "Zmieniono wydarzenie" : "Dodano wydarzenie");
  } catch (error) { showError("#calendarEventError", error); }
  finally { button.disabled = false; button.textContent = "Zapisz"; }
}

async function deleteCalendarEvent() {
  const eventId = $("#calendarEventId").value;
  if (!eventId || !confirm("Usunąć to wydarzenie z Kalendarza Google?")) return;
  const button = $("#deleteCalendarEvent");
  button.disabled = true;
  button.textContent = "Usuwam…";
  clearError("#calendarEventError");
  try {
    await api(`/api/calendar/events/${encodeURIComponent(eventId)}`, { method: "DELETE" });
    $("#calendarEventDialog").close();
    await loadCalendar(true);
    toast("Usunięto wydarzenie");
  } catch (error) { showError("#calendarEventError", error); }
  finally { button.disabled = false; button.textContent = "Usuń"; }
}

function changeCalendarDate(days) {
  state.calendarDate = addCalendarDays(state.calendarDate, days);
  state.calendarAutoScrolled = false;
  loadCalendar();
}

const PLAYED_CATEGORY_LABELS = {
  music: "MUZYKA",
  jingle: "JINGLE",
  shows: "AUDYCJA",
  ads: "REKL",
  etm: "ETM",
  other: "INNE",
};

function setPlayedPolling(active) {
  clearInterval(state.playedTimer);
  clearInterval(state.playedProgressTimer);
  state.playedTimer = null;
  state.playedProgressTimer = null;
  if (!active) return;
  state.playedTimer = setInterval(() => {
    if (localIso(state.playedDate) === localIso(new Date())) loadPlayed(true);
  }, 20000);
  state.playedProgressTimer = setInterval(updatePlayedProgress, 1000);
}

function playedClock(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    const match = String(value).match(/(\d{1,2}:\d{2}(?::\d{2})?)/);
    return match?.[1] || "—";
  }
  return new Intl.DateTimeFormat("pl-PL", {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).format(date);
}

function playedRuntime(item) {
  const milliseconds = Number(item.runtime_ms || item.duration_ms || 0);
  return milliseconds > 0 ? formatDuration(Math.round(milliseconds / 1000)) : "—";
}

function playedMatchesFilter(item) {
  return state.playedFilter === "all" || item.category === state.playedFilter;
}

function playedRow(item, child = false) {
  const row = document.createElement("article");
  row.className = `played-row category-${item.category || "other"}`;
  row.dataset.rowId = item.row_id;
  row.dataset.statusCode = String(item.status_code ?? "");
  if (child) row.classList.add("played-child");
  if ([2, 9].includes(Number(item.status_code))) row.classList.add("current");
  else if ([3, 6, 7, 8].includes(Number(item.status_code))) row.classList.add("played-past");
  else if ([4, 5].includes(Number(item.status_code))) row.classList.add("not-played");

  const time = document.createElement("time");
  time.textContent = playedClock(item.air_time);
  const category = document.createElement("span");
  category.className = "played-category";
  category.textContent = PLAYED_CATEGORY_LABELS[item.category] || PLAYED_CATEGORY_LABELS.other;
  const copy = document.createElement("div");
  copy.className = "played-copy";
  const title = document.createElement("strong");
  title.textContent = item.artist ? `${item.artist} — ${item.title}` : item.title;
  const note = document.createElement("small");
  note.textContent = item.edit_reason || (item.etm_type ? `ETM ${item.etm_type}` : "");
  note.classList.toggle("hidden", !note.textContent);
  copy.append(title, note);
  const runtime = document.createElement("span");
  runtime.className = "played-runtime";
  runtime.textContent = playedRuntime(item);
  const status = document.createElement("span");
  status.className = "played-status";
  status.textContent = [2, 9].includes(Number(item.status_code)) ? `▶ ${item.status}` : item.status;
  if (item.edit_reason) status.title = `${item.edit_reason} (EditCode ${item.edit_code})`;
  row.append(time, category, copy, runtime, status);

  if ([2, 9].includes(Number(item.status_code)) && item.start_timestamp && item.runtime_ms) {
    row.dataset.startedAt = String(Number(item.start_timestamp) * 1000);
    row.dataset.runtimeMs = String(item.runtime_ms);
    const progress = document.createElement("div");
    progress.className = "played-progress";
    const fill = document.createElement("span");
    progress.append(fill);
    row.append(progress);
  }
  return row;
}

function playedAdGroup(item) {
  const wrapper = document.createElement("div");
  wrapper.className = "played-ad-group";
  const parent = playedRow(item);
  const status = parent.querySelector(".played-status");
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "played-group-toggle";
  toggle.textContent = `＋ ${item.children.length} poz.`;
  toggle.setAttribute("aria-expanded", "false");
  status.replaceChildren(toggle);
  const children = document.createElement("div");
  children.className = "played-children hidden";
  children.replaceChildren(...item.children.map(child => playedRow(child, true)));
  toggle.addEventListener("click", () => {
    const opening = children.classList.contains("hidden");
    children.classList.toggle("hidden", !opening);
    toggle.textContent = `${opening ? "−" : "＋"} ${item.children.length} poz.`;
    toggle.setAttribute("aria-expanded", String(opening));
  });
  wrapper.append(parent, children);
  return wrapper;
}

function playedHourSeparator(hour, topOfHour = null) {
  const separator = document.createElement("div");
  separator.className = `played-hour-separator${topOfHour ? " top-of-hour" : ""}`;
  separator.id = `played-hour-${String(hour).padStart(2, "0")}`;
  separator.innerHTML = `<span></span><strong>${String(hour).padStart(2, "0")}:00${topOfHour ? " · TOP OF THE HOUR" : ""}</strong><span></span>`;
  return separator;
}

function renderPlayed() {
  const items = state.played.items || [];
  const list = $("#playedList");
  list.replaceChildren();
  const filtered = items.filter(playedMatchesFilter);
  const byHour = new Map();
  filtered.forEach(item => {
    const hour = Number.isFinite(Number(item.hour)) ? Number(item.hour) : 0;
    if (!byHour.has(hour)) byHour.set(hour, []);
    byHour.get(hour).push(item);
  });
  [...byHour.keys()].sort((a, b) => a - b).forEach(hour => {
    const hourItems = byHour.get(hour);
    const top = hourItems.find(item => item.category === "toh");
    list.append(playedHourSeparator(hour, top));
    hourItems.filter(item => item.category !== "toh").forEach(item => {
      list.append(item.category === "ads" && item.children?.length ? playedAdGroup(item) : playedRow(item));
    });
  });
  $("#playedEmpty").classList.toggle("hidden", Boolean(filtered.length));
  $("#playedSetupNotice").classList.toggle("hidden", Boolean(state.played.configured));
  $("#playedLiveState").textContent = items.some(item => [2, 9].includes(Number(item.status_code)))
    ? "● Emisja na żywo"
    : "Brak elementu CURRENT";
  $("#playedLiveState").classList.toggle("live", items.some(item => [2, 9].includes(Number(item.status_code))));
  $("#playedLastSync").textContent = state.played.last_sync
    ? `Ostatnia synchronizacja: ${formatLocalDateTime(state.played.last_sync)}`
    : "Jeszcze nie zsynchronizowano";
  if (state.played.sync_error) showError("#playedError", new Error(state.played.sync_error));
  else clearError("#playedError");
  updatePlayedProgress();
}

function updatePlayedProgress() {
  $$(".played-row.current[data-started-at][data-runtime-ms]").forEach(row => {
    const elapsed = Date.now() - Number(row.dataset.startedAt);
    const runtime = Number(row.dataset.runtimeMs);
    const percentage = Math.max(0, Math.min(100, elapsed / runtime * 100));
    row.querySelector(".played-progress span")?.style.setProperty("width", `${percentage}%`);
  });
}

async function loadPlayed(preservePosition = false) {
  const loadId = ++state.playedLoadId;
  const previousY = preservePosition ? window.scrollY : null;
  $("#playedDate").value = localIso(state.playedDate);
  clearError("#playedError");
  try {
    const result = await api(`/api/played?date=${encodeURIComponent(localIso(state.playedDate))}`);
    if (loadId !== state.playedLoadId) return;
    state.played = result;
    renderPlayed();
    if (previousY !== null) requestAnimationFrame(() => window.scrollTo(0, previousY));
  } catch (error) {
    if (loadId === state.playedLoadId) showError("#playedError", error);
  }
}

async function refreshPlayed() {
  const button = $("#playedRefresh");
  button.disabled = true;
  button.textContent = "Synchronizuję…";
  clearError("#playedError");
  try {
    const result = await api("/api/played/refresh", {
      method: "POST",
      body: JSON.stringify({ date: localIso(state.playedDate), full: true }),
    });
    state.played = result;
    renderPlayed();
    toast(`Pobrano ${result.sync?.rows ?? 0} pozycji z Zetta2GO`);
  } catch (error) { showError("#playedError", error); }
  finally { button.disabled = false; button.textContent = "Odśwież Zettę"; }
}

function changePlayedDate(days) {
  state.playedDate = addCalendarDays(state.playedDate, days);
  loadPlayed();
}

function scrollPlayedTo(hour) {
  document.getElementById(`played-hour-${String(hour).padStart(2, "0")}`)
    ?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function scrollPlayedNow() {
  const current = $(".played-row.current");
  if (current) current.scrollIntoView({ behavior: "smooth", block: "center" });
  else scrollPlayedTo(new Date().getHours());
}

function renderPlayedHourButtons() {
  const container = $("#playedHourButtons");
  container.replaceChildren(...Array.from({ length: 24 }, (_, hour) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "played-hour-button";
    button.textContent = String(hour).padStart(2, "0");
    button.addEventListener("click", () => scrollPlayedTo(hour));
    return button;
  }));
}

function ftpStatusMeta(status) {
  return {
    synced: { label: "Pobrano", className: "success" },
    failed: { label: "Błąd", className: "danger" },
    pending: { label: "W toku", className: "pending" },
  }[status] || { label: "Oczekuje", className: "idle" };
}

async function loadFtpTasks() {
  const button = $("#ftpTasksRefresh");
  button.disabled = true;
  clearError("#ftpTasksError");
  try {
    const result = await api("/api/ftp/tasks");
    state.ftpTasks = result;
    renderFtpTasks();
  } catch (error) {
    showError("#ftpTasksError", error);
  } finally {
    button.disabled = false;
  }
}

function renderFtpTasks() {
  const result = state.ftpTasks || { summary: {}, items: [], history: [] };
  const summary = result.summary || {};
  const tasks = result.items || [];
  const history = result.history || [];
  $("#ftpTaskCount").textContent = String(summary.tasks ?? 0);
  $("#ftpSyncedToday").textContent = String(summary.synced_today ?? 0);
  $("#ftpFailedToday").textContent = String(summary.failed_today ?? 0);
  $("#ftpRunningCount").textContent = String(summary.running ?? 0);
  $("#ftpTasksBadge").textContent = String(tasks.length);
  $("#ftpHistoryBadge").textContent = String(history.length);
  const credentials = $("#ftpCredentialsStatus");
  credentials.textContent = result.credentials_available ? "Dane FTP: dostępne" : "Dane FTP: brak dostępu";
  credentials.classList.toggle("ok", Boolean(result.credentials_available));
  credentials.classList.toggle("error", !result.credentials_available);

  $("#ftpTasksList").replaceChildren(...tasks.map(task => {
    const card = document.createElement("article");
    card.className = "ftp-task-card";
    const header = document.createElement("div");
    header.className = "ftp-task-header";
    const title = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = task.name;
    const rule = document.createElement("small");
    rule.textContent = task.rule;
    title.append(name, rule);
    const lastMeta = ftpStatusMeta(task.last_run?.status);
    const status = document.createElement("span");
    status.className = `ftp-status-badge ${lastMeta.className}`;
    status.textContent = lastMeta.label;
    header.append(title, status);

    const routes = document.createElement("div");
    routes.className = "ftp-task-routes";
    [["Źródło FTP", task.source], ["Folder docelowy", task.destination]].forEach(([labelText, value]) => {
      const field = document.createElement("div");
      const label = document.createElement("span");
      label.textContent = labelText;
      const code = document.createElement("code");
      code.textContent = value;
      code.title = value;
      field.append(label, code);
      routes.append(field);
    });

    const timing = document.createElement("div");
    timing.className = "ftp-task-timing";
    const next = document.createElement("div");
    const nextLabel = document.createElement("span");
    nextLabel.textContent = "Następna próba";
    next.append(nextLabel);
    const nextStrong = document.createElement("strong");
    const nextDate = task.next_run ? new Date(task.next_run) : null;
    const generated = result.generated_at ? new Date(result.generated_at) : null;
    nextStrong.textContent = nextDate && generated && Math.abs(nextDate - generated) < 60000
      ? "teraz"
      : formatLocalDateTime(task.next_run);
    next.append(nextStrong);
    const last = document.createElement("div");
    const lastLabel = document.createElement("span");
    lastLabel.textContent = "Ostatnia próba";
    last.append(lastLabel);
    const lastStrong = document.createElement("strong");
    lastStrong.textContent = task.last_run
      ? `${formatLocalDateTime(task.last_run.updated_at)} • ${ftpStatusMeta(task.last_run.status).label}`
      : "jeszcze nie wykonano";
    last.append(lastStrong);
    timing.append(next, last);

    const schedule = document.createElement("div");
    schedule.className = "ftp-task-schedule";
    (task.schedule || []).forEach(entry => {
      const line = document.createElement("div");
      const entryName = document.createElement("strong");
      entryName.textContent = `${entry.label}:`;
      const description = document.createElement("span");
      description.textContent = `${entry.description}${entry.times?.length ? ` • ${entry.times.join(", ")}` : " • bez godziny"}`;
      line.append(entryName, description);
      schedule.append(line);
    });

    const actions = document.createElement("div");
    actions.className = "ftp-task-actions";
    const cadence = document.createElement("span");
    cadence.className = "active";
    cadence.textContent = "Codziennie, co godzinę";
    actions.append(cadence);
    const sync = document.createElement("button");
    sync.type = "button";
    sync.className = "primary-button compact-button";
    sync.textContent = "Synchronizuj FTP";
    sync.addEventListener("click", () => syncFtp(task.show_id, sync));
    const open = document.createElement("button");
    open.type = "button";
    open.className = "secondary-button compact-button";
    open.textContent = "Pokaż audycję";
    open.addEventListener("click", () => {
      const show = state.shows.find(item => item.id === task.show_id);
      if (show) openShowDialog(show);
      else toast("Nie znaleziono audycji");
    });
    if (state.unlocked) actions.append(sync);
    actions.append(open);
    card.append(header, routes, timing, schedule, actions);
    return card;
  }));
  $("#ftpTasksEmpty").classList.toggle("hidden", tasks.length > 0);

  const renderHistoryRow = entry => {
    const row = document.createElement("article");
    row.className = "ftp-history-row";
    const statusMeta = ftpStatusMeta(entry.status);
    const status = document.createElement("span");
    status.className = `ftp-status-badge ${statusMeta.className}`;
    status.textContent = statusMeta.label;
    const description = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = entry.show_name;
    const meta = document.createElement("small");
    meta.textContent = entry.trigger === "manual"
      ? `Ręczna synchronizacja • ${formatLocalDateTime(entry.updated_at)}`
      : `${entry.emission_date}, godz. ${String(entry.hour_slot).padStart(2, "0")}:00 • automatycznie • ${formatLocalDateTime(entry.updated_at)}`;
    description.append(title, meta);
    row.append(status, description);
    if (entry.detail) {
      const details = document.createElement("details");
      const summaryElement = document.createElement("summary");
      summaryElement.textContent = "Log";
      const log = document.createElement("pre");
      log.textContent = entry.detail;
      details.append(summaryElement, log);
      row.append(details);
    }
    return row;
  };
  const recentHistory = history.slice(0, 10).map(renderHistoryRow);
  if (history.length > 10) {
    const older = document.createElement("details");
    older.className = "ftp-history-older";
    const summaryElement = document.createElement("summary");
    summaryElement.textContent = `Pokaż starsze próby (${history.length - 10})`;
    const olderList = document.createElement("div");
    olderList.className = "ftp-history-list ftp-history-list-older";
    olderList.replaceChildren(...history.slice(10).map(renderHistoryRow));
    older.append(summaryElement, olderList);
    recentHistory.push(older);
  }
  $("#ftpHistoryList").replaceChildren(...recentHistory);
  $("#ftpHistoryEmpty").classList.toggle("hidden", history.length > 0);
}

function audioUrl(root, path) {
  return `/api/audio?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`;
}

function playAudio(root, path, title, context = {}) {
  mountAudioPlayer();
  const audio = $("#audioElement");
  const url = audioUrl(root, path);
  if (audio.dataset.url !== url) {
    audio.src = url;
    audio.dataset.url = url;
  }
  state.audioContext = { root, path, ...context };
  $("#audioPlayerTitle").textContent = title || path.split("/").pop();
  $("#audioPlayerSource").textContent = `${root === "spy" ? "Szpieg" : fileRootLabel(root)}/${path}`;
  $("#audioPlayer").classList.remove("hidden");
  document.body.classList.add("player-open");
  audio.play().catch(error => {
    if (error.name !== "AbortError") toast(`Nie udało się uruchomić odtwarzania: ${error.message}`, 7000);
  });
}

function playLiveStream() {
  const mountpoint = $("#spyLiveStream").value;
  const label = $("#spyLiveStream").selectedOptions[0]?.textContent || mountpoint;
  const url = `https://stream.radioemaus.pl:8443/${mountpoint}`;
  mountAudioPlayer();
  const audio = $("#audioElement");
  if (audio.dataset.url !== url) {
    audio.pause();
    audio.src = url;
    audio.dataset.url = url;
  }
  state.audioContext = { root: "live", path: mountpoint, live: true };
  $("#audioPlayerTitle").textContent = label;
  $("#audioPlayerSource").textContent = `Radio Emaus • /${mountpoint}`;
  $("#audioPlayer").classList.remove("hidden");
  document.body.classList.add("player-open");
  audio.play().catch(error => {
    if (error.name !== "AbortError") toast(`Nie udało się uruchomić streamu: ${error.message}`, 7000);
  });
}

function mountAudioPlayer() {
  const player = $("#audioPlayer");
  if (player.parentElement !== document.body) document.body.append(player);
}

function audioErrorMessage() {
  const error = $("#audioElement").error;
  if (!error) return "Nie udało się odtworzyć pliku audio";
  const messages = {
    1: "Odtwarzanie zostało przerwane",
    2: "Błąd sieci podczas pobierania audio",
    3: "Przeglądarka nie potrafi zdekodować tego pliku — możliwy nieobsługiwany kodek",
    4: "Nieobsługiwany format lub kodek audio",
  };
  return messages[error.code] || `Nie udało się odtworzyć pliku audio (kod ${error.code})`;
}

function stopAudio() {
  const audio = $("#audioElement");
  audio.pause();
  try { audio.currentTime = 0; } catch (_) { /* stream live nie pozwala przewijać */ }
}

function closeAudioPlayer() {
  stopAudio();
  $("#audioElement").removeAttribute("src");
  $("#audioElement").dataset.url = "";
  $("#audioPlayer").classList.add("hidden");
  document.body.classList.remove("player-open");
  state.audioContext = null;
}

async function loadAuth() {
  const result = await api("/api/auth/status");
  setUnlocked(result.unlocked);
}

function setUnlocked(value) {
  state.unlocked = value;
  state.timetableUnlocked = value;
  document.body.classList.toggle("locked", !value);
  $("#lockButton").classList.toggle("unlocked", value);
  $("#lockIcon").textContent = value ? "🔓" : "🔒";
  $("#lockText").textContent = value ? "Odblokowana" : "Edycja";
  $("#lockButton").title = value ? "Zablokuj edycję" : "Odblokuj edycję";
  renderShows();
  if (state.report) renderReport(state.report);
  if (state.ftpTasks) renderFtpTasks();
  $("#addTimetableEntry").classList.toggle("hidden", !value);
  if (state.timetable.entries.length) renderTimetable();
  updateCalendarAccessUi();
  if (state.calendarLoaded) renderCalendar();
}

async function handleLock() {
  if (state.unlocked) {
    await api("/api/auth/lock", { method: "POST" });
    setUnlocked(false);
    toast("Edycja zablokowana");
    return;
  }
  $("#pinInput").value = "";
  clearError("#pinError");
  openModal($("#unlockDialog"));
  setTimeout(() => $("#pinInput").focus(), 50);
}

async function submitUnlock(event) {
  event.preventDefault();
  clearError("#pinError");
  try {
    await api("/api/auth/unlock", { method: "POST", body: JSON.stringify({ pin: $("#pinInput").value }) });
    setUnlocked(true);
    $("#unlockDialog").close();
    toast("Edycja odblokowana na 8 godzin");
  } catch (error) { showError("#pinError", error); }
}

function openChangePin() {
  $("#newPinInput").value = "";
  $("#repeatPinInput").value = "";
  clearError("#changePinError");
  openModal($("#changePinDialog"));
  setTimeout(() => $("#newPinInput").focus(), 50);
}

async function submitChangePin(event) {
  event.preventDefault();
  clearError("#changePinError");
  const pin = $("#newPinInput").value;
  if (pin !== $("#repeatPinInput").value) {
    showError("#changePinError", "Wpisane PIN-y są różne");
    return;
  }
  try {
    await api("/api/auth/change-pin", { method: "POST", body: JSON.stringify({ new_pin: pin }) });
    $("#changePinDialog").close();
    toast("PIN został zmieniony");
  } catch (error) { showError("#changePinError", error); }
}

function updateDateHeader(report = null) {
  const date = state.selectedDate;
  $("#datePicker").value = localIso(date);
  $("#dateLabel").textContent = formatDate(date);
  $("#weekLabel").textContent = `Tydzień ${isoWeekNumber(date)}`;
  const weekday = report?.weekday || new Intl.DateTimeFormat("pl-PL", { weekday: "long" }).format(date);
  $("#weekdayLabel").textContent = capitalizeFirst(weekday);
}

async function loadReport() {
  updateDateHeader();
  $("#refreshButton").disabled = true;
  try {
    const report = await api(`/api/report?date=${localIso(state.selectedDate)}`);
    updateDateHeader(report);
    renderReport(report);
  } catch (error) {
    toast(error.message);
  } finally { $("#refreshButton").disabled = false; }
}

function renderReport(report) {
  state.report = report;
  $("#totalCount").textContent = report.total;
  $("#foundCount").textContent = report.found;
  $("#missingCount").textContent = report.missing;
  const order = items => [...items].sort((a, b) => {
    if (state.reportSort === "name") return a.name.localeCompare(b.name, "pl", { sensitivity: "base" });
    return (a.emission_time || "99:99").localeCompare(b.emission_time || "99:99")
      || a.name.localeCompare(b.name, "pl", { sensitivity: "base" });
  });
  const found = order(report.items.filter(item => item.found || item.ignored));
  const missing = order(report.items.filter(item => !item.found && !item.ignored));
  renderReportList("#foundList", found);
  renderReportList("#missingList", missing);
  $("#foundBadge").textContent = found.length;
  $("#missingBadge").textContent = missing.length;
  $("#foundSection").classList.toggle("hidden", !found.length);
  $("#missingSection").classList.toggle("hidden", !missing.length);
  $("#emptyReport").classList.toggle("hidden", report.total !== 0);
}

function renderReportList(selector, items) {
  const list = $(selector);
  list.replaceChildren(...items.map(item => {
    const row = document.createElement("article");
    row.className = `report-row ${item.ignored ? "ignored" : item.status}`;
    const dot = document.createElement("span");
    dot.className = "status-dot";
    dot.textContent = item.found ? "✓" : "!";
    const name = document.createElement("div");
    name.className = "report-name";
    const titleLine = document.createElement("div");
    titleLine.className = "report-title-line";
    const strong = document.createElement("strong");
    strong.textContent = item.name;
    titleLine.append(strong, createTagList(item.tags || []));
    const small = document.createElement("small");
    const timeLabel = item.emission_times?.length
      ? `${item.emission_times.length > 1 ? "emisje" : "emisja"} ${item.emission_times.join(", ")}`
      : "godzina nieustawiona";
    small.textContent = `${item.occurrence_label || "Emisja główna"} • ${timeLabel}`;
    name.append(titleLine, small);
    const path = document.createElement("div");
    path.className = "file-path-list";
    const parts = item.parts || [{ part_number: 1, found: item.found, relative_path: item.relative_path, duration: item.duration }];
    parts.forEach(part => {
      const line = document.createElement("div");
      line.className = `file-path-part ${part.found ? "found" : "missing"}`;
      const mark = document.createElement("span");
      mark.className = "part-mark";
      mark.textContent = part.found ? "✓" : "!";
      const label = document.createElement("span");
      label.className = "part-label";
      label.textContent = part.label || (parts.length > 1 ? `cz. ${part.part_number}` : "plik");
      const code = document.createElement("code");
      const displayPath = `/AUDYCJE/${part.relative_path}`;
      code.textContent = displayPath;
      code.title = displayPath;
      const playSlot = document.createElement("span");
      playSlot.className = "file-play-slot";
      if (part.found) {
        const play = document.createElement("button");
        play.type = "button";
        play.className = "inline-play-button";
        play.textContent = "▶";
        play.title = `Odtwórz ${part.label || part.relative_path}`;
        play.addEventListener("click", event => {
          event.stopPropagation();
          playAudio("media", part.relative_path, `${item.name} — ${part.label || "plik"}`);
        });
        playSlot.append(play);
      }
      line.append(mark, label, playSlot, code);
      path.append(line);
    });
    (item.ftp_sources || []).forEach(source => {
      const line = document.createElement("div");
      line.className = `file-path-part ftp-source-part ${source.found ? "found" : "missing"}`;
      const mark = document.createElement("span");
      mark.className = "part-mark";
      mark.textContent = source.found ? "✓" : "!";
      const label = document.createElement("span");
      label.className = "part-label";
      label.textContent = `FTP ${source.part_number}`;
      const code = document.createElement("code");
      code.textContent = `/AUDYCJE/${source.relative_path}`;
      code.title = code.textContent;
      const playSlot = document.createElement("span");
      playSlot.className = "file-play-slot";
      if (source.found) {
        const play = document.createElement("button");
        play.type = "button";
        play.className = "inline-play-button";
        play.textContent = "▶";
        play.addEventListener("click", event => {
          event.stopPropagation();
          playAudio("media", source.relative_path, `${item.name} — plik FTP ${source.part_number}`);
        });
        playSlot.append(play);
      }
      line.append(mark, label, playSlot, code);
      path.append(line);
    });
    const actions = document.createElement("div");
    actions.className = "report-actions";
    const duration = document.createElement("span");
    duration.className = "duration";
    const actualDuration = item.actual_duration || item.duration;
    duration.textContent = parts.length > 1
      ? `${item.files_found}/${item.parts_total}${actualDuration ? ` • ${actualDuration}` : ""}`
      : (actualDuration || (item.found ? "—" : "brak"));
    if (item.duration_exceeded) {
      row.classList.add("duration-exceeded");
      duration.classList.add("duration-warning");
      duration.textContent = `⚠ ${duration.textContent}`;
      duration.title = `Audycja przekracza maksymalny czas ${durationLimitLabel(item.max_duration_minutes)}`;
    }
    actions.append(duration);
    if (item.max_duration_minutes != null) {
      const limit = document.createElement("span");
      limit.className = `duration-limit${item.duration_exceeded ? " exceeded" : ""}`;
      limit.textContent = `maks. ${durationLimitLabel(item.max_duration_minutes)}`;
      actions.append(limit);
    }
    if ((item.production_watch_folders || []).length) {
      const openProduction = document.createElement("button");
      openProduction.type = "button";
      openProduction.className = "production-folder-button";
      openProduction.textContent = "📁";
      openProduction.title = item.production_watch_folders.length === 1
        ? "Otwórz folder produkcyjny"
        : `Otwórz foldery produkcyjne (${item.production_watch_folders.length})`;
      openProduction.addEventListener("click", event => {
        event.stopPropagation();
        openProductionFolder(item.production_watch_folders[0]);
      });
      actions.append(openProduction);
    }
    if (item.ignored) {
      const ignored = document.createElement("button");
      ignored.type = "button";
      ignored.className = "ignored-report-button";
      ignored.textContent = "⚠ Zignorowane";
      ignored.title = "Brak tej emisji został świadomie zignorowany";
      ignored.disabled = true;
      actions.append(ignored);
    } else if (!item.found && state.unlocked) {
      const ignore = document.createElement("button");
      ignore.type = "button";
      ignore.className = "ignore-report-button";
      ignore.textContent = "Ignoruj";
      ignore.addEventListener("click", async event => {
        event.stopPropagation();
        if (!confirm(`Czy na pewno zignorować brak audycji „${item.name}” w tym dniu?`)) return;
        ignore.disabled = true;
        ignore.textContent = "Ignoruję…";
        try {
          await api("/api/report/ignore", {
            method: "POST",
            body: JSON.stringify({
              show_id: item.id,
              occurrence_key: item.occurrence_key,
              date: localIso(state.selectedDate),
            }),
          });
          toast(`Zignorowano brak audycji „${item.name}”`);
          await loadReport();
        } catch (error) {
          toast(error.message);
          ignore.disabled = false;
          ignore.textContent = "Ignoruj";
        }
      });
      actions.append(ignore);
    }
    if (item.can_generate && state.unlocked) {
      const generate = document.createElement("button");
      generate.type = "button";
      generate.className = "generate-repeat-button";
      generate.textContent = "Kopiuj premierę";
      generate.title = item.source_relative_path
        ? `Skopiuj ostatnią zaplanowaną premierę z /AUDYCJE/${item.source_relative_path}`
        : "Użyj plików ostatniej zaplanowanej premiery";
      generate.addEventListener("click", () => generateRepeat(item, generate));
      actions.append(generate);
    }
    const missingBroadcastFile = (item.parts || []).some(part => !part.found && part.file_type !== "youtube");
    if (missingBroadcastFile && state.unlocked) {
      const substitute = document.createElement("button");
      substitute.type = "button";
      substitute.className = "generate-repeat-button";
      substitute.textContent = "Wybierz ręcznie";
      substitute.title = "Wybierz inne pliki audio i skopiuj je pod nazwę tej emisji";
      substitute.addEventListener("click", event => { event.stopPropagation(); openSubstitute(item); });
      actions.append(substitute);
    }
    if (item.ftp_can_sync && state.unlocked) {
      const download = document.createElement("button");
      download.type = "button";
      download.className = "ftp-action-button";
      download.textContent = "Synchronizuj FTP";
      download.addEventListener("click", () => syncFtp(item.id, download));
      actions.append(download);
    }
    if (item.ftp_rename_enabled && state.unlocked) {
      const rename = document.createElement("button");
      rename.type = "button";
      rename.className = "ftp-action-button rename-action-button";
      if (item.ftp_renamed) {
        rename.textContent = "✓ Przemianowane";
        rename.classList.add("renamed");
        rename.disabled = true;
        rename.title = "Wszystkie pliki docelowe są już aktualne";
      } else {
        rename.textContent = "Przemianuj";
        rename.disabled = !item.ftp_can_rename;
        rename.title = item.ftp_can_rename ? "Utwórz lub zaktualizuj pliki docelowe" : "Najpierw pobierz wszystkie pliki źródłowe";
        rename.addEventListener("click", () => renameFtp(item.id, item.repeat_id, rename));
      }
      actions.append(rename);
    }
    if (item.send_to_author && item.occurrence_type === "main" && state.unlocked) {
      const send = document.createElement("button");
      send.type = "button";
      send.className = "author-action-button";
      if (item.author_sent) {
        send.textContent = "✓ Wysłano";
        send.classList.add("sent");
        send.disabled = true;
        const sentAt = item.author_delivery?.sent_at ? ` (${item.author_delivery.sent_at} UTC)` : "";
        send.title = `Wysłano do ${(item.author_emails || []).join(", ") || item.author_email}${sentAt}`;
      } else {
        send.textContent = "Wyślij autorowi";
        send.disabled = !item.found;
        send.title = !item.found
          ? "Najpierw muszą być dostępne wszystkie pliki premiery"
          : (state.unlocked ? `Skopiuj pliki na Google Drive i wyślij osobny e-mail do: ${(item.author_emails || []).join(", ") || item.author_email}` : "Najpierw odblokuj edycję");
        send.addEventListener("click", async event => {
          event.stopPropagation();
          if (!state.unlocked) { await handleLock(); return; }
          sendToAuthor(item, send);
        });
      }
      actions.append(send);
    }
    row.append(dot, name, path, actions);
    row.classList.add("viewable");
    row.addEventListener("click", event => {
      if (event.target.closest("button")) return;
      const show = state.shows.find(candidate => candidate.id === item.id);
      if (show) openShowDialog(show);
    });
    return row;
  }));
}

async function generateRepeat(item, button) {
  if (!state.unlocked) {
    await handleLock();
    return;
  }
  button.disabled = true;
  button.textContent = "Tworzę…";
  try {
    const result = await api("/api/report/generate-repeat", {
      method: "POST",
      body: JSON.stringify({ show_id: item.id, repeat_id: item.repeat_id, date: localIso(state.selectedDate) }),
    });
    const copied = (result.files || []).map(file => {
      const source = file.source.split("/").pop();
      const target = file.target.split("/").pop();
      return `${source} → ${target}`;
    });
    toast(`Skopiowano ${result.created_count} ${result.created_count === 1 ? "plik" : "pliki"}${copied.length ? `:\n${copied.join("\n")}` : ""}`, 8000);
    await loadReport();
  } catch (error) {
    toast(error.message);
    button.disabled = false;
    button.textContent = "Kopiuj premierę";
  }
}

function openSubstitute(item) {
  state.substituteItem = item;
  state.substituteSources = [];
  openBrowser("substitute");
}

function renderSubstituteSelection() {
  const box = $("#substituteSelection");
  if (state.browserMode !== "substitute" || !state.substituteItem) {
    box.classList.add("hidden");
    return;
  }
  const required = (state.substituteItem.parts || []).filter(part => part.file_type !== "youtube").length;
  box.classList.remove("hidden");
  const label = document.createElement("strong");
  label.textContent = `Wybrano ${state.substituteSources.length}/${required}`;
  const hint = document.createElement("span");
  hint.textContent = state.substituteSources.length
    ? "Pliki zostaną przypisane do części w pokazanej kolejności."
    : (required > 1
      ? `Wybierz ${required} pliki po kolei: część 1, część 2 itd.`
      : "Kliknij plik audio poniżej.");
  const chips = document.createElement("div");
  chips.className = "substitute-chips";
  state.substituteSources.forEach((source, index) => {
    const chip = document.createElement("button");
    chip.type = "button";
    const rootLabel = fileRootLabel(source.root);
    chip.textContent = `${index + 1}. ${rootLabel}/${source.path.split("/").pop()} ×`;
    chip.title = "Usuń z wyboru";
    chip.addEventListener("click", () => {
      state.substituteSources.splice(index, 1);
      renderSubstituteSelection();
    });
    chips.append(chip);
  });
  box.replaceChildren(label, hint, chips);
  $("#confirmSubstitute").classList.toggle("hidden", state.substituteSources.length !== required);
}

async function confirmSubstitute() {
  const item = state.substituteItem;
  if (!item) return;
  const button = $("#confirmSubstitute");
  button.disabled = true;
  try {
    const result = await api("/api/report/substitute", {
      method: "POST",
      body: JSON.stringify({
        show_id: item.id,
        repeat_id: item.repeat_id,
        date: localIso(state.selectedDate),
        source_files: state.substituteSources,
      }),
    });
    $("#fileDialog").close();
    toast(`Utworzono audycję zastępczą (${result.copied} plik(i))`);
    await loadReport();
  } catch (error) {
    showError("#browserError", error);
  } finally { button.disabled = false; }
}

async function sendToAuthor(item, button) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Wysyłam…";
  try {
    const result = await api("/api/report/send-author", {
      method: "POST",
      body: JSON.stringify({ show_id: item.id, date: localIso(state.selectedDate) }),
    });
    if (result.already_sent) {
      toast(`Pliki były już wysłane do: ${result.recipient}.`, 8000);
    } else {
      const sentTo = (result.sent_recipients || result.recipients || [result.recipient]).join(", ");
      const skipped = result.already_sent_recipients?.length
        ? ` Wcześniej wysłano już do: ${result.already_sent_recipients.join(", ")}.`
        : "";
      const access = result.link_access
        ? " Folder jest dostępny bez konta Google dla osób mających link."
        : "";
      toast(`Wysłano do: ${sentTo}. Pliki: ${result.files.join(", ")}.${skipped}${access}`, 10000);
    }
    await loadReport();
  } catch (error) {
    toast(error.message, 8000);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function syncFtp(showId, button, draft = null) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Synchronizuję…";
  try {
    const result = await api("/api/ftp/sync", { method: "POST", body: JSON.stringify({ show_id: showId, ...(draft || {}) }) });
    toast(`Synchronizacja FTP zakończona${result.destination ? `: ${result.destination}` : ""}`, 5000);
    await Promise.all([
      loadReport(),
      loadFtpStatus(),
      $("#ftpView").classList.contains("active") ? loadFtpTasks() : Promise.resolve(),
    ]);
  } catch (error) {
    const fullMessage = error.message || "Synchronizacja FTP nie powiodła się";
    const shortMessage = fullMessage.length > 900
      ? `${fullMessage.slice(0, 900)}…\nPełny log zapisano w zakładce FTP.`
      : fullMessage;
    toast(shortMessage, 9000);
    if ($("#ftpView").classList.contains("active")) await loadFtpTasks();
  } finally {
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = original;
    }
  }
}

async function renameFtp(showId, repeatId, button) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Kopiuję…";
  try {
    const result = await api("/api/ftp/rename", {
      method: "POST",
      body: JSON.stringify({ show_id: showId, repeat_id: repeatId, date: localIso(state.selectedDate) }),
    });
    toast(`Utworzono ${result.copied} ${result.copied === 1 ? "plik" : "pliki"}`);
    await Promise.all([loadReport(), loadFtpStatus()]);
  } catch (error) {
    toast(error.message);
    button.disabled = false;
    button.textContent = original;
  }
}

function createTagList(tags) {
  const list = document.createElement("div");
  list.className = "tag-list";
  tags.forEach(value => {
    const tag = document.createElement("span");
    const key = value.toLocaleLowerCase("pl-PL").replace("ż", "z").replace("ó", "o");
    tag.className = `tag tag-${key}`;
    tag.textContent = value;
    list.append(tag);
  });
  return list;
}

function hideImportWarning(persist = true) {
  clearTimeout(state.importWarningTimer);
  $("#importWarning").classList.add("hidden");
  if (!persist || !state.importWarningKey) return;
  try { localStorage.setItem("dismissedImportWarning", state.importWarningKey); } catch (_) { /* storage unavailable */ }
}

function renderImportWarning(importInfo) {
  clearTimeout(state.importWarningTimer);
  const warnings = importInfo?.warnings || [];
  if (!warnings.length) { hideImportWarning(false); return; }
  if (!$("#showsView").classList.contains("active")) { hideImportWarning(false); return; }
  const key = `${importInfo.created_at || "import"}:${warnings.join("|")}`;
  state.importWarningKey = key;
  let dismissed = null;
  try { dismissed = localStorage.getItem("dismissedImportWarning"); } catch (_) { /* storage unavailable */ }
  if (dismissed === key) { hideImportWarning(false); return; }
  $("#importWarningText").textContent = `Import: ${warnings.join(" ")}`;
  $("#importWarning").classList.remove("hidden");
  state.importWarningTimer = setTimeout(() => hideImportWarning(true), 15000);
}

function renderTimetableLayers() {
  const host = $("#timetableLayers");
  host.replaceChildren(...TIMETABLE_LAYERS.map(layer => {
    const label = document.createElement("label");
    label.className = `timetable-layer layer-${layer.key}`;
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = state.timetableLayers.has(layer.key);
    input.addEventListener("change", () => {
      if (input.checked) state.timetableLayers.add(layer.key);
      else state.timetableLayers.delete(layer.key);
      try { localStorage.setItem("timetableLayers", JSON.stringify([...state.timetableLayers])); } catch (_) { /* unavailable */ }
      renderTimetable();
    });
    const span = document.createElement("span");
    span.textContent = layer.label;
    label.append(input, span);
    return label;
  }));
}

function timetableSelectOptions() {
  const day = $("#timetableDay");
  day.replaceChildren(...TIMETABLE_WEEKDAYS.map((name, index) => new Option(name, String(index))));
  day.value = String(state.timetableDay);
  const weekday = $("#timetableWeekday");
  weekday.replaceChildren(...TIMETABLE_WEEKDAYS.map((name, index) => new Option(name, String(index))));
  const category = $("#timetableCategory");
  category.replaceChildren(...TIMETABLE_LAYERS.filter(layer => layer.key !== "shows").map(layer => new Option(layer.label, layer.key)));
}

async function loadTimetable() {
  clearError("#timetableError");
  try {
    const timetable = await api("/api/timetable");
    state.timetable = timetable;
    setTimetableUnlocked(state.unlocked);
    renderTimetableLayers();
    timetableSelectOptions();
    renderTimetable();
  } catch (error) { showError("#timetableError", error); }
}

function setTimetableUnlocked(unlocked) {
  state.timetableUnlocked = unlocked;
  $("#addTimetableEntry").classList.toggle("hidden", !unlocked);
  if (state.timetable.entries.length) renderTimetable();
}

function timetableEntryPayload(entry, changes = {}) {
  return {
    item_id: entry.item_id,
    name: entry.name,
    category: entry.category,
    show_id: entry.show_id,
    show_role: entry.show_role || "",
    weekday: entry.weekday,
    start_time: entry.start_time,
    duration_minutes: entry.duration_minutes,
    approximate: entry.approximate,
    note: entry.note || "",
    source: "manual",
    ...changes,
  };
}

function timetableTimeFromMinutes(totalMinutes) {
  const safe = Math.max(0, Math.min(1439, totalMinutes));
  return `${String(Math.floor(safe / 60)).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
}

function timetableMinutes(value) {
  const [hour, minute] = String(value || "00:00").split(":").map(Number);
  return hour * 60 + minute;
}

function timetableDurationLabel(value) {
  const duration = Number(value);
  if (!Number.isFinite(duration)) return "—";
  return `${new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 1 }).format(duration)} min`;
}

function timetableRecurrenceVariant(entry) {
  const note = String(entry?.note || "").toLocaleLowerCase("pl-PL");
  if (note.includes("nieparzyste tygodnie")) return { key: "odd", label: "TYG. NIEPARZYSTE", tone: "odd" };
  if (note.includes("parzyste tygodnie")) return { key: "even", label: "TYG. PARZYSTE", tone: "even" };
  const nth = note.match(/([1-5](?:\s*,\s*[1-5])*)\.\s*w miesiącu/);
  if (nth) {
    const occurrences = nth[1].replaceAll(" ", "");
    return { key: `nth-${occurrences}`, label: `${occurrences}. TYDZ. MIESIĄCA`, tone: "nth" };
  }
  if (note.includes("daty:")) return { key: `dates-${note}`, label: "WYBRANE DATY", tone: "dates" };
  return null;
}

function timetableAlternatingEntries(entries, entry) {
  const variant = timetableRecurrenceVariant(entry);
  if (!variant || entry.category !== "shows") return [];
  const matching = entries.filter(candidate =>
    candidate.category === "shows"
    && candidate.start_time === entry.start_time
    && timetableRecurrenceVariant(candidate)
  );
  return new Set(matching.map(candidate => timetableRecurrenceVariant(candidate).key)).size >= 2 ? matching : [];
}

async function moveTimetableEntry(entry, weekday, totalMinutes, copy = false) {
  if (!state.timetableUnlocked) return;
  const startTime = timetableTimeFromMinutes(totalMinutes);
  try {
    const updated = await api(copy ? "/api/timetable/entries" : `/api/timetable/entries/${entry.id}`, {
      method: copy ? "POST" : "PUT",
      body: JSON.stringify(timetableEntryPayload(entry, {
        weekday,
        start_time: startTime,
      })),
    });
    await loadTimetable();
    toast(`${copy ? "Skopiowano" : "Przeniesiono"}: ${updated.show_name || updated.name} → ${TIMETABLE_WEEKDAYS[weekday]}, ${updated.start_time}`);
  } catch (error) {
    if (error.message.includes("zablokowana")) setTimetableUnlocked(false);
    toast(error.message);
  }
}

function timetableBlock(entry) {
  const block = document.createElement("button");
  block.type = "button";
  block.className = `timetable-block layer-${entry.category}`;
  const recurrence = timetableRecurrenceVariant(entry);
  if (recurrence) block.classList.add("timetable-block-alternating", `timetable-alternate-${recurrence.tone}`);
  block.draggable = state.timetableUnlocked;
  block.title = `${entry.approximate ? "około " : ""}${entry.start_time} • ${timetableDurationLabel(entry.duration_minutes)}${entry.note ? `\n${entry.note}` : ""}`;
  const time = document.createElement("span");
  time.className = "timetable-block-time";
  time.textContent = `${entry.approximate ? "~" : ""}${entry.start_time}`;
  const name = document.createElement("strong");
  name.textContent = entry.show_name || entry.name;
  const meta = document.createElement("small");
  const pieces = [];
  if (entry.show_id != null) pieces.push(entry.show_role === "repeat" ? "Powtórka" : "Premiera");
  else if (entry.note) pieces.push(entry.note);
  if (entry.duration_minutes) pieces.push(timetableDurationLabel(entry.duration_minutes));
  meta.textContent = pieces.join(" • ");
  block.append(time, name);
  if (recurrence) {
    const badge = document.createElement("span");
    badge.className = "timetable-recurrence-badge";
    badge.textContent = recurrence.label;
    block.append(badge);
  }
  if (pieces.length) block.append(meta);
  block.addEventListener("click", () => {
    if (entry.show_id != null) {
      const show = (state.timetable.shows || []).find(item => item.id === entry.show_id);
      if (show) openShowDialog(show);
      else toast("Nie znaleziono audycji");
      return;
    }
    openTimetableEntryDialog(entry);
  });
  block.addEventListener("dragstart", event => {
    if (!state.timetableUnlocked) { event.preventDefault(); return; }
    state.timetableDraggedId = entry.id;
    state.timetableDragCopy = event.altKey;
    event.dataTransfer.effectAllowed = "copyMove";
    event.dataTransfer.setData("text/plain", String(entry.id));
    block.classList.add("dragging");
  });
  block.addEventListener("dragend", () => {
    state.timetableDraggedId = null;
    state.timetableDragCopy = false;
    block.classList.remove("dragging");
  });
  return block;
}

function visibleTimetableDays() {
  if (state.timetableRange === 7) return TIMETABLE_WEEKDAYS.map((_, index) => index);
  return Array.from({ length: state.timetableRange }, (_, index) => (state.timetableDay + index) % 7);
}

function renderTimetableHourJumps() {
  $("#timetableHourJumps").replaceChildren(...Array.from({ length: 18 }, (_, index) => {
    const hour = index + 6;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "timetable-hour-jump";
    button.textContent = `${String(hour).padStart(2, "0")}:00`;
    button.addEventListener("click", () => jumpTimetableHour(hour));
    return button;
  }));
}

function jumpTimetableHour(hour) {
  const shell = $(".timetable-board-shell");
  const label = [...$("#timetableBoard").querySelectorAll(".timetable-hour")]
    .find(item => item.textContent === `${String(hour).padStart(2, "0")}:00`);
  if (!label) return;
  shell.scrollTo({ top: Math.max(0, label.offsetTop - 46), behavior: "smooth" });
}

function bindTimetableDropTarget(cell, day, totalMinutes, preserveEntryMinute = false) {
  cell.addEventListener("dragover", event => {
    if (!state.timetableUnlocked || !state.timetableDraggedId) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = (event.altKey || state.timetableDragCopy) ? "copy" : "move";
    cell.classList.add("drop-target");
  });
  cell.addEventListener("dragleave", () => cell.classList.remove("drop-target"));
  cell.addEventListener("drop", event => {
    event.preventDefault();
    cell.classList.remove("drop-target");
    const id = Number(event.dataTransfer.getData("text/plain") || state.timetableDraggedId);
    const entry = state.timetable.entries.find(item => item.id === id);
    const copy = event.altKey || state.timetableDragCopy;
    const destination = preserveEntryMinute && entry
      ? totalMinutes + (timetableMinutes(entry.start_time) % 60)
      : totalMinutes + (copy && entry ? timetableMinutes(entry.start_time) % 5 : 0);
    if (entry) moveTimetableEntry(entry, day, destination, copy);
  });
  cell.addEventListener("dblclick", event => {
    if (!state.timetableUnlocked || event.target.closest(".timetable-block")) return;
    openTimetableEntryDialog(null, day, timetableTimeFromMinutes(totalMinutes));
  });
}

function timetableHeader(fragment, days) {
  const corner = document.createElement("div");
  corner.className = "timetable-corner";
  corner.textContent = "Godz.";
  fragment.append(corner);
  days.forEach(day => {
    const header = document.createElement("div");
    header.className = "timetable-day-header";
    header.textContent = TIMETABLE_WEEKDAYS[day];
    fragment.append(header);
  });
}

function renderCompactTimetable(board, days) {
  const fragment = document.createDocumentFragment();
  timetableHeader(fragment, days);
  const visibleEntries = (state.timetable.entries || []).filter(entry =>
    days.includes(entry.weekday) && state.timetableLayers.has(entry.category)
  );
  const visibleHours = new Set(
    visibleEntries.map(entry => Number(String(entry.start_time || "").slice(0, 2)))
  );
  for (let hour = 0; hour < 24; hour += 1) {
    if (!visibleHours.has(hour)) continue;
    const hourLabel = document.createElement("div");
    hourLabel.className = "timetable-hour";
    hourLabel.textContent = `${String(hour).padStart(2, "0")}:00`;
    fragment.append(hourLabel);
    days.forEach(day => {
      const cell = document.createElement("div");
      cell.className = "timetable-cell";
      const entries = visibleEntries
        .filter(entry => entry.weekday === day && Number(entry.start_time.slice(0, 2)) === hour && state.timetableLayers.has(entry.category))
        .sort((a, b) => a.start_time.localeCompare(b.start_time) || a.id - b.id);
      const rendered = new Set();
      entries.forEach(entry => {
        if (rendered.has(entry.id)) return;
        const alternating = timetableAlternatingEntries(entries, entry);
        if (alternating.length >= 2) {
          const group = document.createElement("div");
          group.className = "timetable-alternate-group";
          const label = document.createElement("span");
          label.className = "timetable-alternate-label";
          label.textContent = `${entry.start_time} · naprzemienny harmonogram`;
          group.append(label);
          alternating
            .sort((a, b) => timetableRecurrenceVariant(a).label.localeCompare(timetableRecurrenceVariant(b).label, "pl"))
            .forEach(candidate => {
              rendered.add(candidate.id);
              group.append(timetableBlock(candidate));
            });
          cell.append(group);
          return;
        }
        rendered.add(entry.id);
        cell.append(timetableBlock(entry));
      });
      bindTimetableDropTarget(cell, day, hour * 60, true);
      fragment.append(cell);
    });
  }
  board.replaceChildren(fragment);
}

function renderFullTimetable(board, days) {
  const fragment = document.createDocumentFragment();
  timetableHeader(fragment, days);
  for (let slot = 0; slot < 288; slot += 1) {
    if (slot % 12 === 0) {
      const hourLabel = document.createElement("div");
      hourLabel.className = "timetable-hour timetable-hour-full";
      hourLabel.style.gridColumn = "1";
      hourLabel.style.gridRow = `${slot + 2} / span 12`;
      hourLabel.textContent = `${String(slot / 12).padStart(2, "0")}:00`;
      fragment.append(hourLabel);
    }
    days.forEach((day, dayIndex) => {
      const cell = document.createElement("div");
      cell.className = `timetable-slot${slot % 12 === 0 ? " hour-start" : ""}`;
      cell.style.gridColumn = String(dayIndex + 2);
      cell.style.gridRow = String(slot + 2);
      bindTimetableDropTarget(cell, day, slot * 5);
      fragment.append(cell);
    });
  }
  const visibleEntries = (state.timetable.entries || [])
    .filter(entry => days.includes(entry.weekday) && state.timetableLayers.has(entry.category));
  const overlapLayout = timetableOverlapLayout(visibleEntries);
  const alternatingIds = new Set();
  visibleEntries.forEach(entry => timetableAlternatingEntries(
    visibleEntries.filter(candidate => candidate.weekday === entry.weekday), entry
  ).forEach(candidate => alternatingIds.add(candidate.id)));
  visibleEntries
    .forEach(entry => {
      const dayIndex = days.indexOf(entry.weekday);
      const start = timetableMinutes(entry.start_time);
      const startSlot = Math.floor(start / 5);
      const block = timetableBlock(entry);
      block.classList.add("timetable-block-full");
      if (alternatingIds.has(entry.id)) block.classList.add("timetable-alternate-member-full");
      block.style.gridColumn = String(dayIndex + 2);
      block.style.gridRow = String(startSlot + 2);
      block.dataset.minuteOffset = String(start % 5);
      block.dataset.durationMinutes = String(entry.duration_minutes);
      if (Number(entry.duration_minutes) < 5) {
        block.classList.add("timetable-block-short");
      }
      const overlap = overlapLayout.get(entry.id) || { lane: 0, count: 1 };
      const laneWidth = 100 / overlap.count;
      block.style.width = `calc(${laneWidth}% - 4px)`;
      block.style.marginLeft = `calc(${laneWidth * overlap.lane}% + 2px)`;
      block.style.marginRight = "0";
      scaleFullTimetableBlock(block);
      fragment.append(block);
    });
  board.replaceChildren(fragment);
}

function timetableOverlapLayout(entries) {
  const layout = new Map();
  const byDay = new Map();
  entries.forEach(entry => {
    if (!byDay.has(entry.weekday)) byDay.set(entry.weekday, []);
    byDay.get(entry.weekday).push(entry);
  });
  byDay.forEach(dayEntries => {
    const sorted = [...dayEntries].sort((a, b) =>
      timetableMinutes(a.start_time) - timetableMinutes(b.start_time) || a.id - b.id
    );
    let component = [];
    let componentEnd = -1;
    const flush = () => {
      if (!component.length) return;
      const laneEnds = [];
      const assigned = [];
      component.forEach(entry => {
        const start = timetableMinutes(entry.start_time);
        const end = start + timetableDisplayDurationMinutes(entry.duration_minutes);
        let lane = laneEnds.findIndex(value => value <= start);
        if (lane < 0) lane = laneEnds.length;
        laneEnds[lane] = end;
        assigned.push([entry.id, lane]);
      });
      const count = Math.max(1, laneEnds.length);
      assigned.forEach(([id, lane]) => layout.set(id, { lane, count }));
      component = [];
      componentEnd = -1;
    };
    sorted.forEach(entry => {
      const start = timetableMinutes(entry.start_time);
      const end = start + timetableDisplayDurationMinutes(entry.duration_minutes);
      if (component.length && start >= componentEnd) flush();
      component.push(entry);
      componentEnd = Math.max(componentEnd, end);
    });
    flush();
  });
  return layout;
}

function updateTimetableViewControls() {
  $$("#timetableRange [data-range]").forEach(button => button.classList.toggle("active", Number(button.dataset.range) === state.timetableRange));
  $$("#timetableDensity [data-density]").forEach(button => button.classList.toggle("active", button.dataset.density === state.timetableDensity));
  $(".timetable-day-navigation").classList.toggle("hidden", state.timetableRange === 7);
  $("#timetableDay").value = String(state.timetableDay);
  $("#timetableZoom").value = String(state.timetableZoom);
  $("#timetableZoomValue").textContent = `${state.timetableZoom} px / 5 min`;
  $("#timetableViewportHeight").value = String(state.timetableViewportHeight);
  $("#timetableViewportHeightValue").textContent = `${state.timetableViewportHeight}% ekranu`;
  $("#timetableWideButton").classList.toggle("active", state.timetableWide);
  $("#timetableWideButton").setAttribute("aria-pressed", String(state.timetableWide));
  $("#timetableWideButton").textContent = state.timetableWide ? "↔ Szeroki: włączony" : "↔ Szeroki";
}

function applyTimetableZoom(value) {
  const next = Math.max(36, Math.min(144, Number(value) || 60));
  const previous = state.timetableZoom;
  const shell = $(".timetable-board-shell");
  const previousScroll = shell.scrollTop;
  state.timetableZoom = next;
  try { localStorage.setItem("timetableZoom", String(next)); } catch (_) { /* unavailable */ }
  $("#timetableBoard").style.setProperty("--timetable-slot-height", `${next}px`);
  $("#timetableBoard").style.setProperty("--timetable-hour-height", `${next * 12}px`);
  $("#timetableBoard").style.setProperty("--timetable-compact-hour-height", `${next * 4}px`);
  $("#timetableZoomValue").textContent = `${next} px / 5 min`;
  renderTimetable();
  if (previous > 0 && previousScroll > 0) {
    requestAnimationFrame(() => { shell.scrollTop = previousScroll * (next / previous); });
  }
}

function applyTimetableViewportHeight(value) {
  state.timetableViewportHeight = Math.max(45, Math.min(95, Number(value) || 72));
  try { localStorage.setItem("timetableViewportHeight", String(state.timetableViewportHeight)); } catch (_) { /* unavailable */ }
  $(".timetable-board-shell").style.setProperty("--timetable-viewport-height", `${state.timetableViewportHeight}vh`);
  $("#timetableViewportHeightValue").textContent = `${state.timetableViewportHeight}% ekranu`;
}

function toggleTimetableWide() {
  state.timetableWide = !state.timetableWide;
  try { localStorage.setItem("timetableWide", String(state.timetableWide)); } catch (_) { /* unavailable */ }
  document.body.classList.toggle("timetable-wide-mode", state.timetableWide);
  updateTimetableViewControls();
  requestAnimationFrame(renderTimetable);
}

function updateTimetableFullscreenButton() {
  const active = document.fullscreenElement === $("#timetableView") || state.timetableFullscreenFallback;
  $("#timetableFullscreenButton").textContent = active ? "× Zamknij pełny ekran" : "⛶ Pełny ekran";
  $("#timetableFullscreenButton").classList.toggle("active", active);
}

async function toggleTimetableFullscreen() {
  const view = $("#timetableView");
  if (document.fullscreenElement === view) {
    await document.exitFullscreen();
    return;
  }
  if (state.timetableFullscreenFallback) {
    state.timetableFullscreenFallback = false;
    view.classList.remove("timetable-fullscreen-fallback");
    updateTimetableFullscreenButton();
    return;
  }
  try {
    if (!view.requestFullscreen) throw new Error("Fullscreen API unavailable");
    await view.requestFullscreen();
  } catch (_) {
    state.timetableFullscreenFallback = true;
    view.classList.add("timetable-fullscreen-fallback");
    updateTimetableFullscreenButton();
  }
}

function timetableDisplayHeight(durationValue, zoom = state.timetableZoom) {
  const duration = Math.max(0.5, Number(durationValue) || 0.5);
  const natural = (duration / 5) * zoom;
  if (zoom >= 90) return natural;
  const progress = Math.max(0, Math.min(1, (90 - zoom) / 54));
  const readabilityMinimum = 24 + (24 * progress);
  const proportionalBoost = progress * Math.min(16, natural * 0.35);
  return Math.max(natural + proportionalBoost, readabilityMinimum);
}

function timetableDisplayDurationMinutes(durationValue, zoom = state.timetableZoom) {
  return timetableDisplayHeight(durationValue, zoom) * 5 / zoom;
}

function scaleFullTimetableBlock(block, zoom = state.timetableZoom) {
  const duration = Number(block.dataset.durationMinutes) || 5;
  const minuteOffset = Number(block.dataset.minuteOffset) || 0;
  const height = timetableDisplayHeight(duration, zoom);
  block.style.height = `${height}px`;
  block.style.transform = `translateY(${(minuteOffset / 5) * zoom}px)`;
  block.classList.toggle("timetable-block-condensed", height < 48);
  block.classList.toggle("timetable-block-tiny", height < 26);
}

function renderTimetable() {
  const board = $("#timetableBoard");
  if (!board) return;
  const days = visibleTimetableDays();
  board.style.setProperty("--timetable-days", String(days.length));
  board.style.setProperty("--timetable-slot-height", `${state.timetableZoom}px`);
  board.style.setProperty("--timetable-hour-height", `${state.timetableZoom * 12}px`);
  board.style.setProperty("--timetable-compact-hour-height", `${state.timetableZoom * 4}px`);
  const fontScale = state.timetableZoom < 90
    ? 1 + ((90 - state.timetableZoom) / 54) * 0.16
    : 1 + Math.min(0.12, ((state.timetableZoom - 90) / 54) * 0.12);
  board.style.setProperty("--timetable-block-font-scale", fontScale.toFixed(3));
  board.style.minWidth = window.innerWidth <= 760 ? `${58 + (days.length * 220)}px` : "";
  $(".timetable-board-shell").style.setProperty("--timetable-viewport-height", `${state.timetableViewportHeight}vh`);
  board.classList.toggle("timetable-board-full", state.timetableDensity === "full");
  board.classList.toggle("timetable-board-compact", state.timetableDensity === "compact");
  [1, 3, 7].forEach(range => board.classList.toggle(`timetable-range-${range}`, state.timetableRange === range));
  updateTimetableViewControls();
  if (state.timetableDensity === "full") renderFullTimetable(board, days);
  else renderCompactTimetable(board, days);
  const scrollKey = `${state.timetableDensity}-${state.timetableRange}`;
  if (board.dataset.initialScroll !== scrollKey) {
    board.dataset.initialScroll = scrollKey;
    requestAnimationFrame(() => {
      const five = [...board.querySelectorAll(".timetable-hour")].find(item => item.textContent === "05:00");
      if (five) board.parentElement.scrollTop = Math.max(0, five.offsetTop - 46);
    });
  }
}

function updateTimetableEntryForm() {
  const isShow = $("#timetableEntryType").value === "show";
  $("#timetableShowField").classList.toggle("hidden", !isShow);
  $("#timetableShowRoleField").classList.toggle("hidden", !isShow);
  $("#timetableElementField").classList.toggle("hidden", isShow);
  $("#timetableCategoryField").classList.toggle("hidden", isShow);
  const isNewElement = !isShow && $("#timetableElement").value === "new";
  $("#timetableElementNameField").classList.toggle("hidden", !isNewElement);
  if (!isShow && !isNewElement) {
    const selected = state.timetable.items.find(item => item.id === Number($("#timetableElement").value));
    if (selected) $("#timetableCategory").value = selected.category;
  }
  if (isShow) {
    const show = state.timetable.shows.find(item => item.id === Number($("#timetableShow").value));
    if (show && !$("#timetableEntryId").value) $("#timetableDuration").value = String(show.duration_minutes || 45);
  }
  renderTimetableBulkOptions();
}

function timetableEditingEntry() {
  const id = Number($("#timetableEntryId").value);
  return id ? state.timetable.entries.find(entry => entry.id === id) : null;
}

function renderTimetableBulkOptions() {
  const entry = timetableEditingEntry();
  const isShow = $("#timetableEntryType").value === "show";
  $("#timetableShowSyncInfo").classList.toggle("hidden", !isShow);
  const panel = $("#timetableBulkOptions");
  const selectedItemId = Number($("#timetableElement").value);
  const candidates = entry && !isShow && selectedItemId === entry.item_id
    ? (state.timetable.entries || [])
      .filter(item => item.show_id == null && item.item_id === entry.item_id)
      .sort((a, b) => a.weekday - b.weekday || a.start_time.localeCompare(b.start_time) || a.id - b.id)
    : [];
  const visible = state.timetableUnlocked && candidates.length > 1;
  panel.classList.toggle("hidden", !visible);
  if (!visible) {
    $("#timetableBulkMinutes").replaceChildren();
    $("#timetableBulkDayChoices").replaceChildren();
    return;
  }
  const selectionKey = `${entry.id}:${selectedItemId}`;
  const currentMinute = Number(entry.start_time.slice(3, 5));
  if (state.timetableBulkEntryId !== selectionKey) {
    state.timetableBulkEntryId = selectionKey;
    state.timetableBulkMinutes = new Set([currentMinute]);
    state.timetableBulkDays = new Set([entry.weekday]);
  }
  const minuteGroups = [...new Set(candidates.map(candidate => Number(candidate.start_time.slice(3, 5))))].sort((a, b) => a - b);
  $("#timetableBulkAllTimes").checked = minuteGroups.length > 0
    && minuteGroups.every(minute => state.timetableBulkMinutes.has(minute));
  $("#timetableBulkMinutes").replaceChildren(...minuteGroups.map(minute => {
    const label = document.createElement("label");
    label.className = "timetable-bulk-entry";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = String(minute);
    input.checked = state.timetableBulkMinutes.has(minute);
    input.addEventListener("change", () => {
      if (input.checked) state.timetableBulkMinutes.add(minute);
      else state.timetableBulkMinutes.delete(minute);
      renderTimetableBulkOptions();
    });
    const text = document.createElement("span");
    const sameDayTimes = candidates
      .filter(candidate => candidate.weekday === entry.weekday && Number(candidate.start_time.slice(3, 5)) === minute)
      .map(candidate => candidate.start_time);
    const exampleTimes = (sameDayTimes.length ? sameDayTimes : candidates
      .filter(candidate => Number(candidate.start_time.slice(3, 5)) === minute)
      .map(candidate => candidate.start_time))
      .slice(0, 6);
    text.textContent = `:${String(minute).padStart(2, "0")} — ${exampleTimes.join(", ")}${exampleTimes.length === 6 ? "…" : ""}`;
    label.append(input, text);
    return label;
  }));
  $("#timetableBulkDayChoices").replaceChildren(...TIMETABLE_WEEKDAYS.map((day, weekday) => {
    const label = document.createElement("label");
    label.className = "timetable-bulk-entry";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = String(weekday);
    input.checked = state.timetableBulkDays.has(weekday);
    input.disabled = !candidates.some(candidate => candidate.weekday === weekday);
    input.addEventListener("change", () => {
      if (input.checked) state.timetableBulkDays.add(weekday);
      else state.timetableBulkDays.delete(weekday);
      renderTimetableBulkOptions();
    });
    const text = document.createElement("span");
    text.textContent = day;
    label.append(input, text);
    return label;
  }));
  const availableDays = new Set(candidates.map(candidate => candidate.weekday));
  $("#timetableBulkAllDays").checked = availableDays.size > 0
    && [...availableDays].every(day => state.timetableBulkDays.has(day));
  $("#timetableBulkTimesSummary").textContent = state.timetableBulkMinutes.size
    ? [...state.timetableBulkMinutes].sort((a, b) => a - b).map(value => `:${String(value).padStart(2, "0")}`).join(", ")
    : "— nic";
  $("#timetableBulkDaysSummary").textContent = state.timetableBulkDays.size
    ? [...state.timetableBulkDays].sort().map(day => TIMETABLE_WEEKDAYS[day].slice(0, 2)).join(", ")
    : "— nic";
  const selected = timetableSelectedBulkEntries(candidates);
  const affectedCount = new Set([entry.id, ...selected.map(item => item.id)]).size;
  $("#timetableBulkSelectionSummary").textContent = `Zmiana obejmie ${affectedCount} ${affectedCount === 1 ? "emisję" : "emisji"}.`;
}

function timetableSelectedBulkEntries(candidates = null) {
  const entry = timetableEditingEntry();
  const pool = candidates || (entry ? (state.timetable.entries || []).filter(item =>
    item.show_id == null && item.item_id === entry.item_id
  ) : []);
  return pool.filter(candidate =>
    state.timetableBulkMinutes.has(Number(candidate.start_time.slice(3, 5)))
    && state.timetableBulkDays.has(candidate.weekday)
  );
}

function selectTimetableBulkMinutes(scope, enabled = true) {
  const entry = timetableEditingEntry();
  const candidates = entry ? (state.timetable.entries || []).filter(item => item.show_id == null && item.item_id === entry.item_id) : [];
  state.timetableBulkMinutes = scope === "all"
    ? (enabled ? new Set(candidates.map(item => Number(item.start_time.slice(3, 5)))) : new Set())
    : new Set(entry ? [Number(entry.start_time.slice(3, 5))] : []);
  renderTimetableBulkOptions();
}

function selectTimetableBulkDays(scope, enabled = true) {
  const entry = timetableEditingEntry();
  const available = new Set(entry ? (state.timetable.entries || [])
    .filter(item => item.show_id == null && item.item_id === entry.item_id)
    .map(item => item.weekday) : []);
  const requested = scope === "all" ? [0, 1, 2, 3, 4, 5, 6]
    : scope === "workdays" ? [0, 1, 2, 3, 4]
      : scope === "weekend" ? [5, 6]
        : [entry?.weekday];
  state.timetableBulkDays = enabled ? new Set(requested.filter(day => available.has(day))) : new Set();
  renderTimetableBulkOptions();
}

function setTimetableFormReadOnly(readOnly) {
  $("#timetableEntryForm").querySelectorAll("input, select, textarea").forEach(control => {
    if (control.id !== "timetableEntryId") control.disabled = readOnly;
  });
  $("#saveTimetableEntry").classList.toggle("hidden", readOnly);
  $("#deleteTimetableEntry").classList.toggle("hidden", readOnly || !$("#timetableEntryId").value);
}

function openTimetableEntryDialog(entry = null, weekday = state.timetableDay, startTime = "08:00") {
  if (!entry && !state.timetableUnlocked) return handleLock();
  const elements = (state.timetable.items || []).filter(item => item.show_id == null);
  $("#timetableShow").replaceChildren(...(state.timetable.shows || []).map(show => new Option(show.name, String(show.id))));
  $("#timetableElement").replaceChildren(
    ...elements.map(item => new Option(`${item.name} — ${TIMETABLE_LAYERS.find(layer => layer.key === item.category)?.label || item.category}`, String(item.id))),
    new Option("+ Nowy typ pozycji", "new"),
  );
  $("#timetableEntryId").value = entry?.id || "";
  $("#timetableEntryTitle").textContent = entry ? (state.timetableUnlocked ? "Edytuj pozycję" : "Podgląd pozycji") : "Dodaj pozycję";
  const isShow = entry ? entry.show_id != null : false;
  $("#timetableEntryType").value = isShow ? "show" : "element";
  if (isShow && (entry?.show_id || state.timetable.shows?.[0]?.id)) {
    $("#timetableShow").value = String(entry?.show_id || state.timetable.shows[0].id);
  }
  $("#timetableShowRole").value = entry?.show_role || "main";
  if (!isShow && entry) $("#timetableElement").value = String(entry.item_id);
  $("#timetableElementName").value = "";
  $("#timetableCategory").value = entry?.category === "shows" ? "other" : (entry?.category || "other");
  $("#timetableWeekday").value = String(entry?.weekday ?? weekday);
  $("#timetableStartTime").value = entry?.start_time || startTime;
  const selectedShow = state.timetable.shows.find(item => item.id === Number($("#timetableShow").value));
  $("#timetableDuration").value = String(entry?.duration_minutes || selectedShow?.duration_minutes || 5);
  $("#timetableApproximate").checked = entry?.approximate || false;
  $("#timetableNote").value = entry?.note || "";
  state.timetableBulkEntryId = null;
  clearError("#timetableEntryError");
  updateTimetableEntryForm();
  setTimetableFormReadOnly(!state.timetableUnlocked);
  openModal($("#timetableEntryDialog"));
}

async function saveTimetableEntry(event) {
  event.preventDefault();
  if (!state.timetableUnlocked) return;
  clearError("#timetableEntryError");
  const isShow = $("#timetableEntryType").value === "show";
  const selectedItem = !isShow && $("#timetableElement").value !== "new"
    ? state.timetable.items.find(item => item.id === Number($("#timetableElement").value))
    : null;
  const normalizedTime = normalizeTime24($("#timetableStartTime").value);
  if (!normalizedTime) { showError("#timetableEntryError", "Wpisz godzinę jako HH:MM lub 1810"); return; }
  const duration = Number($("#timetableDuration").value);
  if (!Number.isFinite(duration) || duration < 0.5 || duration > 240 || Math.abs(duration * 2 - Math.round(duration * 2)) > 1e-9) {
    showError("#timetableEntryError", "Czas trwania musi wynosić od 0,5 do 240 minut, z dokładnością do pół minuty");
    return;
  }
  const payload = {
    item_id: selectedItem?.id || null,
    name: isShow ? "" : (selectedItem?.name || $("#timetableElementName").value),
    category: isShow ? "shows" : (selectedItem?.category || $("#timetableCategory").value),
    show_id: isShow ? Number($("#timetableShow").value) : null,
    show_role: isShow ? $("#timetableShowRole").value : "",
    weekday: Number($("#timetableWeekday").value),
    start_time: normalizedTime,
    duration_minutes: duration,
    approximate: $("#timetableApproximate").checked,
    note: $("#timetableNote").value,
    source: "manual",
  };
  const id = $("#timetableEntryId").value;
  try {
    const original = timetableEditingEntry();
    const bulkIds = !isShow && id
      ? timetableSelectedBulkEntries().filter(item => item.id !== Number(id)).map(item => item.id)
      : [];
    if (bulkIds.length && original) {
      const timeShift = timetableMinutes(normalizedTime) - timetableMinutes(original.start_time);
      const others = bulkIds.map(entryId => {
        const entry = state.timetable.entries.find(item => item.id === entryId);
        if (!entry) throw new Error("Nie znaleziono jednej z zaznaczonych emisji");
        const shiftedMinutes = timetableMinutes(entry.start_time) + timeShift;
        if (shiftedMinutes < 0 || shiftedMinutes >= 24 * 60) {
          throw new Error(`Przesunięcie emisji ${TIMETABLE_WEEKDAYS[entry.weekday]} ${entry.start_time} wykracza poza dobę`);
        }
        return {
          id: entry.id,
          ...timetableEntryPayload(entry, {
            start_time: timetableTimeFromMinutes(shiftedMinutes),
            duration_minutes: duration,
            approximate: payload.approximate,
          }),
        };
      });
      await api("/api/timetable/entries/bulk", {
        method: "PUT",
        body: JSON.stringify({ updates: [{ id: Number(id), ...payload }, ...others] }),
      });
      toast(`Zapisano pozycję i ${bulkIds.length} wybranych emisji`);
    } else {
      await api(id ? `/api/timetable/entries/${id}` : "/api/timetable/entries", {
        method: id ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      toast(id ? "Zapisano pozycję ramówki" : "Dodano pozycję ramówki");
    }
    $("#timetableEntryDialog").close();
    await loadTimetable();
  } catch (error) {
    if (error.message.includes("zablokowana")) setTimetableUnlocked(false);
    showError("#timetableEntryError", error);
  }
}

async function deleteTimetableEntry() {
  const id = Number($("#timetableEntryId").value);
  const entry = state.timetable.entries.find(item => item.id === id);
  if (!id || !entry || !confirm(`Usunąć z ramówki „${entry.name}”?`)) return;
  try {
    await api(`/api/timetable/entries/${id}`, { method: "DELETE" });
    $("#timetableEntryDialog").close();
    toast("Usunięto pozycję ramówki");
    await loadTimetable();
  } catch (error) { showError("#timetableEntryError", error); }
}

function changeTimetableDay(offset) {
  state.timetableDay = (state.timetableDay + offset + 7) % 7;
  $("#timetableDay").value = String(state.timetableDay);
  renderTimetable();
}

async function loadShows() {
  try {
    const payload = await api("/api/shows");
    state.shows = payload.items;
    $("#showsMeta").textContent = `${payload.items.length} audycji • ${payload.items.filter(item => item.active).length} aktywnych`;
    renderImportWarning(payload.import);
    renderShows();
  } catch (error) { toast(error.message); }
}

function renderShows() {
  const list = $("#showsList");
  if (!list || !state.shows) return;
  const query = $("#showSearch")?.value.trim().toLocaleLowerCase("pl") || "";
  const shows = state.shows.filter(item => `${item.name} ${item.folder_pattern} ${(item.filename_patterns || [item.filename_pattern]).join(" ")} ${(item.tags || []).join(" ")}`.toLocaleLowerCase("pl").includes(query));
  list.replaceChildren(...shows.map(show => {
    const row = document.createElement("article");
    row.className = `show-row viewable ${show.active ? "" : "inactive"} ${state.unlocked ? "editable" : ""}`;
    const title = document.createElement("div");
    title.className = "show-title";
    const strong = document.createElement("strong");
    strong.textContent = show.name;
    const small = document.createElement("small");
    small.textContent = show.active ? "Aktywna" : "Nieaktywna";
    title.append(strong, small);
    const tags = createTagList(show.tags || []);
    tags.classList.add("show-tags");
    const schedule = document.createElement("div");
    schedule.className = "show-schedule";
    const premiereSchedule = document.createElement("div");
    premiereSchedule.className = "show-schedule-premiere";
    if (show.premiere_slots?.length) {
      const premiereLines = show.premiere_slots.map((slot, index) => {
        const label = show.premiere_slots.length > 1 ? (slot.label || `Plan ${index + 1}`) : "Premiera";
        const days = slot.schedule_description || "brak dni";
        const times = slot.emission_times?.length ? slot.emission_times.join(", ") : "godzina nieustawiona";
        return `${label}: ${days} • ${times}`;
      });
      premiereSchedule.textContent = premiereLines.join("\n");
    } else {
      premiereSchedule.textContent = show.repeats?.length ? "Brak premiery" : "Brak emisji";
    }
    if ((show.filename_patterns || []).length > 1) {
      premiereSchedule.textContent += ` • ${(show.filename_patterns || []).length} części`;
    }
    schedule.append(premiereSchedule);
    (show.repeats || []).forEach((repeat, index) => {
      const repeatSchedule = document.createElement("div");
      repeatSchedule.className = "show-schedule-repeat";
      const label = repeat.label || `Powtórka ${index + 1}`;
      const times = repeat.emission_times?.length
        ? repeat.emission_times.join(", ")
        : "godzina nieustawiona";
      const rule = repeat.schedule_description ? ` • ${repeat.schedule_description}` : "";
      repeatSchedule.textContent = `${label}: ${times}${rule}`;
      schedule.append(repeatSchedule);
    });
    const durationSummary = document.createElement("div");
    durationSummary.className = "show-schedule-duration";
    const expectedDuration = timetableDurationLabel(show.duration_minutes);
    const maximumDuration = show.max_duration_minutes == null
      ? "bez limitu"
      : timetableDurationLabel(show.max_duration_minutes);
    durationSummary.textContent = `Czas: oczekiwany ${expectedDuration} • maksymalny ${maximumDuration}`;
    schedule.append(durationSummary);
    const time = document.createElement("div");
    time.className = "show-time";
    time.textContent = show.emission_time || "—";
    const actions = document.createElement("div");
    actions.className = "row-actions";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "edit-row-button";
    edit.textContent = state.unlocked ? "Edytuj" : "Podgląd";
    edit.addEventListener("click", event => { event.stopPropagation(); openShowDialog(show); });
    actions.append(edit);
    row.append(title, tags, schedule, time, actions);
    row.addEventListener("click", () => openShowDialog(show));
    return row;
  }));
}

function openShowDialog(show = null) {
  if (!show && !state.unlocked) return handleLock();
  state.viewOnly = !state.unlocked;
  $("#showId").value = show?.id || "";
  $("#showName").value = show?.name || "";
  $("#showDuration").value = String(show?.duration_minutes || 45);
  $("#showMaxDuration").value = show?.max_duration_minutes ?? "";
  $("#showActive").checked = show?.active ?? true;
  $("#showEditing").checked = show?.requires_editing ?? false;
  state.productionWatchFolders = structuredClone(show?.production_watch_folders || []);
  $("#showFtp").checked = show?.is_ftp ?? false;
  $("#showYoutube").checked = show?.has_youtube_version ?? false;
  $("#showSendAuthor").checked = show?.send_to_author ?? false;
  $("#showAutoArchive").checked = show?.auto_archive ?? false;
  $("#authorEmail").value = show?.author_email || "";
  $("#ftpSourcePath").value = show?.ftp_source_path || "";
  $("#ftpAutoSync").checked = show?.ftp_auto_sync ?? false;
  $("#ftpRenameEnabled").checked = show?.ftp_rename_enabled ?? false;
  $("#folderPattern").value = show?.folder_pattern || "";
  $("#filenamePattern").value = show?.filename_pattern || "";
  state.additionalFilePatterns = structuredClone(show?.filename_patterns?.slice(1) || []);
  state.ftpSourcePatterns = structuredClone(show?.ftp_source_patterns || []);
  state.premiereSlots = show
    ? structuredClone(show.premiere_slots || [])
    : [defaultEmissionSlot(0)];
  state.repeats = structuredClone(show?.repeats || []);
  $("#showDialogEyebrow").textContent = state.viewOnly ? "Podgląd audycji" : (show ? "Edycja audycji" : "Nowa audycja");
  $("#showDialogTitle").textContent = show?.name || "Dodaj audycję";
  $("#deleteShowButton").classList.toggle("hidden", !show || state.viewOnly);
  $("#saveShowButton").classList.toggle("hidden", state.viewOnly);
  $("#cancelShowButton").textContent = state.viewOnly ? "Zamknij" : "Anuluj";
  clearError("#showError");
  renderPremiereSlots();
  renderRepeats();
  renderAdditionalFilePatterns();
  updateProductionMonitoringSection();
  updateFtpSection();
  updateAuthorSection();
  updatePreview();
  $("#showForm").classList.toggle("view-only", state.viewOnly);
  $$("#showForm input, #showForm select, #showForm textarea").forEach(control => control.disabled = state.viewOnly);
  $$("#showForm button:not([data-close-dialog]):not(.ftp-operation-button)").forEach(button => button.disabled = state.viewOnly);
  openModal($("#showDialog"));
  loadFtpStatus();
}

function stableShowFolderPath() {
  const parts = $("#folderPattern").value.replaceAll("\\", "/").split("/").filter(Boolean);
  const stable = [];
  for (const part of parts) {
    if (part.includes("%")) break;
    stable.push(part);
  }
  return stable.join("/");
}

function renderFtpSourcePatterns() {
  const expected = 1 + state.additionalFilePatterns.length;
  while (state.ftpSourcePatterns.length < expected) state.ftpSourcePatterns.push("");
  if (state.ftpSourcePatterns.length > expected) state.ftpSourcePatterns.length = expected;
  const container = $("#ftpSourcePatterns");
  container.replaceChildren(...state.ftpSourcePatterns.map((pattern, index) => {
    const field = document.createElement("label");
    field.className = "field";
    const caption = document.createElement("span");
    caption.textContent = `Schemat źródłowy FTP — część ${index + 1}`;
    const input = document.createElement("input");
    input.type = "text";
    input.required = $("#showFtp").checked && $("#ftpRenameEnabled").checked;
    input.value = pattern;
    input.placeholder = index ? `Nazwa źródłowa części ${index + 1}` : "np. %Y%m_nazwa_(%d-1).mp3";
    input.disabled = state.viewOnly;
    input.addEventListener("input", () => state.ftpSourcePatterns[index] = input.value);
    field.append(caption, input);
    return field;
  }));
}

function renderFtpSourceStatus(sources = []) {
  const container = $("#ftpSourceStatus");
  if (!$("#ftpRenameEnabled").checked) {
    container.replaceChildren();
    return;
  }
  if (!sources.length) {
    const empty = document.createElement("div");
    empty.className = "mini-empty";
    empty.textContent = $("#showId").value ? "Brak skonfigurowanych schematów źródłowych." : "Zapisz audycję, aby sprawdzić pliki źródłowe.";
    container.replaceChildren(empty);
    return;
  }
  container.replaceChildren(...sources.map(source => {
    const line = document.createElement("div");
    line.className = `ftp-status-line ${source.found ? "found" : "missing"}`;
    const mark = document.createElement("strong");
    mark.textContent = source.found ? "✓" : "!";
    const label = document.createElement("span");
    label.textContent = `Źródło ${source.part_number}`;
    const path = document.createElement("code");
    path.textContent = `/AUDYCJE/${source.relative_path}`;
    path.title = path.textContent;
    line.append(mark, label, path);
    return line;
  }));
}

function updateFtpSection() {
  const enabled = $("#showFtp").checked;
  const renameEnabled = enabled && $("#ftpRenameEnabled").checked;
  $("#ftpSection").classList.toggle("hidden", !enabled);
  $("#ftpSourcePatternsBlock").classList.toggle("hidden", !renameEnabled);
  const destination = stableShowFolderPath();
  $("#ftpDestinationPreview").textContent = destination ? `/AUDYCJE/${destination}` : "/AUDYCJE";
  renderFtpSourcePatterns();
  if (!renameEnabled) renderFtpSourceStatus();
  const saved = Boolean($("#showId").value);
  $("#ftpSyncNowButton").disabled = !saved || !$("#ftpSourcePath").value.trim();
  $("#ftpRenameNowButton").classList.toggle("hidden", !renameEnabled);
  $("#ftpRenameNowButton").disabled = !saved;
  $("#ftpRenameNowButton").textContent = "Przemianuj";
  $("#ftpRenameNowButton").classList.remove("renamed");
}

function updateAuthorSection() {
  const enabled = $("#showSendAuthor").checked;
  $("#authorEmailField").classList.toggle("hidden", !enabled);
  $("#authorEmail").required = enabled;
}

async function loadFtpStatus() {
  if (!$("#showDialog").open || !$("#showFtp").checked || !$("#showId").value) return;
  clearError("#ftpError");
  try {
    const result = await api(`/api/ftp/status?show_id=${encodeURIComponent($("#showId").value)}&date=${localIso(state.selectedDate)}`);
    renderFtpSourceStatus(result.sources || []);
    $("#ftpRenameNowButton").textContent = result.renamed ? "✓ Przemianowane" : "Przemianuj";
    $("#ftpRenameNowButton").classList.toggle("renamed", result.renamed);
    $("#ftpRenameNowButton").disabled = result.renamed || !result.can_rename;
  } catch (error) {
    showError("#ftpError", error);
  }
}

function weekdayChips(selected, onChange) {
  const labels = ["Pn", "Wt", "Śr", "Cz", "Pt", "Sb", "Nd"];
  const wrapper = document.createElement("div");
  wrapper.className = "chip-list";
  labels.forEach((label, index) => {
    const item = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = selected.includes(index);
    input.addEventListener("change", () => onChange(index, input.checked));
    const span = document.createElement("span");
    span.textContent = label;
    item.append(input, span);
    wrapper.append(item);
  });
  return wrapper;
}

function toggleArray(array, value, checked) {
  const result = [...array].filter(item => item !== value);
  if (checked) result.push(value);
  return result.sort((a, b) => a - b);
}

function normalizeTime24(value) {
  let candidate = String(value).trim();
  if (/^\d{3,4}$/.test(candidate)) {
    candidate = `${candidate.slice(0, -2)}:${candidate.slice(-2)}`;
  }
  const match = /^(\d{1,2}):(\d{2})$/.exec(candidate);
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour > 23 || minute > 59) return null;
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function renderTimesEditor(times, onChange) {
  const wrapper = document.createElement("div");
  wrapper.className = "times-editor";
  const list = document.createElement("div");
  list.className = "time-chip-list";
  (times || []).forEach((value, index) => {
    const chip = document.createElement("div");
    chip.className = "time-chip";
    const input = document.createElement("input");
    input.type = "text";
    input.inputMode = "numeric";
    input.placeholder = "HH:MM";
    input.pattern = "(?:[0-2]?[0-9]:[0-5][0-9]|[0-9]{3,4})";
    input.value = value;
    input.addEventListener("change", () => {
      const normalized = normalizeTime24(input.value);
      input.setCustomValidity(input.value.trim() && !normalized ? "Wpisz godzinę jako HH:MM lub 1810" : "");
      if (input.value.trim() && !normalized) { input.reportValidity(); return; }
      input.value = normalized || "";
      times[index] = normalized || "";
      onChange([...new Set(times.filter(Boolean))].sort());
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.title = "Usuń godzinę";
    remove.addEventListener("click", () => {
      times.splice(index, 1);
      onChange(times);
    });
    chip.append(input, remove);
    list.append(chip);
  });
  const add = document.createElement("button");
  add.type = "button";
  add.className = "secondary-button compact-button";
  add.textContent = "+ godzina";
  add.addEventListener("click", () => {
    times.push("");
    onChange(times);
  });
  wrapper.append(list, add);
  return wrapper;
}

function defaultEmissionSlot(index = state.premiereSlots.length) {
  return {
    id: repeatId(),
    label: `Plan ${index + 1}`,
    emission_times: [""],
    schedule: [{ type: "weekly", weekdays: [] }],
  };
}

function renderPremiereSlots() {
  const container = $("#premiereSlots");
  container.replaceChildren(...state.premiereSlots.map((slot, index) => renderPremiereSlot(slot, index)));
  $("#noPremiereSlots").classList.toggle("hidden", state.premiereSlots.length > 0);
  enforceInactiveWithoutSchedule();
}

function renderPremiereSlot(slot, index) {
  slot.schedule ||= [];
  slot.emission_times ||= slot.emission_time ? [slot.emission_time] : [];
  const card = document.createElement("article");
  card.className = "emission-slot-card";
  const header = document.createElement("div");
  header.className = "emission-slot-header";
  const title = document.createElement("strong");
  title.textContent = `Plan premierowy ${index + 1}`;
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "rule-remove";
  remove.textContent = "×";
  remove.title = "Usuń plan";
  remove.addEventListener("click", () => { state.premiereSlots.splice(index, 1); renderPremiereSlots(); });
  header.append(title, remove);

  const timeBlock = document.createElement("div");
  timeBlock.className = "slot-block";
  const timeLabel = document.createElement("span");
  timeLabel.className = "compact-label";
  timeLabel.textContent = "Godziny emisji";
  const renderTimes = () => {
    const editor = renderTimesEditor(slot.emission_times, values => {
      slot.emission_times = values;
      renderPremiereSlots();
    });
    timeBlock.replaceChildren(timeLabel, editor);
  };
  renderTimes();

  const ruleHeader = document.createElement("div");
  ruleHeader.className = "compact-section-header";
  const ruleLabel = document.createElement("span");
  ruleLabel.className = "compact-label";
  ruleLabel.textContent = "Dni emisji";
  const addRule = document.createElement("button");
  addRule.type = "button";
  addRule.className = "secondary-button compact-button";
  addRule.textContent = "+ reguła";
  addRule.addEventListener("click", () => { slot.schedule.push(defaultRule("weekly")); renderPremiereSlots(); });
  ruleHeader.append(ruleLabel, addRule);
  const rules = document.createElement("div");
  rules.className = "schedule-rules compact-rules";
  rules.replaceChildren(...slot.schedule.map((rule, ruleIndex) => renderRule(rule, ruleIndex, slot.schedule, renderPremiereSlots)));
  card.append(header, timeBlock, ruleHeader, rules);
  return card;
}

function renderRule(rule, index, rules, rerender) {
  const row = document.createElement("div");
  row.className = "schedule-rule";
  const select = document.createElement("select");
  select.className = "rule-select";
  [
    ["weekly", "Co tydzień"], ["nth_month", "Wybrane tygodnie miesiąca"],
    ["iso_week_parity", "Parzyste / nieparzyste tygodnie"], ["dates", "Konkretne daty"],
  ].forEach(([value, label]) => select.add(new Option(label, value)));
  select.value = rule.type;
  select.addEventListener("change", () => {
    rules[index] = defaultRule(select.value);
    rerender();
  });
  const controls = document.createElement("div");
  controls.className = "rule-controls";
  if (rule.type !== "dates") {
    controls.append(weekdayChips(rule.weekdays || [], (day, checked) => {
      rule.weekdays = toggleArray(rule.weekdays || [], day, checked);
    }));
  }
  if (rule.type === "nth_month") {
    const sub = document.createElement("div");
    sub.className = "sub-controls";
    sub.append(document.createTextNode("Wystąpienie w miesiącu:"));
    const chips = document.createElement("div");
    chips.className = "chip-list";
    [1,2,3,4,5].forEach(number => {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = (rule.occurrences || []).includes(number);
      input.addEventListener("change", () => rule.occurrences = toggleArray(rule.occurrences || [], number, input.checked));
      const span = document.createElement("span"); span.textContent = `${number}.`; label.append(input, span); chips.append(label);
    });
    sub.append(chips); controls.append(sub);
  } else if (rule.type === "iso_week_parity") {
    const sub = document.createElement("div"); sub.className = "sub-controls";
    const parity = document.createElement("select"); parity.className = "rule-select";
    parity.add(new Option("Parzyste tygodnie ISO", "even")); parity.add(new Option("Nieparzyste tygodnie ISO", "odd"));
    parity.value = rule.parity || "even"; parity.addEventListener("change", () => rule.parity = parity.value);
    sub.append(parity); controls.append(sub);
  } else if (rule.type === "dates") {
    const sub = document.createElement("div"); sub.className = "sub-controls";
    const picker = document.createElement("input"); picker.type = "date";
    const add = document.createElement("button"); add.className = "secondary-button"; add.type = "button"; add.textContent = "Dodaj datę";
    add.addEventListener("click", () => { if (picker.value && !rule.dates.includes(picker.value)) { rule.dates.push(picker.value); rule.dates.sort(); rerender(); } });
    sub.append(picker, add); controls.append(sub);
    const dates = document.createElement("div"); dates.className = "dates-list";
    (rule.dates || []).forEach(date => {
      const pill = document.createElement("span"); pill.className = "date-pill"; pill.textContent = formatDate(dateFromIso(date));
      const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "×";
      remove.addEventListener("click", () => { rule.dates = rule.dates.filter(item => item !== date); rerender(); });
      pill.append(remove); dates.append(pill);
    });
    controls.append(dates);
  }
  const remove = document.createElement("button"); remove.type = "button"; remove.className = "rule-remove"; remove.textContent = "×"; remove.title = "Usuń regułę";
  remove.addEventListener("click", () => { rules.splice(index, 1); rerender(); });
  row.append(select, controls, remove);
  return row;
}

function defaultRule(type) {
  if (type === "dates") return { type, dates: [] };
  if (type === "nth_month") return { type, weekdays: [], occurrences: [1] };
  if (type === "iso_week_parity") return { type, weekdays: [], parity: "even" };
  return { type: "weekly", weekdays: [] };
}

function repeatId() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  return `repeat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function settingsId(prefix) {
  if (globalThis.crypto?.randomUUID) return `${prefix}-${crypto.randomUUID()}`;
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function defaultPushoverRecipient() {
  return {
    id: settingsId("recipient"),
    label: `Odbiorca ${state.notificationSettings.recipients.length + 1}`,
    app_token: "",
    user_key: "",
    device: "",
    enabled: true,
    production_folder_notifications: false,
  };
}

async function openSettings() {
  try {
    const status = await api("/api/settings/status");
    if (!status.unlocked) {
      $("#settingsPassword").value = "";
      clearError("#settingsUnlockError");
      openModal($("#settingsUnlockDialog"));
      setTimeout(() => $("#settingsPassword").focus(), 30);
      return;
    }
    await loadNotificationSettings();
  } catch (error) { toast(error.message); }
}

async function unlockSettings(event) {
  event.preventDefault();
  clearError("#settingsUnlockError");
  try {
    await api("/api/settings/unlock", {
      method: "POST",
      body: JSON.stringify({ password: $("#settingsPassword").value }),
    });
    $("#settingsUnlockDialog").close();
    await loadNotificationSettings();
  } catch (error) { showError("#settingsUnlockError", error); }
}

async function loadNotificationSettings() {
  const [settings, delivery, maintenance, windowsPaths, zetta] = await Promise.all([
    api("/api/settings/notifications"),
    api("/api/settings/delivery"),
    api("/api/settings/file-maintenance"),
    api("/api/settings/windows-paths"),
    api("/api/settings/zetta"),
  ]);
  state.notificationSettings = structuredClone(settings);
  state.deliverySettings = structuredClone(delivery);
  state.fileMaintenanceSettings = structuredClone(maintenance);
  state.windowsPathSettings = structuredClone(windowsPaths);
  state.zettaSettings = structuredClone(zetta);
  if (!state.notificationSettings.recipients.length) {
    state.notificationSettings.recipients.push(defaultPushoverRecipient());
  }
  clearError("#settingsError");
  renderNotificationSettings();
  renderDeliverySettings();
  renderFileMaintenanceSettings();
  renderWindowsPathSettings();
  renderZettaSettings();
  openModal($("#settingsDialog"));
  if (state.deliverySettings.google_calendar_access) {
    loadGoogleCalendars().catch(error => showError("#settingsError", error));
  }
}

function renderDeliverySettings() {
  const config = state.deliverySettings || {};
  $("#googleClientId").value = config.google_client_id || "";
  $("#googleClientSecret").value = "";
  $("#googleClientSecret").placeholder = config.google_client_secret_set
    ? "Zapisany — pozostaw puste, aby nie zmieniać"
    : "Wklej Client Secret";
  $("#calendarClientId").value = config.calendar_client_id || "";
  $("#calendarClientSecret").value = "";
  $("#calendarClientSecret").placeholder = config.calendar_client_secret_set
    ? "Zapisany — pozostaw puste, aby nie zmieniać"
    : "Wklej Client Secret klienta Web application";
  $("#calendarRedirectUri").value = config.calendar_redirect_uri || "https://sprawdzacz-oauth.soundcode.pl/";
  $("#driveRootName").value = config.drive_root_folder_name || "Emaus Hub";
  $("#driveRetentionDays").value = String(config.retention_days || 30);
  $("#smtpHost").value = config.smtp_host || "";
  $("#smtpPort").value = String(config.smtp_port || 587);
  $("#smtpSecurity").value = config.smtp_security || "starttls";
  $("#smtpUsername").value = config.smtp_username || "";
  $("#smtpPassword").value = "";
  $("#smtpPassword").placeholder = config.smtp_password_set
    ? "Zapisane — pozostaw puste, aby nie zmieniać"
    : "Hasło lub hasło aplikacji";
  $("#smtpFromEmail").value = config.smtp_from_email || "";
  $("#smtpFromName").value = config.smtp_from_name || "Radio Emaus";
  $("#googleStatus").textContent = config.google_connected
    ? `Google: połączony${config.google_connected_email ? ` jako ${config.google_connected_email}` : ""}`
    : "Google: niepołączony";
  $("#googleConnectButton").textContent = "Połącz Google Drive";
  $("#googleConnectButton").classList.toggle("hidden", Boolean(config.google_connected));
  $("#googleDisconnectButton").classList.toggle("hidden", !config.google_connected);
  if (config.google_connected) $("#googleDeviceFlow").classList.add("hidden");
  $("#calendarGoogleStatus").textContent = config.calendar_connected
    ? `Kalendarz: połączony${config.calendar_connected_email ? ` jako ${config.calendar_connected_email}` : ""}`
    : "Kalendarz: niepołączony";
  $("#calendarConnectButton").classList.toggle("hidden", Boolean(config.calendar_connected));
  $("#calendarDisconnectButton").classList.toggle("hidden", !config.calendar_connected);
  if (!config.google_calendar_access) state.googleCalendars = [];
  renderGoogleCalendarOptions();
}

function renderGoogleCalendarOptions() {
  const config = state.deliverySettings || {};
  const select = $("#googleCalendarId");
  select.replaceChildren();
  if (!config.google_calendar_access) {
    select.add(new Option("Najpierw połącz konto Kalendarza", ""));
    select.disabled = true;
    $("#googleCalendarsRefresh").disabled = true;
    $("#googleCalendarStatus").textContent = "Grafik: konto Kalendarza niepołączone";
    return;
  }
  const calendars = state.googleCalendars || [];
  if (!calendars.length && config.calendar_id) {
    const saved = new Option(config.calendar_name || "Zapisany kalendarz", config.calendar_id);
    saved.dataset.name = config.calendar_name || "";
    saved.dataset.accessRole = config.calendar_access_role || "";
    select.add(saved);
  } else if (!calendars.length) {
    select.add(new Option("Odśwież listę kalendarzy", ""));
  } else {
    calendars.forEach(calendar => {
      const suffix = calendar.writable ? "zapis" : "tylko odczyt";
      const primary = calendar.primary ? " · główny" : "";
      const option = new Option(`${calendar.name}${primary} (${suffix})`, calendar.id);
      option.dataset.name = calendar.name;
      option.dataset.accessRole = calendar.access_role;
      select.add(option);
    });
  }
  if (config.calendar_id && [...select.options].some(option => option.value === config.calendar_id)) {
    select.value = config.calendar_id;
  } else if (calendars.length) {
    const primary = calendars.find(calendar => calendar.primary) || calendars[0];
    select.value = primary.id;
  }
  select.disabled = false;
  $("#googleCalendarsRefresh").disabled = false;
  updateGoogleCalendarSelectionStatus();
}

function updateGoogleCalendarSelectionStatus() {
  const config = state.deliverySettings || {};
  const select = $("#googleCalendarId");
  const selected = select.selectedOptions[0];
  const role = selected?.dataset.accessRole || config.calendar_access_role || "";
  const writable = ["owner", "writer", "writerWithoutPrivateAccess"].includes(role);
  $("#googleCalendarStatus").textContent = select.value
    ? `Grafik: ${selected?.dataset.name || config.calendar_name || "wybrany kalendarz"}${writable ? " · edycja dostępna" : " · tylko odczyt"}`
    : "Grafik: wybierz kalendarz";
}

async function loadGoogleCalendars() {
  const button = $("#googleCalendarsRefresh");
  button.disabled = true;
  button.textContent = "Pobieram…";
  clearError("#settingsError");
  try {
    const result = await api("/api/settings/delivery/calendars");
    state.googleCalendars = result.calendars || [];
    renderGoogleCalendarOptions();
  } finally {
    button.textContent = "Odśwież listę";
    button.disabled = !state.deliverySettings.google_calendar_access;
  }
}

function deliveryPayload() {
  const calendarOption = $("#googleCalendarId").selectedOptions[0];
  return {
    google_client_id: $("#googleClientId").value,
    google_client_secret: $("#googleClientSecret").value,
    calendar_client_id: $("#calendarClientId").value,
    calendar_client_secret: $("#calendarClientSecret").value,
    calendar_redirect_uri: $("#calendarRedirectUri").value,
    drive_root_folder_name: $("#driveRootName").value,
    retention_days: Number($("#driveRetentionDays").value),
    calendar_id: $("#googleCalendarId").value,
    calendar_name: calendarOption?.dataset.name || state.deliverySettings.calendar_name || "",
    calendar_access_role: calendarOption?.dataset.accessRole || state.deliverySettings.calendar_access_role || "",
    smtp_host: $("#smtpHost").value,
    smtp_port: Number($("#smtpPort").value),
    smtp_security: $("#smtpSecurity").value,
    smtp_username: $("#smtpUsername").value,
    smtp_password: $("#smtpPassword").value,
    smtp_from_email: $("#smtpFromEmail").value,
    smtp_from_name: $("#smtpFromName").value,
  };
}

function renderFileMaintenanceSettings() {
  const config = state.fileMaintenanceSettings || {};
  $("#archiveAfterDays").value = String(config.archive_after_days || 30);
  $("#productionDeleteAfterDays").value = String(config.production_delete_after_days || 30);
}

function renderWindowsPathSettings() {
  const mappings = state.windowsPathSettings?.mappings || {};
  $("#windowsPathMedia").value = mappings.media || "";
  $("#windowsPathArchive").value = mappings.archive || "";
  $("#windowsPathEmaus").value = mappings.emaus || "";
  $("#windowsPathEmausContact").value = mappings.emaus_contact || "";
}

function renderZettaSettings() {
  const config = state.zettaSettings || {};
  $("#zettaUrl").value = config.url || "https://emaus-zetta-srv.swdm.local/Zetta2GO/Zetta/Go";
  $("#zettaStationId").value = config.station_id || "3658ac9a-335e-4839-ac18-2159ba1e4a16";
  $("#zettaUsername").value = config.username || "";
  $("#zettaPassword").value = "";
  $("#zettaPassword").placeholder = config.password_set
    ? "Zapisane — pozostaw puste, aby nie zmieniać"
    : "Wpisz hasło";
  $("#zettaStatus").textContent = config.configured
    ? "Zetta2GO: skonfigurowane"
    : "Zetta2GO: nieskonfigurowane";
}

async function saveFileMaintenanceSettings() {
  const saved = await api("/api/settings/file-maintenance", {
    method: "PUT",
    body: JSON.stringify({
      archive_after_days: Number($("#archiveAfterDays").value),
      production_delete_after_days: Number($("#productionDeleteAfterDays").value),
    }),
  });
  state.fileMaintenanceSettings = structuredClone(saved);
  return saved;
}

async function saveWindowsPathSettings() {
  const saved = await api("/api/settings/windows-paths", {
    method: "PUT",
    body: JSON.stringify({
      mappings: {
        media: $("#windowsPathMedia").value,
        archive: $("#windowsPathArchive").value,
        emaus: $("#windowsPathEmaus").value,
        emaus_contact: $("#windowsPathEmausContact").value,
      },
    }),
  });
  state.windowsPathSettings = structuredClone(saved);
  return saved;
}

async function saveZettaSettings() {
  const saved = await api("/api/settings/zetta", {
    method: "PUT",
    body: JSON.stringify({
      url: $("#zettaUrl").value,
      station_id: $("#zettaStationId").value,
      username: $("#zettaUsername").value,
      password: $("#zettaPassword").value,
    }),
  });
  state.zettaSettings = structuredClone(saved);
  renderZettaSettings();
  return saved;
}

async function testZettaConnection() {
  const button = $("#zettaTestButton");
  button.disabled = true;
  button.textContent = "Łączę…";
  clearError("#settingsError");
  try {
    await saveZettaSettings();
    const result = await api("/api/settings/zetta/test", { method: "POST" });
    $("#zettaStatus").textContent = `Zetta2GO: połączenie działa · ${result.row_count} poz. w bieżącej godzinie`;
    toast("Połączenie z Zetta2GO działa");
  } catch (error) { showError("#settingsError", error); }
  finally { button.disabled = false; button.textContent = "Test połączenia"; }
}

async function saveDeliverySettings() {
  const saved = await api("/api/settings/delivery", {
    method: "PUT",
    body: JSON.stringify(deliveryPayload()),
  });
  state.deliverySettings = structuredClone(saved);
  return saved;
}

async function connectGoogle() {
  const button = $("#googleConnectButton");
  button.disabled = true;
  clearError("#settingsError");
  try {
    await saveDeliverySettings();
    const flow = await api("/api/settings/delivery/google/start", { method: "POST" });
    state.googleFlowId = flow.flow_id;
    $("#googleUserCode").textContent = flow.user_code;
    $("#googleVerificationLink").href = flow.verification_url || "https://www.google.com/device";
    $("#googleDeviceFlow").classList.remove("hidden");
    toast("Otwórz Google, wpisz kod i zatwierdź dostęp");
  } catch (error) { showError("#settingsError", error); }
  finally { button.disabled = false; }
}

async function checkGoogleConnection() {
  if (!state.googleFlowId) return;
  const button = $("#googleCheckButton");
  button.disabled = true;
  button.textContent = "Sprawdzam…";
  clearError("#settingsError");
  try {
    const result = await api("/api/settings/delivery/google/poll", {
      method: "POST",
      body: JSON.stringify({ flow_id: state.googleFlowId }),
    });
    if (result.connected) {
      state.googleFlowId = null;
      state.deliverySettings = await api("/api/settings/delivery");
      renderDeliverySettings();
      toast("Połączono Google Drive");
    } else {
      toast("Google czeka na zatwierdzenie kodu");
    }
  } catch (error) { showError("#settingsError", error); }
  finally { button.disabled = false; button.textContent = "Sprawdź połączenie"; }
}

async function disconnectGoogle() {
  if (!confirm("Odłączyć konto Google? Istniejące foldery, pliki i wydarzenia nie zostaną usunięte.")) return;
  clearError("#settingsError");
  try {
    await api("/api/settings/delivery/google/disconnect", { method: "POST" });
    state.deliverySettings = await api("/api/settings/delivery");
    state.googleCalendars = [];
    renderDeliverySettings();
    toast("Odłączono konto Google");
  } catch (error) { showError("#settingsError", error); }
}

async function connectCalendarGoogle() {
  const button = $("#calendarConnectButton");
  button.disabled = true;
  clearError("#settingsError");
  try {
    await saveDeliverySettings();
    const flow = await api("/api/settings/delivery/calendar/start", { method: "POST" });
    state.calendarOauthState = flow.state;
    $("#calendarReturnedValue").value = "";
    $("#calendarOauthFinish").classList.remove("hidden");
    window.open(flow.authorization_url, "_blank", "noopener");
    toast("Zaloguj konto Kalendarza, a potem wklej adres strony końcowej");
  } catch (error) { showError("#settingsError", error); }
  finally { button.disabled = false; }
}

async function finishCalendarGoogle() {
  const button = $("#calendarFinishButton");
  button.disabled = true;
  clearError("#settingsError");
  try {
    await api("/api/settings/delivery/calendar/finish", {
      method: "POST",
      body: JSON.stringify({
        state: state.calendarOauthState,
        returned_value: $("#calendarReturnedValue").value,
      }),
    });
    state.calendarOauthState = null;
    state.deliverySettings = await api("/api/settings/delivery");
    $("#calendarOauthFinish").classList.add("hidden");
    renderDeliverySettings();
    await loadGoogleCalendars();
    toast("Połączono osobne konto Kalendarza");
  } catch (error) { showError("#settingsError", error); }
  finally { button.disabled = false; }
}

async function disconnectCalendarGoogle() {
  if (!confirm("Odłączyć konto Kalendarza? Wydarzenia nie zostaną usunięte.")) return;
  try {
    await api("/api/settings/delivery/calendar/disconnect", { method: "POST" });
    state.deliverySettings = await api("/api/settings/delivery");
    state.googleCalendars = [];
    renderDeliverySettings();
    toast("Odłączono konto Kalendarza");
  } catch (error) { showError("#settingsError", error); }
}

async function testDeliverySmtp() {
  const button = $("#smtpTestButton");
  button.disabled = true;
  button.textContent = "Wysyłam…";
  clearError("#settingsError");
  try {
    await saveDeliverySettings();
    await api("/api/settings/delivery/smtp/test", { method: "POST" });
    toast("Wiadomość testowa SMTP została wysłana");
  } catch (error) { showError("#settingsError", error); }
  finally { button.disabled = false; button.textContent = "Wyślij test SMTP do nadawcy"; }
}

function settingField(captionText, value, onInput, type = "text") {
  const label = document.createElement("label");
  label.className = "field";
  const caption = document.createElement("span");
  caption.textContent = captionText;
  const input = document.createElement("input");
  input.type = type;
  input.value = value || "";
  input.addEventListener("input", () => onInput(input.value));
  label.append(caption, input);
  return label;
}

function renderNotificationSettings() {
  const recipients = $("#pushoverRecipients");
  recipients.replaceChildren(...state.notificationSettings.recipients.map((recipient, index) => {
    const card = document.createElement("article");
    card.className = "settings-card";
    const header = document.createElement("div");
    header.className = "settings-card-header";
    const title = document.createElement("strong");
    title.textContent = recipient.label || `Odbiorca ${index + 1}`;
    const enabled = document.createElement("label");
    enabled.className = "toggle-field compact-toggle";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = recipient.enabled;
    checkbox.addEventListener("change", () => recipient.enabled = checkbox.checked);
    const enabledText = document.createElement("span");
    enabledText.textContent = "Aktywny";
    enabled.append(checkbox, enabledText);
    header.append(title, enabled);

    const fields = document.createElement("div");
    fields.className = "form-grid settings-fields";
    const name = settingField("Nazwa", recipient.label, value => {
      recipient.label = value;
      title.textContent = value || `Odbiorca ${index + 1}`;
    });
    const device = settingField("Urządzenie (opcjonalnie)", recipient.device, value => recipient.device = value);
    const token = settingField("Application API Token", recipient.app_token, value => recipient.app_token = value, "password");
    const user = settingField("User/Group Key", recipient.user_key, value => recipient.user_key = value, "password");
    token.classList.add("span-2");
    user.classList.add("span-2");
    fields.append(name, device, token, user);

    const productionNotifications = document.createElement("label");
    productionNotifications.className = "toggle-field settings-recipient-option";
    const productionCheckbox = document.createElement("input");
    productionCheckbox.type = "checkbox";
    productionCheckbox.checked = Boolean(recipient.production_folder_notifications);
    productionCheckbox.addEventListener("change", () => {
      recipient.production_folder_notifications = productionCheckbox.checked;
    });
    const productionText = document.createElement("span");
    productionText.textContent = "Informuj o zmianach w folderach produkcji";
    productionNotifications.append(productionCheckbox, productionText);

    const actions = document.createElement("div");
    actions.className = "settings-card-actions";
    const test = document.createElement("button");
    test.type = "button";
    test.className = "secondary-button";
    test.textContent = "Wyślij test";
    test.addEventListener("click", async () => {
      test.disabled = true;
      test.textContent = "Wysyłam…";
      clearError("#settingsError");
      try {
        await api("/api/settings/pushover/test", { method: "POST", body: JSON.stringify(recipient) });
        toast(`Wysłano test: ${recipient.label || `Odbiorca ${index + 1}`}`);
      } catch (error) { showError("#settingsError", error); }
      finally { test.disabled = false; test.textContent = "Wyślij test"; }
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger-button";
    remove.textContent = "Usuń";
    remove.addEventListener("click", () => {
      state.notificationSettings.recipients.splice(index, 1);
      renderNotificationSettings();
    });
    actions.append(test, remove);
    card.append(header, fields, productionNotifications, actions);
    return card;
  }));

  const rules = $("#notificationRules");
  rules.replaceChildren(...state.notificationSettings.rules.map((rule, index) => renderNotificationRule(rule, index)));
  $("#noNotificationRules").classList.toggle("hidden", state.notificationSettings.rules.length > 0);
}

function leadUnit(minutes) {
  if (minutes % 1440 === 0) return { unit: "days", factor: 1440, value: minutes / 1440 };
  if (minutes % 60 === 0) return { unit: "hours", factor: 60, value: minutes / 60 };
  return { unit: "minutes", factor: 1, value: minutes };
}

function renderNotificationRule(rule, index) {
  const card = document.createElement("article");
  card.className = "notification-rule-card";
  const phrase = document.createElement("span");
  phrase.textContent = "Jeśli brakuje audycji, powiadom";
  const current = leadUnit(rule.lead_minutes);
  const number = document.createElement("input");
  number.type = "number";
  number.min = "1";
  number.max = "43200";
  number.value = String(current.value);
  const unit = document.createElement("select");
  unit.add(new Option("minut", "minutes"));
  unit.add(new Option("godzin", "hours"));
  unit.add(new Option("dni", "days"));
  unit.value = current.unit;
  const updateLead = () => {
    const factors = { minutes: 1, hours: 60, days: 1440 };
    rule.lead_minutes = Math.max(1, Number(number.value || 1)) * factors[unit.value];
  };
  number.addEventListener("input", updateLead);
  unit.addEventListener("change", updateLead);
  const suffix = document.createElement("span");
  suffix.textContent = "przed emisją";
  const enabled = document.createElement("label");
  enabled.className = "toggle-field compact-toggle";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = rule.enabled;
  checkbox.addEventListener("change", () => rule.enabled = checkbox.checked);
  const enabledText = document.createElement("span");
  enabledText.textContent = "Aktywne";
  enabled.append(checkbox, enabledText);
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "rule-remove";
  remove.textContent = "×";
  remove.title = "Usuń powiadomienie";
  remove.addEventListener("click", () => {
    state.notificationSettings.rules.splice(index, 1);
    renderNotificationSettings();
  });
  card.append(phrase, number, unit, suffix, enabled, remove);
  return card;
}

async function saveNotificationSettings(event) {
  event.preventDefault();
  clearError("#settingsError");
  try {
    const [saved] = await Promise.all([
      api("/api/settings/notifications", {
        method: "PUT",
        body: JSON.stringify(state.notificationSettings),
      }),
      saveDeliverySettings(),
      saveFileMaintenanceSettings(),
      saveWindowsPathSettings(),
      saveZettaSettings(),
    ]);
    state.notificationSettings = structuredClone(saved);
    $("#settingsDialog").close();
    toast("Zapisano ustawienia");
    if ($("#calendarView").classList.contains("active")) {
      state.calendarAutoScrolled = false;
      loadCalendar();
    }
  } catch (error) {
    if (error.message.includes("zablokowane")) $("#settingsDialog").close();
    else showError("#settingsError", error);
  }
}

async function lockNotificationSettings() {
  await api("/api/settings/lock", { method: "POST" });
  $("#settingsDialog").close();
  toast("Ustawienia zablokowane");
}

function renderAdditionalFilePatterns() {
  const container = $("#additionalFilePatterns");
  container.replaceChildren(...state.additionalFilePatterns.map((pattern, index) => {
    const field = document.createElement("label");
    field.className = "field pattern-row";
    const caption = document.createElement("span");
    caption.textContent = `Schemat nazwy pliku — część ${index + 2}`;
    const controls = document.createElement("div");
    controls.className = "input-with-remove";
    const input = document.createElement("input");
    input.type = "text";
    input.required = true;
    input.value = pattern;
    input.placeholder = `Schemat części ${index + 2}`;
    input.addEventListener("input", () => state.additionalFilePatterns[index] = input.value);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "rule-remove";
    remove.textContent = "×";
    remove.title = "Usuń część";
    remove.addEventListener("click", () => {
      state.additionalFilePatterns.splice(index, 1);
      state.ftpSourcePatterns.splice(index + 1, 1);
      state.repeats.forEach(repeat => repeat.filename_patterns?.splice(index + 1, 1));
      renderAdditionalFilePatterns();
      updateFtpSection();
      renderRepeats();
    });
    controls.append(input, remove);
    field.append(caption, controls);
    return field;
  }));
}

function renderProductionWatchFolders() {
  const container = $("#productionWatchFolders");
  container.replaceChildren(...state.productionWatchFolders.map((folder, index) => {
    const source = productionFolderSource(folder);
    const field = document.createElement("div");
    field.className = "field pattern-row";
    const caption = document.createElement("span");
    caption.textContent = `Monitorowany folder ${index + 1}`;
    const controls = document.createElement("div");
    controls.className = "production-folder-row";
    const rootSelect = document.createElement("select");
    rootSelect.className = "production-root-select";
    rootSelect.title = "Źródło monitorowanego folderu";
    FILE_ROOTS.forEach(root => {
      const option = document.createElement("option");
      option.value = root.key;
      option.textContent = root.label;
      rootSelect.append(option);
    });
    rootSelect.value = source.root;
    rootSelect.disabled = state.viewOnly;
    rootSelect.addEventListener("change", () => {
      source.root = rootSelect.value;
      state.productionWatchFolders[index] = productionFolderValue(source);
    });
    const input = document.createElement("input");
    input.type = "text";
    input.value = source.path;
    input.placeholder = "np. Do montażu/Audycja";
    input.disabled = state.viewOnly;
    input.addEventListener("input", () => {
      source.path = input.value;
      state.productionWatchFolders[index] = productionFolderValue(source);
    });
    const browseButton = document.createElement("button");
    browseButton.type = "button";
    browseButton.className = "secondary-button compact-button";
    browseButton.textContent = "Wybierz";
    browseButton.disabled = state.viewOnly;
    browseButton.addEventListener("click", () => {
      state.productionBrowseIndex = index;
      openBrowser("production-folder");
    });
    const autoDelete = document.createElement("label");
    autoDelete.className = "production-auto-delete";
    const autoDeleteText = document.createElement("span");
    autoDeleteText.textContent = "Autokasowanie";
    const autoDeleteCheckbox = document.createElement("input");
    autoDeleteCheckbox.type = "checkbox";
    autoDeleteCheckbox.checked = source.auto_delete;
    autoDeleteCheckbox.disabled = state.viewOnly;
    autoDeleteCheckbox.title = "Kasuj pliki z tego folderu po czasie ustawionym w Ustawieniach";
    autoDeleteCheckbox.addEventListener("change", () => {
      source.auto_delete = autoDeleteCheckbox.checked;
      state.productionWatchFolders[index] = productionFolderValue(source);
    });
    autoDelete.append(autoDeleteText, autoDeleteCheckbox);
    const openFolder = document.createElement("button");
    openFolder.type = "button";
    openFolder.className = "production-folder-button";
    openFolder.textContent = "📁";
    openFolder.title = "Otwórz monitorowany folder";
    openFolder.disabled = !source.path;
    openFolder.addEventListener("click", () => openProductionFolder(source));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "rule-remove";
    remove.textContent = "×";
    remove.title = "Usuń monitorowany folder";
    remove.disabled = state.viewOnly;
    remove.addEventListener("click", () => {
      state.productionWatchFolders.splice(index, 1);
      renderProductionWatchFolders();
    });
    controls.append(rootSelect, input, autoDelete, openFolder, browseButton, remove);
    field.append(caption, controls);
    return field;
  }));
  $("#noProductionWatchFolders").classList.toggle("hidden", state.productionWatchFolders.length > 0);
}

function updateProductionMonitoringSection() {
  const enabled = $("#showEditing").checked;
  $("#productionMonitoringSection").classList.toggle("hidden", !enabled);
  renderProductionWatchFolders();
}

function enforceInactiveWithoutSchedule() {
  const hasEmission = state.premiereSlots.some(slot => (slot.schedule || []).length > 0)
    || state.repeats.some(repeat => (repeat.schedule || []).length > 0);
  $("#showActive").title = hasEmission ? "" : "Po zapisaniu audycja bez emisji zostanie ustawiona jako nieaktywna";
}

function renderRepeats() {
  const list = $("#repeatsList");
  list.replaceChildren(...state.repeats.map((repeat, index) => renderRepeat(repeat, index)));
  $("#noRepeats").classList.toggle("hidden", state.repeats.length > 0);
  enforceInactiveWithoutSchedule();
}

function renderRepeat(repeat, index) {
  repeat.schedule ||= [];
  repeat.emission_times ||= repeat.emission_time ? [repeat.emission_time] : [];
  repeat.filename_patterns ||= [repeat.filename_pattern || $("#filenamePattern").value, ...state.additionalFilePatterns];
  const expectedParts = 1 + state.additionalFilePatterns.length;
  while (repeat.filename_patterns.length < expectedParts) repeat.filename_patterns.push("");
  if (repeat.filename_patterns.length > expectedParts) repeat.filename_patterns.length = expectedParts;
  const card = document.createElement("article");
  card.className = "repeat-card";

  const header = document.createElement("div");
  header.className = "repeat-card-header";
  const heading = document.createElement("div");
  const eyebrow = document.createElement("span");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = `Powtórka ${index + 1}`;
  const label = document.createElement("input");
  label.className = "repeat-label";
  label.type = "text";
  label.value = repeat.label || `Powtórka ${index + 1}`;
  label.setAttribute("aria-label", "Nazwa powtórki");
  label.addEventListener("input", () => repeat.label = label.value);
  heading.append(eyebrow, label);
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "danger-button repeat-remove";
  remove.textContent = "Usuń powtórkę";
  remove.addEventListener("click", () => { state.repeats.splice(index, 1); renderRepeats(); });
  header.append(heading, remove);

  const fields = document.createElement("div");
  fields.className = "form-grid repeat-fields";
  const timeField = document.createElement("div");
  timeField.className = "field";
  const timeCaption = document.createElement("span");
  timeCaption.textContent = "Godziny emisji powtórki";
  timeField.append(timeCaption, renderTimesEditor(repeat.emission_times, values => {
    repeat.emission_times = values;
    repeat.emission_time = values[0] || null;
    renderRepeats();
  }));

  const folderField = document.createElement("label");
  folderField.className = "field";
  const folderCaption = document.createElement("span");
  folderCaption.textContent = "Folder powtórki";
  const folder = document.createElement("input");
  folder.type = "text";
  folder.value = repeat.folder_pattern ?? $("#folderPattern").value;
  folder.addEventListener("input", () => repeat.folder_pattern = folder.value);
  folderField.append(folderCaption, folder);

  fields.append(timeField, folderField);
  repeat.filename_patterns.forEach((pattern, partIndex) => {
    const filenameField = document.createElement("label");
    filenameField.className = "field span-2";
    const filenameCaption = document.createElement("span");
    filenameCaption.textContent = `Schemat powtórki — część ${partIndex + 1}`;
    const filename = document.createElement("input");
    filename.type = "text";
    filename.required = true;
    filename.value = pattern;
    filename.addEventListener("input", () => {
      repeat.filename_patterns[partIndex] = filename.value;
      repeat.filename_pattern = repeat.filename_patterns[0];
    });
    filenameField.append(filenameCaption, filename);
    fields.append(filenameField);
  });

  const scheduleHeader = document.createElement("div");
  scheduleHeader.className = "repeat-schedule-header";
  const scheduleTitle = document.createElement("h4");
  scheduleTitle.textContent = "Harmonogram powtórki";
  const addRule = document.createElement("button");
  addRule.type = "button";
  addRule.className = "secondary-button";
  addRule.textContent = "Dodaj regułę";
  addRule.addEventListener("click", () => { repeat.schedule.push(defaultRule("weekly")); renderRepeats(); });
  scheduleHeader.append(scheduleTitle, addRule);
  const rules = document.createElement("div");
  rules.className = "schedule-rules";
  rules.replaceChildren(...repeat.schedule.map((rule, ruleIndex) => renderRule(rule, ruleIndex, repeat.schedule, renderRepeats)));
  if (!repeat.schedule.length) {
    const empty = document.createElement("div");
    empty.className = "mini-empty";
    empty.textContent = "Brak harmonogramu tej powtórki.";
    rules.append(empty);
  }
  card.append(header, fields, scheduleHeader, rules);
  return card;
}

async function updatePreview() {
  clearTimeout(state.previewTimer);
  state.previewTimer = setTimeout(async () => {
    const folder = $("#folderPattern").value;
    const filename = $("#filenamePattern").value;
    $("#previewDateLabel").textContent = formatDate(state.selectedDate);
    if (!filename) { $("#pathPreview").textContent = "—"; return; }
    try {
      const result = await api("/api/pattern/preview", { method: "POST", body: JSON.stringify({ folder_pattern: folder, filename_pattern: filename, date: localIso(state.selectedDate) }) });
      $("#pathPreview").textContent = `/AUDYCJE/${result.path}`;
    } catch (error) { $("#pathPreview").textContent = error.message; }
  }, 180);
}

async function saveShow(event) {
  event.preventDefault();
  if (state.viewOnly || !state.unlocked) return;
  clearError("#showError");
  const id = $("#showId").value;
  const maxDurationValue = $("#showMaxDuration").value.trim();
  const payload = {
    name: $("#showName").value,
    duration_minutes: Number($("#showDuration").value),
    max_duration_minutes: maxDurationValue ? Number(maxDurationValue) : null,
    active: $("#showActive").checked,
    requires_editing: $("#showEditing").checked,
    production_watch_folders: state.productionWatchFolders,
    auto_archive: $("#showAutoArchive").checked,
    is_ftp: $("#showFtp").checked,
    ftp_source_path: $("#ftpSourcePath").value,
    ftp_auto_sync: $("#ftpAutoSync").checked,
    ftp_rename_enabled: $("#ftpRenameEnabled").checked,
    ftp_source_patterns: state.ftpSourcePatterns,
    has_youtube_version: $("#showYoutube").checked,
    send_to_author: $("#showSendAuthor").checked,
    author_email: $("#authorEmail").value,
    folder_pattern: $("#folderPattern").value,
    filename_pattern: $("#filenamePattern").value,
    filename_patterns: [$("#filenamePattern").value, ...state.additionalFilePatterns],
    premiere_slots: state.premiereSlots,
    repeats: state.repeats,
  };
  try {
    const result = await api(id ? `/api/shows/${id}` : "/api/shows", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) });
    $("#showDialog").close();
    toast(result.pattern_template_warning || (id ? "Zapisano zmiany" : "Dodano audycję"), result.pattern_template_warning ? 7000 : 2800);
    await Promise.all([loadShows(), loadTimetable(), loadReport()]);
  } catch (error) {
    if (error.message.includes("zablokowana")) { setUnlocked(false); $("#showDialog").close(); }
    else showError("#showError", error);
  }
}

async function deleteShow() {
  const id = $("#showId").value;
  const name = $("#showName").value;
  const folder = $("#folderPattern").value || "(brak folderu)";
  const ftpNote = $("#showFtp").checked ? "\nAutomatyczne zadanie FTP zostanie trwale usunięte." : "";
  if (!id || !confirm(
    `Usunąć audycję „${name}”?\n\n` +
    `Cały dedykowany folder /AUDYCJE/${folder} zostanie wcześniej przeniesiony do Archiwum.${ftpNote}`
  )) return;
  try {
    const result = await api(`/api/shows/${id}`, { method: "DELETE" });
    $("#showDialog").close();
    const archived = result.archive?.status === "moved"
      ? ` Folder: ${result.archive.target} (${result.archive.files} plików).`
      : result.archive?.status === "missing"
        ? " Folder źródłowy nie istniał."
        : " Audycja nie miała osobnego folderu do przeniesienia.";
    toast(`Usunięto audycję.${archived}`, 7000);
    await Promise.all([loadShows(), loadTimetable()]);
  } catch (error) { showError("#showError", error); }
}

async function loadFileFavorites() {
  const result = await api("/api/files/favorites");
  state.fileFavorites = result.items || [];
  return state.fileFavorites;
}

async function loadPublicWindowsPathSettings() {
  const result = await api("/api/files/windows-paths");
  state.windowsPathSettings = structuredClone(result);
  return result;
}

function isFileFavorite(root, path) {
  return state.fileFavorites.some(item => item.root === root && item.path === path);
}

async function toggleFolderFavorite(event, root, path, reload) {
  event.preventDefault();
  event.stopPropagation();
  try {
    const result = await api("/api/files/favorites/toggle", {
      method: "POST",
      body: JSON.stringify({ root, path }),
    });
    state.fileFavorites = result.items || [];
    toast(result.favorite ? "Dodano folder do ulubionych" : "Usunięto folder z ulubionych");
    await reload();
  } catch (error) {
    toast(error.message, 6000);
  }
}

function favoriteFolderLabel(item) {
  const parent = item.path.split("/").slice(0, -1).join("/");
  return parent ? `${item.root_label}/${parent}` : item.root_label;
}

async function showBrowserFavorites() {
  try {
    await loadFileFavorites();
    state.browserFavoritesMode = true;
    state.browserFavoriteBase = null;
    state.browserRoot = "favorites";
    state.browserPath = "";
    $("#fileRootButton").textContent = "Ulubione";
    $("#browserPath").textContent = "";
    updateBrowserRootShortcuts();
    updateBrowserActions();
    const rows = state.fileFavorites.map(item => fileItem(
      "▸",
      item.name,
      () => {
        state.browserFavoritesMode = false;
        state.browserRoot = item.root;
        state.browserFavoriteBase = { root: item.root, path: item.path };
        browse(item.path);
      },
      false,
      null,
      {
        subtitle: favoriteFolderLabel(item),
        root: item.root,
        entry: { type: "directory", name: item.name, path: item.path, windows_path: item.windows_path },
        favorite: true,
        reload: showBrowserFavorites,
      },
    ));
    $("#fileList").replaceChildren(...rows);
    if (!rows.length) $("#fileList").append(fileItem("★", "Brak ulubionych folderów", null, true));
  } catch (error) {
    showError("#browserError", error);
  }
}

async function showListenFavorites() {
  clearError("#listenBrowserError");
  try {
    await loadFileFavorites();
    state.listenFavoritesMode = true;
    state.listenFavoriteBase = null;
    state.listenBrowserRoot = "favorites";
    state.listenBrowserPath = "";
    $("#listenBrowserRootButton").textContent = "Ulubione";
    $("#listenBrowserPath").textContent = "";
    updateListenBrowserRoots();
    const rows = state.fileFavorites.map(item => fileItem(
      "▸",
      item.name,
      () => {
        state.listenFavoritesMode = false;
        state.listenBrowserRoot = item.root;
        state.listenFavoriteBase = { root: item.root, path: item.path };
        loadListenBrowser(item.path);
      },
      false,
      null,
      {
        subtitle: favoriteFolderLabel(item),
        root: item.root,
        entry: { type: "directory", name: item.name, path: item.path, windows_path: item.windows_path },
        favorite: true,
        reload: showListenFavorites,
      },
    ));
    $("#listenBrowserList").replaceChildren(...rows);
    if (!rows.length) $("#listenBrowserList").append(fileItem("★", "Brak ulubionych folderów", null, true));
  } catch (error) {
    showError("#listenBrowserError", error);
  }
}

async function openBrowser(mode) {
  state.browserMode = mode;
  state.browserFavoritesMode = false;
  state.browserFavoriteBase = null;
  const productionSource = mode === "production-folder"
    ? productionFolderSource(state.productionWatchFolders[state.productionBrowseIndex])
    : (mode === "production-view" ? state.productionViewSource : null);
  state.browserRoot = productionSource?.root || "media";
  state.browserPath = mode === "ftp"
    ? ($("#ftpSourcePath").value.trim() || "/")
    : (productionSource
      ? productionSource.path
      : (mode === "folder" || mode === "file"
        ? stableShowFolderPath()
        : (mode === "substitute" ? (state.substituteItem?.source_browse_path || "") : "")));
  $("#fileDialogTitle").textContent = mode === "ftp" ? "Wybierz folder na FTP" : (mode === "production-folder" ? "Wybierz monitorowany folder" : (mode === "production-view" ? "Folder produkcyjny" : (mode === "folder" ? "Wybierz folder" : (mode === "substitute" ? "Wybierz pliki powtórki" : "Wybierz przykładowy plik"))));
  $("#cancelFileDialog").textContent = mode === "production-view" ? "Zamknij" : "Anuluj";
  $("#fileRootButton").textContent = mode === "ftp" ? "FTP" : fileRootLabel(state.browserRoot);
  $("#browserToolbar").classList.toggle("hidden", mode === "ftp");
  updateBrowserRootShortcuts();
  updateBrowserActions();
  $("#confirmSubstitute").classList.add("hidden");
  renderSubstituteSelection();
  $("#newFolderForm").classList.add("hidden");
  $("#newFolderName").value = "";
  state.newFolderParent = null;
  clearError("#browserError");
  openFileBrowserDialog();
  await browse(state.browserPath);
}

async function browse(path) {
  try {
    const endpoint = state.browserMode === "ftp" ? "/api/ftp/directories" : "/api/files";
    const rootQuery = state.browserMode === "ftp"
      ? ""
      : `&root=${encodeURIComponent(state.browserRoot)}&sort=${encodeURIComponent(state.browserSort)}`;
    const payload = await api(`${endpoint}?path=${encodeURIComponent(path)}${rootQuery}`);
    state.browserFavoritesMode = false;
    state.browserPath = payload.path;
    $("#fileRootButton").textContent = state.browserMode === "ftp" ? "FTP" : fileRootLabel(state.browserRoot);
    $("#browserPath").textContent = payload.path;
    updateBrowserRootShortcuts();
    updateBrowserActions();
    const list = $("#fileList");
    const rows = [];
    const durationJobs = [];
    const atFavoriteBase = state.browserFavoriteBase
      && state.browserFavoriteBase.root === state.browserRoot
      && state.browserFavoriteBase.path === payload.path;
    if (atFavoriteBase) rows.push(fileItem("↰", "Ulubione", showBrowserFavorites));
    else if (payload.parent !== null) rows.push(fileItem("↰", "..", () => browse(payload.parent)));
    sortBrowserEntries(payload.entries || []).forEach(entry => {
      const reload = () => browse(state.browserPath);
      if (entry.type === "directory") {
        rows.push(state.browserMode === "ftp"
          ? fileItem("▸", entry.name, () => browse(entry.path))
          : fileItem(
            "▸", entry.name, () => browse(entry.path), false, null,
            {
              root: state.browserRoot,
              entry,
              favorite: isFileFavorite(state.browserRoot, entry.path),
              reload,
            },
          ));
      }
      else if (["file", "substitute", "production-view"].includes(state.browserMode) && entry.audio) {
        const root = state.browserRoot;
        const choose = state.browserMode === "production-view"
          ? () => playAudio(root, entry.path, entry.name, { browser: true })
          : state.browserMode === "file" && root !== "media"
          ? () => playAudio(root, entry.path, entry.name, { browser: true })
          : () => chooseFile(entry.path);
        const row = fileItem(
          "♪", entry.name, choose, false,
          () => playAudio(root, entry.path, entry.name, { browser: true }),
          { root, entry, reload },
        );
        rows.push(row);
        durationJobs.push({ row, root, path: entry.path });
      }
      else if (["file", "substitute", "production-view"].includes(state.browserMode)) rows.push(fileItem(
        "·", entry.name, null, true, null,
        { root: state.browserRoot, entry, reload },
      ));
    });
    list.replaceChildren(...rows);
    durationJobs.forEach(job => scheduleBrowserDuration(job.row, job.root, job.path));
  } catch (error) { showError("#browserError", error); }
}

function sortBrowserEntries(entries, sort = state.browserSort) {
  const direction = sort === "oldest" ? 1 : -1;
  return [...entries].sort((left, right) => {
    const typeOrder = Number(left.type !== "directory") - Number(right.type !== "directory");
    if (typeOrder) return typeOrder;
    if (sort !== "name") {
      const leftTime = Date.parse(left.modified_at || "") || 0;
      const rightTime = Date.parse(right.modified_at || "") || 0;
      if (leftTime !== rightTime) return (leftTime - rightTime) * direction;
    }
    return left.name.localeCompare(right.name, "pl", { sensitivity: "base", numeric: true });
  });
}

async function loadListenBrowser(path = state.listenBrowserPath) {
  clearError("#listenBrowserError");
  updateListenBrowserRoots();
  $("#listenBrowserRootButton").textContent = fileRootLabel(state.listenBrowserRoot);
  try {
    const payload = await api(
      `/api/files?path=${encodeURIComponent(path)}&root=${encodeURIComponent(state.listenBrowserRoot)}&sort=${encodeURIComponent(state.listenBrowserSort)}`,
    );
    state.listenFavoritesMode = false;
    state.listenBrowserPath = payload.path;
    $("#listenBrowserRootButton").textContent = fileRootLabel(state.listenBrowserRoot);
    $("#listenBrowserPath").textContent = payload.path;
    updateListenBrowserRoots();
    const rows = [];
    const durationJobs = [];
    const atFavoriteBase = state.listenFavoriteBase
      && state.listenFavoriteBase.root === state.listenBrowserRoot
      && state.listenFavoriteBase.path === payload.path;
    if (atFavoriteBase) {
      rows.push(fileItem("↰", "Ulubione", showListenFavorites));
    } else if (payload.parent !== null) {
      rows.push(fileItem("↰", "..", () => loadListenBrowser(payload.parent)));
    }
    sortBrowserEntries(payload.entries || [], state.listenBrowserSort).forEach(entry => {
      const reload = () => loadListenBrowser(state.listenBrowserPath);
      if (entry.type === "directory") {
        rows.push(fileItem(
          "▸", entry.name, () => loadListenBrowser(entry.path), false, null,
          {
            root: state.listenBrowserRoot,
            entry,
            favorite: isFileFavorite(state.listenBrowserRoot, entry.path),
            reload,
          },
        ));
      } else if (entry.audio) {
        const root = state.listenBrowserRoot;
        const row = fileItem(
          "♪",
          entry.name,
          () => playAudio(root, entry.path, entry.name, { browser: true }),
          false,
          () => playAudio(root, entry.path, entry.name, { browser: true }),
          { root, entry, reload },
        );
        rows.push(row);
        durationJobs.push({ row, root, path: entry.path });
      } else {
        rows.push(fileItem(
          "·", entry.name, null, true, null,
          { root: state.listenBrowserRoot, entry, reload },
        ));
      }
    });
    $("#listenBrowserList").replaceChildren(...rows);
    durationJobs.forEach(job => scheduleBrowserDuration(job.row, job.root, job.path));
  } catch (error) {
    $("#listenBrowserList").replaceChildren();
    showError("#listenBrowserError", error);
  }
}

function updateListenBrowserRoots() {
  $$("#listenBrowserRootShortcuts [data-listen-root]").forEach(button => {
    const favoritesActive = state.listenFavoritesMode || state.listenFavoriteBase;
    button.classList.toggle(
      "active",
      button.dataset.listenRoot === "favorites"
        ? Boolean(favoritesActive)
        : (!favoritesActive && button.dataset.listenRoot === state.listenBrowserRoot),
    );
  });
}

function chooseListenBrowserRoot(root) {
  if (root === "favorites") return showListenFavorites();
  state.listenFavoritesMode = false;
  state.listenFavoriteBase = null;
  state.listenBrowserRoot = root;
  state.listenBrowserPath = "";
  loadListenBrowser("");
}

function fileItem(icon, name, handler, muted = false, playHandler = null, options = {}) {
  const row = document.createElement("div");
  row.className = "file-item-row";
  const button = document.createElement("button"); button.type = "button"; button.className = `file-item ${muted ? "muted" : ""}`;
  const iconElement = document.createElement("span"); iconElement.textContent = icon;
  const copy = document.createElement("span"); copy.className = "file-item-copy";
  const label = document.createElement("span"); label.textContent = name;
  copy.append(label);
  if (options.subtitle) {
    const subtitle = document.createElement("small"); subtitle.textContent = options.subtitle;
    copy.append(subtitle);
  }
  button.append(iconElement, copy); if (handler) button.addEventListener("click", handler);
  row.append(button);
  if (playHandler || options.entry?.type === "directory" || options.entry?.windows_path) {
    const actions = document.createElement("div");
    actions.className = "browser-file-actions";
    if (options.entry?.type === "file" && !isAndroidClient()) {
      const dragHandle = document.createElement("span");
      dragHandle.className = "browser-drag-handle";
      dragHandle.textContent = "⋮⋮";
      prepareBrowserFileDrag(dragHandle, options.root, options.entry);
      actions.append(dragHandle);
    }
    if (options.entry?.type === "directory") {
      const favorite = document.createElement("button");
      favorite.type = "button";
      favorite.className = `browser-favorite-button${options.favorite ? " active" : ""}`;
      favorite.textContent = options.favorite ? "★" : "☆";
      favorite.title = options.favorite ? "Usuń folder z ulubionych" : "Dodaj folder do ulubionych";
      favorite.addEventListener("click", event => toggleFolderFavorite(
        event, options.root, options.entry.path, options.reload,
      ));
      actions.append(favorite);
    }
    if (playHandler) {
      const time = document.createElement("span");
      time.className = "browser-file-duration";
      time.textContent = "…";
      time.title = "Wczytywanie czasu trwania";
      actions.append(time);
      const play = document.createElement("button");
      play.type = "button";
      play.className = "browser-play-button";
      play.textContent = "▶";
      play.title = `Odtwórz ${name}`;
      play.addEventListener("click", playHandler);
      actions.append(play);
    }
    row.append(actions);
  }
  if (options.entry && options.root) {
    row.addEventListener("contextmenu", event => showFileContextMenu(
      event, row, options.root, options.entry, options.reload,
    ));
  }
  return row;
}

function closeFileContextMenu() {
  document.querySelector(".file-context-menu")?.remove();
}

function addCreateFolderContextAction(menu, parentPath) {
  const createFolder = document.createElement("button");
  createFolder.type = "button";
  createFolder.textContent = "Nowy folder tutaj";
  createFolder.addEventListener("click", () => {
    closeFileContextMenu();
    openNewFolderForm(parentPath);
  });
  menu.append(createFolder);
}

function placeFileContextMenu(menu, event, host) {
  host.append(menu);
  menu.style.left = `${Math.max(8, Math.min(event.clientX, window.innerWidth - 230))}px`;
  menu.style.top = `${Math.max(8, Math.min(event.clientY, window.innerHeight - menu.offsetHeight - 8))}px`;
  setTimeout(() => document.addEventListener("pointerdown", pointerEvent => {
    if (!menu.contains(pointerEvent.target)) closeFileContextMenu();
  }, { once: true }), 0);
}

function showFileContextMenu(event, row, root, entry, reload) {
  event.preventDefault();
  event.stopPropagation();
  closeFileContextMenu();
  const menu = document.createElement("div");
  menu.className = "file-context-menu";
  if (entry.windows_path && !isAndroidClient()) {
    const explorer = document.createElement("button");
    explorer.type = "button";
    explorer.textContent = "Kopiuj ścieżkę Windows";
    explorer.addEventListener("click", () => {
      closeFileContextMenu();
      copyWindowsPath(root, entry.path);
    });
    menu.append(explorer);
  }
  const properties = document.createElement("button");
  properties.type = "button";
  properties.textContent = "Właściwości";
  properties.addEventListener("click", () => {
    closeFileContextMenu();
    openFileProperties(root, entry.path);
  });
  menu.append(properties);
  if (root === "media" && state.unlocked && state.browserMode !== "ftp" && row.closest("#fileDialog")) {
    addCreateFolderContextAction(
      menu,
      entry.type === "directory" ? entry.path : state.browserPath,
    );
  }
  if (entry.type === "file") {
    const rename = document.createElement("button");
    rename.type = "button";
    rename.textContent = state.unlocked ? "Zmień nazwę" : "Zmień nazwę — odblokuj edycję";
    rename.disabled = !state.unlocked;
    if (state.unlocked) rename.addEventListener("click", () => {
      closeFileContextMenu();
      openRenameFile(root, entry, reload);
    });
    menu.append(rename);
    if (root === "media" && state.unlocked) {
      const archive = document.createElement("button");
      archive.type = "button";
      archive.textContent = "Archiwizuj teraz";
      archive.addEventListener("click", () => {
        closeFileContextMenu();
        archiveFileNow(root, entry, reload);
      });
      menu.append(archive);
    }
  }
  const host = row.closest("dialog[open]") || document.body;
  placeFileContextMenu(menu, event, host);
}

function showCurrentFolderContextMenu(event) {
  if (event.target.closest(".file-item-row")) return;
  if (
    state.browserMode === "ftp"
    || state.browserFavoritesMode
    || state.browserRoot !== "media"
    || !state.unlocked
  ) return;
  event.preventDefault();
  event.stopPropagation();
  closeFileContextMenu();
  const menu = document.createElement("div");
  menu.className = "file-context-menu";
  addCreateFolderContextAction(menu, state.browserPath);
  placeFileContextMenu(menu, event, $("#fileDialog"));
}

async function archiveFileNow(root, entry, reload) {
  if (!confirm(
    `Przenieść teraz „${entry.name}” z AUDYCJE do Archiwum?\n\n` +
    "Ta operacja pomija ustawiony czas autoarchiwizacji."
  )) return;
  try {
    if (state.audioContext?.root === root && state.audioContext?.path === entry.path) {
      closeAudioPlayer();
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    const result = await api("/api/files/archive-now", {
      method: "POST",
      body: JSON.stringify({ root, path: entry.path }),
    });
    toast(`Zarchiwizowano: ${result.target}`, 5000);
    await Promise.all([reload(), loadReport()]);
  } catch (error) {
    toast(error.message || String(error), 6000);
  }
}

function formatPropertyDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("pl-PL", {
    dateStyle: "medium", timeStyle: "medium",
  }).format(new Date(value));
}

function formatPropertyBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value)) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toLocaleString("pl-PL", { maximumFractionDigits: 1 })} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toLocaleString("pl-PL", { maximumFractionDigits: 1 })} MB`;
  return `${(value / 1024 / 1024 / 1024).toLocaleString("pl-PL", { maximumFractionDigits: 2 })} GB`;
}

async function openFileProperties(root, path) {
  clearError("#filePropertiesError");
  $("#filePropertiesTitle").textContent = "Właściwości";
  $("#filePropertiesContent").innerHTML = '<div class="mini-empty">Wczytywanie…</div>';
  openModal($("#filePropertiesDialog"));
  try {
    const item = await api(`/api/files/properties?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`);
    $("#filePropertiesTitle").textContent = item.name;
    const values = [
      ["Położenie", `/${item.root_label}/${item.path}`],
      ["Typ", item.type === "directory" ? "Folder" : (item.mime_type || item.extension || "Plik")],
      ["Rozmiar", item.type === "file" ? formatPropertyBytes(item.size) : null],
      ["Zmodyfikowano", formatPropertyDate(item.modified_at)],
      ["Utworzono", item.created_at ? formatPropertyDate(item.created_at) : null],
      ["Ostatni dostęp", formatPropertyDate(item.accessed_at)],
      ["Zmiana metadanych", formatPropertyDate(item.changed_at)],
      ["Czas trwania", item.duration],
      ["Bitrate", item.bitrate_kbps ? `${item.bitrate_kbps} kb/s` : null],
      ["Próbkowanie", item.sample_rate_hz ? `${item.sample_rate_hz.toLocaleString("pl-PL")} Hz` : null],
      ["Kanały", item.channels],
      ["Kodek", item.codec],
    ].filter(([, value]) => value !== null && value !== undefined && value !== "");
    const content = $("#filePropertiesContent");
    content.replaceChildren(...values.map(([label, value]) => {
      const row = document.createElement("div");
      const term = document.createElement("span"); term.textContent = label;
      const detail = document.createElement("strong"); detail.textContent = String(value);
      row.append(term, detail);
      return row;
    }));
  } catch (error) {
    $("#filePropertiesContent").replaceChildren();
    showError("#filePropertiesError", error);
  }
}

function openRenameFile(root, entry, reload) {
  state.renameFileContext = { root, entry, reload };
  $("#renameFileName").value = entry.name;
  clearError("#renameFileError");
  openModal($("#renameFileDialog"));
  setTimeout(() => {
    $("#renameFileName").focus();
    $("#renameFileName").select();
  }, 20);
}

async function submitRenameFile(event) {
  event.preventDefault();
  const context = state.renameFileContext;
  if (!context) return;
  clearError("#renameFileError");
  const button = event.submitter;
  if (button) button.disabled = true;
  try {
    const result = await api("/api/files/rename", {
      method: "POST",
      body: JSON.stringify({
        root: context.root,
        path: context.entry.path,
        name: $("#renameFileName").value,
      }),
    });
    $("#renameFileDialog").close();
    toast(`Zmieniono nazwę na ${result.name}`);
    await context.reload();
  } catch (error) {
    showError("#renameFileError", error);
  } finally {
    if (button) button.disabled = false;
  }
}

async function chooseFile(path) {
  if (state.browserMode === "substitute") {
    const required = (state.substituteItem?.parts || []).filter(part => part.file_type !== "youtube").length;
    const source = { root: state.browserRoot, path };
    const alreadySelected = state.substituteSources.some(item => item.root === source.root && item.path === source.path);
    if (!alreadySelected && state.substituteSources.length < required) {
      state.substituteSources.push(source);
    }
    renderSubstituteSelection();
    return;
  }
  try {
    const patterns = await api("/api/files/infer-pattern", { method: "POST", body: JSON.stringify({ path }) });
    $("#folderPattern").value = patterns.folder_pattern;
    $("#filenamePattern").value = patterns.filename_pattern;
    $("#fileDialog").close();
    updatePreview();
    toast("Rozpoznano schemat daty — możesz go poprawić ręcznie");
  } catch (error) { showError("#browserError", error); }
}

async function chooseBrowserRoot(root) {
  if (root === "favorites") return showBrowserFavorites();
  state.browserFavoritesMode = false;
  state.browserFavoriteBase = null;
  state.browserRoot = root;
  state.browserPath = "";
  $("#fileRootButton").textContent = fileRootLabel(root);
  updateBrowserRootShortcuts();
  updateBrowserActions();
  clearError("#browserError");
  await browse("");
}

function updateBrowserRootShortcuts() {
  const favoritesActive = state.browserFavoritesMode || state.browserFavoriteBase;
  $("#mediaRootShortcut").classList.toggle("active", !favoritesActive && state.browserRoot === "media");
  $("#archiveRootShortcut").classList.toggle("active", !favoritesActive && state.browserRoot === "archive");
  $("#emausRootShortcut").classList.toggle("active", !favoritesActive && state.browserRoot === "emaus");
  $("#emausContactRootShortcut").classList.toggle("active", !favoritesActive && state.browserRoot === "emaus_contact");
  $("#favoritesRootShortcut").classList.toggle("active", Boolean(favoritesActive));
}

function updateBrowserActions() {
  const canSelectFolder = state.browserMode === "ftp"
    || state.browserMode === "production-folder"
    || (state.browserMode === "folder" && state.browserRoot === "media");
  $("#selectCurrentFolder").classList.toggle("hidden", !canSelectFolder);
  $("#newFolderButton").classList.toggle(
    "hidden",
    state.browserMode !== "folder" || state.browserRoot !== "media",
  );
}

function selectCurrentFolder() {
  if (state.browserMode === "ftp") $("#ftpSourcePath").value = state.browserPath;
  else if (state.browserMode === "production-folder") {
    if (state.productionBrowseIndex !== null) {
      const previous = productionFolderSource(
        state.productionWatchFolders[state.productionBrowseIndex],
      );
      state.productionWatchFolders[state.productionBrowseIndex] = productionFolderValue({
        root: state.browserRoot,
        path: state.browserPath,
        auto_delete: previous.auto_delete,
      });
      renderProductionWatchFolders();
    }
  } else $("#folderPattern").value = state.browserPath;
  $("#fileDialog").close();
  updateFtpSection();
  updatePreview();
}

function openNewFolderForm(parentPath = state.browserPath) {
  clearError("#browserError");
  state.newFolderParent = parentPath;
  $("#newFolderForm").classList.remove("hidden");
  $("#newFolderName").value = "";
  setTimeout(() => $("#newFolderName").focus(), 20);
}

async function createNewFolder() {
  const name = $("#newFolderName").value.trim();
  if (!name) { showError("#browserError", "Podaj nazwę folderu"); return; }
  $("#saveNewFolder").disabled = true;
  clearError("#browserError");
  try {
    const result = await api("/api/files/directories", {
      method: "POST",
      body: JSON.stringify({ path: state.newFolderParent ?? state.browserPath, name }),
    });
    $("#newFolderForm").classList.add("hidden");
    state.newFolderParent = null;
    toast("Utworzono folder");
    await browse(result.path);
  } catch (error) {
    showError("#browserError", error);
  } finally {
    $("#saveNewFolder").disabled = false;
  }
}

function changeSpyDate(days) {
  const copy = new Date(state.spyDate);
  copy.setDate(copy.getDate() + days);
  state.spyDate = copy;
  loadSpy();
}

async function loadSpy() {
  $("#spyDate").value = localIso(state.spyDate);
  clearError("#spyError");
  try {
    const result = await api(`/api/spy?date=${localIso(state.spyDate)}`);
    state.spyFiles = result.items || [];
    renderSpyFiles();
  } catch (error) {
    state.spyFiles = [];
    renderSpyFiles();
    showError("#spyError", error);
  }
}

function formatBytes(bytes) {
  const megabytes = Number(bytes || 0) / (1024 * 1024);
  return `${megabytes.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} MB`;
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds || 0)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

function renderSpyFiles() {
  $("#spyCount").textContent = String(state.spyFiles.length);
  $("#spyEmpty").classList.toggle("hidden", state.spyFiles.length > 0);
  $("#spyFileList").replaceChildren(...state.spyFiles.map(file => {
    const row = document.createElement("article");
    row.className = "spy-file-row";
    const time = document.createElement("strong");
    time.textContent = `${file.start_time}–${file.end_time}`;
    const details = document.createElement("div");
    const name = document.createElement("span");
    name.textContent = file.name;
    const meta = document.createElement("small");
    meta.textContent = `${formatDuration(file.duration_seconds)} • ${formatBytes(file.size)}`;
    details.append(name, meta);
    const play = document.createElement("button");
    play.type = "button";
    play.className = "primary-button compact-button";
    play.textContent = "▶ Odtwórz";
    play.addEventListener("click", () => playAudio("spy", file.path, file.name, { startedAt: file.started_at }));
    row.append(time, details, play);
    return row;
  }));
}

function playerTimecode() {
  if (state.audioContext?.root !== "spy" || !state.audioContext.startedAt) {
    throw new Error("Najpierw odtwórz plik z zakładki Szpieg");
  }
  const moment = new Date(state.audioContext.startedAt);
  moment.setMilliseconds(moment.getMilliseconds() + Math.round($("#audioElement").currentTime * 1000));
  return `${String(moment.getHours()).padStart(2, "0")}:${String(moment.getMinutes()).padStart(2, "0")}:${String(moment.getSeconds()).padStart(2, "0")}`;
}

function usePlayerTime(target) {
  try { $(target).value = playerTimecode(); }
  catch (error) { toast(error.message); }
}

async function cutSpyAudio(event) {
  event.preventDefault();
  clearError("#spyCutError");
  const button = $("#spyCutButton");
  button.disabled = true;
  button.textContent = "Wycinam…";
  try {
    const result = await api("/api/spy/cut", {
      method: "POST",
      body: JSON.stringify({
        date: localIso(state.spyDate),
        start_time: $("#spyStartTime").value,
        end_time: $("#spyEndTime").value,
        filename: $("#spyFilename").value,
      }),
    });
    const link = document.createElement("a");
    link.href = result.download_url;
    link.download = result.filename;
    document.body.append(link);
    link.click();
    link.remove();
    toast(`Przygotowano ${result.filename}`);
  } catch (error) { showError("#spyCutError", error); }
  finally { button.disabled = false; button.textContent = "Przygotuj i pobierz MP3"; }
}

function changeDate(days) {
  const copy = new Date(state.selectedDate);
  copy.setDate(copy.getDate() + days);
  state.selectedDate = copy;
  loadReport();
}

function bindEvents() {
  $$('[data-view]').forEach(link => link.addEventListener("click", event => {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const name = link.dataset.view;
    if (location.hash !== `#${name}`) history.pushState(null, "", `#${name}`);
    switchView(name);
  }));
  window.addEventListener("popstate", () => switchView(viewFromLocation()));
  $("#helpButton").addEventListener("click", () => openModal($("#helpDialog")));
  $("#settingsButton").addEventListener("click", openSettings);
  $("#settingsUnlockForm").addEventListener("submit", unlockSettings);
  $("#settingsForm").addEventListener("submit", saveNotificationSettings);
  $("#lockSettingsButton").addEventListener("click", lockNotificationSettings);
  $("#googleConnectButton").addEventListener("click", connectGoogle);
  $("#googleCheckButton").addEventListener("click", checkGoogleConnection);
  $("#googleDisconnectButton").addEventListener("click", disconnectGoogle);
  $("#calendarConnectButton").addEventListener("click", connectCalendarGoogle);
  $("#calendarFinishButton").addEventListener("click", finishCalendarGoogle);
  $("#calendarDisconnectButton").addEventListener("click", disconnectCalendarGoogle);
  $("#googleCalendarsRefresh").addEventListener("click", () => loadGoogleCalendars().catch(error => showError("#settingsError", error)));
  $("#googleCalendarId").addEventListener("change", updateGoogleCalendarSelectionStatus);
  $("#smtpTestButton").addEventListener("click", testDeliverySmtp);
  $("#zettaTestButton").addEventListener("click", testZettaConnection);
  $("#addPushoverRecipient").addEventListener("click", () => {
    state.notificationSettings.recipients.push(defaultPushoverRecipient());
    renderNotificationSettings();
  });
  $("#addNotificationRule").addEventListener("click", () => {
    state.notificationSettings.rules.push({ id: settingsId("rule"), lead_minutes: 60, enabled: true });
    renderNotificationSettings();
  });
  $("#lockButton").addEventListener("click", handleLock);
  $("#unlockForm").addEventListener("submit", submitUnlock);
  $("#previousDate").addEventListener("click", () => changeDate(-1));
  $("#nextDate").addEventListener("click", () => changeDate(1));
  $("#todayButton").addEventListener("click", () => { state.selectedDate = new Date(); loadReport(); });
  $("#refreshButton").addEventListener("click", loadReport);
  $("#spyPreviousDate").addEventListener("click", () => changeSpyDate(-1));
  $("#spyNextDate").addEventListener("click", () => changeSpyDate(1));
  $("#spyToday").addEventListener("click", () => { state.spyDate = new Date(); loadSpy(); });
  $("#spyRefresh").addEventListener("click", loadSpy);
  $("#spyLivePlay").addEventListener("click", playLiveStream);
  $("#ftpTasksRefresh").addEventListener("click", loadFtpTasks);
  $("#timetableRefresh").addEventListener("click", loadTimetable);
  $("#calendarPrevious").addEventListener("click", () => changeCalendarDate(-state.calendarRange));
  $("#calendarNext").addEventListener("click", () => changeCalendarDate(state.calendarRange));
  $("#calendarToday").addEventListener("click", () => {
    state.calendarDate = new Date();
    state.calendarAutoScrolled = false;
    loadCalendar();
  });
  $("#calendarDate").addEventListener("change", event => {
    state.calendarDate = dateFromIso(event.target.value);
    state.calendarAutoScrolled = false;
    loadCalendar();
  });
  $("#calendarRefresh").addEventListener("click", () => loadCalendar(true));
  $("#calendarOpenSettings").addEventListener("click", openSettings);
  $("#addCalendarEvent").addEventListener("click", () => openCalendarEventDialog());
  $$("#calendarRange [data-range]").forEach(button => button.addEventListener("click", () => {
    state.calendarRange = Number(button.dataset.range);
    try { localStorage.setItem("calendarRange", String(state.calendarRange)); } catch (_) { /* unavailable */ }
    state.calendarAutoScrolled = false;
    loadCalendar();
  }));
  $("#calendarEventForm").addEventListener("submit", saveCalendarEvent);
  $("#calendarEventAllDay").addEventListener("change", updateCalendarEventTimeFields);
  $("#calendarEventStartTime").addEventListener("blur", event => normalizeCalendarTimeInput(event.target));
  $("#calendarEventEndTime").addEventListener("blur", event => normalizeCalendarTimeInput(event.target));
  $("#deleteCalendarEvent").addEventListener("click", deleteCalendarEvent);
  $("#playedPreviousDate").addEventListener("click", () => changePlayedDate(-1));
  $("#playedNextDate").addEventListener("click", () => changePlayedDate(1));
  $("#playedToday").addEventListener("click", () => { state.playedDate = new Date(); loadPlayed(); });
  $("#playedDate").addEventListener("change", event => { state.playedDate = dateFromIso(event.target.value); loadPlayed(); });
  $("#playedRefresh").addEventListener("click", refreshPlayed);
  $("#playedOpenSettings").addEventListener("click", openSettings);
  $("#playedNow").addEventListener("click", scrollPlayedNow);
  $$("#playedFilters [data-played-filter]").forEach(button => button.addEventListener("click", () => {
    state.playedFilter = button.dataset.playedFilter;
    $$("#playedFilters [data-played-filter]").forEach(item => item.classList.toggle("active", item === button));
    renderPlayed();
  }));
  $("#timetableWideButton").addEventListener("click", toggleTimetableWide);
  $("#timetableFullscreenButton").addEventListener("click", toggleTimetableFullscreen);
  $("#addTimetableEntry").addEventListener("click", () => openTimetableEntryDialog());
  $("#timetableEntryForm").addEventListener("submit", saveTimetableEntry);
  $("#deleteTimetableEntry").addEventListener("click", deleteTimetableEntry);
  $("#timetableEntryType").addEventListener("change", updateTimetableEntryForm);
  $("#timetableShow").addEventListener("change", updateTimetableEntryForm);
  $("#timetableElement").addEventListener("change", updateTimetableEntryForm);
  $("#timetableBulkAllTimes").addEventListener("change", event => selectTimetableBulkMinutes("all", event.target.checked));
  $("#timetableBulkCurrentTime").addEventListener("click", () => selectTimetableBulkMinutes("current"));
  $("#timetableBulkAllDays").addEventListener("change", event => selectTimetableBulkDays("all", event.target.checked));
  $("#timetableBulkWorkdays").addEventListener("click", () => selectTimetableBulkDays("workdays"));
  $("#timetableBulkWeekend").addEventListener("click", () => selectTimetableBulkDays("weekend"));
  $("#timetableBulkCurrentDay").addEventListener("click", () => selectTimetableBulkDays("current"));
  $("#timetablePreviousDay").addEventListener("click", () => changeTimetableDay(-1));
  $("#timetableNextDay").addEventListener("click", () => changeTimetableDay(1));
  $("#timetableDay").addEventListener("change", event => {
    state.timetableDay = Number(event.target.value);
    renderTimetable();
  });
  $$("#timetableRange [data-range]").forEach(button => button.addEventListener("click", () => {
    state.timetableRange = Number(button.dataset.range);
    try { localStorage.setItem("timetableRange", String(state.timetableRange)); } catch (_) { /* unavailable */ }
    renderTimetable();
  }));
  $$("#timetableDensity [data-density]").forEach(button => button.addEventListener("click", () => {
    state.timetableDensity = button.dataset.density;
    try { localStorage.setItem("timetableDensity", state.timetableDensity); } catch (_) { /* unavailable */ }
    renderTimetable();
  }));
  $("#timetableZoom").addEventListener("input", event => applyTimetableZoom(event.target.value));
  $("#timetableViewportHeight").addEventListener("input", event => applyTimetableViewportHeight(event.target.value));
  $("#spyDate").addEventListener("change", event => { state.spyDate = dateFromIso(event.target.value); loadSpy(); });
  $("#spyCutForm").addEventListener("submit", cutSpyAudio);
  $("#spyUseStart").addEventListener("click", () => usePlayerTime("#spyStartTime"));
  $("#spyUseEnd").addEventListener("click", () => usePlayerTime("#spyEndTime"));
  $("#audioStopButton").addEventListener("click", stopAudio);
  $("#audioCloseButton").addEventListener("click", closeAudioPlayer);
  $("#audioElement").addEventListener("error", () => toast(audioErrorMessage(), 8000));
  $("#renameFileForm").addEventListener("submit", submitRenameFile);
  $("#reportSort").value = state.reportSort;
  $("#reportSort").addEventListener("change", event => {
    state.reportSort = event.target.value;
    try { localStorage.setItem("reportSort", state.reportSort); } catch (_) { /* storage unavailable */ }
    if (state.report) renderReport(state.report);
  });
  $("#dateButton").addEventListener("click", () => { const picker = $("#datePicker"); if (picker.showPicker) picker.showPicker(); else picker.click(); });
  $("#datePicker").addEventListener("change", event => { state.selectedDate = dateFromIso(event.target.value); loadReport(); });
  $("#showSearch").addEventListener("input", renderShows);
  $("#dismissImportWarning").addEventListener("click", () => hideImportWarning(true));
  $("#changePinButton").addEventListener("click", openChangePin);
  $("#changePinForm").addEventListener("submit", submitChangePin);
  $("#addShowButton").addEventListener("click", () => openShowDialog());
  $("#showForm").addEventListener("submit", saveShow);
  $("#deleteShowButton").addEventListener("click", deleteShow);
  $("#addPremiereSlotButton").addEventListener("click", () => {
    state.premiereSlots.push(defaultEmissionSlot());
    renderPremiereSlots();
  });
  $("#addRepeatButton").addEventListener("click", () => {
    state.repeats.push({
      id: repeatId(),
      label: `Powtórka ${state.repeats.length + 1}`,
      emission_time: null,
      emission_times: [""],
      folder_pattern: $("#folderPattern").value,
      filename_pattern: $("#filenamePattern").value,
      filename_patterns: [$("#filenamePattern").value, ...state.additionalFilePatterns],
      schedule: [],
    });
    renderRepeats();
  });
  $("#folderPattern").addEventListener("input", () => { updatePreview(); updateFtpSection(); });
  $("#filenamePattern").addEventListener("input", updatePreview);
  $("#showEditing").addEventListener("change", updateProductionMonitoringSection);
  $("#showFtp").addEventListener("change", updateFtpSection);
  $("#showSendAuthor").addEventListener("change", updateAuthorSection);
  $("#ftpSourcePath").addEventListener("input", updateFtpSection);
  $("#ftpRenameEnabled").addEventListener("change", () => { updateFtpSection(); loadFtpStatus(); });
  $("#browseFtpButton").addEventListener("click", () => openBrowser("ftp"));
  $("#ftpSyncNowButton").addEventListener("click", event => syncFtp(
    Number($("#showId").value),
    event.currentTarget,
    state.viewOnly ? null : { ftp_source_path: $("#ftpSourcePath").value, folder_pattern: $("#folderPattern").value },
  ));
  $("#ftpRenameNowButton").addEventListener("click", event => renameFtp(Number($("#showId").value), null, event.currentTarget));
  $("#addFilePatternButton").addEventListener("click", () => {
    state.additionalFilePatterns.push("");
    state.ftpSourcePatterns.push("");
    state.repeats.forEach(repeat => {
      repeat.filename_patterns ||= [repeat.filename_pattern || $("#filenamePattern").value];
      repeat.filename_patterns.push("");
    });
    renderAdditionalFilePatterns();
    updateFtpSection();
    renderRepeats();
  });
  $("#addProductionWatchFolder").addEventListener("click", () => {
    state.productionWatchFolders.push("");
    renderProductionWatchFolders();
  });
  $("#browseFileButton").addEventListener("click", () => openBrowser("file"));
  $("#browseFolderButton").addEventListener("click", () => openBrowser("folder"));
  $("#fileRootButton").addEventListener("click", () => {
    if (state.browserFavoritesMode || state.browserFavoriteBase) showBrowserFavorites();
    else browse(state.browserMode === "ftp" ? "/" : "");
  });
  $("#mediaRootShortcut").addEventListener("click", () => chooseBrowserRoot("media"));
  $("#archiveRootShortcut").addEventListener("click", () => chooseBrowserRoot("archive"));
  $("#emausRootShortcut").addEventListener("click", () => chooseBrowserRoot("emaus"));
  $("#emausContactRootShortcut").addEventListener("click", () => chooseBrowserRoot("emaus_contact"));
  $("#favoritesRootShortcut").addEventListener("click", () => chooseBrowserRoot("favorites"));
  $("#browserSort").value = state.browserSort;
  $("#browserSort").addEventListener("change", event => {
    state.browserSort = event.target.value;
    try { localStorage.setItem("browserSort", state.browserSort); } catch (_) { /* storage unavailable */ }
    if (state.browserFavoritesMode) showBrowserFavorites();
    else browse(state.browserPath);
  });
  $("#listenBrowserSort").value = state.listenBrowserSort;
  $("#listenBrowserSort").addEventListener("change", event => {
    state.listenBrowserSort = event.target.value;
    try { localStorage.setItem("listenBrowserSort", state.listenBrowserSort); } catch (_) { /* storage unavailable */ }
    if (state.listenFavoritesMode) showListenFavorites();
    else loadListenBrowser(state.listenBrowserPath);
  });
  $$("#listenBrowserRootShortcuts [data-listen-root]").forEach(button => {
    button.addEventListener("click", () => chooseListenBrowserRoot(button.dataset.listenRoot));
  });
  $("#listenBrowserRootButton").addEventListener("click", () => {
    if (state.listenFavoritesMode || state.listenFavoriteBase) showListenFavorites();
    else loadListenBrowser("");
  });
  $("#selectCurrentFolder").addEventListener("click", selectCurrentFolder);
  $("#fileList").addEventListener("contextmenu", showCurrentFolderContextMenu);
  $("#browserPath").closest(".browser-path").addEventListener("contextmenu", showCurrentFolderContextMenu);
  $("#newFolderButton").addEventListener("click", openNewFolderForm);
  $("#saveNewFolder").addEventListener("click", createNewFolder);
  $("#cancelNewFolder").addEventListener("click", () => {
    state.newFolderParent = null;
    $("#newFolderForm").classList.add("hidden");
  });
  $("#newFolderName").addEventListener("keydown", event => {
    if (event.key === "Enter") { event.preventDefault(); createNewFolder(); }
  });
  $("#closeFileDialog").addEventListener("click", () => $("#fileDialog").close());
  $("#cancelFileDialog").addEventListener("click", () => $("#fileDialog").close());
  $("#fileDialog").addEventListener("close", () => {
    document.body.classList.remove("file-dialog-open");
    closeFileContextMenu();
  });
  $("#confirmSubstitute").addEventListener("click", confirmSubstitute);
  $$("dialog").forEach(dialog => {
    dialog.addEventListener("click", event => {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", unlockPageScrollWhenIdle);
  });
  let timetableResizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(timetableResizeTimer);
    timetableResizeTimer = setTimeout(() => {
      if ($("#timetableView").classList.contains("active")) renderTimetable();
      if ($("#calendarView").classList.contains("active") && state.calendarLoaded) renderCalendar();
    }, 120);
  });
  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement) state.timetableFullscreenFallback = false;
    $("#timetableView").classList.toggle("timetable-native-fullscreen", document.fullscreenElement === $("#timetableView"));
    updateTimetableFullscreenButton();
  });
}

async function init() {
  $("#audioElement").volume = 0.2;
  bindEvents();
  renderTimetableHourJumps();
  renderPlayedHourButtons();
  updateVersionBadge();
  updateDateHeader();
  try { await Promise.all([loadAuth(), loadReport(), loadShows(), loadFileFavorites(), loadPublicWindowsPathSettings()]); }
  catch (error) { toast(error.message); }
  switchView(viewFromLocation());
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").then(registration => registration.update()).catch(() => {});
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (sessionStorage.getItem("swReloaded") === "0.10.1") return;
      sessionStorage.setItem("swReloaded", "0.10.1");
      location.reload();
    });
  }
}

document.addEventListener("DOMContentLoaded", init);
