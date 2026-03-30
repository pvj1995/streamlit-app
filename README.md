# Tourism Dashboard for Slovenian Destinations

Streamlit application for exploring tourism indicators across Slovenian municipalities, destinations, macro-destinations, and tourism regions.

The app combines:

- interactive map views
- municipality and region comparison tables
- grouped top/bottom indicator diagnostics
- AI-generated commentary and recommendations
- market structure analysis by source market

The codebase is modularized under `tourism_dashboard/`, while `streamlit_app_sandbox.py` is the entrypoint that wires the modules together.

Short Slovenian end-user guide: [README_uporabnik.md](./README_uporabnik.md)

## What the app does

The app loads a master Excel file with tourism indicators and a municipal GeoJSON, then lets the user:

- choose a territorial view such as `Turistične regije`, `Vodilne destinacije`, `Makrodestinacije`, `Regijske destinacije`, or `Perspektivne destinacije`
- select a group of indicators through image buttons
- inspect one indicator on a map and in tables
- compare either all areas or a single selected area
- view top/bottom indicators for each indicator group separately
- generate a holistic AI commentary for the selected area based on all group-level top/bottom results
- inspect market structure of overnight stays by source market and year

## Main features

- Password-protected entry using `APP_PASSWORD`
- Automatic loading of default data from `data/`
- Optional upload override for Excel and GeoJSON from the sidebar
- Aggregation rules for `sum`, `mean`, and weighted mean indicators
- Separate top/bottom ranking per indicator group
- Special handling for cumulative indicators in top/bottom comparison so large regions do not dominate results
- Persistent AI commentary cache through a Streamlit SQL connection
- Fallback non-AI commentary if the OpenAI key is missing or the API call fails
- Image-based group selector and slideshow title header

## Project structure

```text
streamlit app/
├── assets/
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
├── streamlit_app_sandbox.py
├── requirements.txt
└── README.md
```

## Architecture at a glance

### Entrypoint

`streamlit_app_sandbox.py` is responsible for:

- page config
- password gate
- header rendering
- loading default or uploaded data
- assembling `DashboardContext`
- rendering the two main tabs

### Package responsibilities

- `tourism_dashboard/config.py`
  Central constants, aggregation rules, indicator flags, exclusions, market settings, and UI text.
- `tourism_dashboard/helpers.py`
  File loading, secret access, normalization, column detection, numeric parsing, and SQL wrapper helpers.
- `tourism_dashboard/analytics.py`
  Indicator aggregation, special-case precomputed metrics, region-level comparisons, top/bottom ranking, and market-column discovery.
- `tourism_dashboard/maps.py`
  GeoJSON handling and folium map rendering.
- `tourism_dashboard/ui.py`
  Streamlit rendering for the map/table views, top/bottom section, AI commentary section, and market structure tab.
- `tourism_dashboard/assets.py`
  Image loading, button preparation, page header rendering, and AI header rendering.
- `tourism_dashboard/ai.py`
  OpenAI prompt building, API calling, retry behavior, and persistent cache read/write.
- `tourism_dashboard/auth.py`
  Password gate.
- `tourism_dashboard/formatting.py`
  Number, percent, and indicator-specific formatting helpers.
- `tourism_dashboard/models.py`
  `DashboardContext` dataclass passed into the UI layer.
- `tourism_dashboard/paths.py`
  Canonical project paths.

## Requirements

- Python 3.10 or newer recommended
- A working virtual environment
- `pip`
- Optional but recommended for AI commentary:
  - OpenAI API key
  - SQL database connection for AI response cache

## Installation

### 1. Create and activate a virtual environment

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Add Streamlit secrets

Create:

```text
.streamlit/secrets.toml
```

Minimum example:

```toml
APP_PASSWORD = "your-password"
```

If you want AI commentary:

```toml
APP_PASSWORD = "your-password"
OPENAI_API_KEY = "sk-..."
OPENAI_MODEL = "gpt-5.4"
AI_CACHE_CONNECTION_NAME = "ai_cache_db"

[connections.ai_cache_db]
url = "postgresql://USER:PASSWORD@HOST:5432/postgres"
```

