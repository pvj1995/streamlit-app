import base64
import hashlib
import re
import tempfile
import textwrap
from pathlib import Path

import streamlit as st

from tourism_dashboard.config import (
    AI_ICON_FILENAME,
    APP_DESCRIPTION,
    APP_KICKER,
    APP_SUBTITLE,
    APP_TITLE,
    GROUP_BUTTON_IMAGE_FILES,
    TITLE_FALLBACK_FILENAME,
)
from tourism_dashboard.paths import (
    BASE_DIR,
    BUTTONS_DIR,
    ICONS_DIR,
    TITLE_DIR,
    TITLE_SLIDES_DIR,
    first_existing,
)


try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None


def get_button_image_path(group_key: str) -> Path:
    filename = GROUP_BUTTON_IMAGE_FILES.get(group_key, "")
    return first_existing(BUTTONS_DIR / filename, BASE_DIR / filename)


def get_ai_icon_path() -> Path:
    return first_existing(ICONS_DIR / AI_ICON_FILENAME, BASE_DIR / AI_ICON_FILENAME)


def get_title_fallback_path() -> Path:
    return first_existing(TITLE_DIR / TITLE_FALLBACK_FILENAME, BASE_DIR / TITLE_FALLBACK_FILENAME)


def get_title_slides_dir() -> Path:
    return first_existing(TITLE_SLIDES_DIR, BASE_DIR / "Title")


