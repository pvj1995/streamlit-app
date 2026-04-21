# Tourism Dashboard for Slovenian Destinations

Streamlit application for exploring tourism indicators across Slovenian municipalities,
destinations, tourism regions, macro destinations, and the national level.

The app provides:

- indicator maps and comparison tables
- territorial aggregation from municipality-level data
- grouped top/bottom diagnostics
- source-market structure and seasonality analysis
- optional AI commentary and recommendations
- optional PostgreSQL/Supabase-backed runtime data

Short Slovenian end-user guide: [README_uporabnik.md](./README_uporabnik.md).

## Current Architecture

The app is still pandas-based internally. That is intentional: the analytics and UI are built
around `DataFrame`s, while the data source can now be either Excel files or PostgreSQL/Supabase.

Recommended production flow:

```text
Excel source files -> import script -> PostgreSQL/Supabase -> Streamlit app
```

For development and emergency overrides, the app can still read the Excel files directly.

## Project Structure

```text
streamlit app/
├── assets/                     # images, logos, title slides, button images
├── data/                       # source Excel files and GeoJSON files
├── db/
│   └── dashboard_frames.sql    # PostgreSQL schema for imported dashboard data
├── scripts/
│   └── import_excel_to_db.py   # imports data/*.xlsx into PostgreSQL/Supabase
├── tourism_dashboard/
│   ├── ai.py                   # AI prompt, OpenAI call, AI cache
│   ├── analytics.py            # aggregation, ranking, market calculations
│   ├── assets.py               # image/header rendering helpers
│   ├── auth.py                 # password gate
│   ├── config.py               # constants, labels, aggregation rules
│   ├── database.py             # database-backed DataFrame loaders
│   ├── formatting.py           # number and table formatting
│   ├── helpers.py              # Excel loading, parsing, source selection
│   ├── maps.py                 # GeoJSON and folium rendering
│   ├── models.py               # shared dataclasses
│   ├── paths.py                # project paths
│   └── ui.py                   # Streamlit views
├── streamlit_app_sandbox.py    # Streamlit entrypoint
├── requirements.txt
├── pyrightconfig.json
├── README.md
└── README_uporabnik.md
```

## Data Sources

Required source files:

- `data/Skupna tabela občine.xlsx`
  - sheet `Skupna Tabela`
  - sheet `Rast prenočitev po trgih`
- `data/mapping.xlsx`
- `data/si.json`
- `data/si_display.json`

Market/seasonality source files:

- `data/Sezonskost prenocitev po mesecih in trgih - 2024.xlsx`
- `data/Sezonskost prenocitev po mesecih in trgih - 2025.xlsx`
- `data/Sezonskost prihodov po mesecih in trgih - 2024.xlsx`
- `data/Sezonskost prihodov po mesecih in trgih - 2025.xlsx`
- `data/Sezonskost PDB po mesecih in trgih - 2024.xlsx`
- `data/Sezonskost PDB po mesecih in trgih - 2025.xlsx`

The GeoJSON files are still loaded from disk. They are not imported into the database.

## Data Backend Modes

### Excel Mode

Excel mode is the default fallback.

```toml
DATA_BACKEND = "excel"
```

In this mode the app reads files from `data/` directly. This is useful for local development,
debugging, or when no database is configured.

### Database Mode

Database mode is recommended for private deployment.

```toml
DATA_BACKEND = "database"
DASHBOARD_DB_CONNECTION_NAME = "ai_cache_db"

[connections.ai_cache_db]
url = "postgresql://USER:PASSWORD@HOST:5432/postgres"
```

In this mode the app reads imported data from PostgreSQL/Supabase through Streamlit SQL
connections. The Excel uploader in the sidebar remains available as a temporary override.

Imported dashboard frames are cached in Streamlit for six hours
(`DASHBOARD_DB_CACHE_TTL_SECONDS` in [tourism_dashboard/config.py](./tourism_dashboard/config.py)).
After running a new import, restart the Streamlit process or clear Streamlit's cache if the new
data must appear immediately.

## Database Schema

The importer creates and updates these tables:

- `dashboard_frames`
- `dashboard_frame_columns`
- `dashboard_frame_cells`

This schema stores each parsed Excel sheet as a typed frame. It avoids creating SQL columns from
long Slovenian indicator names, and it lets the app reconstruct the same `DataFrame`s it used when
reading Excel directly.

Schema file: [db/dashboard_frames.sql](./db/dashboard_frames.sql).

## Setup

### 1. Create a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Secrets

Create `.streamlit/secrets.toml`.

Minimum local example:

```toml
APP_PASSWORD = "your-password"
```

Recommended private-server/Supabase example:

```toml
APP_PASSWORD = "your-password"
DATA_BACKEND = "database"
DASHBOARD_DB_CONNECTION_NAME = "ai_cache_db"
AI_CACHE_CONNECTION_NAME = "ai_cache_db"

[connections.ai_cache_db]
url = "postgresql://USER:PASSWORD@HOST:5432/postgres"
```

Optional AI settings:

```toml
OPENAI_API_KEY = "sk-..."
OPENAI_MODEL = "gpt-5.4"
```

Secrets:

- `APP_PASSWORD`: required
- `DATA_BACKEND`: `excel` or `database`
- `DASHBOARD_DB_CONNECTION_NAME`: Streamlit SQL connection used for dashboard data
- `AI_CACHE_CONNECTION_NAME`: Streamlit SQL connection used for AI cache
- `OPENAI_API_KEY`: optional
- `OPENAI_MODEL`: optional, defaults in code if omitted

## Importing Data Into PostgreSQL/Supabase

Run:

```bash
python scripts/import_excel_to_db.py
```

The importer:

1. reads all supported Excel files from `data/`
2. parses them using the same helper functions as the app
3. creates the database schema if missing
4. replaces current imported frames
5. prunes stale frames for the current schema version
6. verifies database contents against the parsed Excel frames

If the verification fails, treat the import as failed and do not deploy that data version.

## Updating Data

Best current workflow:

```text
edit Excel files -> run importer -> run smoke check -> deploy/restart app or clear cache
```

Do not manually edit `dashboard_frame_cells` in Supabase except for an emergency. The database is
optimized as a runtime mirror of the Excel source files, not as a friendly manual editing interface.

### Add or Remove an Indicator

1. Edit `data/Skupna tabela občine.xlsx`, sheet `Skupna Tabela`.
2. Add or remove the exact indicator label in `data/mapping.xlsx`.
3. If needed, update `AGG_RULES` in [tourism_dashboard/config.py](./tourism_dashboard/config.py).
4. If lower values are better, update `LOWER_IS_BETTER_INDICATORS`.
5. If the indicator needs special formatting or warnings, update the matching config lists.
6. Run:

```bash
python scripts/import_excel_to_db.py
```

### Update Municipality or Area Values

1. Edit values in `data/Skupna tabela občine.xlsx`.
2. Keep the `Občine` and `Turistična regija` columns intact.
3. Run the importer.

### Update Market Growth

1. Edit `data/Skupna tabela občine.xlsx`, sheet `Rast prenočitev po trgih`.
2. Preserve column naming like `Število nočitev 2025 - Domači trg`.
3. Run the importer.

### Update Monthly Market Files

1. Edit the relevant `Sezonskost ... - YEAR.xlsx` file.
2. Preserve the two-row market/month header structure.
3. Preserve expected sheet levels such as `Občine`, `Turistična regija`, `Vodilne destinacije`,
   `Perspektivne destinacije`, and `Makro destinacije`.
4. Run the importer.

### Update GeoJSON

1. Replace `data/si.json` or `data/si_display.json`.
2. Make sure municipality names match the app data after normalization.
3. Restart the app if the previous GeoJSON was cached in the Streamlit session.

## Running The App

```bash
streamlit run streamlit_app_sandbox.py
```

On first load, sign in with `APP_PASSWORD`.

## Private Server Deployment

Typical deployment shape:

```text
Nginx or Caddy -> Streamlit -> PostgreSQL/Supabase
```

Recommended server steps:

1. Clone or pull the repository.
2. Create/update `.streamlit/secrets.toml`.
3. Install dependencies in `.venv`.
4. Run `python scripts/import_excel_to_db.py` after every data update.
5. Start Streamlit with a process manager such as `systemd`, `supervisor`, or Docker.
6. Put Nginx/Caddy in front of Streamlit for TLS and domain routing.
7. Back up the PostgreSQL/Supabase database and keep source Excel files versioned.

Example Streamlit command:

```bash
streamlit run streamlit_app_sandbox.py --server.address 127.0.0.1 --server.port 8501
```

## Streamlit Community Cloud

The app can still run on Streamlit Community Cloud.

1. Push the repository to GitHub.
2. Set the entrypoint to `streamlit_app_sandbox.py`.
3. Add secrets in the Streamlit app settings.
4. Use `DATA_BACKEND = "database"` if using Supabase.
5. Keep `assets/`, `data/`, and the app code committed if Excel fallback is desired.

## Runtime Flow

At startup, `streamlit_app_sandbox.py`:

1. configures the Streamlit page
2. requires a password through `tourism_dashboard/auth.py`
3. renders the page header
4. chooses database or Excel data source
5. builds/caches the numeric dashboard bundle
6. loads GeoJSON and indicator groups
7. creates a `DashboardContext`
8. renders `Kazalniki` and `Turistični promet in sezonskost po trgih`

## Key Configuration

Most behavior is controlled from [tourism_dashboard/config.py](./tourism_dashboard/config.py):

- text labels and page copy
- file names
- database backend constants
- market labels and colors
- territorial view candidates
- aggregation rules
- top/bottom limits
- lower-is-better indicators
- formatting lists
- warning lists

## Aggregation Model

Aggregation rules are defined in `AGG_RULES`.

Supported modes:

- `sum`: additive indicators such as totals, capacities, visits, nights, and counts
- `mean`: simple averages
- `wmean`: weighted averages

Example:

```python
"Delež tujih prenočitev - 2025": ("wmean", "Prenočitve turistov SKUPAJ - 2025")
```

That means municipality percentages are weighted by total overnight stays instead of being summed.

## Top/Bottom Methodology

Top/bottom analysis is grouped by indicator category. It does not simply rank raw values.

For `sum` indicators, the app compares the region's share of the indicator against a relevant
benchmark share. For non-`sum` indicators, it compares the direct gap against Slovenia. The final
ranking score is scaled by same-level peer spread so mixed indicator types can be compared more
fairly.

Important configuration:

- `TOP_BOTTOM_GROUP_LIMITS`
- `TOP_BOTTOM_EXCLUDED_INDICATORS`
- `LOWER_IS_BETTER_INDICATORS`
- `get_sum_comparison_base()` in [tourism_dashboard/analytics.py](./tourism_dashboard/analytics.py)

## AI Commentary

AI commentary is optional.

If `OPENAI_API_KEY` is configured, the app calls the OpenAI API. If the call fails or the key is
missing, the app displays fallback commentary. If the SQL cache is available, generated commentary is
stored in `ai_commentary_cache` and reused for unchanged input payloads.

The AI cache table/security check is also cached for six hours
(`AI_CACHE_SCHEMA_TTL_SECONDS`) so normal cache reads and writes do not repeatedly run database DDL.
If an AI response is generated but cannot be saved to the SQL cache, the app displays a short cache
save warning under the AI output.

## Verification

Compile check:

```bash
python -m py_compile streamlit_app_sandbox.py tourism_dashboard/*.py scripts/*.py
```

Database import and parity check:

```bash
python scripts/import_excel_to_db.py
```

Manual smoke test:

1. Start the app.
2. Log in.
3. Open `Kazalniki`.
4. Test one `Vsa območja` view.
5. Test one individual area view.
6. Confirm the map renders.
7. Confirm top/bottom tables render.
8. Open the market tab.
9. Test 2024 and 2025.
10. Confirm AI fallback or AI commentary appears.

## Troubleshooting

### App Stops On Startup

Check that `.streamlit/secrets.toml` contains `APP_PASSWORD`.

### Database Data Is Not Used

Check:

- `DATA_BACKEND = "database"`
- `DASHBOARD_DB_CONNECTION_NAME` matches a `[connections.<name>]` block
- the connection URL is valid
- `python scripts/import_excel_to_db.py` has completed successfully

If database tables are missing, the app falls back to Excel and shows a warning.

### Map Does Not Render

Check:

- `data/si_display.json` or `data/si.json` exists
- GeoJSON municipality names match the Excel municipality names closely enough
- `geopandas`, `shapely`, and `folium` are installed

### AI Commentary Does Not Appear

Check:

- `OPENAI_API_KEY` is present if AI generation is expected
- network access is available on the server
- the configured model is available
- `AI_CACHE_CONNECTION_NAME` points to a writable SQL connection if persistent AI cache is expected

The app should still show fallback commentary if AI is unavailable.

### Updated Database Data Does Not Appear Immediately

Check:

- `python scripts/import_excel_to_db.py` completed successfully
- the Streamlit process was restarted after the import, or Streamlit cache was cleared
- `DATA_BACKEND = "database"` is active

Without a restart or cache clear, imported dashboard data can remain cached for up to six hours.

### Indicator Is Missing

Check:

- exact column name in `Skupna Tabela`
- exact label in `mapping.xlsx`
- whether the indicator is excluded from top/bottom
- whether the selected group contains that indicator

## Maintenance Rules

- Keep source Excel files versioned.
- Run the importer after every data update.
- Keep `assets/` and `data/` paths stable.
- Do not commit `.streamlit/secrets.toml`.
- Do not commit `__pycache__`, `.pyc`, `.DS_Store`, or Excel lock files.
- Prefer adding focused helpers over large changes inside `ui.py`, which is already the largest file.
