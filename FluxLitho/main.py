import sys
from PySide6.QtWidgets import QApplication
from gui import BrassEtcherGUI

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BrassEtcherGUI()
    window.resize(1000, 800)
    window.show()
    sys.exit(app.exec())