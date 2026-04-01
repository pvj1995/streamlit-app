# Tourism Dashboard for Slovenian Destinations

Streamlit application for exploring tourism indicators across Slovenian municipalities, destinations, tourism regions, and macro destinations.

The app combines:

- map-based indicator exploration
- comparison tables for areas and municipalities
- grouped top/bottom diagnostics
- AI-generated commentary and recommendations
- source-market structure analysis

Short Slovenian end-user guide: [README_uporabnik.md](./README_uporabnik.md)

## Overview

The project is organized as a modular Streamlit app:

- [`streamlit_app_sandbox.py`](./streamlit_app_sandbox.py) is the entrypoint
- [`tourism_dashboard/`](./tourism_dashboard) contains the app logic
- [`data/`](./data) contains the default Excel, mapping workbook, and GeoJSON
- [`assets/`](./assets) contains buttons, banners, icons, logos, and title images

The app is password-protected, supports optional local file uploads, and can persist AI commentary in a SQL database through a Streamlit connection.

## Current features

- Password gate via `APP_PASSWORD`
- Default loading from `data/`
- Optional upload override for Excel and GeoJSON
- Territorial views:
  - `Turistične regije`
  - `Vodilne destinacije`
  - `Makrodestinacije`
  - `Regijske destinacije`
  - `Perspektivne destinacije`
- Image-based indicator-group selector
- Area-wide and municipality-level maps
- Region summary KPIs and optional dashboard indicators
- Top/bottom analysis per indicator group
- AI commentary built from all group-level top/bottom results
- Source-market structure tab for 2024 and 2025
- Persistent AI response cache through SQL
- Fallback rule-based commentary if the OpenAI call is unavailable

## Project structure

```text
streamlit app/
├── assets/
│   ├── banners/
│   ├── buttons/
│   ├── icons/
│   ├── logos/
│   └── title/
│       └── slides/
├── data/
│   ├── Skupna tabela občine.xlsx
│   ├── mapping.xlsx
│   └── si.json
├── tourism_dashboard/
│   ├── ai.py
│   ├── analytics.py
│   ├── assets.py
│   ├── auth.py
│   ├── config.py
│   ├── formatting.py
│   ├── helpers.py
│   ├── maps.py
│   ├── models.py
│   ├── paths.py
│   └── ui.py
├── .streamlit/
│   └── secrets.toml
├── requirements.txt
├── streamlit_app_sandbox.py
├── README.md
└── README_uporabnik.md
```

## Runtime flow

`streamlit_app_sandbox.py` currently does the following:

1. sets Streamlit page config
2. requires a password through [`tourism_dashboard/auth.py`](./tourism_dashboard/auth.py)
3. renders the page header
4. loads the default or uploaded Excel
5. prepares a cached numeric dataframe for the current dataset
6. loads the GeoJSON and indicator-group mapping
7. builds a `DashboardContext`
8. renders two main tabs:
   - `Kazalniki`
   - `Struktura prenočitev po trgih`

The heaviest dataset preprocessing now happens once per loaded Excel source and is reused across reruns through cached helpers and session state.

## Local setup

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create local Streamlit secrets

Create:

```text
.streamlit/secrets.toml
```

Minimum example:

```toml
APP_PASSWORD = "your-password"
```

Example with AI and SQL cache:

```toml
APP_PASSWORD = "your-password"
OPENAI_API_KEY = "sk-..."
OPENAI_MODEL = "gpt-5.4"
AI_CACHE_CONNECTION_NAME = "ai_cache_db"

[connections.ai_cache_db]
url = "postgresql://USER:PASSWORD@HOST:5432/postgres"
```

Notes:

- `APP_PASSWORD` is required
- `OPENAI_API_KEY` is optional
- `OPENAI_MODEL` defaults to `gpt-5.4`
- `AI_CACHE_CONNECTION_NAME` defaults to `ai_cache_db`
- if the SQL connection is missing, the app still works, but commentary cache persistence is skipped

### 4. Run

```bash
streamlit run streamlit_app_sandbox.py
```

## Deployment

The app is designed for both local use and Streamlit Community Cloud.

For Streamlit Community Cloud:

1. push the repository to GitHub
2. point Streamlit to `streamlit_app_sandbox.py`
3. add the same secrets in the Streamlit app settings
4. keep `data/` and `assets/` committed

## Default data and assets

### Required data files

