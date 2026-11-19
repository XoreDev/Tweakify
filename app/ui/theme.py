"""Tweakify 1.2 design system: "Obsidian".

- One near-black neutral ramp (dark) or a cool paper ramp (light). Layers are told
  apart by lightness and a 1px hairline, never by drop shadows or gradients.
- One user-selectable accent (Sky light blue by default) used only for primary actions,
  selection, focus, and live data. Semantic colors only carry meaning:
  green = on/safe, amber = pending/advanced, red = experimental/failed.
- Type: Segoe UI Variable Display for headings and numbers, Text for body.
- Spacing scale 4/8/12/16/24/32; radii 6 (chips), 8 (controls), 12 (cards).
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ThemePalette:
    mode: str
    text: str
    text_muted: str
    text_subtle: str
    window: str
    sidebar: str
    surface: str
    surface_raised: str
    surface_hover: str
    inset: str
    border: str
    border_strong: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    accent_soft: str
    accent_soft_border: str
    positive: str
    positive_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    scroll_thumb: str
    scroll_thumb_hover: str


def _rgba(hex_color: str, alpha: int) -> str:
    value = hex_color.lstrip("#")
    red, green, blue = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return f"rgba({red}, {green}, {blue}, {alpha})"


# Each accent: (dark-mode color, dark hover, dark pressed, text-on-accent dark,
#               light-mode color, light hover, light pressed, text-on-accent light)
ACCENTS: dict[str, tuple[str, str, str, str, str, str, str, str]] = {
    "sky": ("#6CC8FF", "#8FD5FF", "#47B6F5", "#021422", "#0284C7", "#0B93D8", "#0369A1", "#FFFFFF"),
    "volt": ("#C6F432", "#D4F865", "#AFDA1F", "#0B0F00", "#4D7C0F", "#5A8F14", "#3F660C", "#FFFFFF"),
    "cyan": ("#22D3EE", "#4BDDF2", "#0FB5CF", "#03141A", "#0E7490", "#0F86A6", "#0B5F76", "#FFFFFF"),
    "azure": ("#5B9BFF", "#7DB0FF", "#3D85F5", "#020B1C", "#2563EB", "#3B74F0", "#1D4FC4", "#FFFFFF"),
    "ember": ("#FF8A4C", "#FFA26F", "#F0702E", "#1C0800", "#C2410C", "#D24F15", "#9A3409", "#FFFFFF"),
    "rose": ("#FF5C8A", "#FF7EA1", "#F23D72", "#1F0010", "#BE185D", "#CF2A6D", "#9B124B", "#FFFFFF"),
}
ACCENT_LABELS = {"sky": "Sky", "volt": "Volt", "cyan": "Cyan", "azure": "Azure", "ember": "Ember", "rose": "Rose"}
DEFAULT_ACCENT = "sky"

_BASE: dict[str, ThemePalette] = {
    "dark": ThemePalette(
        mode="dark",
        text="#F2F4F7",
        text_muted="#9399A6",
        text_subtle="#5E6573",
        window="#08090B",
        sidebar="#0C0D10",
        surface="#111317",
        surface_raised="#171A1F",
        surface_hover="#1C2026",
        inset="#0A0B0E",
        border="#1E2229",
        border_strong="#2B313B",
        accent="", accent_hover="", accent_pressed="", accent_text="", accent_soft="", accent_soft_border="",
        positive="#3DDC97",
        positive_soft=_rgba("#3DDC97", 30),
        warning="#F5B544",
        warning_soft=_rgba("#F5B544", 30),
        danger="#FF5F5F",
        danger_soft=_rgba("#FF5F5F", 30),
        scroll_thumb="#262B34",
        scroll_thumb_hover="#363D49",
    ),
    "light": ThemePalette(
        mode="light",
        text="#0F1115",
        text_muted="#5A6170",
        text_subtle="#8A909C",
        window="#F3F4F6",
        sidebar="#ECEEF1",
        surface="#FFFFFF",
        surface_raised="#F8F9FA",
        surface_hover="#F0F2F5",
        inset="#F4F5F7",
        border="#E1E4E9",
        border_strong="#CDD2DA",
        accent="", accent_hover="", accent_pressed="", accent_text="", accent_soft="", accent_soft_border="",
        positive="#0E9F6E",
        positive_soft=_rgba("#0E9F6E", 26),
        warning="#B7791F",
        warning_soft=_rgba("#B7791F", 26),
        danger="#DC2626",
        danger_soft=_rgba("#DC2626", 24),
        scroll_thumb="#CDD2DA",
        scroll_thumb_hover="#B3BAC5",
    ),
}

# Icons come from Segoe Fluent Icons (Windows 11), which keeps the Segoe MDL2
# Assets (Windows 10) code points for every glyph used here.
ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
NAV_ICONS = {
    "dashboard": "",  # Home
    "presets": "",  # Library
    "startup": "",  # Power
    "performance": "",  # SpeedHigh
    "gaming": "",  # Game
    "network": "",  # Globe
    "privacy": "",  # Shield
    "services": "",  # Manage
    "cleanup": "",  # Broom
    "input_ui": "",  # Mouse
    "graphics": "",  # TVMonitor
    "compatibility": "",  # CheckList
    "restore": "",  # History
    "settings": "",  # Settings
}
ICONS = {
    "brand": "",  # LightningBolt
    "search": "",
    "chevron_down": "",
    "chevron_up": "",
    "chevron_right": "",
    "close": "",
    "refresh": "",
    "play": "",
    "check": "",
    "warning": "",
    "error": "",
    "info": "",
    "cpu": "",  # Processing
    "memory": "",  # Memory chip (falls back cleanly)
    "gpu": "",
    "disk": "",  # HardDrive
    "ping": "",  # Network
    "restore_point": "",  # UpdateRestore
    "task_manager": "",  # Diagnostic
    "broom": "",
    "bolt": "",
    "export": "",  # Export
    "import": "",  # Import
    "trash": "",
    "sun": "",
    "moon": "",
    "shield": "",
    "clock": "",
    "sparkle": "",  # Lightbulb-ish highlight
    "filter": "",
    "game": "",
    "lock": "",
}
BRAND_GLYPH = ICONS["brand"]

DISPLAY_FONT = '"Segoe UI Variable Display", "Segoe UI", sans-serif'
TEXT_FONT = '"Segoe UI Variable Text", "Segoe UI", sans-serif'
MONO_FONT = '"Cascadia Mono", "Cascadia Code", Consolas, monospace'


def resolve_theme_mode(preference: str, system_mode: str) -> str:
    if preference == "system":
        return system_mode if system_mode in _BASE else "dark"
    return preference if preference in _BASE else "dark"


def resolve_accent(accent: str | None) -> str:
    return accent if accent in ACCENTS else DEFAULT_ACCENT


def palette_for(mode: str, accent: str | None = None) -> ThemePalette:
    resolved = resolve_theme_mode(mode, "dark")
    base = _BASE[resolved]
    a = ACCENTS[resolve_accent(accent)]
    color, hover, pressed, on_accent = a[0:4] if resolved == "dark" else a[4:8]
    return replace(
        base,
        accent=color,
        accent_hover=hover,
        accent_pressed=pressed,
        accent_text=on_accent,
        accent_soft=_rgba(color, 28 if resolved == "dark" else 22),
        accent_soft_border=_rgba(color, 110 if resolved == "dark" else 120),
    )


def score_color(palette: ThemePalette, score: int) -> str:
    if score >= 75:
        return palette.positive
    if score >= 55:
        return palette.warning
    return palette.danger


def build_app_stylesheet(
    resolved_theme_mode: str = "dark",
    accent_intensity: float = 0.62,
    compact_mode: bool = False,
    accent: str | None = None,
) -> str:
    p = palette_for(resolved_theme_mode, accent)
    del accent_intensity  # kept for settings-file compatibility; the accent is a fixed design token now
    row_pad = "10px 16px" if compact_mode else "14px 18px"
    btn_pad = "6px 12px" if compact_mode else "8px 14px"
    nav_pad = "7px 10px" if compact_mode else "9px 10px"

    return f"""
