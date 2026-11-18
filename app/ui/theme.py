"""Tweakify design system.

One neutral "carbon" base, one accent (electric cyan), and semantic colors that only
carry meaning (green = on/safe, amber = staged/advanced, red = experimental/failed).
Surfaces are flat and layered by lightness instead of gradients and glow.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemePalette:
    mode: str
    # Text
    text: str
    text_muted: str
    text_subtle: str
    # Layers, darkest to lightest (dark mode)
    window: str
    sidebar: str
    surface: str
    surface_raised: str
    surface_hover: str
    inset: str
    border: str
    border_strong: str
    # Accent
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    accent_soft: str
    accent_soft_border: str
    # Semantic
    positive: str
    positive_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    # Scrollbars
    scroll_thumb: str
    scroll_thumb_hover: str


PALETTES: dict[str, ThemePalette] = {
    "dark": ThemePalette(
        mode="dark",
        text="#E9ECF2",
        text_muted="#9AA1B2",
        text_subtle="#6B7285",
        window="#0B0D12",
        sidebar="#0F1218",
        surface="#13161D",
        surface_raised="#191D26",
        surface_hover="#1F2430",
        inset="#0E1016",
        border="#232836",
        border_strong="#323A4D",
        accent="#22D3EE",
        accent_hover="#4BDDF2",
        accent_pressed="#0FB5CF",
        accent_text="#041218",
        accent_soft="rgba(34, 211, 238, 30)",
        accent_soft_border="rgba(34, 211, 238, 110)",
        positive="#34D399",
        positive_soft="rgba(52, 211, 153, 34)",
        warning="#FBBF24",
        warning_soft="rgba(251, 191, 36, 34)",
        danger="#F87171",
        danger_soft="rgba(248, 113, 113, 34)",
        scroll_thumb="#2B3242",
        scroll_thumb_hover="#3B4459",
    ),
    "light": ThemePalette(
        mode="light",
        text="#141821",
        text_muted="#5B6375",
        text_subtle="#8A91A2",
        window="#F3F5F8",
        sidebar="#ECEFF4",
        surface="#FFFFFF",
        surface_raised="#F8F9FB",
        surface_hover="#EEF1F6",
        inset="#F4F6F9",
        border="#DDE2EA",
        border_strong="#C5CCD8",
        accent="#0891B2",
        accent_hover="#0AA3C8",
        accent_pressed="#077A96",
        accent_text="#FFFFFF",
        accent_soft="rgba(8, 145, 178, 22)",
        accent_soft_border="rgba(8, 145, 178, 110)",
        positive="#059669",
        positive_soft="rgba(5, 150, 105, 26)",
        warning="#B45309",
        warning_soft="rgba(217, 119, 6, 26)",
        danger="#DC2626",
        danger_soft="rgba(220, 38, 38, 22)",
        scroll_thumb="#C9CFDA",
        scroll_thumb_hover="#AEB6C5",
    ),
}

# Nav icons from Segoe Fluent Icons (Windows 11), which keeps the same code points
# as Segoe MDL2 Assets (Windows 10) for these glyphs.
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
BRAND_GLYPH = ""  # LightningBolt


def resolve_theme_mode(preference: str, system_mode: str) -> str:
    if preference == "system":
        return system_mode if system_mode in PALETTES else "dark"
    return preference if preference in PALETTES else "dark"


def palette_for(mode: str) -> ThemePalette:
    return PALETTES[resolve_theme_mode(mode, "dark")]


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
) -> str:
    p = palette_for(resolved_theme_mode)
    intensity = max(0.2, min(1.0, accent_intensity))
    selection_alpha = int(40 + 90 * intensity)
    radius_lg = 10 if compact_mode else 12
    radius_md = 7 if compact_mode else 8
    radius_sm = 5 if compact_mode else 6
    pad_btn = "6px 12px" if compact_mode else "8px 14px"
    pad_nav = "7px 12px" if compact_mode else "9px 12px"

    return f"""
QWidget {{
    background: transparent;
    color: {p.text};
    font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
}}
QMainWindow, QWidget#appRoot {{
    background: {p.window};
}}
QToolTip {{
    background: {p.surface_raised};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {radius_sm}px;
    padding: 6px 8px;
}}

/* ---------- Shell ---------- */
QFrame#sidebarPanel {{
    background: {p.sidebar};
    border: 1px solid {p.border};
    border-radius: {radius_lg}px;
}}
QFrame#reviewDrawer {{
    background: {p.sidebar};
    border: 1px solid {p.border};
    border-radius: {radius_lg}px;
}}
QFrame#pagePanel {{
    background: transparent;
    border: none;
}}
QLabel#brandMark {{
    background: {p.accent};
    color: {p.accent_text};
    border-radius: {radius_md}px;
    font-family: "Segoe Fluent Icons", "Segoe MDL2 Assets";
    font-size: 14pt;
    qproperty-alignment: AlignCenter;
}}
QLabel#brandLabel {{
    font-family: "Segoe UI Variable Display", "Segoe UI";
    font-size: 15pt;
    font-weight: 700;
}}
QLabel#navSectionLabel {{
    color: {p.text_subtle};
    font-size: 8pt;
    font-weight: 700;
    padding: 10px 12px 2px 12px;
}}