- [`data/Skupna tabela občine.xlsx`](./data/Skupna%20tabela%20obc%CC%8Cine.xlsx)
- [`data/mapping.xlsx`](./data/mapping.xlsx)
- [`data/si.json`](./data/si.json)

### Main asset folders

- [`assets/buttons/`](./assets/buttons)
- [`assets/banners/`](./assets/banners)
- [`assets/icons/`](./assets/icons)
- [`assets/logos/`](./assets/logos)
- [`assets/title/`](./assets/title)
- [`assets/title/slides/`](./assets/title/slides)

The app will still fall back to some root-level lookup patterns for compatibility, but the current intended layout is `data/` plus `assets/`.

## Excel requirements

The Excel workbook must contain at least:

- `Občine`
- `Turistična regija`

Additional territorial columns are optional but expected if you want the corresponding views to appear.

The first row is treated as the authoritative Slovenia row for national baselines. This is important for:

- top/bottom comparison
- KPI comparison to Slovenia
- AI commentary inputs

## Mapping workbook requirements

[`data/mapping.xlsx`](./data/mapping.xlsx) is read column-by-column:

- each column name becomes a group name
- each non-empty cell in that column becomes an indicator in that group

Expected shape:

```text
| Družbeni kazalniki | Okoljski kazalniki | ... |
| indicator A        | indicator X        | ... |
| indicator B        | indicator Y        | ... |
```

## GeoJSON requirements

The default GeoJSON should contain municipality polygons.

The app tries to auto-detect a municipality-name property from:

- `name`
- `NAME`
- `Občina`
- `OBČINA`

If none match, the first available property key is used.

## Aggregation logic

Aggregation rules are defined in [`tourism_dashboard/config.py`](./tourism_dashboard/config.py) under `AGG_RULES`.

Supported modes:

- `sum`
  For additive indicators such as totals, counts, capacities, overnight stays, establishments, and sector totals.
- `mean`
  For genuine simple averages.
- `wmean`
  For weighted averages where municipalities should contribute proportionally to a denominator or scale.

Example:

```python
"Delež tujih prenočitev - 2025": ("wmean", "Prenočitve turistov SKUPAJ - 2025")
```

Meaning:

- municipality percentages are not summed
- the region value is a weighted average
- the weight is total overnight stays

## Top/bottom methodology

The current top/bottom section is intentionally not a naive raw-value ranking.

### Group-specific ranking

Each indicator group is ranked separately, using limits from `TOP_BOTTOM_GROUP_LIMITS`:

- `Družbeni kazalniki`: top 4 / bottom 4
- `Okoljski kazalniki`: top 3 / bottom 3
- `Ekonomski nastanitveni in tržni turistični kazalniki`: top 5 / bottom 5
- `Ekonomsko poslovni kazalniki turistične dejavnosti`: top 5 / bottom 5

### Excluded indicators

Indicators listed in `TOP_BOTTOM_EXCLUDED_INDICATORS` are excluded from the top/bottom analysis.

### Lower-is-better handling

Indicators listed in `LOWER_IS_BETTER_INDICATORS` are sign-adjusted so that:

- positive aligned score means stronger / more favorable
- negative aligned score means weaker / less favorable

### Slovenia baseline

The comparison baseline always comes from the dedicated Slovenia row in the Excel, not from re-aggregating municipalities.

### `sum` indicators

`sum` indicators do not compare raw region totals directly to raw Slovenia totals.

Instead, the app compares:

- the region share of the indicator within Slovenia
- against the region share of a benchmark base chosen by `get_sum_comparison_base()`

The displayed formula is:

```text
indicator_share = region_value / slovenia_value
benchmark_share = base_reg / base_slo
display_delta = (indicator_share - benchmark_share) * 100
```

The result is shown in `o.t.` (`odstotne točke`).

Current routing logic in [`tourism_dashboard/analytics.py`](./tourism_dashboard/analytics.py):

- tourism-flow totals such as `prenočitve` and `prihodi turistov`
  compare to matched-year permanent bed capacity
- total accommodation supply such as `Nastanitvene kapacitete - ...` and `Število vseh nastanitvenih obratov 2025`
  compare to matched-year population
- accommodation subtype establishment counts such as `Število hotelov ipd. NO 2025` or `Število kampov 2025`
  compare to total accommodation establishments
- room/unit subtype totals compare to total room/unit stock
- bed subtype totals compare to total permanent-bed stock

This is meant to reflect structural tourism strength more truthfully than comparing all totals to population.

### Non-`sum` indicators

Non-`sum` indicators now use a direct gap to Slovenia for display.