Notes:

- `APP_PASSWORD` is required. Without it, the app stops on startup.
- `OPENAI_API_KEY` is optional. If missing, the app falls back to a rule-based text summary.
- `OPENAI_MODEL` is optional. The default is `gpt-5.4`.
- `AI_CACHE_CONNECTION_NAME` is optional. The default is `ai_cache_db`.
- If the SQL connection is missing, AI cache reads/writes are skipped and the app still works.

### 4. Run the app

```bash
streamlit run streamlit_app_sandbox.py
```

## Deployment

The app is designed to run locally and on Streamlit Community Cloud.

For Streamlit Community Cloud:

1. Push the repository to GitHub.
2. Connect the repo in Streamlit.
3. Add the same secrets in the Streamlit app settings.
4. Ensure the `data/` and `assets/` folders are committed.

## Data files

### Required files

- `data/Skupna tabela občine.xlsx`
  Master indicator dataset.
- `data/mapping.xlsx`
  Indicator-to-group mapping.
- `data/si.json`
  Municipal GeoJSON.

The app also supports backward-compatible fallback lookup from the project root, but the intended structure is the `data/` and `assets/` folders.

### Master Excel requirements

The Excel file must contain at least:

- `Občine`
- `Turistična regija`

Optional but normally expected columns for additional views:

- `Vodilne destinacije`
- `Perspektivne destinacije`
- `Makro destinacije`
- `Regijska destinacija` or `Regijske destinacije`
- `SLOVENIJA`

All indicator columns should be one-column-per-indicator with a human-readable Slovenian label used consistently across:

- the Excel file
- `mapping.xlsx`
- `config.py`

### Mapping file requirements

`data/mapping.xlsx` is read column-by-column:

- each column name becomes an indicator group name
- each non-empty cell in that column is treated as an indicator belonging to that group

This means the workbook structure should look like:

```text
| Družbeni kazalniki | Okoljski kazalniki | ... |
| indicator A        | indicator X        | ... |
| indicator B        | indicator Y        | ... |
```

### GeoJSON requirements

The GeoJSON should contain municipality polygons. The code tries to auto-detect a municipality name property from:

- `name`
- `NAME`
- `Občina`
- `OBČINA`

If none match, the first property key in the feature is used.

## Assets

### Group selector buttons

The image selector uses files configured in `GROUP_BUTTON_IMAGE_FILES` in `tourism_dashboard/config.py`.

They currently live in:

- `assets/buttons/`

### AI icon

- `assets/icons/AI image.png`

### Footer logo

- `assets/logos/footer_logo.jpg`

### Title images

- fallback image: `assets/title/Title.jpg`
- slideshow images: `assets/title/slides/`

If slideshow images exist, the header cycles through them. If not, the fallback image is used.

## How to use the app

### Login

On startup the user sees a password form:

- title: `Prijava`
- input: `Geslo`
- button: `Vstopi`

Authentication is stored in `st.session_state["authenticated"]`.

### Sidebar

The sidebar contains:

- Excel uploader
- GeoJSON uploader
- `Dashboard način (več kazalnikov)` checkbox

If no file is uploaded:

- the Excel is auto-loaded from `data/`
- the GeoJSON is auto-loaded from `data/si.json`

### Main tabs

The app has two tabs:

- `Kazalniki`
- `Struktura prenočitev po trgih`

### Kazalniki tab

This tab allows the user to:

- choose a territorial view
- choose a region or `Vsa območja`
- choose an indicator group through image buttons
- choose the map indicator
- optionally choose up to 6 dashboard indicators
- view the relevant map, KPIs, and table
- view group-specific top/bottom sections
- view AI commentary for the selected area

### Struktura prenočitev po trgih tab

This tab allows the user to:

- choose year
- choose territorial view
- choose an area
- see normalized market-share pie charts
- inspect either whole-area market structure or municipal market structure

## How aggregation works

