"""Colours, fonts and the Qt stylesheet for AirSlide."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

BACKGROUND = "#0f1419"
SURFACE = "#171e26"
SURFACE_2 = "#1f2832"
BORDER = "#2a3440"
TEXT = "#e6edf3"
TEXT_MUTED = "#8b98a5"
ACCENT = "#3ecf8e"
ACCENT_DARK = "#2fa872"
WARNING = "#f5b945"
ERROR = "#f06a6a"
INFO = "#6cb6ff"

FONT_FAMILY = "Segoe UI"

STATUS_COLORS = {"ok": ACCENT, "warn": WARNING, "error": ERROR, "info": INFO, "muted": TEXT_MUTED}

STYLESHEET = f"""
QWidget {{
    background: {BACKGROUND};
    color: {TEXT};
    font-family: "{FONT_FAMILY}";
    font-size: 10.5pt;
}}
QLabel {{ background: transparent; }}
QWidget#transparent {{ background: transparent; }}
QLabel#title {{ font-size: 30pt; font-weight: 700; }}
QLabel#tagline {{ font-size: 13pt; color: {TEXT_MUTED}; }}
QLabel#sectionTitle {{ font-size: 9pt; font-weight: 600; color: {TEXT_MUTED}; letter-spacing: 1px; }}
QLabel#muted {{ color: {TEXT_MUTED}; }}
QLabel#fileName {{ font-size: 16pt; font-weight: 600; }}
QLabel#bigGesture {{ font-size: 22pt; font-weight: 700; }}
QFrame#card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QPushButton {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 16px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {TEXT_MUTED}; border-color: {SURFACE_2}; }}
QPushButton#primary {{
    background: {ACCENT};
    color: #06140d;
    border: none;
    font-size: 14pt;
    font-weight: 700;
    padding: 16px 32px;
    border-radius: 12px;
}}
QPushButton#primary:hover {{ background: {ACCENT_DARK}; }}
QPushButton#primary:disabled {{ background: {SURFACE_2}; color: {TEXT_MUTED}; }}
QPushButton#danger {{ border-color: {ERROR}; color: {ERROR}; }}
QPushButton#danger:hover {{ background: {ERROR}; color: {BACKGROUND}; }}
QLabel#cameraView {{
    background: #000000;
    border: 1px solid {BORDER};
    border-radius: 10px;
    color: {TEXT_MUTED};
}}
QListWidget {{
    background: {SURFACE};
    border: none;
    color: {TEXT_MUTED};
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding: 12px 10px 8px 10px;
    font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {TEXT_MUTED}; }}
QSpinBox, QDoubleSpinBox, QComboBox, QTimeEdit {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 6px;
    min-width: 110px;
}}
QSpinBox:disabled, QTimeEdit:disabled, QComboBox:disabled {{ color: {TEXT_MUTED}; }}
QRadioButton, QCheckBox {{ background: transparent; spacing: 8px; }}
QRadioButton:checked {{ color: {ACCENT}; font-weight: 600; }}
QRadioButton::indicator {{
    width: 14px; height: 14px;
    border: 2px solid {TEXT_MUTED};
    border-radius: 9px;
    background: {SURFACE_2};
}}
QRadioButton::indicator:hover, QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QRadioButton::indicator:checked {{
    border-color: {ACCENT};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                                stop:0 {ACCENT}, stop:0.5 {ACCENT}, stop:0.6 {SURFACE_2}, stop:1 {SURFACE_2});
}}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 2px solid {TEXT_MUTED};
    border-radius: 4px;
    background: {SURFACE_2};
}}
QCheckBox::indicator:checked {{ border-color: {ACCENT}; background: {ACCENT}; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {TEXT_MUTED}; }}
QScrollArea {{ border: none; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER}; }}
"""


def app_font(point_size: float = 10.5, bold: bool = False) -> QFont:
    font = QFont(FONT_FAMILY, point_size)
    font.setBold(bold)
    return font


def make_app_icon() -> QIcon:
    """A simple generated icon: open hand on a green rounded square."""
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(ACCENT))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
        painter.setFont(QFont("Segoe UI Emoji", max(6, int(size * 0.5))))
        painter.setPen(QColor(BACKGROUND))
        painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "🖐")
        painter.end()
        icon.addPixmap(pixmap)
    return icon