/* ---------- Navigation ---------- */
QPushButton#navButton {{
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: {radius_md}px;
    color: {p.text_muted};
    padding: {pad_nav};
    text-align: left;
    font-weight: 600;
}}
QPushButton#navButton:hover {{
    background: {p.surface_hover};
    color: {p.text};
}}
QPushButton#navButton:checked {{
    background: {p.accent_soft};
    border-left: 3px solid {p.accent};
    color: {p.text};
}}

/* ---------- Surfaces ---------- */
QFrame#heroPanel {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {p.border};
    border-radius: 0px;
    padding-bottom: 4px;
}}
QFrame#metricCard,
QFrame#actionCard,
QFrame#presetCard,
QFrame#toolCard,
QFrame#dependencyCard,
QFrame#settingsGroup,
QFrame#healthCard,
QFrame#summaryCard {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {radius_lg}px;
}}
QFrame#sectionGroup {{
    background: transparent;
    border: none;
}}
QFrame#actionCard:hover,
QFrame#presetCard:hover,
QFrame#metricCard:hover {{
    border-color: {p.border_strong};
    background: {p.surface_raised};
}}
QFrame#actionCard[staged="true"] {{
    border: 1px solid {p.warning};
}}
QFrame#summaryCard {{
    border-left: 3px solid {p.accent};
}}

/* ---------- Type ---------- */
QLabel#titleLabel {{
    font-family: "Segoe UI Variable Display", "Segoe UI";
    font-size: 20pt;
    font-weight: 700;
}}
QLabel#sectionTitle {{
    font-family: "Segoe UI Variable Display", "Segoe UI";
    font-size: 11.5pt;
    font-weight: 650;
}}
QLabel#groupTitle {{
    color: {p.text_muted};
    font-size: 8.5pt;
    font-weight: 700;
    letter-spacing: 0.08em;
    padding: 6px 2px 0px 2px;
}}
QLabel#metricValue {{
    font-family: "Segoe UI Variable Display", "Segoe UI";
    font-size: 17pt;
    font-weight: 700;
}}
QLabel#metricValueSmall {{
    font-family: "Segoe UI Variable Display", "Segoe UI";
    font-size: 11pt;
    font-weight: 650;
}}
QPushButton#linkButton {{
    background: transparent;
    border: none;
    color: {p.accent};
    font-weight: 600;
    padding: 2px 4px;
}}
QPushButton#linkButton:hover {{
    color: {p.accent_hover};
    text-decoration: underline;
}}
QLabel#eyebrowLabel {{
    color: {p.text_subtle};
    font-size: 8.5pt;
    font-weight: 700;
    letter-spacing: 0.06em;
}}
QLabel#captionLabel {{
    color: {p.text_muted};
}}
QLabel#detailLabel {{
    color: {p.text_muted};
    background: {p.inset};
    border: 1px solid {p.border};
    border-radius: {radius_md}px;
    padding: 8px 10px;
    font-size: 9pt;
}}

/* ---------- Buttons ---------- */
QPushButton#accentButton {{
    background: {p.accent};
    color: {p.accent_text};
    border: 1px solid {p.accent};
    border-radius: {radius_md}px;
    padding: {pad_btn};
    font-weight: 700;
}}
QPushButton#accentButton:hover {{
    background: {p.accent_hover};
    border-color: {p.accent_hover};
}}
QPushButton#accentButton:pressed {{
    background: {p.accent_pressed};
}}
QPushButton#ghostButton,
QPushButton#actionButton {{
    background: {p.surface_raised};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {radius_md}px;
    padding: {pad_btn};
    font-weight: 600;
}}
QPushButton#ghostButton:hover,
QPushButton#actionButton:hover {{
    background: {p.surface_hover};
    border-color: {p.border_strong};
}}
QPushButton#actionButton[staged="true"] {{
    background: {p.warning_soft};
    border-color: {p.warning};
    color: {p.text};
}}
QPushButton#pillSwitch {{
    min-width: 76px;
    border-radius: 15px;
    padding: 6px 14px;
    font-weight: 700;
    background: {p.inset};
    color: {p.text_muted};
    border: 1px solid {p.border_strong};
}}
QPushButton#pillSwitch:hover {{
    border-color: {p.text_subtle};
    color: {p.text};
}}
QPushButton#pillSwitch:checked {{
    background: {p.accent};
    color: {p.accent_text};
    border: 1px solid {p.accent};
}}
QPushButton#pillSwitch:checked:hover {{
    background: {p.accent_hover};
}}
QPushButton:disabled,
QPushButton#pillSwitch:disabled,
QPushButton#accentButton:disabled {{
    background: {p.surface};
    color: {p.text_subtle};
    border-color: {p.border};
}}