- percent-like indicators are shown in `o.t.`
- currency indicators are shown in `€`
- other indicators use raw unit gap

This avoids the old issue where very small Slovenian baselines could create misleadingly huge relative `%` deviations.

### Final ranking score

Displayed gaps are not used directly as the final mixed ranking scale.

The app computes a separate internal score:

```text
ranking_score = aligned_display_gap / typical_peer_spread
```

The spread is estimated robustly from same-level peer areas using:

- MAD-based scale first
- IQR fallback
- standard deviation fallback
- median magnitude fallback

This allows `sum` and non-`sum` indicators to coexist within the same group without one unit system dominating the ranking.

## AI commentary

AI commentary is built from all group-level top/bottom outputs together.

Flow:

1. [`build_top_bottom_group_sections()`](./tourism_dashboard/analytics.py) prepares grouped results
2. [`render_region_top_bottom_and_ai()`](./tourism_dashboard/ui.py) builds a stable JSON payload
3. the payload hash becomes the cache key
4. the app first checks the SQL cache
5. if missing, it calls the OpenAI Responses API
6. if the AI call fails, it falls back to a local summary

### SQL cache

The default table name is:

```text
ai_commentary_cache
```

It is created automatically if the SQL connection is available.

Main columns:

- `cache_key`
- `payload_hash`
- `region`
- `group_name`
- `response_text`
- `model`
- `updated_at`

### When cached commentary is reused

The same cached response is reused when the hashed input payload is unchanged, meaning the selected area and all relevant grouped top/bottom inputs are the same.

## Performance notes

The current version includes several performance improvements:

- Excel loading is cached separately for file-path and uploaded-byte sources
- the numeric dataframe is built once per loaded dataset and reused across reruns
- regional aggregation now groups once per territorial level instead of repeatedly refiltering the dataframe
- generated folium map HTML is cached

The main places that still have noticeable cost are:

- first render after changing the Excel source
- top/bottom calculation for a region, because it still computes a fairly broad reference aggregation set
- first AI generation when no cache entry exists

## Key modules

- [`tourism_dashboard/auth.py`](./tourism_dashboard/auth.py)
  Password gate based on `APP_PASSWORD`.
- [`tourism_dashboard/helpers.py`](./tourism_dashboard/helpers.py)
  Excel loading, cached load helpers, numeric parsing, column normalization, secret access.
- [`tourism_dashboard/analytics.py`](./tourism_dashboard/analytics.py)
  Aggregation rules, top/bottom logic, benchmark-base routing, and market-column discovery.
- [`tourism_dashboard/ui.py`](./tourism_dashboard/ui.py)
  Main Streamlit views for indicators, maps, grouped diagnostics, and market structure.
- [`tourism_dashboard/maps.py`](./tourism_dashboard/maps.py)
  GeoJSON transformation and folium rendering.
- [`tourism_dashboard/assets.py`](./tourism_dashboard/assets.py)
  Page header, banner rendering, group button assets, image helpers.
- [`tourism_dashboard/ai.py`](./tourism_dashboard/ai.py)
  Prompt assembly, OpenAI call, retry behavior, fallback commentary, SQL cache read/write.
- [`tourism_dashboard/config.py`](./tourism_dashboard/config.py)
  Constants, UI labels, aggregation rules, exclusions, flags, and visual configuration.

## Key function reference

This is a practical reference for the main maintenance points in the project.

### Entrypoint

`load_source_dataframe(uploaded_file, default_path)` in [`streamlit_app_sandbox.py`](./streamlit_app_sandbox.py)

- `uploaded_file`
  Streamlit uploader object or `None`
- `default_path`
  `Path | None`
- returns
  `(signature, dataframe)` pair used to decide whether cached prepared data can be reused

### Helpers

`load_excel_from_path(path_str: str) -> pd.DataFrame` in [`helpers.py`](./tourism_dashboard/helpers.py)

- loads the Excel from disk
- cached with `st.cache_data`

`load_excel_from_bytes(raw_bytes: bytes) -> pd.DataFrame` in [`helpers.py`](./tourism_dashboard/helpers.py)

- loads an uploaded Excel from in-memory bytes
- cached with `st.cache_data`

`build_numeric_dataframe(df: pd.DataFrame, numeric_columns: list[str]) -> pd.DataFrame` in [`helpers.py`](./tourism_dashboard/helpers.py)

- converts configured value columns to numeric form
- leaves metadata columns intact

### Analytics

