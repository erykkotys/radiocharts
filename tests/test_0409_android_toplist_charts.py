from pathlib import Path


def test_android_toplist_rows_open_landscape_chart_screen():
    root = Path(__file__).resolve().parents[1]
    main = (root / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")

    assert '"chart/{id}/{source}"' in main
    assert 'clickable{navigate("chart/$id/${Uri.encode(src)}")}' in main
    assert 'ToplistChartScreen(' in main
    assert 'SCREEN_ORIENTATION_SENSOR_LANDSCAPE' in main
    assert 'ToplistLineChart(points=points' in main
    assert 'drawPath(path,Accent' in main
    assert 'val chartOpen = currentBackStackEntry?.destination?.route?.startsWith("chart/") == true' in main
    assert 'if (!chartOpen)' in main
    assert 'OutlinedButton(onClick={ leaveChart() })' in main
    assert 'OutlinedButton(onClick={leaveChart})' not in main
