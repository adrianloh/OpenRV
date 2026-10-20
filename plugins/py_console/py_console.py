from rv import rvtypes, commands, extra_commands
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QTextEdit, QApplication,
)
from PySide6.QtCore import Qt
import os
import time


class PyConsoleWidget(QWidget):
    """Modeless Python console window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Python Console")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.resize(700, 400)

        layout = QVBoxLayout(self)

        # Output area
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setStyleSheet(
            "QTextEdit { background: #1e1e1e; color: #d4d4d4; "
            "font-family: Consolas, monospace; font-size: 11px; }"
        )
        layout.addWidget(self._output)

        # Input row
        inputRow = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Enter Python code...")
        self._input.setStyleSheet(
            "QLineEdit { background: #252526; color: #d4d4d4; "
            "font-family: Consolas, monospace; font-size: 11px; "
            "padding: 4px; }"
        )
        self._input.returnPressed.connect(self._run)
        inputRow.addWidget(self._input)

        runBtn = QPushButton("Run")
        runBtn.clicked.connect(self._run)
        inputRow.addWidget(runBtn)

        clearBtn = QPushButton("Clear")
        clearBtn.clicked.connect(self._output.clear)
        inputRow.addWidget(clearBtn)

        layout.addLayout(inputRow)

        # History
        self._history = []
        self._historyIdx = -1

        # Namespace for eval/exec
        import rv.commands as c
        import rv.extra_commands as ec
        self._namespace = {
            "commands": c, "c": c,
            "extra_commands": ec, "ec": ec,
            "os": os, "time": time,
        }

    def _run(self):
        code = self._input.text().strip()
        if not code:
            return

        self._history.append(code)
        self._historyIdx = -1
        self._output.append("<span style='color:#569cd6'>&gt;&gt;&gt; %s</span>" % code)

        try:
            val = eval(code, self._namespace)
            output = repr(val)
            self._output.append("<span style='color:#b5cea8'>%s</span>" % output)
        except SyntaxError:
            try:
                exec(code, self._namespace)
                self._output.append("<span style='color:#6a9955'>(ok)</span>")
            except Exception as e:
                self._output.append("<span style='color:#f44747'>ERROR: %s</span>" % e)
        except Exception as e:
            self._output.append("<span style='color:#f44747'>ERROR: %s</span>" % e)

        self._input.clear()
        # Scroll to bottom
        sb = self._output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Up and self._history:
            if self._historyIdx == -1:
                self._historyIdx = len(self._history) - 1
            elif self._historyIdx > 0:
                self._historyIdx -= 1
            self._input.setText(self._history[self._historyIdx])
        elif event.key() == Qt.Key_Down and self._history:
            if self._historyIdx < len(self._history) - 1:
                self._historyIdx += 1
                self._input.setText(self._history[self._historyIdx])
            else:
                self._historyIdx = -1
                self._input.clear()
        else:
            super().keyPressEvent(event)


class PyConsoleMode(rvtypes.MinorMode):
    """OpenRV mode that provides a Python console."""

    def __init__(self):
        rvtypes.MinorMode.__init__(self)

        import shutil
        try:
            shutil.rmtree("C:\\Users\\TTWP\\AppData\\Roaming\\RV\\Python\\__pycache__")
        except Exception:
            pass

        self.init(
            "py_console_mode",
            [("key-down--control--`", self._toggle, "Toggle Python Console")],
            None,
            [
                (
                    "Tools",
                    [
                        ("Python Console", self._toggle, None, None),
                    ],
                )
            ],
        )
        self._widget = None

    def _toggle(self, event):
        if isinstance(event, object) and hasattr(event, 'reject'):
            event.reject()

        if self._widget and self._widget.isVisible():
            self._widget.hide()
        else:
            if not self._widget:
                parent = QApplication.activeWindow()
                self._widget = PyConsoleWidget(parent)
            self._widget.show()
            self._widget.raise_()
            self._widget._input.setFocus()


def createMode():
    return PyConsoleMode()
