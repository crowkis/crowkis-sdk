"""CrowkisSynthesizer: cached voice clips in front of one of Bolna's own synthesizers."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, AsyncIterator

from bolna.helpers.utils import create_ws_data_packet

from .call_links import CallLinks, ClipPlan, SequenceClip
from .clip_shelf import ClipOutput

_INNER_DONE = object()


class CrowkisSynthesizer:
    """Decorator around a Bolna synthesizer: a served answer whose clip is cached is played
    from the cache, and the audio of an answer the cache shares is kept for the next caller.

    One instance serves one call (Bolna builds one synthesizer per call), and finds the
    LLM wrapper's orders for that call through ``CallLinks``. ``push`` swallows the text of a
    sequence that is to be played from a clip (anything else goes to the wrapped synthesizer
    untouched) and ``generate`` merges the clip's packet with the wrapped synthesizer's own.
    Packets keep Bolna's shape, so its sequence gate, marks and history commit work as for
    any speech. ``handle_interruption`` drops everything in flight; every other attribute and
    method is the wrapped synthesizer's own."""

    def __init__(self, inner: Any, links: CallLinks) -> None:
        self._inner = inner
        self._plan: ClipPlan = links.plan_for(inner.task_manager_instance)
        self._plan.bind_output(ClipOutput.of_synthesizer(inner))
        self._outbox: "asyncio.Queue[Any]" = asyncio.Queue()

    def __getattr__(self, name: str) -> Any:
        inner = self.__dict__.get("_inner")
        if inner is None:
            raise AttributeError(name)
        return getattr(inner, name)

    @property
    def failures(self) -> Any:
        """How many times each Crowkis concern failed and was skipped."""
        return self._plan.boundary.failures

    async def push(self, message: dict) -> None:
        """Bolna gives the synthesizer a piece of text: swallowed when its sequence plays a clip."""
        meta_info = message.get("meta_info") or {}
        sequence_id = meta_info.get("sequence_id")
        playing = self._plan.playing(sequence_id)
        if playing is None:
            self._plan.hear_text(sequence_id, message.get("data"), bool(meta_info.get("end_of_llm_stream")))
            await self._inner.push(message)
        elif meta_info.get("end_of_llm_stream"):
            self._plan.drop(sequence_id)
            self._outbox.put_nowait(self._clip_packet(playing, meta_info))

    async def generate(self) -> AsyncIterator[dict]:
        """The wrapped synthesizer's packets, with the clip packets of this call among them."""
        pump = asyncio.create_task(self._pump_inner())
        try:
            while True:
                item = await self._outbox.get()
                if item is _INNER_DONE:
                    return
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump

    async def handle_interruption(self) -> None:
        """Barge-in: audio collected so far and clips not yet played are dropped."""
        self._plan.drop_all()
        await self._inner.handle_interruption()

    def _clip_packet(self, playing: SequenceClip, meta_info: dict) -> dict:
        """A cached clip as one packet of Bolna's shape, stamped as its own synthesizer would."""
        meta = dict(meta_info)
        self._inner._stamp_first_chunk(meta)
        self._inner._stamp_end_of_stream(meta)
        meta["format"] = self._plan.wire_format
        meta["text"] = playing.text
        meta["text_synthesized"] = f"{playing.text} "
        self._inner._stamp_mark_id(meta)
        return create_ws_data_packet(playing.playing, meta)

    async def _pump_inner(self) -> None:
        try:
            async for packet in self._inner.generate():
                await self._observe(packet)
                self._outbox.put_nowait(packet)
        except Exception as error:  # noqa: BLE001 - handed to generate(), which raises it to Bolna
            self._outbox.put_nowait(error)
        else:
            self._outbox.put_nowait(_INNER_DONE)

    async def _observe(self, packet: dict) -> None:
        meta_info = packet.get("meta_info") or {}
        await self._plan.hear_audio(meta_info.get("sequence_id"), packet.get("data"), meta_info.get("format"),
                                    bool(meta_info.get("end_of_synthesizer_stream")))
