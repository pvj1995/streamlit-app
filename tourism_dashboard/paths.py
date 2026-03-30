from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

ASSETS_DIR = BASE_DIR / "assets"
BUTTONS_DIR = ASSETS_DIR / "buttons"
ICONS_DIR = ASSETS_DIR / "icons"
LOGOS_DIR = ASSETS_DIR / "logos"
TITLE_DIR = ASSETS_DIR / "title"
TITLE_SLIDES_DIR = TITLE_DIR / "slides"

DATA_DIR = BASE_DIR / "data"


def first_existing(*paths: Path) -> Path:
    for path in paths:
        if path.exists():
            return path
    return paths[0]

