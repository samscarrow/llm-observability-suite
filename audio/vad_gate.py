from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from typing import Callable, Deque, Optional, Tuple, List


@dataclass
class Frame:
    data: bytes
    t0: float  # start time in seconds (relative)
    duration: float  # seconds


@dataclass
class Segment:
    pcm: bytes
    t0: float
    t1: float
    sample_rate: int


class VADGate:
    """Finite state machine (IDLE -> LISTENING -> ENDING) for VAD gating.

    - Uses webrtcvad if a `vad` is not injected.
    - Emits pre-roll + speech (excludes trailing silence used for stop rule).
    - Stop rule: end after `silence_duration_ms` continuous non-speech (default 700 ms).

    Hooks:
      - on_wake() when first speech is detected
      - on_segment_ready(segment: Segment) when segment finalized

    Diagnostics counters exposed via `stats` dict.
    """

    IDLE = "IDLE"
    LISTENING = "LISTENING"
    ENDING = "ENDING"

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        frame_ms: int = 30,
        aggressiveness: int = 2,
        pre_roll_ms: int = 300,
        silence_duration_ms: int = 700,
        on_wake: Optional[Callable[[], None]] = None,
        on_segment_ready: Optional[Callable[[Segment], None]] = None,
        vad: Optional[object] = None,
    ) -> None:
        if frame_ms not in (10, 20, 30):
            raise ValueError("frame_ms must be one of 10, 20, 30")
        if sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError("sample_rate must be 8000, 16000, 32000, or 48000")

        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.frame_samples = int(sample_rate * frame_ms / 1000)
        self.frame_bytes = self.frame_samples * 2  # 16-bit PCM
        self.frame_duration = frame_ms / 1000.0
        self.pre_roll_ms = pre_roll_ms
        self.silence_duration_ms = silence_duration_ms
        self.on_wake = on_wake
        self.on_segment_ready = on_segment_ready

        # Diagnostics
        self.stats = {
            "frames_total": 0,
            "frames_speech": 0,
            "frames_silence": 0,
            "wake_ups": 0,
            "segments": 0,
            "flaps": 0,
        }

        # webrtcvad instance (optional injection for tests)
        if vad is None:
            try:
                import webrtcvad  # type: ignore
            except Exception as e:  # pragma: no cover - only at runtime without dep
                raise ImportError(
                    "webrtcvad is required for runtime; inject a fake in tests"
                ) from e
            self.vad = webrtcvad.Vad(aggressiveness)
        else:
            # Assume duck-typed object with is_speech(bytes, sample_rate) -> bool
            self.vad = vad
            # If injected VAD has aggressiveness config, set if available
            if hasattr(self.vad, "set_mode"):
                try:
                    self.vad.set_mode(aggressiveness)  # type: ignore[attr-defined]
                except Exception:
                    pass

        # FSM state
        self.state = self.IDLE
        self.time_s = 0.0

        # Buffers
        self._pre_roll: Deque[Frame] = deque(maxlen=max(1, int(pre_roll_ms // frame_ms)))
        self._active_frames: List[Frame] = []  # frames captured after wake
        self._tail_silence: Deque[Frame] = deque()
        self._consec_silence_ms = 0
        self._last_speech_end: Optional[float] = None

        # Byte accumulator for external chunk processing
        self._leftover = b""

    def reset(self) -> None:
        self.state = self.IDLE
        self._pre_roll.clear()
        self._active_frames.clear()
        self._tail_silence.clear()
        self._consec_silence_ms = 0
        self._last_speech_end = None
        self._leftover = b""

    def process_pcm(self, pcm: bytes) -> None:
        """Process a stream of little-endian 16-bit PCM bytes."""
        buf = self._leftover + pcm
        frame_size = self.frame_bytes
        idx = 0
        while idx + frame_size <= len(buf):
            chunk = buf[idx : idx + frame_size]
            self._process_frame(Frame(chunk, self.time_s, self.frame_duration))
            self.time_s += self.frame_duration
            idx += frame_size
        self._leftover = buf[idx:]

    def _process_frame(self, frame: Frame) -> None:
        decision = bool(self.vad.is_speech(frame.data, self.sample_rate))
        self.stats["frames_total"] += 1
        if decision:
            self.stats["frames_speech"] += 1
        else:
            self.stats["frames_silence"] += 1

        if self.state == self.IDLE:
            if decision:
                # Do not include this frame in pre-roll; it's the first speech frame
                self._wake()
                self._add_speech(frame)
            else:
                self._pre_roll.append(frame)
        elif self.state == self.LISTENING:
            if decision:
                # speech
                self._add_speech(frame)
            else:
                # silence while listening
                self._add_silence(frame)
                if self._consec_silence_ms >= self.silence_duration_ms:
                    self._end_segment()
        elif self.state == self.ENDING:
            # Should not receive frames in ENDING; reset to IDLE
            self.stats["flaps"] += 1
            self.reset()
            self._pre_roll.append(frame)

    # --- state actions ---
    def _wake(self) -> None:
        self.state = self.LISTENING
        self.stats["wake_ups"] += 1
        if self.on_wake:
            try:
                self.on_wake()
            except Exception:
                pass

    def _add_speech(self, frame: Frame) -> None:
        # Any pending tail silence becomes part of active frames until we trim
        if self._tail_silence:
            self._active_frames.extend(self._tail_silence)
            self._tail_silence.clear()
        self._active_frames.append(frame)
        self._last_speech_end = frame.t0 + frame.duration
        self._consec_silence_ms = 0

    def _add_silence(self, frame: Frame) -> None:
        self._tail_silence.append(frame)
        self._consec_silence_ms += self.frame_ms
        # Limit tail buffer to at most the stop-window
        max_tail = max(1, self.silence_duration_ms // self.frame_ms)
        while len(self._tail_silence) > max_tail:
            # Keep only last max_tail frames
            self._active_frames.append(self._tail_silence.popleft())

    def _end_segment(self) -> None:
        self.state = self.ENDING
        pre = list(self._pre_roll)
        active = list(self._active_frames)
        # Exclude tail silence used for stop detection
        # last_speech_end marks end time; tail_silence frames come after it
        pcm_parts: List[bytes] = []
        t0 = pre[0].t0 if pre else (active[0].t0 if active else self.time_s)
        t1 = self._last_speech_end if self._last_speech_end is not None else self.time_s

        # Append pre-roll fully
        for fr in pre:
            # only include pre-roll frames strictly before active start to avoid duplication
            pcm_parts.append(fr.data)
        # Append active up to last speech end
        for fr in active:
            if fr.t0 + fr.duration <= t1 + 1e-9:
                pcm_parts.append(fr.data)

        segment = Segment(pcm=b"".join(pcm_parts), t0=t0, t1=t1, sample_rate=self.sample_rate)
        self.stats["segments"] += 1

        if self.on_segment_ready:
            try:
                self.on_segment_ready(segment)
            except Exception:
                pass

        # Reset for next utterance
        self.reset()
