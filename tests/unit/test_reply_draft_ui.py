"""Unit coverage for exact and safe draft preview UI."""

from uuid import uuid4

from app.bot.handlers.replies import _render_preview, _render_sent_edit_preview
from app.bot.keyboards.replies import (
    build_draft_conflict_keyboard,
    build_draft_preview_keyboard,
    build_sent_edit_keyboard,
)
from app.database.repositories.outbound_commands import SentEditPreview
from app.database.repositories.reply_drafts import DraftDestination, StoredDraft


def test_preview_preserves_exact_text_and_escapes_only_html_transport() -> None:
    question_id = uuid4()
    draft = StoredDraft(
        destination=DraftDestination(question_id, "Chat <one>", "Topic & two"),
        version_number=1,
        text="line 1\n<line & 2>",
    )

    preview = _render_preview(draft)

    assert "Chat &lt;one&gt;" in preview
    assert "Topic &amp; two" in preview
    assert "<pre>line 1\n&lt;line &amp; 2&gt;</pre>" in preview
    assert draft.text == "line 1\n<line & 2>"


def test_preview_and_conflict_callbacks_use_only_opaque_question_ids() -> None:
    active_id = uuid4()
    requested_id = uuid4()

    preview = build_draft_preview_keyboard(active_id)
    conflict = build_draft_conflict_keyboard(active_id, requested_id)
    callbacks = [
        button.callback_data
        for keyboard in (preview, conflict)
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert callbacks == [
        f"draft:confirm:{active_id}",
        f"draft:edit:{active_id}",
        f"draft:cancel:{active_id}",
        f"draft:continue:{active_id}",
        f"draft:replace:{requested_id}",
    ]


def test_sent_edit_preview_shows_escaped_old_and_new_text_with_opaque_callbacks() -> None:
    question_id = uuid4()
    preview = SentEditPreview(question_id, "old <final>", "new & final")

    rendered = _render_sent_edit_preview(preview)
    keyboard = build_sent_edit_keyboard(question_id)

    assert "<pre>old &lt;final&gt;</pre>" in rendered
    assert "<pre>new &amp; final</pre>" in rendered
    assert [button.callback_data for row in keyboard.inline_keyboard for button in row] == [
        f"sent-edit:confirm:{question_id}",
        f"sent-edit:cancel:{question_id}",
    ]