QWidget {{
    background: transparent;
    color: {p.text};
    font-family: {TEXT_FONT};
    font-size: 10pt;
}}
QMainWindow, QWidget#appRoot {{ background: {p.window}; }}
QToolTip {{
    background: {p.surface_raised}; color: {p.text};
    border: 1px solid {p.border_strong}; border-radius: 6px; padding: 6px 8px;
}}

/* ======================= Shell ======================= */
QFrame#sidebar {{ background: {p.sidebar}; border-right: 1px solid {p.border}; }}
QLabel#brandName {{ font-family: {DISPLAY_FONT}; font-size: 14pt; font-weight: 700; }}
QLabel#versionTag {{
    color: {p.accent}; background: {p.accent_soft}; border: 1px solid {p.accent_soft_border};
    border-radius: 6px; padding: 1px 6px; font-size: 8pt; font-weight: 700;
}}
QLabel#navSection {{
    color: {p.text_subtle}; font-size: 8pt; font-weight: 700;
    padding: 14px 10px 4px 10px;
}}
QPushButton#navButton {{
    text-align: left; padding: {nav_pad}; border: none; border-radius: 8px;
    background: transparent; color: {p.text_muted}; font-weight: 500;
}}
QPushButton#navButton:hover {{ background: {p.surface_hover}; color: {p.text}; }}
QPushButton#navButton:checked {{ background: {p.surface_raised}; color: {p.text}; font-weight: 600; }}
QFrame#sidebarFooter {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px; }}

