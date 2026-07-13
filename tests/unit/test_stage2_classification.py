"""Unit tests for bounded Stage-2 classifier input."""

from datetime import UTC, datetime

import pytest

from app.classifier.stage2 import format_stage2_input
from app.listener.reply_chain import ReplyChain, ReplyChainItem


def _item(message_id: int, text: str, *, is_target: bool = False) -> ReplyChainItem:
    return ReplyChainItem(
        telegram_message_id=message_id,
        reply_to_message_id=message_id - 1 if message_id > 1 else None,
        topic_id=None,
        reply_to_top_message_id=None,
        author_telegram_id=999,
        author_display_name="Must not reach API",
        telegram_created_at=datetime.now(UTC),
        text=text,
        is_target=is_target,
    )


def test_stage2_input_preserves_order_and_marks_only_final_target() -> None:
    chain = ReplyChain(
        chat_id=-1001,
        items=(
            _item(1, "oldest"),
            _item(2, "parent"),
            _item(3, "target", is_target=True),
        ),
    )

    rendered = format_stage2_input(chain)

    assert rendered == ("[CONTEXT]\noldest\n\n[CONTEXT]\nparent\n\n[TARGET]\ntarget")
    assert "Must not reach API" not in rendered
    assert rendered.count("[TARGET]") == 1


def test_stage2_input_accepts_loader_maximum_of_ten_items() -> None:
    items = tuple(_item(index, f"message {index}") for index in range(1, 10)) + (
        _item(10, "target", is_target=True),
    )

    rendered = format_stage2_input(ReplyChain(chat_id=-1001, items=items))

    assert rendered.count("[CONTEXT]") == 9
    assert rendered.endswith("[TARGET]\ntarget")


@pytest.mark.parametrize(
    "items",
    [
        (),
        tuple(_item(index, str(index)) for index in range(1, 12)),
        (_item(1, "not marked"),),
        (_item(1, "target", is_target=True), _item(2, "trailing context")),
    ],
)
def test_stage2_input_rejects_invalid_target_or_length(
    items: tuple[ReplyChainItem, ...],
) -> None:
    with pytest.raises(ValueError):
        format_stage2_input(ReplyChain(chat_id=-1001, items=items))
