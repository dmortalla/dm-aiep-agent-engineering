"""Session-scoped, in-memory binary content store for deterministic execution (SEC-004, SEC-022).

Binary content is addressed only by opaque references issued here. Callers never supply paths, and
every reference is released when its session is released.
"""

import hashlib

from multimodal_voice_platform.adapters.deterministic.errors import ContentNotFoundError


class SessionContentStore:
    """Holds binary content in memory, keyed by session and opaque reference."""

    def __init__(self) -> None:
        """Create an empty store."""
        self._sessions: dict[str, dict[str, bytes]] = {}

    def put(self, session_id: str, input_id: str, content: bytes) -> str:
        """Store content for a session and return its opaque reference.

        The reference is derived deterministically from the session and input IDs, so identical
        staging produces identical references.

        Args:
            session_id: Session that owns the content.
            input_id: Input the content belongs to.
            content: Binary content to hold.

        Returns:
            The opaque content reference.
        """
        digest = hashlib.sha256(f"{session_id}\x00{input_id}".encode()).hexdigest()
        content_ref = f"ref-{digest[:24]}"
        self._sessions.setdefault(session_id, {})[content_ref] = content
        return content_ref

    def read(self, session_id: str, content_ref: str) -> bytes:
        """Return the content held for a reference.

        Args:
            session_id: Session that owns the content.
            content_ref: Opaque reference issued by ``put``.

        Returns:
            The stored bytes.

        Raises:
            ContentNotFoundError: If the reference is unknown to the session or was released.
        """
        try:
            return self._sessions[session_id][content_ref]
        except KeyError as exc:
            raise ContentNotFoundError("content reference is unknown for this session") from exc

    def release(self, session_id: str) -> int:
        """Delete every reference held for a session.

        Args:
            session_id: Session whose content is deleted.

        Returns:
            How many references were deleted.
        """
        return len(self._sessions.pop(session_id, {}))

    def reference_count(self, session_id: str) -> int:
        """Count the references currently held for a session.

        Args:
            session_id: Session to inspect.

        Returns:
            The number of live references.
        """
        return len(self._sessions.get(session_id, {}))
