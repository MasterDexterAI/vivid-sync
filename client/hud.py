from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

STYLE = """
QWidget#panel { background: rgba(18, 18, 20, 225); border-radius: 12px; }
QLabel { color: #e8e8e8; font-family: 'Inter', 'Segoe UI', sans-serif; font-size: 13px; }
QLabel#status { color: #9aa0a6; font-size: 11px; }
QLabel#header { color: #9aa0a6; font-size: 10px; letter-spacing: 1px; }
QLabel#answer { font-size: 15px; color: #ffffff; }
QListWidget { background: transparent; border: none; color: #e8e8e8; font-size: 12px; }
"""

VERDICT_COLORS = {"contradicted": "#ff6b6b", "unverifiable": "#f5c542", "supported": "#7bd88f"}


class Bridge(QObject):
    event = Signal(dict)


class Hud(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vivid Sync")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(420, 560)
        self.drag_from = None

        panel = QWidget(self)
        panel.setObjectName("panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)

        self.status = QLabel("connecting")
        self.status.setObjectName("status")
        self.answer = QLabel("")
        self.answer.setObjectName("answer")
        self.answer.setWordWrap(True)
        self.transcript = QLabel("")
        self.transcript.setWordWrap(True)
        self.transcript.setStyleSheet("color:#8a8f98; font-size:11px;")
        self.claims = QListWidget()
        self.tasks = QListWidget()

        for title, widget in (("STATUS", self.status), ("SUGGESTION", self.answer), ("HEARD", self.transcript), ("FACT CHECKS", self.claims), ("TASKS", self.tasks)):
            header = QLabel(title)
            header.setObjectName("header")
            layout.addWidget(header)
            layout.addWidget(widget)
        self.setStyleSheet(STYLE)
        self.latency = None
        self.speaking = False

    def mousePressEvent(self, e):
        self.drag_from = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.drag_from is not None:
            self.move(e.globalPosition().toPoint() - self.drag_from)

    def mouseReleaseEvent(self, e):
        self.drag_from = None

    def refresh_status(self, state: str):
        parts = [state]
        if self.latency is not None:
            parts.append(f"first token {self.latency} ms")
        self.status.setText("  ·  ".join(parts))

    def on_event(self, ev: dict):
        kind = ev.get("type")
        if kind == "status":
            self.refresh_status(f"ready · {ev.get('model', '')}")
        elif kind == "speech":
            self.refresh_status("listening" if ev["state"] == "start" else "thinking")
        elif kind == "latency":
            self.latency = ev["ttft_ms"]
            self.refresh_status("answering")
        elif kind == "delta":
            if self.answer.property("fresh"):
                self.answer.setText("")
                self.answer.setProperty("fresh", False)
            self.answer.setText(self.answer.text() + ev["text"])
        elif kind == "done":
            self.answer.setProperty("fresh", True)
        elif kind == "interrupted":
            self.answer.setProperty("fresh", True)
            self.refresh_status("interrupted")
        elif kind == "transcript":
            self.transcript.setText(ev["text"][-240:])
        elif kind == "claim":
            item = QListWidgetItem(f"{ev['verdict'].upper()}  {ev['claim']}\n  {ev['evidence']}")
            item.setForeground(QColor(VERDICT_COLORS.get(ev["verdict"], "#e8e8e8")))
            self.claims.insertItem(0, item)
        elif kind == "task":
            self.tasks.addItem(f"☐ {ev['task']}  ({ev['owner']}, {ev['due']})")
        elif kind == "error":
            self.refresh_status(f"error: {ev.get('message', '')[:80]}")
        elif kind == "connection":
            self.refresh_status(ev["state"])

