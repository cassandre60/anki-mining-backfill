"""Preview dialog: show the plan, accept rows, apply them.

Qt-facing module. It never decides anything itself — the plan comes from
``plan.py`` and the re-assertion from ``applier.py`` — so what the user sees
is exactly what is written.
"""

from __future__ import annotations

from aqt.qt import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFont,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTimer,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import showCritical, showInfo

from .applier import ApplyDecision, run_after_editor_saved
from .collection_io import (
    Preview,
    apply_decision,
    build_decision,
    load_config,
    plan_preview,
    write_run_log,
)
from .plan import PlannedWrite
from .report import OP_LABELS

_HEADERS = ["", "note", "field", "change", "source", "badges"]
_CHECK_ROLE = int(Qt.ItemDataRole.UserRole) + 1
_KEY_ROLE = int(Qt.ItemDataRole.UserRole) + 2


def _clip(text: str, limit: int = 120) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _change_summary(write: PlannedWrite) -> str:
    if write.op == "add_tags":
        added = " ".join(sorted(set(write.new_value.split()) - set(write.old_value.split())))
        base = write.old_value or "(no tags)"
        return _clip(f"{base}  +  {added}")
    if write.old_value:
        return _clip(f"{write.old_value}  →  {write.new_value}")
    return _clip(write.new_value)