Indicator aggregation is driven by `AGG_RULES` in `tourism_dashboard/config.py`.

Supported aggregation modes:

- `sum`
  Used for additive indicators such as counts, total revenues, total overnight stays, and total capacities.
- `mean`
  Used for simple averages where equal weighting is appropriate.
- `wmean`
  Used for weighted averages where a denominator or scale column should act as the weight.

Example:

```python
"Delež tujih prenočitev - 2024": ("wmean", "Prenočitve turistov SKUPAJ - 2024")
```

This means:

- do not sum the percentages
- compute a weighted average across municipalities
- use total overnight stays as weights

## Top/bottom methodology

The top/bottom section is intentionally not a naive ranking.

### Separate ranking per group

Each indicator group is ranked separately using limits from `TOP_BOTTOM_GROUP_LIMITS`:

- `Družbeni kazalniki`: top 4 / bottom 4
- `Okoljski kazalniki`: top 3 / bottom 3
- `Ekonomski nastanitveni in tržni turistični kazalniki`: top 5 / bottom 5
- `Ekonomsko poslovni kazalniki turistične dejavnosti`: top 5 / bottom 5

### Excluded indicators

Indicators listed in `TOP_BOTTOM_EXCLUDED_INDICATORS` are removed from the top/bottom analysis.

This is where you exclude indicators that are:

- structurally misleading in ranking
- too size-dependent
- not meaningful for comparative interpretation
- manually marked for exclusion in previous project decisions

### Lower-is-better indicators

Indicators in `LOWER_IS_BETTER_INDICATORS` are direction-adjusted so that a lower raw value can still count as a stronger result in ranking.

### Special handling for cumulative indicators

For `sum` indicators, the comparison is not simply:

- region total vs Slovenia total

That would strongly favor larger regions.

Instead, the app derives a comparison base via `get_sum_comparison_base()` and compares:

- the region share of the indicator within Slovenia
- against the region share of an appropriate base quantity such as population, area, employment, total firms, or overnight stays

Example logic:

- population counts are compared against the region share of area
- overnight stays are compared against the region share of population
- sector revenues may be compared against the region share of sector employment

The result is expressed in percentage points (`o.t.`), not as a raw total gap.

### Precomputed indicators

Some indicators are not read directly as normal aggregations. They are derived in `get_precomputed_indicator_value()` in `tourism_dashboard/analytics.py`.

Examples include:

- GINI-based derived indicators
- revenue-per-overnight estimates
- room-based derived revenue indicators

## AI commentary

The AI commentary is built from all top/bottom sections together, not from just one group.

The flow is:

1. `build_top_bottom_group_sections()` creates per-group best/worst tables.
2. `render_region_top_bottom_and_ai()` converts those into a stable JSON payload.
3. The payload hash becomes the AI cache key.
4. The app first checks the SQL cache.
5. If no cached commentary exists, it calls the OpenAI Responses API.
6. If the API fails, a fallback commentary is generated locally.

### Cache table

The database cache table is:

```text
ai_commentary_cache
```

Columns created automatically:

- `cache_key`
- `payload_hash`
- `region`
- `group_name`
- `response_text`
- `model`
- `updated_at`

### When the cache is reused

The same cached AI response is reused if the hashed input payload is unchanged, meaning:

- same selected region
- same group top/bottom content

If any underlying top/bottom content changes, a new cache key is generated and a new AI response is requested.

## How to add a new indicator

This is the most important maintenance workflow in the project.

### Step 1. Add the indicator to the Excel file

Add a new column to the master Excel file with the exact label you want to use in the app.

Recommendations:

- keep the label stable
- do not rename existing indicators casually
- use the same year suffix style already used elsewhere

### Step 2. Add the indicator to `mapping.xlsx`

Put the exact same column name into the correct group column inside `data/mapping.xlsx`.

If you skip this step:

- the indicator may still exist in the data
- but it will not appear in the intended group selector logic
- and it will not participate in grouped top/bottom analysis

### Step 3. Decide the aggregation rule

Add the indicator to `AGG_RULES` in `tourism_dashboard/config.py`.