QFrame#topBar {{ background: {p.window}; border-bottom: 1px solid {p.border}; }}
QPushButton#searchLauncher {{
    text-align: left; padding: 8px 12px; color: {p.text_subtle};
    background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px;
}}
QPushButton#searchLauncher:hover {{ border-color: {p.border_strong}; color: {p.text_muted}; }}
QLabel#kbd {{
    color: {p.text_subtle}; background: {p.surface_raised}; border: 1px solid {p.border_strong};
    border-radius: 4px; padding: 0px 5px; font-size: 8pt; font-weight: 600;
}}
QLabel#liveReadout {{ color: {p.text_muted}; font-size: 9pt; font-family: {DISPLAY_FONT}; }}
QPushButton#reviewLauncher {{
    padding: 7px 14px; border-radius: 8px; font-weight: 600;
    background: {p.surface}; border: 1px solid {p.border}; color: {p.text_muted};
}}
QPushButton#reviewLauncher:hover {{ border-color: {p.border_strong}; color: {p.text}; }}
QPushButton#reviewLauncher[pending="true"] {{
    background: {p.accent}; border-color: {p.accent}; color: {p.accent_text};
}}
QPushButton#reviewLauncher[pending="true"]:hover {{ background: {p.accent_hover}; }}

QFrame#reviewPanel {{ background: {p.sidebar}; border-left: 1px solid {p.border}; }}

/* ======================= Typography ======================= */
QLabel#pageTitle {{ font-family: {DISPLAY_FONT}; font-size: 20pt; font-weight: 700; }}
QLabel#pageSubtitle {{ color: {p.text_muted}; font-size: 10pt; }}
QLabel#h2 {{ font-family: {DISPLAY_FONT}; font-size: 12pt; font-weight: 600; }}
QLabel#h3 {{ font-size: 10.5pt; font-weight: 600; }}
QLabel#eyebrow {{ color: {p.text_subtle}; font-size: 8pt; font-weight: 700; }}
QLabel#muted {{ color: {p.text_muted}; }}
QLabel#subtle {{ color: {p.text_subtle}; font-size: 9pt; }}
QLabel#display {{ font-family: {DISPLAY_FONT}; font-size: 26pt; font-weight: 700; }}
QLabel#metric {{ font-family: {DISPLAY_FONT}; font-size: 18pt; font-weight: 600; }}
QLabel#metricUnit {{ color: {p.text_subtle}; font-family: {DISPLAY_FONT}; font-size: 10pt; font-weight: 600; }}
QLabel#mono, QPlainTextEdit#mono {{ font-family: {MONO_FONT}; font-size: 9pt; color: {p.text_muted}; }}
QLabel#accentText {{ color: {p.accent}; font-weight: 600; }}
QLabel#glyph {{ font-family: "Segoe Fluent Icons", "Segoe MDL2 Assets"; color: {p.text_muted}; font-size: 12pt; }}
QLabel#glyph[tone="accent"] {{ color: {p.accent}; }}
QLabel#glyph[tone="positive"] {{ color: {p.positive}; }}
QLabel#glyph[tone="warning"] {{ color: {p.warning}; }}
QLabel#glyph[tone="danger"] {{ color: {p.danger}; }}

/* ======================= Surfaces ======================= */
QFrame#card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; }}
QFrame#cardInset {{ background: {p.inset}; border: 1px solid {p.border}; border-radius: 10px; }}
QFrame#heroCard {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 14px; }}
QFrame#divider {{ background: {p.border}; border: none; max-height: 1px; min-height: 1px; }}
QFrame#vdivider {{ background: {p.border}; border: none; max-width: 1px; min-width: 1px; }}

