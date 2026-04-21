CREATE TABLE IF NOT EXISTS dashboard_frames (
    frame_key TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    sheet_name TEXT,
    frame_type TEXT NOT NULL,
    metric TEXT,
    year INTEGER,
    area_level TEXT,
    frame_kind TEXT,
    row_count INTEGER NOT NULL,
    column_count INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dashboard_frame_columns (
    frame_key TEXT NOT NULL REFERENCES dashboard_frames(frame_key) ON DELETE CASCADE,
    column_index INTEGER NOT NULL,
    column_name TEXT NOT NULL,
    PRIMARY KEY (frame_key, column_index)
);

CREATE TABLE IF NOT EXISTS dashboard_frame_cells (
    frame_key TEXT NOT NULL REFERENCES dashboard_frames(frame_key) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    column_index INTEGER NOT NULL,
    raw_value TEXT,
    PRIMARY KEY (frame_key, row_index, column_index)
);

CREATE INDEX IF NOT EXISTS idx_dashboard_frame_cells_frame_row
    ON dashboard_frame_cells (frame_key, row_index);

CREATE INDEX IF NOT EXISTS idx_dashboard_frames_type_metric
    ON dashboard_frames (frame_type, metric, year, area_level, frame_kind);

ALTER TABLE public.dashboard_frames ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dashboard_frame_columns ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dashboard_frame_cells ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.dashboard_frames FROM anon, authenticated;
REVOKE ALL ON TABLE public.dashboard_frame_columns FROM anon, authenticated;
REVOKE ALL ON TABLE public.dashboard_frame_cells FROM anon, authenticated;