/* ---------- Chips ---------- */
QLabel#chipLabel,
QLabel#stateChip,
QLabel#changedChip {{
    border-radius: {radius_sm}px;
    padding: 2px 8px;
    font-size: 8.5pt;
    font-weight: 700;
}}
QLabel#chipLabel[tone="muted"],
QLabel#chipLabel[tone="safety"] {{
    background: {p.surface_raised};
    border: 1px solid {p.border};
    color: {p.text_muted};
}}
QLabel#chipLabel[tone="safe"] {{
    background: {p.positive_soft};
    border: 1px solid transparent;
    color: {p.positive};
}}
QLabel#chipLabel[tone="advanced"],
QLabel#chipLabel[tone="changed"] {{
    background: {p.warning_soft};
    border: 1px solid transparent;
    color: {p.warning};
}}
QLabel#chipLabel[tone="experimental"] {{
    background: {p.danger_soft};
    border: 1px solid transparent;
    color: {p.danger};
}}
QLabel#stateChip[tone="on"] {{
    background: {p.positive_soft};
    border: 1px solid transparent;
    color: {p.positive};
}}
QLabel#stateChip[tone="off"],
QLabel#stateChip[tone="muted"] {{
    background: {p.surface_raised};
    border: 1px solid {p.border};
    color: {p.text_muted};
}}
QLabel#changedChip {{
    background: {p.warning_soft};
    border: 1px solid transparent;
    color: {p.warning};
}}

/* ---------- Inputs and lists ---------- */
QScrollArea,
QStackedWidget,
QWidget#moduleViewport,
QWidget#qt_scrollarea_viewport {{
    background: transparent;
    border: none;
}}
QPlainTextEdit,
QListWidget,
QLineEdit,
QSpinBox,
QDoubleSpinBox,
QComboBox {{
    background: {p.inset};
    border: 1px solid {p.border};
    border-radius: {radius_md}px;
    padding: 7px 10px;
    selection-background-color: rgba(34, 211, 238, {selection_alpha});
    selection-color: {p.text};
}}
QPlainTextEdit {{
    font-family: "Cascadia Mono", "Cascadia Code", "Consolas", monospace;
    font-size: 9pt;
    color: {p.text_muted};
}}
QLineEdit#searchBox {{
    background: {p.surface};
    padding: 8px 10px;
}}
QPlainTextEdit:focus,
QListWidget:focus,
QLineEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QComboBox:focus {{
    border-color: {p.accent_soft_border};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: {p.surface_raised};
    border: 1px solid {p.border_strong};
    selection-background-color: {p.accent_soft};
}}
QListWidget::item {{
    padding: 6px 6px;
    border-radius: {radius_sm}px;
}}
QListWidget::item:hover {{
    background: {p.surface_hover};
}}
QListWidget::item:selected {{
    background: {p.accent_soft};
    color: {p.text};
}}
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {p.border_strong};
    background: {p.inset};
}}
QCheckBox::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
}}

/* ---------- Tabs ---------- */
QTabWidget::pane {{
    background: transparent;
    border: none;
    border-top: 1px solid {p.border};
    margin-top: 6px;
}}
QTabBar::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: {p.text_muted};
    font-weight: 600;
    padding: 8px 14px;
    margin-right: 4px;
}}
QTabBar::tab:selected {{
    color: {p.text};
    border-bottom: 2px solid {p.accent};
}}
QTabBar::tab:hover {{
    color: {p.text};
}}

/* ---------- Scrollbars ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 14px;
    margin: 4px 2px 4px 4px;
    border: none;
    border-radius: 7px;
}}
QScrollBar::handle:vertical {{
    background: {p.scroll_thumb};
    border: none;
    border-radius: 4px;
    min-height: 48px;
    margin: 0px 3px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p.scroll_thumb_hover};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: none;
    border: none;
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 14px;
    margin: 4px 4px 2px 4px;
    border: none;
    border-radius: 7px;
}}
QScrollBar::handle:horizontal {{
    background: {p.scroll_thumb};
    border: none;
    border-radius: 4px;
    min-width: 48px;
    margin: 3px 0px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {p.scroll_thumb_hover};
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {{
    background: none;
    border: none;
    width: 0px;
}}
"""


APP_STYLESHEET = build_app_stylesheet()