/* Tweak rows inside a section card */
QFrame#tweakRow {{ background: transparent; border: none; border-radius: 0px; padding: 0px; }}
QFrame#tweakRow:hover {{ background: {p.surface_hover}; }}
QFrame#tweakRow[staged="true"] {{ background: {_rgba(p.accent, 13 if p.mode == "dark" else 16)}; }}
QFrame#tweakRow[flash="true"] {{ background: {p.accent_soft}; border: 1px solid {p.accent_soft_border}; }}
QFrame#stagedBar {{ background: transparent; min-width: 3px; max-width: 3px; border-radius: 1px; }}
QFrame#stagedBar[active="true"] {{ background: {p.accent}; }}
QLabel#rowTitle {{ font-size: 10.5pt; font-weight: 600; }}
QLabel#rowBody {{ color: {p.text_muted}; font-size: 9.5pt; }}
QLabel#rowReason {{ color: {p.text_subtle}; font-size: 9pt; }}
QLabel#rowReason[blocked="true"] {{ color: {p.warning}; }}
QFrame#detailsPanel {{ background: {p.inset}; border: 1px solid {p.border}; border-radius: 8px; }}
QLabel#detailKey {{ color: {p.text_subtle}; font-size: 8pt; font-weight: 700; }}
QLabel#detailValue {{ color: {p.text_muted}; font-size: 9.5pt; }}

/* ======================= Chips ======================= */
QLabel#chip {{
    border-radius: 6px; padding: 2px 8px; font-size: 8.5pt; font-weight: 600;
    color: {p.text_muted}; background: {p.surface_raised}; border: 1px solid {p.border};
}}
QLabel#chip[tone="safe"], QLabel#chip[tone="on"], QLabel#chip[tone="positive"] {{
    color: {p.positive}; background: {p.positive_soft}; border-color: transparent;
}}
QLabel#chip[tone="advanced"], QLabel#chip[tone="changed"], QLabel#chip[tone="warning"] {{
    color: {p.warning}; background: {p.warning_soft}; border-color: transparent;
}}
QLabel#chip[tone="experimental"], QLabel#chip[tone="danger"] {{
    color: {p.danger}; background: {p.danger_soft}; border-color: transparent;
}}
QLabel#chip[tone="accent"] {{ color: {p.accent}; background: {p.accent_soft}; border-color: transparent; }}
QLabel#chip[tone="off"], QLabel#chip[tone="muted"] {{ color: {p.text_subtle}; }}
QLabel#stateText {{ color: {p.text_subtle}; font-size: 9pt; }}
QLabel#stateText[tone="on"] {{ color: {p.positive}; }}
QLabel#stateText[tone="changed"] {{ color: {p.accent}; font-weight: 600; }}

/* ======================= Buttons ======================= */
QPushButton {{
    padding: {btn_pad}; border-radius: 8px; font-weight: 600;
    background: {p.surface_raised}; color: {p.text}; border: 1px solid {p.border_strong};
}}
QPushButton:hover {{ background: {p.surface_hover}; }}
QPushButton:disabled {{ color: {p.text_subtle}; background: {p.surface}; border-color: {p.border}; }}
QPushButton:focus {{ outline: none; border-color: {p.accent_soft_border}; }}
QPushButton#primaryButton {{ background: {p.accent}; color: {p.accent_text}; border: 1px solid {p.accent}; }}
QPushButton#primaryButton:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton#primaryButton:pressed {{ background: {p.accent_pressed}; }}
QPushButton#primaryButton:disabled {{ background: {p.surface_raised}; color: {p.text_subtle}; border-color: {p.border}; }}
QPushButton#ghostButton {{ background: transparent; border: 1px solid {p.border_strong}; color: {p.text}; }}
QPushButton#ghostButton:hover {{ background: {p.surface_hover}; }}
QPushButton#quietButton {{ background: transparent; border: 1px solid transparent; color: {p.text_muted}; padding: 6px 10px; }}
QPushButton#quietButton:hover {{ background: {p.surface_hover}; color: {p.text}; }}
QPushButton#quietButton:checked {{ color: {p.accent}; }}
QPushButton#detailsLink {{
    background: transparent; border: none; padding: 2px 0px; color: {p.text_subtle};
    font-family: {TEXT_FONT}, "Segoe Fluent Icons", "Segoe MDL2 Assets"; font-size: 9pt; font-weight: 600;
}}
QPushButton#detailsLink:hover {{ color: {p.text}; }}
QPushButton#detailsLink:checked {{ color: {p.accent}; }}
QPushButton#iconButton {{
    background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 6px;
    font-family: "Segoe Fluent Icons", "Segoe MDL2 Assets"; font-size: 11pt; color: {p.text_muted};
}}
QPushButton#iconButton:hover {{ background: {p.surface_hover}; color: {p.text}; }}
QPushButton#dangerButton {{ background: transparent; color: {p.danger}; border: 1px solid {p.danger_soft}; }}
QPushButton#dangerButton:hover {{ background: {p.danger_soft}; }}
QPushButton#runButton {{
    padding: 6px 14px; background: {p.surface_raised}; border: 1px solid {p.border_strong}; color: {p.text};
}}
QPushButton#runButton[staged="true"] {{ background: {p.accent_soft}; border-color: {p.accent_soft_border}; color: {p.accent}; }}
QPushButton#quickAction {{
    text-align: left; padding: 12px; border-radius: 10px; font-weight: 600;
    background: {p.surface_raised}; border: 1px solid {p.border};
}}
QPushButton#quickAction:hover {{ border-color: {p.accent_soft_border}; background: {p.surface_hover}; }}
QPushButton#swatch {{ border-radius: 13px; padding: 0px; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; }}

