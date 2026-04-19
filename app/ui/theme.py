from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemePalette:
    mode: str
    text: str
    text_muted: str
    text_detail: str
    window_gradient_start: str
    window_gradient_end: str
    window_glow: str
    surface: str
    surface_alt: str
    surface_outline: str
    surface_outline_hover: str
    hero_start: str
    hero_end: str
    nav_fill: str
    nav_border: str
    nav_text: str
    accent_start: str
    accent_end: str
    accent_text: str
    switch_on: str
    switch_off: str
    switch_border: str
    positive_fill: str
    positive_border: str
    warning_fill: str
    warning_border: str
    editor_fill: str
    editor_border: str
    scroll_track: str
    scroll_thumb: str
    scroll_thumb_hover: str


PALETTES: dict[str, ThemePalette] = {
    "dark": ThemePalette(
        mode="dark",
        text="#fff7fb",
        text_muted="#dbcde9",
        text_detail="#f1e6fb",
        window_gradient_start="#2c1838",
        window_gradient_end="#120b22",
        window_glow="rgba(255, 132, 198, 118)",
        surface="rgba(52, 27, 66, 198)",
        surface_alt="rgba(71, 37, 89, 226)",
        surface_outline="rgba(255, 255, 255, 20)",
        surface_outline_hover="rgba(255, 207, 228, 86)",
        hero_start="rgba(233, 95, 177, 214)",
        hero_end="rgba(121, 90, 245, 214)",
        nav_fill="rgba(255, 188, 229, 42)",
        nav_border="rgba(255, 213, 236, 56)",
        nav_text="#fff9fd",
        accent_start="#ff77c8",
        accent_end="#8a73ff",
        accent_text="#190d24",
        switch_on="rgba(255, 153, 210, 116)",
        switch_off="rgba(255, 255, 255, 10)",
        switch_border="rgba(255, 255, 255, 20)",
        positive_fill="rgba(104, 220, 189, 86)",
        positive_border="rgba(159, 255, 224, 134)",
        warning_fill="rgba(255, 192, 132, 78)",
        warning_border="rgba(255, 215, 171, 126)",
        editor_fill="rgba(29, 16, 43, 232)",
        editor_border="rgba(255, 255, 255, 16)",
        scroll_track="rgba(255, 255, 255, 52)",
        scroll_thumb="rgba(255, 247, 251, 214)",
        scroll_thumb_hover="rgba(255, 255, 255, 242)",
    ),
    "light": ThemePalette(
        mode="light",
        text="#34213f",
        text_muted="#725f83",
        text_detail="#4b3759",
        window_gradient_start="#fde7f2",
        window_gradient_end="#efe8ff",
        window_glow="rgba(255, 153, 191, 126)",
        surface="rgba(255, 255, 255, 205)",
        surface_alt="rgba(255, 246, 252, 232)",
        surface_outline="rgba(143, 101, 173, 34)",
        surface_outline_hover="rgba(213, 110, 176, 78)",
        hero_start="rgba(255, 164, 203, 214)",
        hero_end="rgba(176, 153, 255, 214)",
        nav_fill="rgba(255, 188, 221, 68)",
        nav_border="rgba(193, 124, 177, 64)",
        nav_text="#311f43",
        accent_start="#f163ae",
        accent_end="#8674ff",
        accent_text="#ffffff",
        switch_on="rgba(244, 118, 191, 86)",
        switch_off="rgba(255, 255, 255, 138)",
        switch_border="rgba(153, 111, 181, 44)",
        positive_fill="rgba(107, 209, 175, 58)",
        positive_border="rgba(79, 178, 146, 92)",
        warning_fill="rgba(255, 189, 126, 60)",
        warning_border="rgba(223, 161, 94, 92)",
        editor_fill="rgba(255, 255, 255, 220)",
        editor_border="rgba(146, 102, 181, 30)",
        scroll_track="rgba(111, 72, 145, 36)",
        scroll_thumb="rgba(120, 93, 201, 156)",
        scroll_thumb_hover="rgba(107, 82, 196, 196)",
    ),
}


def resolve_theme_mode(preference: str, system_mode: str) -> str:
    if preference == "system":
        return system_mode if system_mode in PALETTES else "dark"
    return preference if preference in PALETTES else "dark"


def _radius(compact: bool, normal: int, compact_value: int) -> int:
    return compact_value if compact else normal


