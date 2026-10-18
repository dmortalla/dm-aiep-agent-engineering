"""Incremental extraction of array elements from a streamed JSON document (Story 9.8).

A structured-output model streams one JSON object such as ``{"fragments": [{...}, {...}]}`` as
many small text deltas. ``ArrayElementScanner`` consumes those deltas and returns each element of
the first top-level array as soon as its closing brace arrives, before the document is complete, so
each element can be validated and streamed on while the provider is still generating the next one.
It never guesses: an element is released only when it is syntactically closed.
"""

from typing import Final

MAX_DOCUMENT_CHARS: Final = 64_000


class StreamedJsonError(ValueError):
    """Raised when the streamed document is malformed or exceeds its bound."""


class ArrayElementScanner:
    """Scans a streamed JSON object and yields the elements of its first top-level array."""

    def __init__(self, max_chars: int = MAX_DOCUMENT_CHARS) -> None:
        """Create the scanner.

        Args:
            max_chars: Longest document accepted.
        """
        self._max_chars = max_chars
        self._text: list[str] = []
        self._length = 0
        self._depth = 0
        self._in_string = False
        self._escape = False
        self._array_depth: int | None = None
        self._array_closed = False
        self._element: list[str] | None = None
        self._finished = False

    @property
    def document(self) -> str:
        """Everything received so far."""
        return "".join(self._text)

    def feed(self, delta: str) -> list[str]:
        """Consume one text delta.

        Args:
            delta: The next piece of the document.

        Returns:
            Every array element completed by this delta, as JSON text, in order.

        Raises:
            StreamedJsonError: If the document exceeds its bound or its structure is invalid.
        """
        self._length += len(delta)
        if self._length > self._max_chars:
            raise StreamedJsonError("the streamed document exceeds its size bound")
        self._text.append(delta)
        completed: list[str] = []
        for char in delta:
            if self._finished and not char.isspace():
                raise StreamedJsonError("content followed the end of the streamed document")
            if self._element is not None:
                self._element.append(char)
            if self._in_string:
                if self._escape:
                    self._escape = False
                elif char == "\\":
                    self._escape = True
                elif char == '"':
                    self._in_string = False
                continue
            if char == '"':
                self._in_string = True
            elif char in "{[":
                if char == "{" and self._at_array_level():
                    self._element = [char]
                self._depth += 1
                if char == "[" and self._depth == 2 and self._array_depth is None:
                    self._array_depth = 2
            elif char in "}]":
                self._depth -= 1
                if self._depth < 0:
                    raise StreamedJsonError("the streamed document closes more than it opens")
                if char == "}" and self._element is not None and self._at_array_level():
                    completed.append("".join(self._element))
                    self._element = None
                if char == "]" and self._array_depth is not None and self._depth == 1:
                    self._array_closed = True
                if self._depth == 0:
                    self._finished = True
        return completed

    def _at_array_level(self) -> bool:
        return (
            self._array_depth is not None
            and not self._array_closed
            and self._depth == self._array_depth
        )

    def close(self) -> None:
        """Confirm the document ended cleanly.

        Raises:
            StreamedJsonError: If the document is incomplete.
        """
        if not self._finished or self._in_string or self._element is not None:
            raise StreamedJsonError("the streamed document ended before it was complete")