Choose one of:

- `("sum", None)`
- `("mean", None)`
- `("wmean", "Weight column name")`

Guidance:

- Use `sum` for additive quantities.
- Use `mean` only for genuine simple averages.
- Use `wmean` for rates, shares, occupancy, average age, profitability percentages, and similar metrics where municipalities should be weighted by a denominator.

### Step 4. Decide whether lower is better

If the indicator represents pressure, burden, cost share, waste, energy intensity, GINI concentration, or similar negative direction, add it to:

```python
LOWER_IS_BETTER_INDICATORS
```

### Step 5. Decide how it should appear in municipality tables

If the indicator is a rate or complex derived value where municipal rows should show an index relative to the selected area instead of a share, add it to:

```python
INDIKATORJI_Z_INDEKSI
```

If you do not add it there and it is not rate-like, the app may show a share-of-area column instead.

### Step 6. Decide whether it needs a shared warning

If the indicator belongs to the financially distorted group described in the shared aggregation warning, add it to:

```python
INDIKATORJI_Z_OPOMBO
```

### Step 7. Decide whether it is a currency metric

If the indicator should render with a euro suffix, add it to:

```python
INDIKATORJI_Z_VALUTO
```

### Step 8. Decide whether it should be excluded from top/bottom

If the indicator is not meaningful in top/bottom ranking, add it to:

```python
TOP_BOTTOM_EXCLUDED_INDICATORS
```

Typical reasons:

- raw totals dominated by scale
- support variables used mainly as weights or bases
- values that are too structural to interpret as strengths/weaknesses

### Step 9. If needed, add custom precomputed logic

If the indicator cannot be aggregated correctly with `sum`, `mean`, or `wmean`, extend:

```python
get_precomputed_indicator_value()
```

in `tourism_dashboard/analytics.py`.

Use this for:

- synthetic metrics
- formulas using multiple columns
- indicators with year-specific hardcoded benchmark dictionaries

### Step 10. If it is a market-share indicator

Market columns are discovered through the prefix:

```python
MARKET_PREFIX = "Delež vseh prenočitev - "
```

To be picked up automatically, name the column like:

```text
Delež vseh prenočitev - Italijanski trg - 2025
```

If you add a new market label, also update:

```python
MARKET_COLOR_MAP
```

so the pie charts get a consistent color.

### Step 11. Test the app

After adding the indicator, verify:

- it appears under the correct group
- it aggregates correctly for a region
- it formats correctly
- its map values look plausible
- it behaves correctly in the municipal table
- it does or does not appear in top/bottom as intended
- the AI commentary still generates successfully

## How to add a new territorial view

If you want a new view such as a new destination hierarchy:

1. Add the grouping column to the Excel file.
2. Add a matching candidate entry to `VIEW_CANDIDATES` in `tourism_dashboard/config.py`.
3. Ensure the column values map municipalities cleanly.
4. Test both the `Kazalniki` tab and the market structure tab.

## Troubleshooting

### The app says `Manjka APP_PASSWORD v Streamlit Secrets.`

Add:

```toml
APP_PASSWORD = "your-password"
```

to `.streamlit/secrets.toml` or Streamlit Cloud secrets.

### AI commentary is always fallback text

Check:

- `OPENAI_API_KEY` exists
- the key has billing/quota
- the network environment allows outbound requests

### AI cache is not being used

Check:

- `[connections.ai_cache_db]` exists in secrets
- `AI_CACHE_CONNECTION_NAME` matches the configured connection name
- the database is reachable

### No map is displayed

Check:

- `data/si.json` exists
- the GeoJSON contains municipality geometries
- a municipality name property exists and matches Excel names after normalization

### Indicator groups are empty

Check:

- `data/mapping.xlsx` exists
- group column names are present
- indicator names match Excel columns exactly

### Group buttons fall back to dropdown

This means one of these failed:

- `streamlit-image-select` is not installed
- a configured button image is missing

### Imports show as unresolved in VS Code

Check:

