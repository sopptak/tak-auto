"""Shorts 2.0(6-41) 배경음악/효과음 합성기.

외부 음원을 다운로드하거나 플랫폼 음악을 쓰지 않는다 - 모든 소리를 이 모듈이
표준 라이브러리(math/random/array/wave)만으로 직접 합성한다. 따라서 저작권
문제가 없는 로컬 QA용 테스트 음원이다. 실제 YouTube 업로드 시에는 YouTube
오디오 라이브러리/정책을 별도로 검토해야 한다.

구조:
- 스타일별 BPM/코드 진행/악기 구성(finance=차분한 비트, human=피아노+패드+잔향,
  ai=빠른 일렉트로닉 비트)
- 장면 경계는 전부 박자 위에 있으므로(shorts_v2_scene.build_timeline) 음악과
  화면 전환이 자동으로 맞는다(beat sync).
- 장면별 audio cue(impact/whoosh/pop/riser/chime)를 해당 시각에 효과음으로 배치한다.
- scene.music == "break"인 장면은 드럼을 빼서 호흡을 만든다.
"""

from __future__ import annotations

import math
import random
import wave
from array import array
from pathlib import Path

from content_engine.shorts_v2_scene import ShortSpec, TimedScene, build_timeline, item_reveal_times

SR = 44100
_TABLE_SIZE = 4096


def _midi(note: float) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def _wavetable(harmonics: tuple[float, ...]) -> array:
    table = array("d", [0.0]) * _TABLE_SIZE
    for i in range(_TABLE_SIZE):
        phase = 2 * math.pi * i / _TABLE_SIZE
        table[i] = sum(amp * math.sin((h + 1) * phase) for h, amp in enumerate(harmonics))
    peak = max(abs(v) for v in table) or 1.0
    for i in range(_TABLE_SIZE):
        table[i] /= peak
    return table


_SOFT = _wavetable((1.0, 0.25, 0.08))
_PIANO = _wavetable((1.0, 0.45, 0.18, 0.1, 0.04))
_SQUAREISH = _wavetable((1.0, 0.0, 0.33, 0.0, 0.2, 0.0, 0.14))


def _tone(freq: float, seconds: float, table: array, attack: float, decay: float, release: float = 0.05) -> array:
    """wavetable 음 하나. decay는 지수 감쇠율(1/초, 0이면 유지)."""
    n = int(seconds * SR)
    out = array("d", [0.0]) * n
    step = freq * _TABLE_SIZE / SR
    phase = 0.0
    a_n = max(1, int(attack * SR))
    r_n = max(1, int(release * SR))
    k = math.exp(-decay / SR) if decay else 1.0
    env = 1.0
    for i in range(n):
        gate = min(1.0, i / a_n, (n - i) / r_n)
        out[i] = table[int(phase) % _TABLE_SIZE] * env * gate
        phase += step
        if i >= a_n:
            env *= k
    return out


def _noise(seconds: float, rng: random.Random) -> array:
    return array("d", (rng.uniform(-1, 1) for _ in range(int(seconds * SR))))


def _kick() -> array:
    n = int(0.35 * SR)
    out = array("d", [0.0]) * n
    phase = 0.0
    for i in range(n):
        t = i / SR
        freq = 48 + 110 * math.exp(-t * 32)
        phase += 2 * math.pi * freq / SR
        out[i] = math.sin(phase) * math.exp(-t * 9)
    return out


def _hat(rng: random.Random, length: float = 0.045) -> array:
    raw = _noise(length, rng)
    out = array("d", [0.0]) * len(raw)
    prev = 0.0
    for i, v in enumerate(raw):  # 1차 차분 = 간단한 highpass
        out[i] = (v - prev) * 0.5 * math.exp(-i / SR * 80)
        prev = v
    return out


def _clap(rng: random.Random) -> array:
    raw = _noise(0.18, rng)
    out = array("d", [0.0]) * len(raw)
    prev = 0.0
    for i, v in enumerate(raw):
        t = i / SR
        burst = 1.0 if t > 0.02 else (0.6 if int(t * 400) % 2 == 0 else 0.2)
        out[i] = (v - prev) * 0.5 * burst * math.exp(-t * 22)
        prev = v
    return out


def _swept_noise(seconds: float, rng: random.Random, lo: float, hi: float, shape) -> array:
    """one-pole lowpass의 cutoff를 lo->hi로 움직이는 노이즈(whoosh/riser 공용)."""
    raw = _noise(seconds, rng)
    n = len(raw)
    out = array("d", [0.0]) * n
    y = 0.0
    for i, v in enumerate(raw):
        x = i / n
        cutoff = lo + (hi - lo) * shape(x)
        alpha = 1 - math.exp(-2 * math.pi * cutoff / SR)
        y += alpha * (v - y)
        out[i] = y * shape(x)
    return out


def _whoosh(rng: random.Random) -> array:
    # x**1.6 로 봉우리를 뒤쪽(약 65%)으로 밀어 "다가와서 지나가는" 느낌을 만든다
    return _swept_noise(0.45, rng, 300, 6000, lambda x: math.sin(math.pi * x ** 1.6) ** 2)


