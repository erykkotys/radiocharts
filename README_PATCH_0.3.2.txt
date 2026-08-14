RadioCharts 0.3.2 — hotfix AG Grid / React

Naprawia błąd:
  Component Error: Minified React error #31 ... [object HTMLAnchorElement]

Przyczyna:
  custom cellRenderer zwracał surowy element DOM. W aktualnym wrapperze React streamlit-aggrid taki obiekt był przekazywany jako React child.

Zmiana:
  - linki Szczegóły i Spotify oraz odsłuch są zwykłymi komórkami tekstowymi;
  - kliknięcia obsługuje grid-level onCellClicked;
  - nie są już zwracane HTMLElement-y z cellRendererów.