- the correct workspace folder is open
- `.venv` is selected as the interpreter
- VS Code has reloaded after the refactor

## Developer reference

### `streamlit_app_sandbox.py`

Entrypoint only. No public helper functions are defined here.

Main responsibilities:

- configure Streamlit page
- enforce password
- load data
- build `DashboardContext`
- render the two application tabs

### `tourism_dashboard/models.py`

#### `DashboardContext`

Frozen dataclass passed into the UI rendering layer.

Fields:

- `df: pd.DataFrame`
  Full source dataframe.
- `geojson_obj: dict | None`
  Loaded municipal GeoJSON.
- `geojson_name_prop: str | None`
  Detected feature property that stores municipality name.
- `grouped_indicators: dict[str, list[str]]`
  Indicator groups loaded from `mapping.xlsx`.
- `market_cols: list[str]`
  Market-share indicator columns.
- `dashboard_mode: bool`
  Whether dashboard KPIs are enabled.
- `meta_cols: set[str]`
  Non-indicator columns that should be excluded from indicator lists.

### Function reference

The sections below list every function currently defined in the package, with expected inputs and outputs.

### `tourism_dashboard/auth.py`

- `require_password() -> None`
  Shows the login form, compares the entered password with `st.secrets["APP_PASSWORD"]`, stores authentication state in `st.session_state`, and stops execution until the user is authenticated.

### `tourism_dashboard/paths.py`

- `first_existing(*paths: Path) -> Path`
  Returns the first path that exists. If none exist, returns the first supplied path unchanged.
  Inputs:
  `paths`: one or more `pathlib.Path` values.

### `tourism_dashboard/helpers.py`

- `find_excel_file() -> Path | None`
  Searches for the default Excel file first in `data/`, then the project root, then falls back to the first `.xlsx` it finds.

- `safe_str(value) -> str`
  Converts `None` and `NaN`-like values to an empty string and everything else to `str`.

- `normalize_name(value: str) -> str`
  Normalizes area names by trimming whitespace, collapsing repeated spaces, and normalizing hyphens.

- `strip_diacritics(value: str) -> str`
  Replaces Slovenian accented characters with ASCII equivalents for fuzzy matching.

- `canon_col(value: str) -> str`
  Converts a column name into a canonical comparison key used for tolerant column detection.

- `find_col(df: pd.DataFrame, wanted: list[str]) -> str | None`
  Finds the best-matching dataframe column for one of the wanted canonical names.
  Inputs:
  `df`: dataframe to inspect.
  `wanted`: list of normalized or partial names to search for.

- `parse_numeric(series: pd.Series) -> pd.Series`
  Parses messy numeric series containing spaces, commas, hyphens, or text noise into floats with `NaN` for invalid values.

- `shorten_label(value: str, max_len: int = 22) -> str`
  Truncates long labels with an ellipsis for chart labels.

- `col_for_year(col_name: str, year: int) -> str`
  Replaces any year in a column name with the provided year.

- `load_excel(path_or_buffer) -> pd.DataFrame`
  Loads the master Excel either from a filesystem path or Streamlit upload buffer.
  If the first row is not a usable header, it attempts a fallback header strategy.

- `try_load_geojson(path: Path)`
  Reads a GeoJSON file from disk and returns parsed JSON or `None` on failure.

- `load_indicator_groups(path: Path) -> dict[str, list[str]]`
  Cached loader for `mapping.xlsx`.
  Returns a dictionary where each column name is a group and each column's non-empty cells are indicators.

- `load_geojson_from_upload_or_file(uploaded, default_path: Path)`
  Returns uploaded GeoJSON if present, otherwise loads the default file.

- `get_secret_value(name: str, default=None)`
  Reads a secret from `st.secrets`, returning `default` on failure or if missing.

- `sql(stmt: str)`
  Wraps SQL text with SQLAlchemy `text()` if SQLAlchemy is available; otherwise returns the plain string.

### `tourism_dashboard/formatting.py`

- `is_rate_like(column_name: str) -> bool`
  Heuristic classifier for indicators that behave like rates, shares, ratios, occupancy values, or derived percentages.