def _riser(rng: random.Random, seconds: float) -> array:
    return _swept_noise(seconds, rng, 200, 7000, lambda x: x ** 2)


def _impact(rng: random.Random) -> array:
    n = int(0.9 * SR)
    out = array("d", [0.0]) * n
    phase = 0.0
    for i in range(n):
        t = i / SR
        freq = 38 + 90 * math.exp(-t * 14)
        phase += 2 * math.pi * freq / SR
        out[i] = math.sin(phase) * math.exp(-t * 4.5)
    click = _hat(rng, 0.03)
    for i, v in enumerate(click):
        out[i] += v * 1.5
    return out


def _pop() -> array:
    n = int(0.07 * SR)
    out = array("d", [0.0]) * n
    phase = 0.0
    for i in range(n):
        t = i / SR
        phase += 2 * math.pi * (900 + 7000 * t) / SR
        out[i] = math.sin(phase) * math.exp(-t * 55)
    return out


def _add(buf: array, start: float, samples: array, gain: float) -> None:
    offset = int(start * SR)
    for i, v in enumerate(samples):
        j = offset + i
        if 0 <= j < len(buf):
            buf[j] += v * gain


# --- 스타일별 음악 --------------------------------------------------------------

# (코드 구성음 MIDI, 베이스 루트 MIDI) - 한 마디(4박)에 코드 하나.
_PROGRESSIONS = {
    "finance": [((53, 57, 60, 64), 41), ((55, 59, 62, 64), 43), ((52, 55, 59, 62), 40), ((57, 60, 64, 67), 45)],
    "human": [((57, 60, 64), 45), ((53, 57, 60), 41), ((48, 52, 55, 60), 36), ((55, 59, 62), 43)],
    "ai": [((50, 53, 57), 38), ((46, 50, 53), 34), ((53, 57, 60), 41), ((48, 52, 55), 36)],
}


def _break_mask(timeline: tuple[TimedScene, ...]):
    breaks = [(ts.start, ts.end) for ts in timeline if ts.scene.music == "break"]
    return lambda t: any(a <= t < b for a, b in breaks)


def _music(spec: ShortSpec, timeline: tuple[TimedScene, ...], total: float, rng: random.Random):
    """(drums, music) 두 버스를 돌려준다 - music 버스는 kick에 맞춰 사이드체인 덕킹된다."""
    n = int(total * SR)
    drums = array("d", [0.0]) * n
    music = array("d", [0.0]) * n
    beat = spec.beat_seconds
    bar = beat * 4
    is_break = _break_mask(timeline)
    progression = _PROGRESSIONS[spec.style]
    kick, hat, clap = _kick(), _hat(rng), _clap(rng)
    kicks: list[float] = []
    cache: dict = {}

    def cached(key, make):
        if key not in cache:
            cache[key] = make()
        return cache[key]

    bars = int(math.ceil(total / bar))
    for b in range(bars):
        t0 = b * bar
        chord, root = progression[b % len(progression)]
        if spec.style == "finance":
            pad = cached(("pad", chord), lambda: _mix([_tone(_midi(m), bar + 0.3, _SOFT, 0.25, 0.4, 0.3) for m in chord]))
            _add(music, t0, pad, 0.10)
            _add(music, t0, cached(("bass", root), lambda: _tone(_midi(root), bar, _SOFT, 0.01, 1.2, 0.1)), 0.30)
            for s in range(8):
                note = chord[(s * 2) % len(chord)] + 12
                _add(music, t0 + s * beat / 2, cached(("pluck", note), lambda: _tone(_midi(note), 0.5, _PIANO, 0.004, 7.0)), 0.07)
            for s in range(8):
                t = t0 + s * beat / 2
                if is_break(t):
                    continue
                if s in (0, 3, 4):
                    _add(drums, t, kick, 0.55)
                    kicks.append(t)
                if s in (2, 6):
                    _add(drums, t, clap, 0.16)
                _add(drums, t, hat, 0.05 if s % 2 else 0.025)
        elif spec.style == "human":
            pad = cached(("pad", chord), lambda: _mix([_tone(_midi(m), bar + 0.8, _SOFT, 0.8, 0.25, 0.8) for m in chord]))
            _add(music, t0, pad, 0.07)
            _add(music, t0, cached(("low", root), lambda: _tone(_midi(root), bar + 0.5, _PIANO, 0.01, 0.9, 0.4)), 0.22)
            pattern = (0, 1, 2, 1, 3, 2, 1, 2)
            voiced = sorted(chord) + [chord[0] + 12]
            for s, idx in enumerate(pattern):
                note = voiced[idx % len(voiced)] + 12
                _add(music, t0 + s * beat / 2, cached(("pno", note), lambda: _tone(_midi(note), 1.8, _PIANO, 0.005, 2.2, 0.2)), 0.11 if s % 2 == 0 else 0.07)
        else:  # ai
            for s in range(8):
                _add(music, t0 + s * beat / 2, cached(("bass", root), lambda: _tone(_midi(root), beat / 2, _SQUAREISH, 0.003, 6.0, 0.02)), 0.24)
            for s in range(16):
                note = chord[s % len(chord)] + (24 if s % 4 == 3 else 12)
                _add(music, t0 + s * beat / 4, cached(("arp", note), lambda: _tone(_midi(note), 0.22, _SQUAREISH, 0.002, 14.0, 0.02)), 0.06)
            pad = cached(("pad", chord), lambda: _mix([_tone(_midi(m + 12), bar + 0.2, _SOFT, 0.1, 0.5, 0.2) for m in chord]))
            _add(music, t0, pad, 0.05)
            for s in range(16):
                t = t0 + s * beat / 4
                if is_break(t):
                    continue
                if s % 4 == 0:
                    _add(drums, t, kick, 0.6)
                    kicks.append(t)
                if s in (4, 12):
                    _add(drums, t, clap, 0.28)
                if s % 2 == 1:
                    _add(drums, t, hat, 0.09 if s % 4 == 2 else 0.06)

    if kicks:  # 사이드체인: kick 직후 음악 버스를 살짝 눌러 리듬감을 만든다
        duck = array("d", [1.0]) * n
        for t in kicks:
            start = int(t * SR)
            for i in range(int(0.25 * SR)):
                j = start + i
                if j < n:
                    duck[j] = min(duck[j], 1 - 0.45 * math.exp(-i / SR * 14))
        for i in range(n):
            music[i] *= duck[i]
    return drums, music