`aggregate_indicator_with_rules(df, indicator, agg_rules, region_name)` in [`analytics.py`](./tourism_dashboard/analytics.py)

- `df`
  subset dataframe for the target area
- `indicator`
  exact indicator label
- `agg_rules`
  `AGG_RULES` mapping
- `region_name`
  area label, used for special derived indicators

`get_sum_comparison_base(indicator: str) -> tuple[str, str]` in [`analytics.py`](./tourism_dashboard/analytics.py)

- returns the benchmark indicator and a human-readable label
- used only for `sum`-indicator comparison

`compute_region_aggregates(numeric_df, regions, indicator_cols, agg_rules, group_col)` in [`analytics.py`](./tourism_dashboard/analytics.py)

- builds an area-level aggregation table for a set of indicators
- used by map views, KPI summaries, and top/bottom reference calculations

`build_top_bottom_group_sections(reg_df, df_slo_total_num, grouped_filtered, agg_rules, region_name, reference_agg_df=None)` in [`analytics.py`](./tourism_dashboard/analytics.py)

- returns the grouped top/bottom payload used both for UI tables and AI commentary

### UI

`render_view(view_title: str, group_col: str, ctx: DashboardContext)` in [`ui.py`](./tourism_dashboard/ui.py)

- renders the main indicator tab for one territorial view

`render_market_structure(view_title: str, group_col: str, ctx: DashboardContext)` in [`ui.py`](./tourism_dashboard/ui.py)

- renders the source-market structure tab

### AI

`generate_region_ai_commentary(region_name: str, group_sections: list[dict[str, Any]])` in [`ai.py`](./tourism_dashboard/ai.py)

- builds the current AI prompt
- calls OpenAI if configured
- falls back to rule-based commentary if unavailable

## Maintenance workflows

### Add a new indicator

1. Add the column to the Excel workbook.
2. Add the exact same label to the correct column in `data/mapping.xlsx`.
3. Add the indicator to `AGG_RULES` in [`config.py`](./tourism_dashboard/config.py).
4. If lower values are better, add it to `LOWER_IS_BETTER_INDICATORS`.
5. If it should render with `€`, add it to `INDIKATORJI_Z_VALUTO`.
6. If municipality tables should behave like an index rather than a share, add it to `INDIKATORJI_Z_INDEKSI`.
7. If it needs the shared warning, add it to `INDIKATORJI_Z_OPOMBO`.
8. If it should be excluded from top/bottom, add it to `TOP_BOTTOM_EXCLUDED_INDICATORS`.
9. If it is a `sum` indicator and needs special benchmark routing, update `get_sum_comparison_base()`.

### Add a new territorial view

Add the desired human-readable title and candidate column names to `VIEW_CANDIDATES` in [`config.py`](./tourism_dashboard/config.py).

### Change button or banner assets

Main asset configuration is in [`config.py`](./tourism_dashboard/config.py):

- `GROUP_BUTTON_IMAGE_FILES`
- `AI_BANNER_FILENAME`
- `AI_ICON_FILENAME`
- `TITLE_FALLBACK_FILENAME`

### Change the AI prompt

Edit:

- `system_prompt` in [`tourism_dashboard/ai.py`](./tourism_dashboard/ai.py#L273)
- `user_prompt` in [`tourism_dashboard/ai.py`](./tourism_dashboard/ai.py#L277)

The grouped top/bottom content that is injected into the prompt is assembled by:

- [`grouped_rows_to_prompt_text()`](./tourism_dashboard/ai.py#L160)

## Troubleshooting

### The app stops immediately on startup

Most likely:

- `APP_PASSWORD` is missing in `.streamlit/secrets.toml`

### The map does not render

Check:

- GeoJSON exists
- municipality names match the Excel closely enough after normalization
- `folium` and `geopandas` are installed

### AI commentary never appears

Possible causes:

- `OPENAI_API_KEY` is missing
- the model request failed
- the SQL cache connection is misconfigured

If AI is unavailable, the app should still display fallback commentary.

### The IDE shows unresolved imports

Make sure:

- the project root is opened in VS Code
- the selected interpreter is `.venv/bin/python`
- the workspace uses the included `.vscode/settings.json` and `pyrightconfig.json`

## Verification

Basic syntax check:

```bash
python3 -m py_compile streamlit_app_sandbox.py tourism_dashboard/*.py
```

For interactive verification, run the app and test:

1. login
2. one all-area map view
3. one single-area top/bottom + AI view
4. market-structure tab for both years
