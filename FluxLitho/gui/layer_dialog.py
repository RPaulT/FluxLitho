from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout as QVLayout, QCheckBox
)


class DynamicLayerDialog(QDialog):
    """Dialog mit dynamischen Checkboxen für Gerber-Layer-Dateien"""
    def __init__(self, layer_display_names, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gerber-Layer auswählen")
        layout = QVLayout(self)
        self.checks = []

        # Standardauswahl (Top/Bottom, Copper, Mask, Silk)
        def default_on(name: str) -> bool:
            low = name.lower()
            keys = ("top", "bottom", "copper", "cu", "mask",
                    "soldermask", "solder_mask", "silk", "legend")
            return any(k in low for k in keys)

        for name in layer_display_names:
            cb = QCheckBox(name)
            cb.setChecked(default_on(name))
            layout.addWidget(cb)
            self.checks.append(cb)

        btns = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        buttonBox = QDialogButtonBox(btns)
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)
        layout.addWidget(buttonBox)

    def selected_names(self):
        return [cb.text() for cb in self.checks if cb.isChecked()]