def _mix(tracks: list[array]) -> array:
    out = array("d", [0.0]) * max(len(t) for t in tracks)
    for track in tracks:
        for i, v in enumerate(track):
            out[i] += v
    return out


def _reverb(buf: array, wet: float = 0.28) -> array:
    """Schroeder 스타일 잔향(병렬 comb 3개 + allpass 1개) - human 스타일 전용."""
    n = len(buf)
    out = array("d", [0.0]) * n
    for delay_ms, feedback in ((29.7, 0.78), (37.1, 0.76), (41.1, 0.74)):
        d = int(delay_ms / 1000 * SR)
        line = array("d", [0.0]) * n
        for i in range(n):
            line[i] = buf[i] + (line[i - d] * feedback if i >= d else 0.0)
        for i in range(n):
            out[i] += line[i] / 3
    d = int(0.005 * SR)
    ap = array("d", [0.0]) * n
    for i in range(n):
        delayed = ap[i - d] if i >= d else 0.0
        ap[i] = out[i] * -0.5 + delayed + (out[i - d] * 0.5 if i >= d else 0.0)
    return array("d", (dry * (1 - wet) + w * wet for dry, w in zip(buf, ap)))


def _sfx(spec: ShortSpec, timeline: tuple[TimedScene, ...], total: float, rng: random.Random) -> array:
    bus = array("d", [0.0]) * int(total * SR)
    whoosh, impact, pop = _whoosh(rng), _impact(rng), _pop()
    for ts in timeline:
        for cue in ts.scene.audio:
            if cue == "impact":
                _add(bus, ts.start, impact, 0.55)
            elif cue == "whoosh":
                _add(bus, ts.start - 0.3, whoosh, 0.35)
            elif cue == "pop":
                _add(bus, ts.start + 0.12, pop, 0.16)
            elif cue == "riser":
                seconds = min(1.6, ts.duration)
                _add(bus, ts.end - seconds, _riser(rng, seconds), 0.18)
            elif cue == "chime":
                for k, note in enumerate((76, 83, 88)):
                    _add(bus, ts.start + 0.2 + k * 0.12, _tone(_midi(note), 1.6, _PIANO, 0.003, 2.5, 0.3), 0.08)
        for t in item_reveal_times(ts, spec.beat_seconds):
            _add(bus, t, pop, 0.13)
    return bus


def synthesize_soundtrack(spec: ShortSpec, output_wav: Path | str, *, seed: int = 41) -> float:
    """spec 전체 길이의 모노 16bit WAV를 만든다. 반환값은 길이(초)."""
    rng = random.Random(seed)  # 결정적 출력 - 같은 spec이면 같은 소리
    timeline = build_timeline(spec)
    total = timeline[-1].end
    drums, music = _music(spec, timeline, total, rng)
    if spec.style == "human":
        music = _reverb(music)
    sfx = _sfx(spec, timeline, total, rng)

    n = len(drums)
    master = array("d", (drums[i] + music[i] + sfx[i] for i in range(n)))
    fade_in, fade_out = int(0.01 * SR), int(1.5 * SR)
    for i in range(fade_in):
        master[i] *= i / fade_in
    for i in range(fade_out):
        master[n - 1 - i] *= i / fade_out
    peak = max(abs(v) for v in master) or 1.0
    pcm = array("h", (int(32767 * math.tanh(1.1 * v / peak) * 0.9) for v in master))

    output_wav = Path(output_wav)
    with wave.open(str(output_wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(pcm.tobytes())
    return n / SR
