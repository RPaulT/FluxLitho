from PySide6.QtWidgets import (
    QMainWindow, QFileDialog, QMenu,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QVBoxLayout, QWidget, QHBoxLayout, QLabel, QLineEdit, QGraphicsPathItem,
    QToolBar, QDialog
)
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer
from PySide6.QtGui import QPen, QColor, QIcon, QAction, QKeySequence

from shapely import affinity

from constants import PANEL_MM_W, PANEL_MM_H
from svg_utils import svg_to_polygon, shapely_to_qpath
from mesh_utils import build_and_transform_mesh

from .layer_dialog import DynamicLayerDialog
from .gerber_utils import collect_gerber_files, load_gerber_files

from pathlib import Path

class BrassEtcherGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FluxLitho – STL/3MF Export")
        self.resize(1000, 800)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # Scene + View
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setViewportMargins(20, 20, 20, 20)
        layout.addWidget(self.view)

        # Controls
        ctrl_layout = QHBoxLayout()
        self.width_edit = QLineEdit("50")
        self.height_edit = QLineEdit("50")
        self.svg_width_edit = QLineEdit("40")

        ctrl_layout.addWidget(QLabel("Rohling Breite [mm]:"))
        ctrl_layout.addWidget(self.width_edit)
        ctrl_layout.addWidget(QLabel("Höhe [mm]:"))
        ctrl_layout.addWidget(self.height_edit)
        ctrl_layout.addWidget(QLabel("Motiv Breite [mm]:"))
        ctrl_layout.addWidget(self.svg_width_edit)
        layout.addLayout(ctrl_layout)

        # Toolbar
        tb = QToolBar("Werkzeuge")
        tb.setMovable(False)
        self.addToolBar(tb)

        act_load = QAction(QIcon("icons/open.svg"), "Importieren", self)
        act_save = QAction(QIcon("icons/save.svg"), "Speichern als…", self)
        act_mirror_h = QAction(QIcon("icons/mirror_h.svg"), "Horizontal spiegeln (H)", self)
        act_mirror_v = QAction(QIcon("icons/mirror_v.svg"), "Vertikal spiegeln (V)", self)
        act_rotate_90 = QAction(QIcon("icons/rotate.svg"), "90° drehen (R)", self)
        act_center = QAction(QIcon("icons/center.svg"), "Zentrieren (Z)", self)

        # Menü für Import
        import_menu = QMenu()
        import_svg = QAction("SVG importieren…", self)
        import_svg.triggered.connect(self.load_svg)
        import_gerber = QAction("Gerber importieren…", self)
        import_gerber.triggered.connect(self.load_gerber)
        import_menu.addAction(import_svg)
        import_menu.addAction(import_gerber)
        act_load.setMenu(import_menu)

        tb.addAction(act_load)
        tb.addAction(act_save)
        tb.addSeparator()
        tb.addAction(act_mirror_h)
        tb.addAction(act_mirror_v)
        tb.addAction(act_rotate_90)
        tb.addSeparator()
        tb.addAction(act_center)

        # Shortcuts
        act_save.setShortcut(QKeySequence("Ctrl+S"))
        act_mirror_h.setShortcut(QKeySequence("H"))
        act_mirror_v.setShortcut(QKeySequence("V"))
        act_rotate_90.setShortcut(QKeySequence("R"))
        act_center.setShortcut(QKeySequence("Z"))

        # State
        self.motif_geom = None
        self.motif_qpath = None
        self.motif_item: QGraphicsPathItem | None = None
        self.panel_item = None
        self.rohteil_item = None

        # Timer
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.setInterval(16)

        # Events
        act_save.triggered.connect(self.save_dialog)
        act_mirror_h.triggered.connect(self.mirror_horizontal)
        act_mirror_v.triggered.connect(self.mirror_vertical)
        act_rotate_90.triggered.connect(self.rotate_90)
        act_center.triggered.connect(self.center_svg)

        self.width_edit.editingFinished.connect(self.update_display)
        self.height_edit.editingFinished.connect(self.update_display)
        self.svg_width_edit.editingFinished.connect(self.rescale_svg_only)
        self.scene.changed.connect(self.schedule_refit)

        self.update_display()
        QTimer.singleShot(0, self.refit_view)

    # ===== Anzeige =====
    def update_display(self):
        last_pos = QPointF(0, 0)
        if self.motif_item:
            last_pos = self.motif_item.pos()

        self.scene.clear()
        self.motif_item = None

        panel_rect = QGraphicsRectItem(QRectF(0, 0, PANEL_MM_W, PANEL_MM_H))
        panel_rect.setBrush(QColor(220, 220, 220))
        panel_rect.setPen(QPen(Qt.black))
        panel_rect.setZValue(-2)
        self.scene.addItem(panel_rect)
        self.panel_item = panel_rect

        try:
            w = float(self.width_edit.text())
            h = float(self.height_edit.text())
        except ValueError:
            w, h = 50, 30
        brass = QGraphicsRectItem(QRectF(0, 0, w, h))
        brass.setBrush(QColor(255, 230, 200))
        brass.setPen(QPen(QColor("red")))
        brass.setZValue(-1)
        self.scene.addItem(brass)
        self.rohteil_item = brass

        if self.motif_qpath:
            item = QGraphicsPathItem(self.motif_qpath)
            item.setPen(QPen(QColor("blue"), 0))
            item.setBrush(QColor(100, 100, 255, 90))
            item.setZValue(5)
            item.setFlags(QGraphicsPathItem.ItemIsMovable | QGraphicsPathItem.ItemIsSelectable)
            self.scene.addItem(item)
            item.setPos(last_pos)
            self.motif_item = item

        self.refit_view()

    def refit_view(self):
        if not self.panel_item:
            return
        rect = self.panel_item.rect()
        expanded = rect.adjusted(-10, -10, 10, 10)
        self.scene.setSceneRect(expanded)
        self.view.fitInView(expanded, Qt.KeepAspectRatio)
        self.view.centerOn(rect.center())

    def schedule_refit(self, *args):
        self._refit_timer.stop()
        self._refit_timer.timeout.connect(self.refit_view)
        self._refit_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refit_view()

    def showEvent(self, event):
        super().showEvent(event)
        self.refit_view()

    # ===== Import =====
    def load_svg(self):
        path, _ = QFileDialog.getOpenFileName(self, "SVG auswählen", "", "SVG Dateien (*.svg)")
        if not path:
            return
        try:
            target_w = float(self.svg_width_edit.text())
        except ValueError:
            target_w = 40
        geom = svg_to_polygon(path, target_width_mm=target_w)
        if not geom or geom.is_empty:
            print("⚠ Keine gültige Geometrie im SVG.")
            return
        geom = affinity.scale(geom, xfact=-1, yfact=-1, origin=(0, 0))
        minx, miny, _, _ = geom.bounds
        geom = affinity.translate(geom, xoff=-minx, yoff=-miny)
        self.motif_geom = geom
        self.update_motif_item(keep_pos=False)
        print("✅ SVG geladen.")
        self.refit_view()

    def load_gerber(self):
        path, _ = QFileDialog.getOpenFileName(self, "Gerber auswählen", "", "Gerber/ZIP (*.gbr *.ger *.zip)")
        if not path:
            return
        files, tempdir = collect_gerber_files(path)
        if not files:
            print("⚠ Keine Gerber gefunden.")
            return

        display_names = [Path(f).name for f in files]
        dlg = DynamicLayerDialog(display_names, self)
        if dlg.exec() != QDialog.Accepted:
            print("❌ Abbruch.")
            return
        selected = set(dlg.selected_names())

        combined = load_gerber_files(files, selected)
        if not combined:
            print("⚠ Keine Geometrie erzeugt.")
            return

        self.motif_geom = combined
        self.update_motif_item(keep_pos=False)
        print("✅ Gerber importiert.")
        self.refit_view()

    # ===== Motiv =====
    def rescale_svg_only(self):
        if not self.motif_geom:
            return
        try:
            target_w = float(self.svg_width_edit.text())
        except ValueError:
            return
        minx, _, maxx, _ = self.motif_geom.bounds
        width = max(maxx - minx, 1e-6)
        scale = target_w / width
        base = affinity.translate(self.motif_geom, xoff=-minx, yoff=0)
        base = affinity.scale(base, xfact=scale, yfact=scale, origin=(0, 0))
        self.motif_geom = base
        self.update_motif_item(keep_pos=False)
        print("✅ Neu skaliert.")
        self.refit_view()

    def center_svg(self):
        if not self.motif_item or not self.rohteil_item or not self.motif_qpath:
            return
        brass_rect = self.rohteil_item.rect()
        b = self.motif_qpath.boundingRect()
        x = brass_rect.x() + (brass_rect.width() - b.width()) / 2
        y = brass_rect.y() + (brass_rect.height() - b.height()) / 2
        self.motif_item.setPos(x, y)
        print("✅ Zentriert.")
        self.refit_view()

    def update_motif_item(self, keep_pos=True):
        if not self.motif_geom:
            return
        last_pos = QPointF(0, 0)
        if keep_pos and self.motif_item:
            last_pos = self.motif_item.pos()
        self.motif_qpath = shapely_to_qpath(self.motif_geom)
        if self.motif_item:
            self.scene.removeItem(self.motif_item)
        item = QGraphicsPathItem(self.motif_qpath)
        item.setPen(QPen(QColor("blue"), 0))
        item.setBrush(QColor(100, 100, 255, 90))
        item.setZValue(5)
        item.setFlags(QGraphicsPathItem.ItemIsMovable | QGraphicsPathItem.ItemIsSelectable)
        self.scene.addItem(item)
        self.motif_item = item
        self.motif_item.setPos(last_pos if keep_pos else QPointF(0, 0))

    # ===== Spiegeln & Rotieren =====
    def mirror_vertical(self):
        if not self.motif_geom:
            return
        self.motif_geom = affinity.scale(self.motif_geom, xfact=-1, yfact=1, origin=(0, 0))
        minx, miny, _, _ = self.motif_geom.bounds
        self.motif_geom = affinity.translate(self.motif_geom, xoff=-minx, yoff=-miny)
        self.update_motif_item(True)
        print("🔄 Vertikal gespiegelt.")
        self.refit_view()

    def mirror_horizontal(self):
        if not self.motif_geom:
            return
        self.motif_geom = affinity.scale(self.motif_geom, xfact=1, yfact=-1, origin=(0, 0))
        minx, miny, _, _ = self.motif_geom.bounds
        self.motif_geom = affinity.translate(self.motif_geom, xoff=-minx, yoff=-miny)
        self.update_motif_item(True)
        print("🔄 Horizontal gespiegelt.")
        self.refit_view()

    def rotate_90(self):
        if not self.motif_geom:
            return
        self.motif_geom = affinity.rotate(self.motif_geom, 90, origin=(0, 0))
        minx, miny, _, _ = self.motif_geom.bounds
        self.motif_geom = affinity.translate(self.motif_geom, xoff=-minx, yoff=-miny)
        self.update_motif_item(True)
        print("🔄 90° gedreht.")
        self.refit_view()


    # ===== Export =====
    def save_dialog(self):
        if not self.motif_geom:
            print("⚠ Kein Motiv.")
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "Exportieren als...",
            "output.stl",
            "STL-Dateien (*.stl);;3MF-Dateien (*.3mf)"
        )
        if not out:
            return
        fmt = "stl" if out.lower().endswith(".stl") else "3mf"
        try:
            pos = self.motif_item.pos() if self.motif_item else QPointF(0, 0)
            mesh = build_and_transform_mesh(self.motif_geom, pos.x(), pos.y())
            mesh.export(out)
            print(f"✅ {fmt.upper()} exportiert: {out}")
        except Exception as e:
            print(f"❌ Export fehlgeschlagen: {e}")