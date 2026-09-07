from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt"

def test_combined_chart_navigation_and_series():
    text = MAIN.read_text(encoding="utf-8")
    assert 'navigate("chart/$id/__ALL__")' in text
    assert 'val allSources=source=="__ALL__"' in text
    assert 'Text(if(allSources) "Wszystkie listy" else source' in text
    assert 'val bySource=points.groupBy{it.source}' in text
    assert 'ToplistSeriesColors' in text

def test_chart_point_details_support_hover_and_touch():
    text = MAIN.read_text(encoding="utf-8")
    assert 'PointerEventType.Move' in text
    assert 'PointerEventType.Press' in text
    assert 'selectedDate' in text
    assert '"${p.source}  #${p.position}"' in text
    assert 'shortChartDate(d)' in text

def test_versions_0410():
    gradle=(ROOT/"android/RadioChartsAndroid/app/build.gradle.kts").read_text(encoding="utf-8")
    assert 'versionCode = 15' in gradle
    assert 'versionName = "1.0.4"' in gradle
    assert (ROOT/"VERSION").read_text(encoding="utf-8").strip()=="1.0.4"
