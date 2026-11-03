"""Material 3-inspired color roles for the Qt Widgets interface."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette


_PALETTES = {
    "light": {
        "background": "#f6f7fa",
        "surface": "#ffffff",
        "surface_container": "#eef1f6",
        "surface_high": "#e5e9f0",
        "input": "#fbfcff",
        "primary": "#315d9b",
        "on_primary": "#ffffff",
        "primary_container": "#d8e3ff",
        "on_primary_container": "#102d55",
        "secondary": "#526176",
        "tertiary": "#006a65",
        "text": "#191c20",
        "muted": "#44474e",
        "outline": "#74777f",
        "outline_variant": "#c4c6d0",
        "hover": "#e8edf6",
        "selected": "#dce6f6",
        "success": "#176b45",
        "error": "#ba1a1a",
        "error_container": "#ffdad6",
        "tooltip": "#30343a",
        "on_tooltip": "#f2f0f7",
    },
    "dark": {
        "background": "#111318",
        "surface": "#191c21",
        "surface_container": "#20242a",
        "surface_high": "#292d34",
        "input": "#15181d",
        "primary": "#b1c9ff",
        "on_primary": "#17345e",
        "primary_container": "#2d4771",
        "on_primary_container": "#d9e2ff",
        "secondary": "#bbc6dc",
        "tertiary": "#70d6cd",
        "text": "#e3e2e9",
        "muted": "#c3c6d0",
        "outline": "#8d9199",
        "outline_variant": "#44474f",
        "hover": "#252a32",
        "selected": "#303e55",
        "success": "#76d6aa",
        "error": "#ffb4ab",
        "error_container": "#93000a",
        "tooltip": "#e3e2e9",
        "on_tooltip": "#30343a",
    },
}

_LOG_BADGES = {
    "light": {
        "Debug": ("#e8e9ed", "#3f4148"),
        "Info": ("#dce7f8", "#23406a"),
        "Success": ("#d7f3e4", "#145a3d"),
        "Warning": ("#f8ebcb", "#5c4500"),
        "Error": ("#ffdad6", "#8c1d18"),
        "Live": ("#e7dff7", "#49376e"),
    },
    "dark": {
        "Debug": ("#353940", "#d0d4dc"),
        "Info": ("#293a53", "#d5e5ff"),
        "Success": ("#1e493b", "#b9f0ce"),
        "Warning": ("#4b401f", "#ffe39d"),
        "Error": ("#4f2930", "#ffdada"),
        "Live": ("#3b3257", "#e5d9ff"),
    },
}


def theme_colors(scheme):
    return _PALETTES[scheme if scheme in _PALETTES else "dark"]


def log_badge_colors(scheme):
    return _LOG_BADGES[scheme if scheme in _LOG_BADGES else "dark"]


def detect_color_scheme(app):
    scheme = app.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Light:
        return "light"
    if scheme == Qt.ColorScheme.Dark:
        return "dark"
    window_color = app.palette().color(QPalette.ColorRole.Window)
    return "light" if window_color.lightness() >= 128 else "dark"


def build_stylesheet(scheme):
    colors = theme_colors(scheme)
    return f"""
