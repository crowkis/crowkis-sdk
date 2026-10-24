"""A cached answer, shaped the way Bolna's own LLMs stream one."""

from __future__ import annotations

from typing import List, Optional

from bolna.llms.types import LatencyData, LLMStreamChunk


class ServedReply:
    """Turns a served answer into ``LLMStreamChunk`` pieces.

    Bolna's LLMs cut synthesised text at the last space once about ``buffer_size``
    characters are waiting, and send an unsynthesised answer whole; the last chunk ends
    the stream. This does the same, so the speech side cannot tell a served answer from
    a model's."""

    def __init__(self, text: str, *, sequence_id: Optional[int], buffer_size: int, synthesize: bool) -> None:
        self._text = text
        self._sequence_id = sequence_id
        self._buffer_size = buffer_size
        self._synthesize = synthesize

    def chunks(self) -> List[LLMStreamChunk]:
        """The pieces to yield, in order."""
        pieces = self._pieces()
        last = len(pieces) - 1
        return [
            LLMStreamChunk(data=piece, end_of_stream=index == last,
                           latency=LatencyData(sequence_id=self._sequence_id))
            for index, piece in enumerate(pieces)
        ]

    def _pieces(self) -> List[str]:
        words = self._text.split()
        if not self._synthesize or not words:
            return [self._text]
        pieces: List[str] = []
        waiting: List[str] = []
        for word in words:
            waiting.append(word)
            if len(" ".join(waiting)) >= self._buffer_size:
                pieces.append(" ".join(waiting))
                waiting = []
        if waiting:
            pieces.append(" ".join(waiting))
        return pieces
