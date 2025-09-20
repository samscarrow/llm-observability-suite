from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pytest

from audio.vad_gate import VADGate, Segment


class FakeVAD:
    """A fake VAD that yields speech/non-speech based on a provided schedule.

    schedule: list[bool] applied per frame in order; if exhausted, repeat last.
    """

    def __init__(self, schedule: List[bool]):
        self.schedule = schedule
        self.i = 0

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:  # noqa: ARG002
        if self.i < len(self.schedule):
            val = self.schedule[self.i]
        else:
            val = self.schedule[-1]
        self.i += 1
        return val


def make_pcm(frame_bytes: int, n_frames: int) -> bytes:
    # Produce zeroed PCM; content is irrelevant with FakeVAD
    return b"\x00" * (frame_bytes * n_frames)


def test_single_utterance_with_preroll_and_stop():
    # Frame config
    sample_rate = 16000
    frame_ms = 30
    frame_samples = int(sample_rate * frame_ms / 1000)
    frame_bytes = frame_samples * 2

    # Pre-roll 300 ms -> 10 frames; Stop after 700 ms -> approx 24 frames of silence
    pre_roll_ms = 300
    silence_ms = 700

    # Schedule: 20 frames silence (warmup), 12 frames speech (~360ms), 25 frames silence (~750ms)
    schedule = [False] * 20 + [True] * 12 + [False] * 25
    fake_vad = FakeVAD(schedule)

    events: list[Segment] = []
    woke = {"count": 0}

    def on_wake():
        woke["count"] += 1

    def on_ready(seg: Segment):
        events.append(seg)

    gate = VADGate(
        sample_rate=sample_rate,
        frame_ms=frame_ms,
        pre_roll_ms=pre_roll_ms,
        silence_duration_ms=silence_ms,
        vad=fake_vad,
        on_wake=on_wake,
        on_segment_ready=on_ready,
    )

    # Feed frames with exact boundary sizes
    pcm = make_pcm(frame_bytes, len(schedule))
    gate.process_pcm(pcm)

    # Assertions
    assert woke["count"] == 1
    assert len(events) == 1
    seg = events[0]
    # Segment must include pre-roll and the speech portion, trimmed of trailing 700ms silence
    # t0 should be at (20 - preroll_frames)*frame_ms
    preroll_frames = pre_roll_ms // frame_ms
    expected_t0 = (20 - preroll_frames) * frame_ms / 1000.0
    assert abs(seg.t0 - expected_t0) < 1e-6

    # t1 is the end of the last speech frame: t0_of_last_speech + duration
    speech_start_frame = 20
    speech_frames = 12
    last_speech_end = (speech_start_frame + speech_frames) * frame_ms / 1000.0
    assert abs(seg.t1 - last_speech_end) < 1e-6

    # Byte length equals frames included * frame_bytes
    included_frames = preroll_frames + speech_frames
    assert len(seg.pcm) == included_frames * frame_bytes

    # Sanity on diagnostics
    assert gate.stats["segments"] == 1
    assert gate.stats["wake_ups"] == 1
    assert gate.stats["frames_speech"] == speech_frames


def test_noise_bursts_do_not_flap():
    # Silence, then brief 1-frame speech burst, then silence, then real speech
    sample_rate = 16000
    frame_ms = 30
    frame_bytes = int(sample_rate * frame_ms / 1000) * 2

    schedule = [False] * 10 + [True] + [False] * 10 + [True] * 15 + [False] * 25
    fake_vad = FakeVAD(schedule)

    events: list[Segment] = []
    def on_ready(seg: Segment):
        events.append(seg)

    gate = VADGate(sample_rate=sample_rate, frame_ms=frame_ms, vad=fake_vad, on_segment_ready=on_ready)
    gate.process_pcm(make_pcm(frame_bytes, len(schedule)))

    # Expect only one meaningful segment (burst filtered by 700ms rule naturally ends quickly)
    assert len(events) == 1

