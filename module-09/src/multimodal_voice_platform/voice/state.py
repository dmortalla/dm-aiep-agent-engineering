"""Application-owned, bounded conversation state for the voice assistant (Story 9.6).

``ConversationStore`` holds one in-memory conversation per active session. The session's
``SessionConfig`` is bound when application code opens the conversation and is the only source of
mode and budget authority for its turns; a turn request names its session by ID and nothing else.
A session ID is correlation identity, not proof of who is speaking.

Turn lifecycle and transaction semantics:

1. ``begin_turn`` checks the session is active, unexpired, idle, under its turn bound, and that the
   turn ID was never committed, then marks the session busy and reserves the turn's provider calls.
   Reserved calls are spent whether or not the turn reaches every provider, so failures cannot be
   retried for free.
2. Every pipeline stage runs without touching history.
3. ``commit`` appends the user transcript and the assistant reply as one exchange, in one step, only
   if the session is still active, still busy with this turn, and unchanged since ``begin_turn``.
   It then evicts the oldest exchanges beyond the retention bounds.
4. ``release`` clears the busy mark. A turn that never commits leaves history exactly as it was.

Committed exchanges hold text only: raw input audio and generated audio are never retained.
"""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from multimodal_voice_platform.contracts.modality import Identifier, TrustLevel
from multimodal_voice_platform.contracts.session import (
    ConversationRole,
    ConversationTurn,
    ExecutionMode,
    SessionConfig,
)
from multimodal_voice_platform.voice.errors import (
    ConversationLimitError,
    DuplicateSessionError,
    DuplicateTurnError,
    LiveVoiceUnavailableError,
    SessionBusyError,
    SessionExpiredError,
    StateCommitError,
    TurnBudgetExhaustedError,
    UnknownSessionError,
)
from multimodal_voice_platform.voice.limits import (
    MAX_RETAINED_TURNS,
    PROVIDER_CALLS_PER_TURN,
    VoiceLimits,
)


class SessionStatus(StrEnum):
    """Lifecycle of one conversation."""

    ACTIVE = "active"
    CLOSED = "closed"


class CommittedTurn(BaseModel):
    """One committed exchange: the user's transcript and the assistant's reply. Text only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: Identifier
    sequence: int = Field(ge=1)
    user: ConversationTurn
    assistant: ConversationTurn

    @model_validator(mode="after")
    def validate_roles(self) -> Self:
        """Bind each side of the exchange to its role.

        Returns:
            The validated exchange.

        Raises:
            ValueError: If the user or assistant side has the wrong role.
        """
        if self.user.role is not ConversationRole.USER:
            raise ValueError("the first side of an exchange is the user's turn")
        if self.assistant.role is not ConversationRole.ASSISTANT:
            raise ValueError("the second side of an exchange is the assistant's turn")
        return self

    @property
    def chars(self) -> int:
        """Characters this exchange holds."""
        return len(self.user.text) + len(self.assistant.text)


class ConversationSnapshot(BaseModel):
    """Reviewer-displayable state of one conversation at a point in time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: Identifier
    status: SessionStatus
    mode: ExecutionMode
    version: int = Field(ge=0)
    committed_turns: int = Field(ge=0)
    evicted_turns: int = Field(ge=0)
    retained: tuple[CommittedTurn, ...] = Field(default=(), max_length=MAX_RETAINED_TURNS)
    retained_chars: int = Field(ge=0)
    max_retained_turns: int = Field(ge=1)
    max_history_chars: int = Field(gt=0)
    max_turns_per_session: int = Field(ge=1)
    provider_calls_reserved: int = Field(ge=0)
    provider_call_budget: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        """Keep counts, ordering, and bounds consistent.

        Returns:
            The validated snapshot.

        Raises:
            ValueError: If retained exchanges are out of order, miscounted, or over their bounds.
        """
        sequences = [turn.sequence for turn in self.retained]
        first = self.evicted_turns + 1
        if sequences != list(range(first, first + len(sequences))):
            raise ValueError("retained exchanges must be the newest, in sequence order")
        if self.status is SessionStatus.ACTIVE and (
            self.evicted_turns + len(self.retained) != self.committed_turns
        ):
            raise ValueError("every committed exchange is either retained or evicted")
        if self.retained_chars != sum(turn.chars for turn in self.retained):
            raise ValueError("retained_chars must match the retained exchanges")
        if len(self.retained) > self.max_retained_turns:
            raise ValueError("retained exchanges exceed max_retained_turns")
        if self.retained_chars > self.max_history_chars:
            raise ValueError("retained exchanges exceed max_history_chars")
        if self.provider_calls_reserved > self.provider_call_budget:
            raise ValueError("reserved provider calls exceed the session budget")
        return self


