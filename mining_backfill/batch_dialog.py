"""Batch dialog: counts and a shortlist, never a thousand checkboxes.

Qt-facing module. Every decision (which rows, which tiers, what a note needs)
comes from the pure ``batch`` module, so the same selection logic is unit
tested headless.
"""

from __future__ import annotations

from aqt.qt import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFont,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTimer,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import showCritical, showInfo

from .applier import ApplyDecision, run_after_editor_saved
from .batch import BatchSelection, allowed_ops, select
from .collection_io import (
    Preview,
    apply_batch,
    build_batch_decision,
    load_config,
    plan_preview,
    write_dry_run,
)

_OP_SUMMARY = {
    "fill": "fills",
    "bold_cloze_word": "bold repairs",
    "add_tags": "tag additions",
    "expand_sentence": "sentence rewrites",
    "replace_source": "source replacements",
}


class BatchDialog(QDialog):
    """One screen for a bulk run: what will change, what will not, what needs
    a human — and the two opt-in replace tiers."""

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

        self.setWindowTitle("Mining Backfill — batch")
        self.resize(760, 520)
        layout = QVBoxLayout(self)

        if self.preview.error:
            layout.addWidget(QLabel(self.preview.error))
            layout.addWidget(self._close_box())
            return

        title = QLabel(self.preview.scope_label)
        font = QFont()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.expand_box = QCheckBox(
            "Also expand Sentence  (fragment → full scene; the fragment stays in cloze-*)"
        )
        self.expand_box.toggled.connect(self._refresh)
        layout.addWidget(self.expand_box)
        self.source_box = QCheckBox(
            "Also replace blob Source  (the blob URL is kept in the run log)"
        )
        self.source_box.toggled.connect(self._refresh)
        layout.addWidget(self.source_box)

        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.review_button = QPushButton("")
        self.review_button.clicked.connect(self._toggle_review)
        layout.addWidget(self.review_button)
        self.review_list = QListWidget()
        self.review_list.setVisible(False)
        self.review_list.setMaximumHeight(200)
        layout.addWidget(self.review_list)

        self.status = QLabel("")
        layout.addWidget(self.status)

        box = QDialogButtonBox()
        self.apply_button = QPushButton("Apply")
        self.apply_button.setDefault(True)
        self.apply_button.clicked.connect(self._on_apply)
        self.dry_button = QPushButton("Write dry-run report")
        self.dry_button.clicked.connect(self._on_dry_run)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        box.addButton(self.apply_button, QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(self.dry_button, QDialogButtonBox.ButtonRole.ActionRole)
        box.addButton(close_button, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(box)
        self._refresh()

    # --- state --------------------------------------------------------

    def _selection(self) -> BatchSelection:
        plan = self.preview.plan
        assert plan is not None
        return select(
            plan,
            allowed_ops(
                expand_sentence=self.expand_box.isChecked(),
                replace_source=self.source_box.isChecked(),
            ),
        )

    def _meta(self, selection: BatchSelection) -> dict:
        plan = self.preview.plan
        assert plan is not None
        return {
            "run": plan.version,
            "kind": "batch",
            "deck": self.cfg.get("deck_name"),
            "scope": len(self.preview.scope),
            "rows": len(selection.rows),
            "notes": selection.notes,
            "expand_sentence": self.expand_box.isChecked(),
            "replace_source": self.source_box.isChecked(),
        }

    def _refresh(self) -> None:
        selection = self._selection()
        by_op = selection.count_by_op()
        field_ops = {op: n for op, n in by_op.items() if op != "add_tags"}
        field_label = ", ".join(
            f"{count} {_OP_SUMMARY.get(op, op)}" for op, count in field_ops.items()
        )
        parts: list[str] = []
        if selection.field_notes:
            parts.append(
                f"{selection.field_notes} note(s) will be filled"
                + (f": {field_label}" if field_label else "")
            )
        if selection.tag_only_notes:
            parts.append(f"{selection.tag_only_notes} note(s) only gain tags")
        if selection.untouched:
            parts.append(f"{selection.untouched} left exactly as they are")
        if selection.sentences_left_alone:
            parts.append(f"{selection.sentences_left_alone} sentence(s) left as they are")
        if selection.left_alone:
            parts.append(f"{len(selection.left_alone)} left alone")
        self.summary.setText((" · ".join(parts) + ".") if parts else "Nothing to do.")

        extras = []
        current_rows = len(selection.rows)
        if not self.expand_box.isChecked():
            with_expand = select(self.preview.plan, allowed_ops(True, self.source_box.isChecked()))
            added = len(with_expand.rows) - current_rows
            if added > 0:
                extra = f"expanding Sentence adds {added} more write(s)"
                more_notes = with_expand.field_notes - selection.field_notes
                if more_notes > 0:
                    extra += f" and fills {more_notes} more note(s)"
                extras.append(extra)
        if not self.source_box.isChecked():
            with_source = select(self.preview.plan, allowed_ops(self.expand_box.isChecked(), True))
            added = len(with_source.rows) - current_rows
            if added > 0:
                extra = f"replacing blob Source adds {added} more write(s)"
                more_notes = with_source.field_notes - selection.field_notes
                if more_notes > 0:
                    extra += f" and fills {more_notes} more note(s)"
                extras.append(extra)
        self.hint.setText(("Available: " + "; ".join(extras) + ".") if extras else "")

        if selection.left_alone:
            self.review_button.setText(f"What was left alone ({len(selection.left_alone)})")
            self.review_button.setVisible(True)
            self.review_list.clear()
            names = self.preview.records_by_id or {}
            for item in selection.left_alone:
                record = names.get(item.note_id)
                expression = record.get("Expression") if record is not None else ""
                suffix = f" [{', '.join(item.rows)}]" if item.rows else ""
                self.review_list.addItem(
                    QListWidgetItem(
                        f"{expression or '(no expression)'} · {item.note_id}: {item.reason}{suffix}"
                    )
                )
        else:
            self.review_button.setVisible(False)
            self.review_list.setVisible(False)

        backup_folder = ""
        try:
            from aqt import mw

            backup_folder = mw.pm.backupFolder() if mw is not None else ""
        except Exception:
            pass
        self.status.setText(
            f"{len(selection.rows)} write(s) · each run takes an Anki backup first"
            + (f" (into {backup_folder})" if backup_folder else "")
        )
        self.apply_button.setText(f"Apply to {selection.notes} note(s)")
        self.apply_button.setEnabled(bool(selection.rows))

    def _toggle_review(self) -> None:
        visible = not self.review_list.isVisible()
        self.review_list.setVisible(visible)
        self.review_button.setText(
            ("Hide" if visible else "Show") + f" what was left alone ({self.review_list.count()})"
        )

    # --- actions ------------------------------------------------------

    def _on_apply(self) -> None:
        plan = self.preview.plan
        if plan is None:
            return
        selection = self._selection()
        if not selection.rows:
            showInfo("Nothing to apply: nothing in this selection needs a change.", parent=self)
            return
        decision = build_batch_decision(self.col, plan, selection.rows, self.cfg)
        if not decision.row_count():
            showInfo("Nothing to apply: everything already matches.", parent=self)
            return
        self.pending = (decision, self._meta(selection))
        self.accept()

    def _on_dry_run(self) -> None:
        plan = self.preview.plan
        if plan is None:
            return
        selection = self._selection()
        path = write_dry_run(plan, self.preview.records_by_id or {}, self._meta(selection))
        showInfo(
            f"Dry-run report written to:\n{path}\n\nNothing was changed in your collection.",
            parent=self,
        )

    def _close_box(self) -> QDialogButtonBox:
        box = QDialogButtonBox()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        box.addButton(close_button, QDialogButtonBox.ButtonRole.RejectRole)
        return box


def _finish_batch(col, pending, parent) -> None:
    decision, meta = pending
    result = apply_batch(col, decision, meta)
    if not result.writes:
        lines = ["Nothing was written."]
        if decision.skipped:
            by_reason: dict[str, int] = {}
            for skipped in decision.skipped:
                by_reason[skipped.reason] = by_reason.get(skipped.reason, 0) + 1
            lines.append(
                "Skipped: "
                + ", ".join(f"{count} {reason}" for reason, count in sorted(by_reason.items()))
            )
        showInfo("\n".join(lines), parent=parent)
        return
    if result.problems and result.log_path is None:
        showInfo(
            "Nothing was written — the safety backup could not be created:\n\n"
            + "\n".join(result.problems),
            parent=parent,
        )
        return
    lines = [
        f"Applied {result.writes} write(s) to {result.modified} note(s).",
        "Backup: " + ("created" if result.backup_created else "not created (no changes yet)"),
    ]
    if result.log_path is not None:
        lines.append(
            f"Undo: Tools → “Mining Backfill: undo last run”.\nLog: {result.log_path.name}"
        )
    if result.problems:
        lines.append("VERIFY PROBLEMS — undo and report these:")
        lines.extend(f"  {problem}" for problem in result.problems)
    else:
        lines.append("Verified: every written value matches the plan.")
    showInfo("\n".join(lines), parent=parent)


def open_batch_dialog(scope_note_ids=None, browser=None) -> None:
    """Browser entry point for a bulk run."""
    from aqt import mw

    if mw is None or mw.col is None:
        showCritical("Open a profile first.", parent=mw)
        return
    dialog = BatchDialog(mw.col, load_config(), scope_note_ids, browser=browser, parent=mw)
    dialog.exec()
    if dialog.pending is not None:
        run_after_editor_saved(
            browser,
            lambda: _finish_batch(mw.col, dialog.pending, parent=mw),
            schedule=lambda once: QTimer.singleShot(1500, once),
        )