- `is_lower_better(indicator: str) -> bool`
  Returns `True` if the indicator is listed in `LOWER_IS_BETTER_INDICATORS`.

- `is_percent_like(column_name: str) -> bool`
  Heuristic classifier for indicators that should be formatted as percentages.

- `format_si_number(value, decimals=None)`
  Formats numbers using Slovenian-style decimal/comma conventions.

- `format_pct(value, decimals=1)`
  Formats a numeric value as a percentage string.

- `format_comparison_delta(value, unit: str) -> str`
  Formats a signed comparison delta either as `%` or `o.t.`.

- `format_indicator_value_tables(indicator: str, value)`
  Returns rounded numeric values for tabular display.

- `format_indicator_value_map(indicator: str, value)`
  Returns fully formatted string display for KPI, map tooltip, and summary display.

- `make_localized_column_config(df: pd.DataFrame)`
  Builds Streamlit `column_config` metadata for numeric dataframe rendering.

### `tourism_dashboard/assets.py`

- `get_button_image_path(group_key: str) -> Path`
  Resolves the image path for a group selector button.

- `get_ai_icon_path() -> Path`
  Returns the current AI icon path.

- `get_title_fallback_path() -> Path`
  Returns the fallback title image path.

- `get_title_slides_dir() -> Path`
  Returns the title slideshow directory.

- `image_path_to_data_uri(path_str: str) -> str | None`
  Encodes a local image file as a browser-ready data URI.

- `load_title_slideshow_images() -> list[str]`
  Loads slideshow images from `assets/title/slides/`, returns data URIs, and falls back to `Title.jpg` if needed.

- `load_button_font(font_size: int)`
  Loads a bold font for button-image text rendering.

- `prepare_group_button_image(path_str: str, label: str = "", canvas_px: int = 360, inset_ratio: float = 0.78) -> str | None`
  Creates a cached square button image from the original asset, optionally adding a label band.
  Inputs:
  `path_str`: original image path.
  `label`: optional text label rendered into the image.
  `canvas_px`: output square size in pixels.
  `inset_ratio`: how much of the canvas the original image should occupy.

- `render_page_header()`
  Renders the large title area with image slideshow, overlay text, and header styling.

- `render_ai_section_header()`
  Renders the AI icon plus the `AI komentar in priporočila za območje` header.

### `tourism_dashboard/analytics.py`

- `get_agg_rule(indicator: str, agg_rules: dict[str, tuple[str, str | None]]) -> tuple[str, str | None]`
  Returns the aggregation rule for an indicator, defaulting to `("sum", None)`.

- `get_default_population_base(indicator: str) -> str`
  Chooses the 2024 or 2025 population denominator based on the indicator name.

- `get_sum_comparison_base(indicator: str) -> tuple[str, str]`
  Returns the reference base indicator and a human-readable label used when comparing cumulative `sum` indicators in top/bottom analysis.

- `get_precomputed_indicator_value(indicator: str, region_name: str | None, df: pd.DataFrame) -> float | None`
  Computes special-case indicators that cannot be handled by normal aggregation.
  Inputs:
  `indicator`: target indicator name.
  `region_name`: selected area name.
  `df`: subset dataframe for the selected area.

- `aggregate_indicator_with_rules(df: pd.DataFrame, indicator: str, agg_rules: dict[str, tuple[str, str | None]] = AGG_RULES, region_name: str | None = None) -> float`
  Aggregates one indicator for one dataframe subset using configured rules.

- `compute_region_aggregates(numeric_df: pd.DataFrame, regions: list[str], indicator_cols: list[str], agg_rules: dict[str, tuple[str, str | None]], group_col: str) -> pd.DataFrame`
  Aggregates a list of indicators for all regions in the selected territorial view.

- `compute_indicator_comparison(reg_df: pd.DataFrame, indicator: str, agg_rules: dict[str, tuple[str, str | None]], region_name: str, df_slo_total_num: pd.Series) -> dict[str, Any] | None`
  Builds one comparison row for the top/bottom engine.
  Returns `None` if the comparison is not valid.