def build_app_stylesheet(
    resolved_theme_mode: str = "dark",
    accent_intensity: float = 0.62,
    compact_mode: bool = False,
) -> str:
    palette = PALETTES[resolve_theme_mode(resolved_theme_mode, "dark")]
    accent_alpha = max(0.38, min(0.95, accent_intensity))
    page_radius = _radius(compact_mode, 24, 18)
    card_radius = _radius(compact_mode, 20, 16)
    control_radius = _radius(compact_mode, 16, 13)
    control_padding = "8px 12px" if compact_mode else "10px 15px"
    scrollbar_margin = 10 if compact_mode else 14

    return f"""
QWidget {{
    background: transparent;
    color: {palette.text};
    font-family: "Segoe UI Variable Text", "Bahnschrift", "Trebuchet MS", "Segoe UI";
    font-size: 10.5pt;
}}
QMainWindow, QWidget#appRoot {{
    background:
        qradialgradient(cx:0.18, cy:0.14, radius:1.22, fx:0.18, fy:0.14,
                        stop:0 {palette.window_glow},
                        stop:0.32 rgba(255,255,255,0),
                        stop:1 rgba(255,255,255,0)),
        qradialgradient(cx:0.92, cy:0.06, radius:1.05, fx:0.92, fy:0.06,
                        stop:0 rgba(255,255,255,0.16),
                        stop:0.24 rgba(255,255,255,0),
                        stop:1 rgba(255,255,255,0)),
        qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 {palette.window_gradient_start},
                        stop:1 {palette.window_gradient_end});
}}
QFrame#pagePanel,
QFrame#metricCard,
QFrame#actionCard,
QFrame#presetCard,
QFrame#heroPanel,
QFrame#sectionGroup,
QFrame#settingsGroup,
QFrame#toolCard,
QFrame#dependencyCard {{
    background: {palette.surface};
    border: 1px solid {palette.surface_outline};
    border-radius: {page_radius}px;
}}
QFrame#sidebarPanel {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 rgba(255,255,255,0.12),
                                stop:1 rgba(255,255,255,0.04));
    border: 1px solid {palette.surface_outline};
    border-radius: {page_radius}px;
}}
QFrame#reviewDrawer {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {palette.surface_alt},
                                stop:1 {palette.surface});
    border: 1px solid {palette.surface_outline_hover};
    border-radius: {page_radius}px;
}}
QFrame#metricCard,
QFrame#actionCard,
QFrame#presetCard,
QFrame#sectionGroup,
QFrame#settingsGroup,
QFrame#toolCard,
QFrame#dependencyCard {{
    border-radius: {card_radius}px;
}}
QFrame#heroPanel {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {palette.hero_start}, stop:1 {palette.hero_end});
    border: 1px solid {palette.surface_outline_hover};
}}
QFrame#pagePanel {{
    background: rgba(255,255,255,0.02);
}}
QPushButton#navButton {{
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.02);
    border-radius: {control_radius}px;
    color: {palette.nav_text};
    padding: 11px 16px;
    text-align: left;
    font-weight: 700;
}}
QPushButton#navButton:hover {{
    background: {palette.nav_fill};
    border-color: {palette.nav_border};
}}
QPushButton#navButton:checked {{
    background: {palette.nav_fill};
    border-color: {palette.surface_outline_hover};
    color: {palette.nav_text};
}}
QPushButton#accentButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {palette.accent_start}, stop:1 {palette.accent_end});
    color: {palette.accent_text};
    border: none;
    border-radius: {control_radius}px;
    padding: 11px 16px;
    font-weight: 800;
}}
QPushButton#accentButton:hover {{
    border: 1px solid rgba(255,255,255,88);
}}
QPushButton#ghostButton,
QPushButton#actionButton {{
    background: {palette.surface_alt};
    color: {palette.text};
    border: 1px solid {palette.surface_outline};
    border-radius: {control_radius}px;
    padding: 10px 14px;
    font-weight: 700;
}}
QPushButton#ghostButton:hover,
QPushButton#actionButton:hover {{
    border-color: {palette.surface_outline_hover};
}}
QPushButton#actionButton[staged="true"] {{
    background: rgba(255,255,255,{int(56 * accent_alpha)});
    border-color: {palette.surface_outline_hover};
}}
QPushButton#pillSwitch {{
    min-width: 112px;
    border-radius: {control_radius}px;
    padding: 10px 16px;
    font-weight: 800;
    background: {palette.switch_off};
    color: {palette.text};
    border: 1px solid {palette.switch_border};
}}
QPushButton#pillSwitch:hover {{
    border-color: {palette.surface_outline_hover};
}}
QPushButton#pillSwitch:checked {{
    background: {palette.switch_on};
    border: 1px solid {palette.surface_outline_hover};
}}
QPushButton:disabled {{
    color: {palette.text_muted};
    border-color: {palette.surface_outline};
}}
QLabel#titleLabel {{
    font-family: "Segoe UI Variable Display", "Bahnschrift", "Segoe UI";
    font-size: 25px;
    font-weight: 800;
}}
QLabel#sectionTitle {{
    font-family: "Segoe UI Variable Display", "Bahnschrift", "Segoe UI";
    font-size: 16px;
    font-weight: 800;
}}
QLabel#metricValue {{
    font-family: "Segoe UI Variable Display", "Bahnschrift", "Segoe UI";
    font-size: 21px;
    font-weight: 800;
}}
QLabel#eyebrowLabel {{
    color: {palette.text_muted};
    font-size: 9.4pt;
    font-weight: 700;
    letter-spacing: 0.06em;
}}
QLabel#captionLabel {{
    color: {palette.text_muted};
}}
QLabel#detailLabel {{
    color: {palette.text_detail};
    line-height: 1.25em;
}}
QLabel#chipLabel,
QLabel#stateChip,
QLabel#changedChip {{
    border-radius: 12px;
    padding: 4px 10px;
    font-size: 9pt;
    font-weight: 700;
}}
QLabel#chipLabel[tone="safety"] {{
    background: rgba(255,255,255,{int(50 * accent_alpha)});
    border: 1px solid {palette.surface_outline_hover};
    color: {palette.text};
}}
QLabel#chipLabel[tone="muted"] {{
    background: {palette.surface_alt};
    border: 1px solid {palette.surface_outline};
    color: {palette.text_muted};
}}
QLabel#stateChip[tone="on"] {{
    background: {palette.positive_fill};
    border: 1px solid {palette.positive_border};
    color: {palette.text};
}}
QLabel#stateChip[tone="off"],
QLabel#stateChip[tone="muted"] {{
    background: {palette.surface_alt};
    border: 1px solid {palette.surface_outline};
    color: {palette.text};
}}
QLabel#changedChip {{
    background: {palette.warning_fill};
    border: 1px solid {palette.warning_border};
    color: {palette.text};
}}
QScrollArea,
QStackedWidget,
QWidget#moduleViewport,
QWidget#qt_scrollarea_viewport {{
    background: transparent;
    border: none;
}}
QTabWidget::pane {{
    background: {palette.surface};
    border: 1px solid {palette.surface_outline};
    border-radius: {card_radius}px;
    margin-top: 10px;
}}
QTabBar::tab {{
    background: {palette.surface_alt};
    border: 1px solid {palette.surface_outline};
    border-bottom: none;
    border-top-left-radius: {control_radius}px;
    border-top-right-radius: {control_radius}px;
    color: {palette.text_muted};
    font-weight: 700;
    padding: 9px 16px;
    margin-right: 6px;
}}
QTabBar::tab:selected {{
    background: rgba(255,255,255,{int(54 * accent_alpha)});
    border-color: {palette.surface_outline_hover};
    color: {palette.text};
}}
QTabBar::tab:hover {{
    border-color: {palette.surface_outline_hover};
}}
QPlainTextEdit,
QListWidget,
QLineEdit,
QSpinBox,
QDoubleSpinBox,
QComboBox {{
    background: {palette.editor_fill};
    border: 1px solid {palette.editor_border};
    border-radius: {control_radius}px;
    padding: 9px 11px;
    selection-background-color: rgba(255,255,255,{int(60 * accent_alpha)});
}}
QPlainTextEdit:focus,
QListWidget:focus,
QLineEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QComboBox:focus {{
    border-color: {palette.surface_outline_hover};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QListWidget::item {{
    padding: 6px 4px;
    border-radius: 8px;
}}
QListWidget::item:selected {{
    background: rgba(255,255,255,{int(70 * accent_alpha)});
}}
QScrollBar:vertical {{
    background: {palette.scroll_track};
    width: 14px;
    margin: {scrollbar_margin}px 8px {scrollbar_margin}px 6px;
    border: 1px solid {palette.surface_outline};
    border-radius: 7px;
}}
QScrollBar::handle:vertical {{
    background: {palette.scroll_thumb};
    border: none;
    border-radius: 7px;
    min-height: 56px;
}}
QScrollBar::handle:vertical:hover {{
    background: {palette.scroll_thumb_hover};
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
    background: {palette.scroll_track};
    height: 14px;
    margin: 6px {scrollbar_margin}px 8px {scrollbar_margin}px;
    border: 1px solid {palette.surface_outline};
    border-radius: 7px;
}}
QScrollBar::handle:horizontal {{
    background: {palette.scroll_thumb};
    border: none;
    border-radius: 7px;
    min-width: 56px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {palette.scroll_thumb_hover};
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
