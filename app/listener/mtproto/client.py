"""Typed Telethon adapter used by MTProto workflows."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, cast

from telethon import TelegramClient, errors, events, types  # type: ignore[import-untyped]
from telethon.tl.functions.messages import (  # type: ignore[import-untyped]
    GetForumTopicsByIDRequest,
)
from telethon.utils import get_display_name, get_peer_id  # type: ignore[import-untyped]

from app.config import AppSettings, ConfigurationError
from app.domain.errors import TelegramErrorCode, TelegramFailureKind, TelegramOutboundError
from app.listener.reply_chain import ReplyMessage


@dataclass(frozen=True, slots=True)
class TelegramAccount:
    """Safe account details returned after session validation."""

    user_id: int
    display_name: str


class ChatVerificationOutcome(StrEnum):
    """Normalized terminal outcomes returned by the MTProto adapter."""

    ACTIVE = "active"
    READ_ONLY = "read_only"
    ACCESS_LOST = "access_lost"
    VERIFICATION_FAILED = "verification_failed"


class ChatVerificationTransientError(RuntimeError):
    """Raised when verification should be retried without changing chat state."""


@dataclass(frozen=True, slots=True)
class ChatVerificationResult:
    """Privacy-safe result of checking one monitored Telegram chat."""

    outcome: ChatVerificationOutcome
    is_supergroup: bool = False
    is_forum: bool = False
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ForumTopicMetadata:
    """Forum topic identity extracted from one Telegram message."""

    topic_id: int
    title: str | None


class TopicTitleCache:
    """Bounded LRU cache, including safe negative lookups for deleted topics."""

    def __init__(self, *, max_size: int = 1_000) -> None:
        if max_size < 1:
            raise ValueError("Topic title cache size must be positive")
        self._max_size = max_size
        self._items: OrderedDict[tuple[int, int], str | None] = OrderedDict()

    def get(self, chat_id: int, topic_id: int) -> tuple[bool, str | None]:
        key = (chat_id, topic_id)
        if key not in self._items:
            return False, None
        self._items.move_to_end(key)
        return True, self._items[key]

    def put(self, chat_id: int, topic_id: int, title: str | None) -> None:
        key = (chat_id, topic_id)
        self._items[key] = title
        self._items.move_to_end(key)
        while len(self._items) > self._max_size:
            self._items.popitem(last=False)


class MTProtoSessionClient(Protocol):
    """Minimal interface needed to create and validate an MTProto session."""

    async def start(self) -> None:
        """Connect and complete interactive authorization when necessary."""

    async def get_account(self) -> TelegramAccount:
        """Return the authenticated account identity."""

    async def disconnect(self) -> None:
        """Close the client and flush its session state."""


class MTProtoListenerClient(Protocol):
    """Minimal interface used by the long-running listener lifecycle."""

    async def connect(self) -> None:
        """Connect using an already authorized persistent session."""

    async def is_user_authorized(self) -> bool:
        """Return whether the loaded session belongs to an authorized user."""

    async def verify_chat(self, telegram_chat_id: int) -> ChatVerificationResult:
        """Resolve a Bot API chat ID and verify access and write capability."""

    def add_new_message_handler(self, handler: Callable[[Any], Awaitable[None]]) -> None:
        """Register one asynchronous handler for incoming Telegram messages."""

    async def run_until_disconnected(self) -> None:
        """Process updates until the connection terminates."""

    async def disconnect(self) -> None:
        """Close the network client and flush its session state."""


class ForumTopicResolver(Protocol):
    """Topic metadata interface consumed by future ingestion workflows."""

    async def get_forum_topic_metadata(
        self,
        telegram_chat_id: int,
        message: types.Message,
    ) -> ForumTopicMetadata | None:
        """Resolve the topic identity and cached title for a forum message."""


class MTProtoOutboundClient(Protocol):
    """Minimal interface used by the listener-owned outbound worker."""

    async def verify_chat(self, telegram_chat_id: int) -> ChatVerificationResult:
        """Verify that the destination chat remains writable."""

    async def get_reply_message(
        self, telegram_chat_id: int, telegram_message_id: int
    ) -> ReplyMessage | None:
        """Load a target message for outbound validation."""

    async def send_reply(self, telegram_chat_id: int, telegram_message_id: int, text: str) -> int:
        """Send text as a direct reply and return the accepted message ID."""

    async def edit_message(
        self, telegram_chat_id: int, telegram_message_id: int, text: str
    ) -> None:
        """Edit one exact message previously sent by this account."""


class MTProtoClient(MTProtoSessionClient, MTProtoListenerClient, MTProtoOutboundClient, Protocol):
    """Combined interface implemented by the production Telethon adapter."""


class TelethonSessionClient:
    """Telethon implementation of the session creation interface."""

    def __init__(self, client: TelegramClient, *, topic_cache_size: int = 1_000) -> None:
        self._client = client
        self._topic_titles = TopicTitleCache(max_size=topic_cache_size)

    async def start(self) -> None:
        await self._client.start()

    async def connect(self) -> None:
        await self._client.connect()

    async def is_user_authorized(self) -> bool:
        return bool(await self._client.is_user_authorized())

    async def verify_chat(self, telegram_chat_id: int) -> ChatVerificationResult:
        try:
            entity = await self._client.get_entity(telegram_chat_id)
            if isinstance(entity, types.Channel):
                if entity.broadcast or not entity.megagroup:
                    return ChatVerificationResult(
                        ChatVerificationOutcome.VERIFICATION_FAILED,
                        error_code="unsupported_chat_type",
                    )
                is_supergroup = True
                is_forum = bool(entity.forum)
            elif isinstance(entity, types.Chat):
                is_supergroup = False
                is_forum = False
            else:
                return ChatVerificationResult(
                    ChatVerificationOutcome.VERIFICATION_FAILED,
                    error_code="unsupported_chat_type",
                )

            # Reading one message proves that the current session can access history.
            await self._client.get_messages(entity, limit=1)
            permissions = await self._client.get_permissions(entity, "me")
            can_send = any(
                bool(getattr(permissions, name, False))
                for name in ("send_messages", "is_creator", "is_admin")
            )
            return ChatVerificationResult(
                ChatVerificationOutcome.ACTIVE if can_send else ChatVerificationOutcome.READ_ONLY,
                is_supergroup=is_supergroup,
                is_forum=is_forum,
            )

        except (
            errors.ChannelPrivateError,
            errors.UserNotParticipantError,
            errors.ChatWriteForbiddenError,
        ):
            return ChatVerificationResult(
                ChatVerificationOutcome.ACCESS_LOST,
                error_code="membership_or_access_lost",
            )
        except ValueError:
            return ChatVerificationResult(
                ChatVerificationOutcome.ACCESS_LOST,
                error_code="peer_unavailable",
            )
        except (
            TimeoutError,
            ConnectionError,
            OSError,
            errors.ServerError,
            errors.FloodWaitError,
        ) as error:
            raise ChatVerificationTransientError(
                "Temporary MTProto verification failure"
            ) from error
        except errors.RPCError as error:
            return ChatVerificationResult(
                ChatVerificationOutcome.VERIFICATION_FAILED,
                error_code=cast(str, error.__class__.__name__),
            )

    async def get_reply_message(
        self, telegram_chat_id: int, telegram_message_id: int
    ) -> ReplyMessage | None:
        """Load one message without entity lookups for sender profile data."""
        result = await self._client.get_messages(telegram_chat_id, ids=telegram_message_id)
        if not isinstance(result, types.Message):
            return None

        sender = result.sender
        sender_name = get_display_name(sender)[:255] if sender is not None else None
        reply = result.reply_to
        reply_to_message_id = (
            cast(int | None, reply.reply_to_msg_id)
            if isinstance(reply, types.MessageReplyHeader)
            else None
        )
        topic_id = self._extract_topic_id(result)
        reply_to_top_message_id = (
            cast(int | None, reply.reply_to_top_id)
            if isinstance(reply, types.MessageReplyHeader)
            else None
        )
        return ReplyMessage(
            telegram_chat_id=cast(int, get_peer_id(result.peer_id)),
            telegram_message_id=result.id,
            reply_to_message_id=reply_to_message_id,
            topic_id=topic_id,
            reply_to_top_message_id=reply_to_top_message_id,
            author_telegram_id=result.sender_id,
            author_display_name=sender_name or None,
            telegram_created_at=result.date,
            text=result.raw_text or "",
        )

    async def send_reply(self, telegram_chat_id: int, telegram_message_id: int, text: str) -> int:
        """Send a reply to the exact target; Telegram preserves its forum topic."""
        try:
            result = await self._client.send_message(
                telegram_chat_id,
                text,
                reply_to=telegram_message_id,
            )
        except errors.FloodWaitError as error:
            raise TelegramOutboundError(
                TelegramErrorCode.FLOOD_WAIT,
                TelegramFailureKind.TEMPORARY,
                retry_after_seconds=max(0, int(error.seconds)),
            ) from error
        except errors.MessageIdInvalidError as error:
            raise TelegramOutboundError(
                TelegramErrorCode.SOURCE_MESSAGE_DELETED, TelegramFailureKind.PERMANENT
            ) from error
        except errors.TopicDeletedError as error:
            raise TelegramOutboundError(
                TelegramErrorCode.TOPIC_DELETED, TelegramFailureKind.PERMANENT
            ) from error
        except errors.ChatWriteForbiddenError as error:
            raise TelegramOutboundError(
                TelegramErrorCode.CHAT_WRITE_FORBIDDEN, TelegramFailureKind.PERMANENT
            ) from error
        except (errors.ChannelPrivateError, errors.UserNotParticipantError) as error:
            raise TelegramOutboundError(
                TelegramErrorCode.ACCESS_LOST, TelegramFailureKind.PERMANENT
            ) from error
        except (TimeoutError, ConnectionError, OSError, errors.ServerError) as error:
            raise TelegramOutboundError(
                TelegramErrorCode.UNKNOWN_ERROR, TelegramFailureKind.AMBIGUOUS
            ) from error
        except errors.RPCError as error:
            code = (
                TelegramErrorCode.TOPIC_CLOSED
                if error.__class__.__name__ == "TopicClosedError"
                else TelegramErrorCode.UNKNOWN_ERROR
            )
            kind = (
                TelegramFailureKind.PERMANENT
                if code is TelegramErrorCode.TOPIC_CLOSED
                else TelegramFailureKind.AMBIGUOUS
            )
            raise TelegramOutboundError(code, kind) from error
        if not isinstance(result, types.Message):
            raise TelegramOutboundError(
                TelegramErrorCode.UNKNOWN_ERROR, TelegramFailureKind.AMBIGUOUS
            )
        return cast(int, result.id)

    async def edit_message(
        self, telegram_chat_id: int, telegram_message_id: int, text: str
    ) -> None:
        """Edit the exact stored outbound message and normalize Telegram failures."""
        try:
            await self._client.edit_message(telegram_chat_id, telegram_message_id, text)
        except errors.FloodWaitError as error:
            raise TelegramOutboundError(
                TelegramErrorCode.FLOOD_WAIT,
                TelegramFailureKind.TEMPORARY,
                retry_after_seconds=max(0, int(error.seconds)),
            ) from error
        except errors.MessageIdInvalidError as error:
            raise TelegramOutboundError(
                TelegramErrorCode.SOURCE_MESSAGE_DELETED, TelegramFailureKind.PERMANENT
            ) from error
        except errors.ChatWriteForbiddenError as error:
            raise TelegramOutboundError(
                TelegramErrorCode.CHAT_WRITE_FORBIDDEN, TelegramFailureKind.PERMANENT
            ) from error
        except (errors.ChannelPrivateError, errors.UserNotParticipantError) as error:
            raise TelegramOutboundError(
                TelegramErrorCode.ACCESS_LOST, TelegramFailureKind.PERMANENT
            ) from error
        except (TimeoutError, ConnectionError, OSError, errors.ServerError) as error:
            raise TelegramOutboundError(
                TelegramErrorCode.UNKNOWN_ERROR, TelegramFailureKind.AMBIGUOUS
            ) from error
        except errors.RPCError as error:
            raise TelegramOutboundError(
                TelegramErrorCode.UNKNOWN_ERROR, TelegramFailureKind.PERMANENT
            ) from error

    async def get_forum_topic_title(self, telegram_chat_id: int, topic_id: int) -> str | None:
        """Resolve one topic title through the shared bounded cache."""
        cached, title = self._topic_titles.get(telegram_chat_id, topic_id)
        if not cached:
            title = await self._load_topic_title(telegram_chat_id, topic_id)
            self._topic_titles.put(telegram_chat_id, topic_id, title)
        return title

    def add_new_message_handler(self, handler: Callable[[Any], Awaitable[None]]) -> None:
        """Register an incoming-message callback on the wrapped Telethon client."""
        self._client.add_event_handler(handler, events.NewMessage(incoming=True))

    async def get_forum_topic_metadata(
        self,
        telegram_chat_id: int,
        message: types.Message,
    ) -> ForumTopicMetadata | None:
        """Resolve topic metadata without failing on an unknown or deleted topic."""
        topic_id = self._extract_topic_id(message)
        if topic_id is None:
            return None

        title = await self.get_forum_topic_title(telegram_chat_id, topic_id)
        return ForumTopicMetadata(topic_id=topic_id, title=title)

    @staticmethod
    def _extract_topic_id(message: types.Message) -> int | None:
        reply = message.reply_to
        if isinstance(reply, types.MessageReplyHeader) and reply.forum_topic:
            return cast(int | None, reply.reply_to_top_id or reply.reply_to_msg_id)
        if isinstance(message.action, types.MessageActionTopicCreate):
            return cast(int, message.id)
        return None

    async def _load_topic_title(self, telegram_chat_id: int, topic_id: int) -> str | None:
        try:
            result = cast(
                Any,
                await self._client(
                    GetForumTopicsByIDRequest(peer=telegram_chat_id, topics=[topic_id])
                ),
            )
        except (ValueError, errors.RPCError):
            return None

        for topic in result.topics:
            if (
                not isinstance(topic, types.ForumTopicDeleted)
                and getattr(topic, "id", None) == topic_id
            ):
                title = getattr(topic, "title", None)
                if isinstance(title, str):
                    return title[:255]
        return None

    async def run_until_disconnected(self) -> None:
        await self._client.run_until_disconnected()

    async def get_account(self) -> TelegramAccount:
        user = await self._client.get_me()
        if user is None:
            raise RuntimeError("Telegram session validation failed")
        return TelegramAccount(user_id=user.id, display_name=get_display_name(user))

    async def disconnect(self) -> None:
        await self._client.disconnect()


def create_telethon_client(settings: AppSettings) -> MTProtoClient:
    """Create a Telethon client using the configured persistent session path."""
    if settings.telegram_api_id is None or settings.telegram_api_hash is None:
        raise ConfigurationError("Missing MTProto credentials")

    session_path = settings.telegram_session_path
    session_path.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(
        str(session_path),
        settings.telegram_api_id,
        settings.telegram_api_hash.get_secret_value(),
    )
    return TelethonSessionClient(client)