- `build_top_bottom_group_sections(reg_df: pd.DataFrame, df_slo_total_num: pd.Series, grouped_filtered: dict[str, list[str]], agg_rules: dict[str, tuple[str, str | None]], region_name: str) -> list[dict[str, Any]]`
  Produces all group-level top/bottom sections used in the UI and AI prompt.

- `get_market_cols_for_year(df: pd.DataFrame, year: int) -> tuple[list[str], list[str]]`
  Finds market-share columns for a selected year and returns:
  `([full_column_names], [market_labels_without_prefix_or_year])`

### `tourism_dashboard/maps.py`

- `get_geojson_name_prop(geojson_obj: dict[str, Any], candidates: tuple[str, ...] = ("name", "NAME", "Občina", "OBČINA")) -> str | None`
  Detects which GeoJSON property stores municipality names.

- `build_region_geojson_from_municipalities(geojson_obj: dict[str, Any], name_prop: str, municipality_to_region: dict[str, str], group_col: str) -> dict[str, Any] | None`
  Dissolves municipal polygons into region polygons using `geopandas`.

- `palette(value: float | None, vmin: float, vmax: float) -> str`
  Maps numeric values to fill colors for the choropleth.

- `render_map_regions(regions_geojson: dict[str, Any], region_to_value: dict[str, float], indicator_label: str, group_col: str, height: int = 680) -> None`
  Renders a region-level folium map.

- `render_map_municipalities(geojson_obj: dict[str, Any] | None, name_prop: str, municipalities_in_region: set[str], municipality_to_value: dict[str, float], indicator_label: str = "Vrednost", height: int = 680) -> None`
  Renders a municipal map, highlighting municipalities inside the selected area and graying out the rest.

### `tourism_dashboard/ai.py`

- `get_ai_cache_connection() -> Tuple[Optional[Any], str]`
  Opens the configured Streamlit SQL connection for AI cache use and returns `(connection, connection_name)`.

- `ensure_ai_cache_table(conn: Any) -> bool`
  Creates the cache table if it does not exist.

- `get_cached_ai_commentary(cache_key: str) -> Optional[Dict[str, Any]]`
  Reads a cached AI response by cache key.

- `store_cached_ai_commentary(cache_key: str, *, payload_hash: str, region_name: str, group_name: str, text: str, model: str) -> None`
  Upserts a cached AI commentary entry into the SQL table.

- `rows_to_prompt_lines(rows: List[Dict[str, Any]]) -> str`
  Converts top/bottom table rows into bullet-like prompt lines for the LLM.

- `grouped_rows_to_prompt_text(group_sections: List[Dict[str, Any]]) -> str`
  Combines all group sections into the final prompt body used for the OpenAI call.

- `fallback_region_commentary(region_name: str, group_sections: List[Dict[str, Any]]) -> str`
  Builds a local non-AI summary when API usage is unavailable.

- `extract_response_text(resp_json: Dict[str, Any]) -> Optional[str]`
  Extracts the text body from an OpenAI Responses API JSON response.

- `extract_openai_error_fields(resp: Any) -> Tuple[Optional[str], Optional[str], Optional[str]]`
  Pulls out message, error type, and code from a failed OpenAI response.

- `format_openai_http_error(resp: Any) -> str`
  Formats a user-facing error string for failed HTTP responses.

- `should_retry_openai_call(status_code: int, err_type: str | None, err_code: str | None) -> bool`
  Decides whether the OpenAI request should be retried.

- `compute_retry_delay_seconds(resp: Any, attempt_index: int) -> float`
  Computes retry delay, honoring `Retry-After` when present.

- `generate_region_ai_commentary(region_name: str, group_sections: List[Dict[str, Any]]) -> Tuple[str, str, Optional[str]]`
  Calls the OpenAI Responses API and returns:
  `(commentary_text, source, error_message)`
  where `source` is typically `ai` or `fallback`.

### `tourism_dashboard/ui.py`