class PreviewDialog(QDialog):
    """The add-on's main window: one row per planned write, checked by default
    exactly as the plan says (guarded rows arrive unchecked)."""

    def __init__(
        self,
        col,
        cfg: dict | None = None,
        scope_note_ids=None,
        browser=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.col = col
        self.cfg = cfg if cfg is not None else load_config()
        self.browser = browser
        self.preview: Preview = plan_preview(col, self.cfg, scope_note_ids)
        self.pending: tuple[ApplyDecision, dict] | None = None
        self.checks: dict[tuple[int, str], bool] = {}

        self.setWindowTitle("Mining Backfill — preview")
        self.resize(1180, 680)
        layout = QVBoxLayout(self)

        if self.preview.error:
            layout.addWidget(QLabel(self.preview.error))
            layout.addWidget(self._close_box())
            return

        plan = self.preview.plan
        assert plan is not None
        checked = sum(1 for w in plan.writes if w.default_checked)
        summary = (
            f"{self.preview.scope_label} · {len(plan.writes)} proposed writes · "
            f"{checked} checked by default · {len(plan.reasons)} not fixable · "
            f"{len(plan.warnings)} warning(s)"
        )
        header = QLabel(summary)
        font = QFont()
        font.setBold(True)
        header.setFont(font)
        layout.addWidget(header)
        if self.preview.excluded:
            excluded = QLabel(
                f"{len(self.preview.excluded)} selected note(s) use a different note type "
                "and were skipped."
            )
            layout.addWidget(excluded)

        tabs = QTabWidget()
        tabs.addTab(self._changes_page(plan.writes), f"Proposed changes ({len(plan.writes)})")
        tabs.addTab(
            self._text_page(self._reason_lines()),
            f"Not fixable ({len(plan.reasons)})",
        )
        tabs.addTab(
            self._text_page(list(plan.warnings)),
            f"Warnings ({len(plan.warnings)})",
        )
        layout.addWidget(tabs)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(150)
        layout.addWidget(self.detail)

        self.status = QLabel("")
        layout.addWidget(self.status)

        box = self._action_box()
        layout.addWidget(box)
        self._refresh_status()

    # --- page builders ------------------------------------------------

    def _changes_page(self, writes) -> QWidget:
        page = QWidget()
        inner = QVBoxLayout(page)
        table = QTableWidget(0, len(_HEADERS))
        table.setHorizontalHeaderLabels(_HEADERS)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(False)
        header = table.horizontalHeader()
        for column in range(len(_HEADERS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        records = self.preview.records_by_id or {}
        seen: set[int] = set()
        table.setRowCount(len(writes))
        for index, write in enumerate(writes):
            key = (write.note_id, write.field)
            self.checks[key] = bool(write.default_checked)

            check_item = QTableWidgetItem()
            check_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            check_item.setCheckState(
                Qt.CheckState.Checked if write.default_checked else Qt.CheckState.Unchecked
            )
            check_item.setData(_KEY_ROLE, f"{key[0]}|{key[1]}")
            table.setItem(index, 0, check_item)

            record = records.get(write.note_id)
            expression = record.get("Expression") if record is not None else ""
            label = f"{expression or '(no expression)'} · {write.note_id}"
            table.setItem(index, 1, QTableWidgetItem(label if write.note_id not in seen else ""))
            seen.add(write.note_id)
            table.setItem(index, 2, QTableWidgetItem(write.field))
            table.setItem(index, 3, QTableWidgetItem(_change_summary(write)))
            source = f"note {write.source_note_id}" if write.source_note_id else ""
            table.setItem(index, 4, QTableWidgetItem(source))
            table.setItem(index, 5, QTableWidgetItem(", ".join(write.badges)))

        table.itemChanged.connect(self._on_item_changed)
        table.itemSelectionChanged.connect(lambda: self._show_detail(table))
        self.table = table
        inner.addWidget(table)
        return page

    def _text_page(self, lines: list[str]) -> QWidget:
        page = QWidget()
        inner = QVBoxLayout(page)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText("\n".join(lines) if lines else "Nothing to report.")
        inner.addWidget(view)
        return page

    def _reason_lines(self) -> list[str]:
        plan = self.preview.plan
        records = self.preview.records_by_id or {}
        assert plan is not None
        lines = []
        for note_id, reason in sorted(plan.reasons.items()):
            record = records.get(note_id)
            expression = record.get("Expression") if record is not None else ""
            lines.append(f"{expression or '(no expression)'} · {note_id}: {reason}")
        return lines

    # --- interaction --------------------------------------------------

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0 or self.table.itemChanged is None:
            return
        raw = item.data(_KEY_ROLE)
        if not raw:
            return
        note_id, field = str(raw).split("|", 1)
        self.checks[(int(note_id), field)] = item.checkState() == Qt.CheckState.Checked
        self._refresh_status()

    def _show_detail(self, table: QTableWidget) -> None:
        plan = self.preview.plan
        if plan is None:
            return
        rows = {index.row() for index in table.selectedIndexes()}
        if not rows:
            return
        write = plan.writes[min(rows)]
        lines = [
            f"note {write.note_id} · {write.field} · {OP_LABELS.get(write.op, write.op)}",
            f"badges: {', '.join(write.badges) or '(none)'}",
            "",
            "current:",
            write.old_value or "(empty)",
            "",
            "after:",
            write.new_value,
        ]
        self.detail.setPlainText("\n".join(lines))

    def _checked_keys(self) -> list[tuple[int, str]]:
        return [key for key, on in self.checks.items() if on]

    def _refresh_status(self) -> None:
        count = len(self._checked_keys())
        applied_tag = self.cfg.get("applied_tag")
        note = f" · notes written get the tag “{applied_tag}”" if applied_tag else ""
        self.status.setText(f"{count} row(s) selected{note}")
        if hasattr(self, "apply_button"):
            self.apply_button.setText(f"Apply {count} checked change(s)")
            self.apply_button.setEnabled(count > 0)

    def _action_box(self) -> QDialogButtonBox:
        box = QDialogButtonBox()
        self.apply_button = QPushButton("Apply")
        self.apply_button.setDefault(True)
        self.apply_button.clicked.connect(self._on_apply)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        box.addButton(self.apply_button, QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(close_button, QDialogButtonBox.ButtonRole.RejectRole)
        return box

    def _close_box(self) -> QDialogButtonBox:
        box = QDialogButtonBox()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        box.addButton(close_button, QDialogButtonBox.ButtonRole.RejectRole)
        return box

    # --- apply --------------------------------------------------------

    def _on_apply(self) -> None:
        plan = self.preview.plan
        if plan is None:
            return
        decision = build_decision(self.col, plan, self._checked_keys(), self.cfg)
        if not decision.row_count() and not decision.skipped:
            showInfo("Nothing to apply: no row is selected.", parent=self)
            return
        # Nothing is written here: this slot runs inside the dialog's nested
        # event loop, and Anki's editor may still be saving. The decision is
        # handed to open_preview_dialog(), which writes after this dialog has
        # closed and the editor has flushed (see applier.run_after_editor_saved).
        self.pending = (
            decision,
            {
                "run": plan.version,
                "deck": self.cfg.get("deck_name"),
                "scope": list(self.preview.scope),
                "rows": decision.row_count(),
            },
        )
        self.accept()


def _finish_apply(col, decision: ApplyDecision, meta: dict, parent) -> None:
    """Perform the writes and report the outcome (runs outside the dialog)."""
    modified = apply_decision(col, decision)
    log_path = write_run_log(decision, meta) if decision.row_count() else None
    lines = [f"Applied {decision.row_count()} write(s) to {modified} note(s)."]
    if decision.skipped:
        by_reason: dict[str, int] = {}
        for skipped in decision.skipped:
            by_reason[skipped.reason] = by_reason.get(skipped.reason, 0) + 1
        detail = ", ".join(f"{count} {reason}" for reason, count in sorted(by_reason.items()))
        lines.append(f"Skipped {len(decision.skipped)} note(s): {detail}.")
    if log_path is not None:
        lines.append(
            f"Undo available: Tools → “Mining Backfill: undo last run”.\nLog: {log_path.name}"
        )
    showInfo("\n".join(lines), parent=parent)


def apply_pending(col, pending, browser=None, parent=None) -> None:
    """Write the accepted rows once the host is quiescent.

    The editor flush comes first so a pending Browser save cannot land on top
    of the values this run writes. The 1.5 s safety net only fires if Anki
    loses the save callback (torn-down editor); the write is once-only either
    way.
    """
    decision, meta = pending
    run_after_editor_saved(
        browser,
        lambda: _finish_apply(col, decision, meta, parent),
        schedule=lambda once: QTimer.singleShot(1500, once),
    )


def open_preview_dialog(scope_note_ids=None, browser=None) -> None:
    """Menu entry point: preview, then apply once the dialog has closed.

    ``scope_note_ids`` is the Browser selection when called from the context
    menu; omitted, the dialog plans the newest ``preview_last_n`` notes.
    ``browser`` (when known) is used to flush its editor before writing, so a
    pending editor save cannot overwrite this run.
    """
    from aqt import mw

    if mw is None or mw.col is None:
        showCritical("Open a profile first.", parent=mw)
        return
    dialog = PreviewDialog(mw.col, load_config(), scope_note_ids, browser=browser, parent=mw)
    dialog.exec()
    if dialog.pending is not None:
        apply_pending(mw.col, dialog.pending, browser=browser, parent=mw)