@st.cache_data(show_spinner=False)
def image_path_to_data_uri(path_str: str) -> str | None:
    source = Path(path_str)
    if not source.exists():
        return None

    suffix = source.suffix.lower()
    mime = "image/png"
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".webp":
        mime = "image/webp"

    raw = base64.b64encode(source.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{raw}"


@st.cache_data(show_spinner=False)
def load_title_slideshow_images() -> list[str]:
    title_dir = get_title_slides_dir()
    if not title_dir.exists() or not title_dir.is_dir():
        fallback = image_path_to_data_uri(str(get_title_fallback_path()))
        return [fallback] if fallback else []

    def natural_sort_key(path: Path):
        parts = re.split(r"(\d+)", path.name.lower())
        return [int(part) if part.isdigit() else part for part in parts]

    image_paths = sorted(
        [
            path for path in title_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ],
        key=natural_sort_key,
    )
    image_uris = [image_path_to_data_uri(str(path)) for path in image_paths]
    image_uris = [image_uri for image_uri in image_uris if image_uri]
    if image_uris:
        return image_uris

    fallback = image_path_to_data_uri(str(get_title_fallback_path()))
    return [fallback] if fallback else []


def load_button_font(font_size: int):
    if ImageFont is None:
        return None
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
    except Exception:
        try:
            return ImageFont.truetype("Arial Bold.ttf", font_size)
        except Exception:
            return ImageFont.load_default()


@st.cache_data(show_spinner=False)
def prepare_group_button_image(
    path_str: str,
    label: str = "",
    canvas_px: int = 360,
    inset_ratio: float = 0.78,
) -> str | None:
    source = Path(path_str)
    if not source.exists():
        return None
    if Image is None or ImageDraw is None:
        return str(source)

    try:
        render_version = "v4"
        signature = (
            f"{render_version}|{source.resolve()}|{source.stat().st_mtime_ns}|"
            f"{label}|{canvas_px}|{inset_ratio}"
        )
        cache_name = hashlib.md5(signature.encode("utf-8")).hexdigest()[:16]
        cache_dir = Path(tempfile.gettempdir()) / "streamlit_button_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        out_path = cache_dir / f"{source.stem}_{cache_name}.png"
        if out_path.exists():
            return str(out_path)

        with Image.open(source) as img:
            img = img.convert("RGBA")
            side = max(120, int(canvas_px))
            has_label = bool(label.strip())
            label_band_height = int(side * 0.31) if has_label else 0
            image_area_height = side - label_band_height - int(side * 0.04)
            fit_width = max(1, int(side * inset_ratio))
            fit_height = max(1, int(image_area_height * 0.88))
            scale = min(fit_width / max(1, img.width), fit_height / max(1, img.height))
            new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
            resized = img.resize(new_size, resampling)

            square = Image.new("RGBA", (side, side), (248, 250, 252, 255))
            offset = ((side - new_size[0]) // 2, max(8, (image_area_height - new_size[1]) // 2))
            square.paste(resized, offset, resized)

            if has_label:
                band_top = side - label_band_height
                draw = ImageDraw.Draw(square)
                draw.rectangle([(0, band_top), (side, side)], fill=(255, 255, 255, 245))
                text_color = (28, 37, 54, 255)
                best_text = label
                best_font = load_button_font(max(14, int(side * 0.06)))
                best_overflow = None
                spacing = 4
                max_text_width = side * 0.88
                band_inner_top = band_top + int(side * 0.025)
                band_inner_bottom = side - int(side * 0.04)
                max_text_height = max(1, band_inner_bottom - band_inner_top)
                manual_multiline = "\n" in label

                for font_size in range(max(18, int(side * 0.074)), 11, -1):
                    font = load_button_font(font_size)
                    if font is None:
                        continue
                    candidate_texts = (
                        [label]
                        if manual_multiline
                        else [textwrap.fill(label, width=wrap_width) for wrap_width in range(10, 22)]
                    )
                    for wrapped in candidate_texts:
                        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center", spacing=spacing)
                        text_width = bbox[2] - bbox[0]
                        text_height = bbox[3] - bbox[1]
                        overflow = max(text_width - max_text_width, 0) + max(text_height - max_text_height, 0)

                        if best_overflow is None or overflow < best_overflow:
                            best_overflow = overflow
                            best_text = wrapped
                            best_font = font

                        if overflow <= 0:
                            best_text = wrapped
                            best_font = font
                            best_overflow = overflow
                            break
                    if best_overflow == 0:
                        break

                text_bbox = draw.multiline_textbbox(
                    (0, 0),
                    best_text,
                    font=best_font,
                    align="center",
                    spacing=spacing,
                )
                text_width = text_bbox[2] - text_bbox[0]
                text_height = text_bbox[3] - text_bbox[1]
                text_x = (side - text_width) / 2
                text_y = band_inner_top + max((max_text_height - text_height) / 2, 0) - text_bbox[1]
                draw.multiline_text(
                    (text_x, text_y),
                    best_text,
                    fill=text_color,
                    font=best_font,
                    align="center",
                    spacing=spacing,
                )

            square.save(out_path, format="PNG", optimize=True)
        return str(out_path)
    except Exception:
        return str(source)


def render_page_header():
    title_slideshow_images = load_title_slideshow_images()
    title_slideshow_step_seconds = 6
    title_slideshow_spacer = title_slideshow_images[0] if title_slideshow_images else ""
    title_slideshow_count = max(1, len(title_slideshow_images))
    title_slideshow_total_seconds = title_slideshow_count * title_slideshow_step_seconds
    title_slide_visible_pct = (title_slideshow_step_seconds * 0.72 / title_slideshow_total_seconds) * 100
    title_slide_fade_end_pct = (title_slideshow_step_seconds / title_slideshow_total_seconds) * 100
    title_slide_animation_css = (
        "animation: none; opacity: 1;"
        if len(title_slideshow_images) <= 1
        else (
            "animation: titleSlideFade "
            f"{title_slideshow_total_seconds}s linear infinite; animation-fill-mode: both;"
        )
    )
    title_slideshow_html = "\n".join(
        (
            f'<img class="title-slide" src="{image_uri}" alt="Naslovna slika {idx + 1}" '
            f'style="animation-delay: {-idx * title_slideshow_step_seconds}s;" />'
        )
        for idx, image_uri in enumerate(title_slideshow_images)
    )

    st.html(
        f"""
        <style>
        body {{
            margin: 0;
            font-family: "Source Sans Pro", sans-serif;
        }}
        .title-panel {{
            position: relative;
            overflow: hidden;
            border-radius: 24px;
            margin: 0 0 8px 0;
            box-shadow: 0 16px 36px rgba(17, 24, 39, 0.10);
            color: #1f2937;
            background: #eef2f7;
        }}
        .title-panel-media {{
            position: relative;
            width: 100%;
        }}
        .title-slide-spacer {{
            display: block;
            width: 100%;
            height: auto;
            visibility: hidden;
        }}
        .title-slide-layer {{
            position: absolute;
            inset: 0;
            overflow: hidden;
        }}
        .title-slide {{
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            object-fit: contain;
            opacity: 0;
            {title_slide_animation_css}
        }}
        .title-slide:first-child {{
            opacity: 1;
        }}
        @keyframes titleSlideFade {{
            0% {{ opacity: 1; }}
            {title_slide_visible_pct:.4f}% {{ opacity: 1; }}
            {title_slide_fade_end_pct:.4f}% {{ opacity: 0; }}
            100% {{ opacity: 0; }}
        }}
        .title-panel-overlay {{
            position: absolute;
            inset: 0;
            background: linear-gradient(
                180deg,
                rgba(10, 18, 32, 0.04) 0%,
                rgba(10, 18, 32, 0.10) 42%,
                rgba(10, 18, 32, 0.42) 100%
            );
        }}
        .title-panel-content {{
            position: absolute;
            left: 28px;
            bottom: 28px;
            width: min(74%, 1200px);
            padding: 22px 26px;
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            box-sizing: border-box;
            background: linear-gradient(
                180deg,
                rgba(15, 23, 42, 0.08) 0%,
                rgba(15, 23, 42, 0.18) 100%
            );
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 20px;
            backdrop-filter: blur(2px);
        }}
        .app-kicker {{
            font-size: 26px;
            font-style: italic;
            font-weight: 500;
            letter-spacing: 0.02em;
            line-height: 1.05;
            margin-bottom: 10px;
            color: rgba(255, 255, 255, 0.98);
            text-shadow: 0 2px 12px rgba(15, 23, 42, 0.30);
        }}
        .app-title {{
            font-size: 42px;
            font-weight: 800;
            line-height: 1.1;
            margin-bottom: 4px;
            color: #ffffff;
            text-shadow: 0 2px 14px rgba(15, 23, 42, 0.35);
        }}
        .app-title .copyright {{
            font-weight: 400;
            font-size: 0.6em;
            vertical-align: super;
        }}
        .app-subtitle {{
            font-size: 34px;
            font-style: italic;
            font-weight: 500;
            color: rgba(255, 255, 255, 0.96);
            margin-bottom: 8px;
            line-height: 1.1;
            text-shadow: 0 2px 12px rgba(15, 23, 42, 0.30);
        }}
        .app-description {{
            font-size: 16px;
            font-style: italic;
            color: rgba(255, 255, 255, 0.92);
            line-height: 1.4;
            max-width: 1200px;
            text-shadow: 0 2px 10px rgba(15, 23, 42, 0.28);
        }}
        @media (max-width: 900px) {{
            .title-panel {{
                border-radius: 18px;
            }}
            .title-panel-content {{
                left: 16px;
                right: 16px;
                bottom: 16px;
                width: auto;
                padding: 16px 16px;
                border-radius: 16px;
            }}
            .app-kicker {{
                font-size: 20px;
                margin-bottom: 8px;
            }}
            .app-title {{
                font-size: 30px;
            }}
            .app-subtitle {{
                font-size: 24px;
            }}
            .app-description {{
                font-size: 14px;
            }}
        }}
        </style>
        <div class="title-panel">
            <div class="title-panel-media">
                <img class="title-slide-spacer" src="{title_slideshow_spacer}" alt="" />
                <div class="title-slide-layer">
                    {title_slideshow_html}
                </div>
                <div class="title-panel-overlay"></div>
                <div class="title-panel-content">
                    <div class="app-kicker">{APP_KICKER}</div>
                    <div class="app-title">
                        {APP_TITLE} <span class="copyright">©</span>
                    </div>
                    <div class="app-subtitle">{APP_SUBTITLE}</div>
                    <div class="app-description">{APP_DESCRIPTION}</div>
                </div>
            </div>
        </div>
        """
    )


def render_ai_section_header():
    ai_icon_uri = image_path_to_data_uri(str(get_ai_icon_path()))
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:0.4rem; margin:0.1rem 0 0.7rem 0;">
            <img src="{ai_icon_uri or ''}" alt="AI" style="width:72px; height:72px; object-fit:contain; display:block;" />
            <div style="font-family:'Source Sans', sans-serif; font-size:1.75rem; font-weight:600; line-height:1.6; margin:0; color:inherit;">
                AI komentar in priporočila za območje
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

