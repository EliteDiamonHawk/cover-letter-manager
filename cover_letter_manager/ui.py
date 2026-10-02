from __future__ import annotations

import subprocess
import sys
import traceback
from datetime import date
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QDate, QObject, QRunnable, QThreadPool, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .models import CoverLetterEntry
from .pdf_convert import SUPPORTED_INPUT_EXTENSIONS
from .repository import CoverLetterRepository, CreateEntryRequest
from .semantic import SemanticIndex


class TaskSignals(QObject):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(str)


class FunctionTask(QRunnable):
    def __init__(self, function: Callable[[Callable[[str], None]], object]) -> None:
        super().__init__()
        self.function = function
        self.signals = TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.function(self.signals.progress.emit)
        except Exception as exc:
            details = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.signals.error.emit(details)
        else:
            self.signals.finished.emit(result)


class NewEntryDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create cover-letter entry")
        self.resize(620, 470)

        self.company_edit = QLineEdit()
        self.company_edit.setPlaceholderText("Example: NVIDIA")
        self.position_edit = QLineEdit()
        self.position_edit.setPlaceholderText("Example: Software Engineer")
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")

        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        browse_button = QPushButton("Choose letter...")
        browse_button.clicked.connect(self._choose_file)
        file_row = QWidget()
        file_layout = QHBoxLayout(file_row)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.addWidget(self.file_edit, 1)
        file_layout.addWidget(browse_button)

        form = QFormLayout()
        form.addRow("Company*", self.company_edit)
        form.addRow("Position*", self.position_edit)
        form.addRow("Date*", self.date_edit)
        form.addRow("Letter file*", file_row)

        metadata_label = QLabel(
            "Optional metadata, one key/value pair per line. Use key=value, for example "
            "job_url=https://example.com or status=applied."
        )
        metadata_label.setWordWrap(True)
        self.metadata_edit = QPlainTextEdit()
        self.metadata_edit.setPlaceholderText(
            "status=applied\njob_url=https://example.com/jobs/123\ncontact=Hiring Manager"
        )

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addSpacing(8)
        layout.addWidget(QLabel("Extra metadata"))
        layout.addWidget(metadata_label)
        layout.addWidget(self.metadata_edit, 1)
        layout.addWidget(self.buttons)

    def _choose_file(self) -> None:
        extensions = " ".join(f"*{extension}" for extension in sorted(SUPPORTED_INPUT_EXTENSIONS))
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a cover letter",
            "",
            f"Supported cover letters ({extensions});;All files (*)",
        )
        if selected:
            self.file_edit.setText(selected)

    def _parse_extra(self) -> dict[str, str]:
        extra: dict[str, str] = {}
        for line_number, raw_line in enumerate(self.metadata_edit.toPlainText().splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"Metadata line {line_number} must use key=value.")
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                raise ValueError(f"Metadata line {line_number} has an empty key.")
            if key in extra:
                raise ValueError(f"Metadata key {key!r} is duplicated.")
            extra[key] = value
        return extra

    def accept(self) -> None:
        if not self.company_edit.text().strip():
            QMessageBox.warning(self, "Missing company", "Company is required.")
            return
        if not self.position_edit.text().strip():
            QMessageBox.warning(self, "Missing position", "Position is required.")
            return
        source = Path(self.file_edit.text())
        if not source.exists() or not source.is_file():
            QMessageBox.warning(self, "Missing letter", "Choose an existing cover-letter file.")
            return
        try:
            self._parse_extra()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid metadata", str(exc))
            return
        super().accept()

    def request(self) -> CreateEntryRequest:
        selected_date = date.fromisoformat(self.date_edit.date().toString("yyyy-MM-dd"))
        return CreateEntryRequest(
            company=self.company_edit.text().strip(),
            position=self.position_edit.text().strip(),
            application_date=selected_date,
            source_file=Path(self.file_edit.text()),
            extra=self._parse_extra(),
        )


def reveal_in_file_manager(path: Path) -> None:
    resolved = path.resolve()
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(resolved)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(resolved)])
        else:
            target = resolved if resolved.is_dir() else resolved.parent
            subprocess.Popen(["xdg-open", str(target)])
    except OSError as exc:
        raise RuntimeError(f"Could not open the file manager: {exc}") from exc