* {{ font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif; font-size: 15px; }}
QMainWindow, QWidget#root {{ background: {colors['background']}; color: {colors['text']}; }}
QWidget {{ color: {colors['text']}; }}
QFrame#sidebar {{ background: {colors['surface']}; border-right: 1px solid {colors['outline_variant']}; }}
QLabel#brand {{ font-size: 21px; font-weight: 800; color: {colors['text']}; }}
QLabel#brandAccent {{ color: {colors['tertiary']}; font-size: 12px; font-weight: 700; }}
QLabel#versionLabel {{ color: {colors['muted']}; font-size: 12px; padding-left: 4px; }}
QLabel#betaNote {{ color: {colors['muted']}; font-size: 12px; }}
QLabel#pageTitle {{ font-size: 29px; font-weight: 750; color: {colors['text']}; }}
QLabel#muted {{ color: {colors['muted']}; }}
QLabel#sectionTitle {{ font-size: 18px; font-weight: 700; }}
QPushButton {{ background: {colors['surface_container']}; color: {colors['text']}; border: 1px solid {colors['outline_variant']}; border-radius: 8px; padding: 10px 15px; min-height: 24px; font-weight: 600; }}
QPushButton:hover {{ background: {colors['hover']}; border-color: {colors['outline']}; }}
QPushButton:pressed {{ background: {colors['selected']}; }}
QPushButton:disabled {{ background: {colors['surface_container']}; color: {colors['outline']}; border-color: {colors['outline_variant']}; }}
QPushButton#navButton {{ text-align: left; background: transparent; border: 0; color: {colors['muted']}; padding: 12px 14px; border-radius: 8px; font-size: 15px; }}
QPushButton#navButton:hover {{ background: {colors['hover']}; color: {colors['text']}; }}
QPushButton#navButton[active="true"] {{ background: {colors['primary_container']}; color: {colors['on_primary_container']}; }}
QPushButton#primary {{ background: {colors['primary']}; border: 1px solid {colors['primary']}; color: {colors['on_primary']}; }}
QPushButton#primary:hover {{ background: {colors['primary_container']}; color: {colors['on_primary_container']}; }}
QPushButton#danger {{ background: {colors['error_container']}; border-color: {colors['error_container']}; color: {colors['error']}; }}
QFrame#card {{ background: {colors['surface_container']}; border: 1px solid {colors['outline_variant']}; border-radius: 8px; }}
QLabel#cardLabel {{ color: {colors['muted']}; font-size: 13px; font-weight: 700; }}
QLabel#cardValue {{ color: {colors['text']}; font-size: 30px; font-weight: 800; }}
QFrame#panel {{ background: {colors['surface']}; border: 1px solid {colors['outline_variant']}; border-radius: 8px; }}
QLineEdit, QComboBox, QTextEdit {{ background: {colors['input']}; border: 1px solid {colors['outline']}; border-radius: 6px; padding: 9px 11px; color: {colors['text']}; selection-background-color: {colors['primary']}; selection-color: {colors['on_primary']}; }}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{ border: 2px solid {colors['primary']}; padding: 8px 10px; }}
QComboBox::drop-down {{ border: 0; width: 28px; }}
QComboBox QAbstractItemView {{ background: {colors['surface']}; color: {colors['text']}; selection-background-color: {colors['selected']}; selection-color: {colors['text']}; border: 1px solid {colors['outline_variant']}; }}
QTableWidget {{ background: {colors['surface']}; alternate-background-color: {colors['surface_container']}; border: 1px solid {colors['outline_variant']}; border-radius: 8px; gridline-color: {colors['outline_variant']}; selection-background-color: {colors['selected']}; selection-color: {colors['text']}; }}
QHeaderView::section {{ background: {colors['surface_container']}; color: {colors['muted']}; border: 0; border-bottom: 1px solid {colors['outline_variant']}; padding: 10px; font-weight: 700; }}
QTableWidget::item {{ padding: 7px; border-bottom: 1px solid {colors['outline_variant']}; }}
QTableWidget#logTable QHeaderView::section {{ padding: 12px 14px; font-size: 13px; }}
QTableWidget#logTable::item {{ padding: 9px 12px; }}
QTableWidget#logTable::item:hover, QTableWidget::item:hover {{ background: {colors['hover']}; }}
QTableWidget#logTable::item:selected, QTableWidget::item:selected {{ background: {colors['selected']}; color: {colors['text']}; }}
QListWidget#recordingList {{ background: {colors['surface']}; border: 1px solid {colors['outline_variant']}; border-radius: 8px; outline: 0; }}
QListWidget#recordingList::item {{ min-height: 72px; padding: 8px; border-bottom: 1px solid {colors['outline_variant']}; }}
QListWidget#recordingList::item:hover {{ background: {colors['hover']}; }}
QListWidget#recordingList::item:selected {{ background: {colors['selected']}; border-left: 3px solid {colors['primary']}; }}
QFrame#recordingPreview {{ background: {colors['surface_high']}; border: 1px solid {colors['outline_variant']}; border-radius: 8px; }}
QLabel#recordingThumbnail {{ background: {colors['surface_high']}; color: {colors['muted']}; }}
QLabel#recordingTitle {{ color: {colors['text']}; font-size: 21px; font-weight: 750; }}
QLabel#monitorStatus {{ font-size: 18px; font-weight: 700; }}
QLabel#monitorStatus[state="running"] {{ color: {colors['success']}; }}
QLabel#monitorStatus[state="stopped"] {{ color: {colors['muted']}; }}
QLabel#activeRecordings {{ color: {colors['tertiary']}; font-weight: 700; padding-right: 10px; }}
QLabel#sidebarStatus {{ color: {colors['muted']}; font-weight: 700; padding: 10px 4px; }}
QLabel#sidebarStatus[state="running"] {{ color: {colors['success']}; }}
QCheckBox {{ color: {colors['text']}; spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; }}
QProgressBar {{ background: {colors['surface_container']}; border: 1px solid {colors['outline_variant']}; border-radius: 6px; min-height: 18px; text-align: center; color: {colors['text']}; }}
QProgressBar::chunk {{ background: {colors['primary']}; border-radius: 5px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {colors['outline_variant']}; min-height: 28px; border-radius: 5px; }}
QScrollBar::handle:vertical:hover {{ background: {colors['outline']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {colors['outline_variant']}; min-width: 28px; border-radius: 5px; }}
QScrollBar::handle:horizontal:hover {{ background: {colors['outline']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QToolTip {{ background: {colors['tooltip']}; color: {colors['on_tooltip']}; border: 1px solid {colors['outline_variant']}; padding: 5px 8px; }}
"""