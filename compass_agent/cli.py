from __future__ import annotations

import argparse
import queue
import sys
import time
from typing import Optional


def _pcm_float_to_int16_bytes(samples) -> bytes:
    import numpy as np

    if isinstance(samples, bytes):
        return samples
    arr = np.asarray(samples)
    arr = (arr * 32767.0).clip(-32768, 32767).astype("<i2")
    return arr.tobytes()


def run_vad_demo(
    *,
    sample_rate: int = 16000,
    frame_ms: int = 30,
    aggressiveness: int = 2,
    pre_roll_ms: int = 300,
    silence_ms: int = 700,
) -> int:
    try:
        import sounddevice as sd  # type: ignore
    except Exception as e:
        print("sounddevice is required for --vad demo. pip install 'sounddevice'", file=sys.stderr)
        return 2

    from audio.vad_gate import VADGate, Segment

    q: "queue.Queue[bytes]" = queue.Queue(maxsize=64)

    def audio_cb(indata, frames, time_info, status):  # type: ignore[no-redef]
        if status:
            # stream status warnings
            pass
        try:
            q.put_nowait(_pcm_float_to_int16_bytes(indata))
        except queue.Full:
            try:
                q.get_nowait()
            except Exception:
                pass

    def on_wake():
        print(f"[wake] t={gate.time_s:.3f}s")

    def on_segment_ready(seg: Segment):
        dur = seg.t1 - seg.t0
        print(f"[segment] t0={seg.t0:.3f}s t1={seg.t1:.3f}s dur={dur:.3f}s bytes={len(seg.pcm)}")

    gate = VADGate(
        sample_rate=sample_rate,
        frame_ms=frame_ms,
        aggressiveness=aggressiveness,
        pre_roll_ms=pre_roll_ms,
        silence_duration_ms=silence_ms,
        on_wake=on_wake,
        on_segment_ready=on_segment_ready,
    )

    blocksize = int(sample_rate * frame_ms / 1000)
    print("Press Ctrl+C to stop. Capturing microphone…")
    try:
        with sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=blocksize,
            callback=audio_cb,
        ):
            while True:
                try:
                    data = q.get(timeout=0.2)
                except queue.Empty:
                    continue
                gate.process_pcm(data)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="compass-agent")
    sub = parser.add_subparsers(dest="cmd", required=True)
    demo = sub.add_parser("demo", help="Run demos")
    demo.add_argument("--vad", action="store_true", help="Run VAD gating demo from microphone")
    demo.add_argument("--aggr", type=int, default=2, help="VAD aggressiveness (0-3)")
    demo.add_argument("--silence-ms", type=int, default=700, help="Silence stop duration ms")
    demo.add_argument("--pre-roll-ms", type=int, default=300, help="Pre-roll ms")
    demo.add_argument("--frame-ms", type=int, default=30, help="Frame size ms (10/20/30)")
    demo.add_argument("--sample-rate", type=int, default=16000, help="Sample rate")

    args = parser.parse_args(argv)
    if args.cmd == "demo" and args.vad:
        return run_vad_demo(
            sample_rate=args.sample_rate,
            frame_ms=args.frame_ms,
            aggressiveness=args.aggr,
            pre_roll_ms=args.pre_roll_ms,
            silence_ms=args.silence_ms,
        )
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