@dataclass(frozen=True)
class TurnReservation:
    """What ``begin_turn`` granted: the bound configuration and the state version it saw.

    Attributes:
        config: The session's application-owned configuration.
        turn_id: The turn being run.
        version: State version when the turn began; ``commit`` requires it to be unchanged.
        sequence: Sequence number the turn will have if it commits.
    """

    config: SessionConfig
    turn_id: str
    version: int
    sequence: int


@dataclass
class _Conversation:
    config: SessionConfig
    started: float
    turns: deque[CommittedTurn] = field(default_factory=deque)
    version: int = 0
    committed: int = 0
    evicted: int = 0
    retained_chars: int = 0
    provider_calls: int = 0
    committed_ids: set[str] = field(default_factory=set)
    busy_turn: str | None = None


class ConversationStore:
    """In-memory, bounded conversations keyed by session ID. Owned by application code."""

    def __init__(
        self,
        limits: VoiceLimits,
        clock: Callable[[], float] = time.monotonic,
        *,
        allow_live: bool = False,
    ) -> None:
        """Create the store.

        Args:
            limits: Conversation bounds from application configuration.
            clock: Monotonic clock in seconds, used for session timeouts.
            allow_live: Whether the owning assistant has live adapters (Story 9.8). Without them,
                live sessions are refused.
        """
        self.limits = limits
        self._clock = clock
        self._allow_live = allow_live
        self._sessions: dict[str, _Conversation] = {}

    def open(self, config: SessionConfig) -> ConversationSnapshot:
        """Open a conversation for an application-owned session configuration.

        Args:
            config: Session configuration built by application code.

        Returns:
            The new conversation's snapshot.

        Raises:
            LiveVoiceUnavailableError: If the session is not deterministic.
            DuplicateSessionError: If the session is already active.
            ConversationLimitError: If the active-session bound is reached.
        """
        if config.mode is not ExecutionMode.DETERMINISTIC and not self._allow_live:
            raise LiveVoiceUnavailableError(
                "live voice providers are not available; use deterministic mode"
            )
        if config.session_id in self._sessions:
            raise DuplicateSessionError("a conversation with this session ID is already active")
        if len(self._sessions) >= self.limits.max_active_sessions:
            raise ConversationLimitError("the assistant has reached its active-session limit")
        conversation = _Conversation(config=config, started=self._clock())
        self._sessions[config.session_id] = conversation
        return self._snapshot(conversation, SessionStatus.ACTIVE)

    def close(self, session_id: str) -> ConversationSnapshot:
        """Close a conversation and release its history.

        Args:
            session_id: The session to close.

        Returns:
            The final snapshot: closed, with counts kept and history released.

        Raises:
            UnknownSessionError: If no such session is active.
        """
        conversation = self._get(session_id)
        del self._sessions[session_id]
        conversation.version += 1
        conversation.turns.clear()
        conversation.retained_chars = 0
        return self._snapshot(conversation, SessionStatus.CLOSED)

    def snapshot(self, session_id: str) -> ConversationSnapshot:
        """Return a conversation's current snapshot.

        Args:
            session_id: The session.

        Returns:
            The snapshot.

        Raises:
            UnknownSessionError: If no such session is active.
        """
        return self._snapshot(self._get(session_id), SessionStatus.ACTIVE)

    def session_config(self, session_id: str) -> SessionConfig:
        """Return the application-owned configuration bound to an active session.

        Args:
            session_id: The session.

        Returns:
            Its configuration, including any ephemeral live credential (never serialized).

        Raises:
            UnknownSessionError: If no such session is active.
        """
        return self._get(session_id).config

    @property
    def active_sessions(self) -> int:
        """Number of active conversations."""
        return len(self._sessions)

    def begin_turn(self, session_id: str, turn_id: str) -> TurnReservation:
        """Admit one turn and reserve its provider calls.

        Args:
            session_id: Session named by the turn request.
            turn_id: Caller-chosen turn ID, unique within the session once committed.

        Returns:
            The reservation the turn runs under.

        Raises:
            UnknownSessionError: If no such session is active.
            SessionExpiredError: If the session outlived its timeout. The session is closed.
            SessionBusyError: If another turn of the session is running.
            DuplicateTurnError: If the turn ID was already committed.
            ConversationLimitError: If the session reached its turn bound.
            TurnBudgetExhaustedError: If the turn would exceed the provider-call budget.
        """
        conversation = self._get(session_id)
        budget = conversation.config.budget
        if self._clock() - conversation.started > budget.session_timeout_s:
            self.close(session_id)
            raise SessionExpiredError("the session exceeded its timeout and was closed")
        if conversation.busy_turn is not None:
            raise SessionBusyError("another turn of this session is still running")
        if turn_id in conversation.committed_ids:
            raise DuplicateTurnError("this turn ID was already committed in the session")
        if conversation.committed >= self.limits.max_turns_per_session:
            raise ConversationLimitError("the session reached its turn limit")
        reserved = conversation.provider_calls + PROVIDER_CALLS_PER_TURN
        if reserved > budget.max_provider_calls_per_session:
            raise TurnBudgetExhaustedError("the turn would exceed the session provider-call budget")
        conversation.busy_turn = turn_id
        conversation.provider_calls = reserved
        return TurnReservation(
            config=conversation.config,
            turn_id=turn_id,
            version=conversation.version,
            sequence=conversation.committed + 1,
        )

    def history(self, session_id: str) -> tuple[ConversationTurn, ...]:
        """Return the bounded history window one reasoning call may see.

        The window holds the newest whole exchanges that fit within ``max_context_turns``, the
        session's ``max_history_turns`` entry budget, and ``max_context_chars``, in chronological
        order. Every entry is untrusted data.

        Args:
            session_id: The session.

        Returns:
            Alternating user and assistant entries, oldest first.

        Raises:
            UnknownSessionError: If no such session is active.
        """
        conversation = self._get(session_id)
        max_exchanges = min(
            self.limits.max_context_turns, conversation.config.budget.max_history_turns // 2
        )
        window: list[CommittedTurn] = []
        chars = 0
        for turn in reversed(conversation.turns):
            if len(window) >= max_exchanges or chars + turn.chars > self.limits.max_context_chars:
                break
            window.append(turn)
            chars += turn.chars
        return tuple(entry for turn in reversed(window) for entry in (turn.user, turn.assistant))

    def commit(
        self, reservation: TurnReservation, user_text: str, assistant_text: str
    ) -> ConversationSnapshot:
        """Atomically append one exchange, then evict beyond the retention bounds.

        Args:
            reservation: The reservation the turn ran under.
            user_text: The validated transcript. Untrusted.
            assistant_text: The validated reply. Untrusted.

        Returns:
            The snapshot after the commit.

        Raises:
            StateCommitError: If the session closed, is not running this turn, or changed since
                the turn began. Nothing is appended.
        """
        conversation = self._sessions.get(reservation.config.session_id)
        if (
            conversation is None
            or conversation.config is not reservation.config
            or conversation.busy_turn != reservation.turn_id
            or conversation.version != reservation.version
        ):
            raise StateCommitError("the conversation changed before the turn could be committed")
        turn = CommittedTurn(
            turn_id=reservation.turn_id,
            sequence=reservation.sequence,
            user=ConversationTurn(
                role=ConversationRole.USER, text=user_text, trust=TrustLevel.UNTRUSTED_EXTERNAL
            ),
            assistant=ConversationTurn(
                role=ConversationRole.ASSISTANT,
                text=assistant_text,
                trust=TrustLevel.UNTRUSTED_MODEL_OUTPUT,
            ),
        )
        conversation.turns.append(turn)
        conversation.retained_chars += turn.chars
        conversation.committed += 1
        conversation.committed_ids.add(reservation.turn_id)
        conversation.version += 1
        conversation.busy_turn = None
        limits = self.limits
        while (
            len(conversation.turns) > limits.max_retained_turns
            or conversation.retained_chars > limits.max_history_chars
        ):
            evicted = conversation.turns.popleft()
            conversation.retained_chars -= evicted.chars
            conversation.evicted += 1
        return self._snapshot(conversation, SessionStatus.ACTIVE)

    def release(self, reservation: TurnReservation) -> None:
        """Clear the busy mark if this turn still holds it. History is not touched.

        Args:
            reservation: The reservation the turn ran under.
        """
        conversation = self._sessions.get(reservation.config.session_id)
        if conversation is not None and conversation.busy_turn == reservation.turn_id:
            conversation.busy_turn = None

    def _get(self, session_id: str) -> _Conversation:
        conversation = self._sessions.get(session_id)
        if conversation is None:
            raise UnknownSessionError("no active conversation has this session ID")
        return conversation

    def _snapshot(self, conversation: _Conversation, status: SessionStatus) -> ConversationSnapshot:
        config = conversation.config
        return ConversationSnapshot(
            session_id=config.session_id,
            status=status,
            mode=config.mode,
            version=conversation.version,
            committed_turns=conversation.committed,
            evicted_turns=conversation.evicted,
            retained=tuple(conversation.turns),
            retained_chars=conversation.retained_chars,
            max_retained_turns=self.limits.max_retained_turns,
            max_history_chars=self.limits.max_history_chars,
            max_turns_per_session=self.limits.max_turns_per_session,
            provider_calls_reserved=conversation.provider_calls,
            provider_call_budget=config.budget.max_provider_calls_per_session,
        )
