"""
Settings window: edit the thresholds from config.py without touching code.

Built automatically from ``src.utils.settings.SETTINGS``. Saved values go to
config.SETTINGS_FILE and are applied immediately; camera / hand-model values
apply from the next presentation.
"""

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import config
from src.utils import settings
from src.utils.settings import SETTINGS, Setting


class SettingsWindow(QDialog):
    def __init__(self, parent: QWidget | None = None, presenting: bool = False):
        super().__init__(parent)
        self.setWindowTitle(f"{config.APP_NAME} - Settings")
        self.setMinimumSize(520, 600)
        self.changed: list[str] = []
        self._presenting = presenting
        self._editors: dict[str, QWidget] = {}

        content = QWidget()
        content_layout = QVBoxLayout(content)
        groups: dict[str, QFormLayout] = {}
        for setting in SETTINGS:
            if not setting.in_window:
                continue
            if setting.group not in groups:
                box = QGroupBox(setting.group)
                groups[setting.group] = QFormLayout(box)
                content_layout.addWidget(box)
            editor = self._make_editor(setting)
            label = setting.label + (" *" if setting.restart else "")
            if setting.help:
                editor.setToolTip(setting.help)
            groups[setting.group].addRow(label, editor)
            self._editors[setting.key] = editor
        note = QLabel("* applies from the next presentation")
        note.setObjectName("muted")
        content_layout.addWidget(note)
        content_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel
                                   | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(buttons)
        self.load_values(settings.current_values())

    # -- editors ------------------------------------------------------------------------------

    @staticmethod
    def _make_editor(setting: Setting) -> QWidget:
        if setting.kind is bool:
            return QCheckBox()
        if setting.kind is str:
            combo = QComboBox()
            combo.addItems(setting.choices or ())
            return combo
        spin = QSpinBox() if setting.kind is int else QDoubleSpinBox()
        spin.setRange(setting.minimum, setting.maximum)
        spin.setSingleStep(setting.step or 1)
        if isinstance(spin, QDoubleSpinBox):
            # Enough decimals for the step (0.0005 needs 4), at least 2.
            step = f"{setting.step or 0.01:.6f}".rstrip("0")
            spin.setDecimals(max(2, len(step.split(".")[1])))
        spin.setSuffix(setting.suffix)
        return spin

    def load_values(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            editor = self._editors.get(key)
            if editor is None:
                continue  # not edited in this window
            if isinstance(editor, QCheckBox):
                editor.setChecked(bool(value))
            elif isinstance(editor, QComboBox):
                editor.setCurrentText(str(value))
            else:
                editor.setValue(value)

    def values(self) -> dict[str, Any]:
        result = {}
        for key, editor in self._editors.items():
            if isinstance(editor, QCheckBox):
                result[key] = editor.isChecked()
            elif isinstance(editor, QComboBox):
                result[key] = editor.currentText()
            else:
                result[key] = editor.value()
        return result

    # -- actions ---------------------------------------------------------------------------------

    def restore_defaults(self) -> None:
        self.load_values({k: v for k, v in settings.DEFAULTS.items() if k in self._editors})

    def save(self) -> None:
        self.changed = settings.apply(self.values())
        settings.save()
        self.accept()