- `show_shared_warning_if_needed_indicator(indicator_name: str)`
  Displays a short warning title for indicators listed in `INDIKATORJI_Z_OPOMBO`.

- `show_shared_warning_if_needed_map(indicator_name: str)`
  Displays the full warning text for indicators listed in `INDIKATORJI_Z_OPOMBO`.

- `green_metric(label, value)`
  Renders a large green metric card.

- `green_metric_small(label, value)`
  Renders a compact green metric card.

- `build_filtered_indicator_groups(indicator_cols: list[str], grouped_indicators: dict[str, list[str]]) -> tuple[dict[str, list[str]], dict[str, str]]`
  Filters configured indicator groups down to indicators present in the current dataframe and returns both:
  `grouped_filtered` and `indicator_to_group`.

- `build_group_selector_specs(indicator_cols: list[str], grouped_filtered: dict[str, list[str]]) -> list[dict[str, Any]]`
  Builds the metadata used to render the image-based group selector.

- `render_group_selector(group_col: str, indicator_cols: list[str], grouped_filtered: dict[str, list[str]]) -> str`
  Renders the image selector or fallback dropdown and returns the selected group key.

- `build_region_indicator_table(region_df: pd.DataFrame, indicator: str, region_total, view_title: str) -> pd.DataFrame`
  Builds the municipality table for a selected area and indicator.

- `format_indicator_option_label(indicator: str, indicator_to_group: dict[str, str]) -> str`
  Adds group emoji prefix to indicator labels shown in selects.

- `render_region_top_bottom_and_ai(selected_region: str, group_col: str, group_sections: list[dict[str, Any]]) -> None`
  Renders grouped top/bottom tabs, loads or generates AI commentary, and shows the result.

- `render_view(view_title: str, group_col: str, ctx: DashboardContext) -> None`
  Renders the complete `Kazalniki` tab for one territorial view.
  Inputs:
  `view_title`: user-facing label such as `Turistične regije`.
  `group_col`: dataframe column used as the grouping field.
  `ctx`: `DashboardContext` bundle.

- `render_market_structure(view_title: str, group_col: str, ctx: DashboardContext) -> None`
  Renders the `Struktura prenočitev po trgih` tab for one territorial view.

## Configuration reference

The most important configuration points in `tourism_dashboard/config.py` are:

- `VIEW_CANDIDATES`
  Which territorial view columns the app can discover.
- `AGG_RULES`
  Aggregation behavior for each indicator.
- `GROUP_BUTTON_IMAGE_FILES`
  Group selector button image mapping.
- `TOP_BOTTOM_GROUP_LIMITS`
  Per-group top/bottom sizes.
- `TOP_BOTTOM_EXCLUDED_INDICATORS`
  Indicators excluded from top/bottom analysis.
- `LOWER_IS_BETTER_INDICATORS`
  Direction overrides for ranking.
- `INDIKATORJI_Z_INDEKSI`
  Indicators treated as index-like in municipality tables.
- `INDIKATORJI_Z_OPOMBO`
  Indicators that trigger the shared warning.
- `INDIKATORJI_Z_VALUTO`
  Indicators formatted as currency.
- `MARKET_PREFIX`
  Prefix used to auto-discover market-share columns.
- `MARKET_COLOR_MAP`
  Color mapping for market pie charts.

## Recommended maintenance workflow

Whenever you change the dataset or indicators:

1. Update the Excel.
2. Update `mapping.xlsx`.
3. Update `AGG_RULES`.
4. Update any relevant indicator sets in `config.py`.
5. If needed, extend `get_precomputed_indicator_value()`.
6. Run the app locally.
7. Test:
   - all views
   - one selected region
   - `Vsa območja`
   - top/bottom tabs
   - AI section
   - market structure tab

## Suggested future improvements

- Add automated tests for aggregation and top/bottom logic.
- Add schema validation for Excel column presence.
- Add an admin/debug page showing resolved file paths and active secrets/config.
- Move especially large constant sets into smaller dedicated config modules if the project keeps growing.