/* Segmented control */
QFrame#segmented {{ background: {p.inset}; border: 1px solid {p.border}; border-radius: 9px; }}
QPushButton#segment {{
    background: transparent; border: none; border-radius: 7px; padding: 5px 12px;
    color: {p.text_muted}; font-weight: 600;
}}
QPushButton#segment:hover {{ color: {p.text}; }}
QPushButton#segment:checked {{ background: {p.surface_raised}; color: {p.text}; border: 1px solid {p.border_strong}; }}

/* ======================= Inputs ======================= */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {p.inset}; border: 1px solid {p.border_strong}; border-radius: 8px;
    padding: 7px 10px; selection-background-color: {p.accent}; selection-color: {p.accent_text};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {p.accent}; }}
QLineEdit#paletteInput {{
    background: transparent; border: none; border-radius: 0px; padding: 14px 6px; font-size: 13pt;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {p.surface_raised}; border: 1px solid {p.border_strong}; border-radius: 8px;
    selection-background-color: {p.surface_hover}; selection-color: {p.text}; outline: none; padding: 4px;
}}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0px; border: none;
}}
QPlainTextEdit {{
    background: {p.inset}; border: 1px solid {p.border}; border-radius: 8px; padding: 8px;
    font-family: {MONO_FONT}; font-size: 9pt; color: {p.text_muted};
    selection-background-color: {p.accent}; selection-color: {p.accent_text};
}}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ border-radius: 8px; padding: 8px 10px; margin: 1px 0px; color: {p.text}; }}
QListWidget::item:hover {{ background: {p.surface_hover}; }}
QListWidget::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QListWidget#paletteList::item {{ padding: 0px; margin: 0px; border-radius: 8px; }}

/* Tabs styled as a segmented control */
QTabWidget::pane {{ border: none; top: 0px; }}
QTabWidget::tab-bar {{ left: 0px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {p.text_muted}; border: 1px solid transparent;
    padding: 6px 14px; margin-right: 4px; border-radius: 8px; font-weight: 600;
}}
QTabBar::tab:hover {{ color: {p.text}; }}
QTabBar::tab:selected {{ background: {p.surface_raised}; color: {p.text}; border-color: {p.border_strong}; }}

/* Command palette + toast */
QFrame#paletteScrim {{ background: rgba(0, 0, 0, {150 if p.mode == "dark" else 70}); }}
QFrame#paletteCard {{ background: {p.surface}; border: 1px solid {p.border_strong}; border-radius: 14px; }}
QFrame#toast {{ background: {p.surface_raised}; border: 1px solid {p.border_strong}; border-radius: 10px; }}

/* ======================= Scrollbars ======================= */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 4px 2px 4px 2px; }}
QScrollBar::handle:vertical {{ background: {p.scroll_thumb}; min-height: 36px; border-radius: 4px; margin: 0px 2px; }}
QScrollBar::handle:vertical:hover {{ background: {p.scroll_thumb_hover}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ height: 0px; }}
"""


APP_STYLESHEET = build_app_stylesheet()