class MainWindow(QMainWindow):
    def __init__(self, repository: CoverLetterRepository, semantic_index: SemanticIndex) -> None:
        super().__init__()
        self.repository = repository
        self.semantic_index = semantic_index
        self.thread_pool = QThreadPool.globalInstance()
        self.entries: list[CoverLetterEntry] = []
        self.entry_by_id: dict[str, CoverLetterEntry] = {}
        self.semantic_scores: dict[str, float] = {}
        self._semantic_query = ""
        self._busy = False

        self.setWindowTitle(f"Cover Letter Manager - {self.repository.root}")
        self.resize(1180, 720)
        self._build_actions()
        self._build_ui()
        self.refresh_entries()

    def _build_actions(self) -> None:
        self.new_action = QAction("New entry", self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.create_entry)

        self.refresh_action = QAction("Refresh", self)
        self.refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self.refresh_action.triggered.connect(self.refresh_entries)

        self.rebuild_action = QAction("Rebuild semantic index", self)
        self.rebuild_action.triggered.connect(self.rebuild_semantic_index)

        self.open_pdf_action = QAction("Open PDF", self)
        self.open_pdf_action.triggered.connect(self.open_pdf)
        self.open_original_action = QAction("Open original", self)
        self.open_original_action.triggered.connect(self.open_original)
        self.reveal_action = QAction("Show in file manager", self)
        self.reveal_action.triggered.connect(self.reveal_selected)

        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.refresh_action)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        tools_menu = self.menuBar().addMenu("Tools")
        tools_menu.addAction(self.rebuild_action)

        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction("About", self.show_about)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addAction(self.new_action)
        toolbar.addAction(self.refresh_action)
        toolbar.addSeparator()
        toolbar.addAction(self.open_pdf_action)
        toolbar.addAction(self.open_original_action)
        toolbar.addAction(self.reveal_action)
        toolbar.addSeparator()
        toolbar.addAction(self.rebuild_action)

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)

        search_group = QGroupBox("Search and filters")
        search_layout = QGridLayout(search_group)

        self.semantic_edit = QLineEdit()
        self.semantic_edit.setPlaceholderText(
            "Example: letters emphasizing distributed systems and Python backend work"
        )
        self.semantic_edit.returnPressed.connect(self.run_search)

        self.company_combo = QComboBox()
        self.company_combo.setEditable(True)
        self.company_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.company_combo.lineEdit().setPlaceholderText("Any company")

        self.position_combo = QComboBox()
        self.position_combo.setEditable(True)
        self.position_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.position_combo.lineEdit().setPlaceholderText("Any position")

        self.from_check = QCheckBox("From")
        self.from_date = QDateEdit(QDate.currentDate().addYears(-1))
        self.from_date.setDisplayFormat("yyyy-MM-dd")
        self.from_date.setCalendarPopup(True)
        self.from_date.setEnabled(False)
        self.from_check.toggled.connect(self.from_date.setEnabled)

        self.to_check = QCheckBox("To")
        self.to_date = QDateEdit(QDate.currentDate())
        self.to_date.setDisplayFormat("yyyy-MM-dd")
        self.to_date.setCalendarPopup(True)
        self.to_date.setEnabled(False)
        self.to_check.toggled.connect(self.to_date.setEnabled)

        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.run_search)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset_filters)

        search_layout.addWidget(QLabel("Semantic query"), 0, 0)
        search_layout.addWidget(self.semantic_edit, 0, 1, 1, 7)
        search_layout.addWidget(QLabel("Company"), 1, 0)
        search_layout.addWidget(self.company_combo, 1, 1)
        search_layout.addWidget(QLabel("Position"), 1, 2)
        search_layout.addWidget(self.position_combo, 1, 3)
        search_layout.addWidget(self.from_check, 1, 4)
        search_layout.addWidget(self.from_date, 1, 5)
        search_layout.addWidget(self.to_check, 1, 6)
        search_layout.addWidget(self.to_date, 1, 7)
        search_layout.addWidget(self.search_button, 2, 6)
        search_layout.addWidget(self.reset_button, 2, 7)
        search_layout.setColumnStretch(1, 1)
        search_layout.setColumnStretch(3, 1)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Score", "Company", "Position", "Date", "Original", "PDF"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self.update_details)
        self.table.itemDoubleClicked.connect(lambda _item: self.open_pdf())

        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.addWidget(QLabel("Selected entry"))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        details_layout.addWidget(self.details, 1)

        button_row = QHBoxLayout()
        self.open_pdf_button = QPushButton("Open PDF")
        self.open_pdf_button.clicked.connect(self.open_pdf)
        self.open_original_button = QPushButton("Open original")
        self.open_original_button.clicked.connect(self.open_original)
        self.reveal_button = QPushButton("Show in file manager")
        self.reveal_button.clicked.connect(self.reveal_selected)
        button_row.addWidget(self.open_pdf_button)
        button_row.addWidget(self.open_original_button)
        button_row.addWidget(self.reveal_button)
        details_layout.addLayout(button_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(details_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([760, 420])

        root_layout.addWidget(search_group)
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage(f"Root: {self.repository.root}")
        self._update_selection_actions()

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        for widget in (
            self.search_button,
            self.reset_button,
            self.new_action,
            self.refresh_action,
            self.rebuild_action,
        ):
            widget.setEnabled(not busy)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor) if busy else QApplication.restoreOverrideCursor()
        if message:
            self.statusBar().showMessage(message)

    def _start_task(
        self,
        function: Callable[[Callable[[str], None]], object],
        *,
        on_finished: Callable[[object], None],
    ) -> None:
        task = FunctionTask(function)
        task.signals.progress.connect(self.statusBar().showMessage)
        task.signals.error.connect(self._task_failed)
        task.signals.finished.connect(on_finished)
        self.thread_pool.start(task)

    def _task_failed(self, message: str) -> None:
        self._set_busy(False)
        QMessageBox.warning(self, "Operation failed", message)
        self.statusBar().showMessage("Operation failed.", 5000)

    def refresh_entries(self) -> None:
        if self._busy:
            return
        result = self.repository.scan()
        self.entries = list(result.entries)
        self.entry_by_id = {entry.entry_id: entry for entry in self.entries}
        self.semantic_scores.clear()
        self._semantic_query = ""
        self._populate_filter_values()
        self._render_entries(self._metadata_filtered_entries())
        warning_text = f"; {len(result.warnings)} warning(s)" if result.warnings else ""
        self.statusBar().showMessage(f"Loaded {len(self.entries)} entries{warning_text}.")
        if result.warnings:
            self.statusBar().setToolTip("\n".join(result.warnings[:20]))
        else:
            self.statusBar().setToolTip("")

    def _populate_filter_values(self) -> None:
        current_company = self.company_combo.currentText()
        current_position = self.position_combo.currentText()
        companies = sorted({entry.company for entry in self.entries}, key=str.casefold)
        positions = sorted({entry.position for entry in self.entries}, key=str.casefold)

        self.company_combo.blockSignals(True)
        self.company_combo.clear()
        self.company_combo.addItem("")
        self.company_combo.addItems(companies)
        self.company_combo.setCurrentText(current_company)
        self.company_combo.blockSignals(False)

        self.position_combo.blockSignals(True)
        self.position_combo.clear()
        self.position_combo.addItem("")
        self.position_combo.addItems(positions)
        self.position_combo.setCurrentText(current_position)
        self.position_combo.blockSignals(False)

    def _metadata_filtered_entries(self) -> list[CoverLetterEntry]:
        company = self.company_combo.currentText().strip().casefold()
        position = self.position_combo.currentText().strip().casefold()
        from_date = (
            date.fromisoformat(self.from_date.date().toString("yyyy-MM-dd"))
            if self.from_check.isChecked()
            else None
        )
        to_date = (
            date.fromisoformat(self.to_date.date().toString("yyyy-MM-dd"))
            if self.to_check.isChecked()
            else None
        )

        filtered: list[CoverLetterEntry] = []
        for entry in self.entries:
            if company and company not in entry.company.casefold():
                continue
            if position and position not in entry.position.casefold():
                continue
            if from_date and entry.application_date < from_date:
                continue
            if to_date and entry.application_date > to_date:
                continue
            filtered.append(entry)
        return filtered

    def run_search(self) -> None:
        if self._busy:
            return
        query = self.semantic_edit.text().strip()
        if not query:
            self.semantic_scores.clear()
            self._semantic_query = ""
            self._render_entries(self._metadata_filtered_entries())
            self.statusBar().showMessage("Metadata filters applied.")
            return

        self._set_busy(True, "Preparing semantic search...")
        self._semantic_query = query

        def operation(progress: Callable[[str], None]):
            return self.semantic_index.search(
                self.entries,
                query,
                top_k=max(100, len(self.entries)),
                progress=progress,
            )

        self._start_task(operation, on_finished=self._semantic_search_finished)

    def _semantic_search_finished(self, result: object) -> None:
        ranked = list(result)  # type: ignore[arg-type]
        self.semantic_scores = {str(entry_id): float(score) for entry_id, score in ranked}
        filtered = [
            entry for entry in self._metadata_filtered_entries() if entry.entry_id in self.semantic_scores
        ]
        filtered.sort(key=lambda entry: self.semantic_scores[entry.entry_id], reverse=True)
        self._render_entries(filtered)
        self._set_busy(False)
        self.statusBar().showMessage(f"Semantic search returned {len(filtered)} entries.")

    def rebuild_semantic_index(self) -> None:
        if self._busy:
            return
        if not self.entries:
            QMessageBox.information(self, "No entries", "Create at least one entry first.")
            return
        self._set_busy(True, "Rebuilding semantic index...")

        def operation(progress: Callable[[str], None]):
            return self.semantic_index.rebuild(self.entries, progress=progress)

        self._start_task(operation, on_finished=self._rebuild_finished)

    def _rebuild_finished(self, result: object) -> None:
        self.semantic_scores.clear()
        self._set_busy(False)
        self.statusBar().showMessage(f"Semantic index rebuilt with {int(result)} chunks.")

    def reset_filters(self) -> None:
        if self._busy:
            return
        self.semantic_edit.clear()
        self.company_combo.setCurrentText("")
        self.position_combo.setCurrentText("")
        self.from_check.setChecked(False)
        self.to_check.setChecked(False)
        self.semantic_scores.clear()
        self._semantic_query = ""
        self._render_entries(self.entries)
        self.statusBar().showMessage("Filters reset.")

    def _render_entries(self, entries: list[CoverLetterEntry]) -> None:
        if not self._semantic_query:
            entries = sorted(entries, key=lambda entry: entry.application_date, reverse=True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            score = self.semantic_scores.get(entry.entry_id)
            score_item = QTableWidgetItem("" if score is None else f"{score:.3f}")
            score_item.setData(Qt.ItemDataRole.UserRole, entry.entry_id)
            self.table.setItem(row, 0, score_item)
            self.table.setItem(row, 1, QTableWidgetItem(entry.company))
            self.table.setItem(row, 2, QTableWidgetItem(entry.position))
            self.table.setItem(row, 3, QTableWidgetItem(entry.application_date.isoformat()))
            self.table.setItem(row, 4, QTableWidgetItem(entry.original_path.suffix.lstrip(".").upper()))
            self.table.setItem(row, 5, QTableWidgetItem("Yes" if entry.pdf_path.exists() else "Missing"))
        self.table.setSortingEnabled(True)
        self.table.resizeRowsToContents()
        if entries:
            self.table.selectRow(0)
        else:
            self.details.clear()
            self._update_selection_actions()

    def selected_entry(self) -> CoverLetterEntry | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        return self.entry_by_id.get(str(entry_id))

    def update_details(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            self.details.clear()
            self._update_selection_actions()
            return
        lines = [
            f"Company: {entry.company}",
            f"Position: {entry.position}",
            f"Date: {entry.application_date.isoformat()}",
            f"Entry ID: {entry.entry_id}",
            f"Original source name: {entry.source_name}",
            "",
            f"Original: {entry.original_path}",
            f"PDF: {entry.pdf_path}",
            f"Metadata: {entry.prop_path}",
        ]
        if entry.extra:
            lines.extend(["", "Extra metadata:"])
            for key, value in sorted(entry.extra.items(), key=lambda item: item[0].casefold()):
                lines.append(f"  {key} = {value}")
        self.details.setPlainText("\n".join(lines))
        self._update_selection_actions()

    def _update_selection_actions(self) -> None:
        entry = self.selected_entry()
        has_entry = entry is not None
        has_pdf = bool(entry and entry.pdf_path.exists())
        has_original = bool(entry and entry.original_path.exists())
        self.open_pdf_action.setEnabled(has_pdf)
        self.open_original_action.setEnabled(has_original)
        self.reveal_action.setEnabled(has_entry)
        self.open_pdf_button.setEnabled(has_pdf)
        self.open_original_button.setEnabled(has_original)
        self.reveal_button.setEnabled(has_entry)

    def create_entry(self) -> None:
        if self._busy:
            return
        dialog = NewEntryDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            entry = self.repository.create_entry(dialog.request())
        except Exception as exc:
            QMessageBox.critical(self, "Could not create entry", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh_entries()
        self._select_entry(entry.entry_id)
        self.statusBar().showMessage(f"Created {entry.company} - {entry.position}.")

    def _select_entry(self, entry_id: str) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) == entry_id:
                self.table.selectRow(row)
                self.table.scrollToItem(item)
                return

    def _open_path(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.warning(self, "File missing", f"File does not exist:\n{path}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            QMessageBox.warning(self, "Could not open file", f"No application could open:\n{path}")

    def open_pdf(self) -> None:
        entry = self.selected_entry()
        if entry:
            self._open_path(entry.pdf_path)

    def open_original(self) -> None:
        entry = self.selected_entry()
        if entry:
            self._open_path(entry.original_path)

    def reveal_selected(self) -> None:
        entry = self.selected_entry()
        if not entry:
            return
        target = entry.pdf_path if entry.pdf_path.exists() else entry.folder
        try:
            reveal_in_file_manager(target)
        except RuntimeError as exc:
            QMessageBox.warning(self, "Could not open file manager", str(exc))

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Cover Letter Manager",
            "Cover Letter Manager\n\n"
            "Files and .prop metadata are the source of truth. Semantic vectors are stored "
            "in a disposable hidden index under the selected root directory.",
        )
