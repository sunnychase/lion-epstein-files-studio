#!/usr/bin/env python3
"""score.py OUT.wav SECONDS -- an original underscore, synthesised here (no samples, no model): dark investigative pulse in D minor,
96 bpm: sub-bass eighths, a sparse plucked motif, slow pad swells, ticking hats, a riser into a restrained climax, a final hit."""
import sys, numpy as np
from scipy.signal import butter, sosfilt
OUT, SEC = sys.argv[1], float(sys.argv[2]); SR = 44100; BPM = 96; BEAT = 60 / BPM; N = int(SEC * SR); t = np.arange(N) / SR
rng = np.random.default_rng(7)
def f(midi): return 440 * 2 ** ((midi - 69) / 12)
def env(n, a, d, s, r, hold):   # ADSR in seconds, hold = total gate length
    out = np.zeros(n); i = np.arange(n) / SR
    out = np.where(i < a, i / max(a, 1e-4), np.where(i < a + d, 1 - (1 - s) * (i - a) / max(d, 1e-4), s))
    rel = np.clip((i - hold) / max(r, 1e-4), 0, 1); return out * (1 - rel)
def lp(x, fc, order=2): sos = butter(order, fc / (SR / 2), output="sos"); return sosfilt(sos, x)
def hp(x, fc, order=2): sos = butter(order, fc / (SR / 2), btype="high", output="sos"); return sosfilt(sos, x)
mix = np.zeros(N)
# harmony: Dm | Bb | F | C  (two bars each, eight-bar loop)
CH = [(50, 53, 57), (46, 50, 53), (41, 45, 48), (48, 52, 55)]; BAR = 4 * BEAT; LOOP = 8 * BAR
def chord_at(time): return CH[int((time % LOOP) // (2 * BAR))]
def add(sig, start):
    i0 = int(start * SR); i1 = min(N, i0 + len(sig)); 
    if i0 < N: mix[i0:i1] += sig[: i1 - i0]
# 1. pad: slow saw-ish stack, low-passed, breathing
for k in range(int(SEC / (2 * BAR)) + 1):
    st = k * 2 * BAR; root, third, fifth = chord_at(st + 0.01); n = int(2 * BAR * SR) + SR
    tt = np.arange(n) / SR; pad = np.zeros(n)
    for m, g in ((root - 12, .9), (root, .6), (third, .5), (fifth, .45), (root + 12, .2)):
        fr = f(m); pad += g * (np.sin(2 * np.pi * fr * tt) + .35 * np.sin(2 * np.pi * 2 * fr * tt + .3) + .15 * np.sin(2 * np.pi * 3 * fr * tt)) * (1 + .04 * np.sin(2 * np.pi * .4 * tt + m))
    pad = lp(pad, 500 + 250 * np.sin(2 * np.pi * .05 * st)) * env(n, 1.6, 0.5, .85, 1.4, 2 * BAR) * .11
    add(pad, st)
# 2. sub bass: eighth-note pulse on the root, sidechain-like dip on the beat
beats = np.arange(0, SEC, BEAT / 2)
for b in beats:
    root = chord_at(b)[0] - 24; n = int(BEAT / 2 * SR); tt = np.arange(n) / SR
    bass = (np.sin(2 * np.pi * f(root) * tt) + .25 * np.sin(2 * np.pi * 2 * f(root) * tt)) * env(n, .005, .12, .6, .06, BEAT / 2 - .02)
    bass *= .32 if (round(b / (BEAT / 2)) % 2 == 0) else .22
    add(lp(bass, 180), b)
# 3. plucked motif (sparse): a four-note cell on the chord tones, every other bar, with octave echoes
motif_cells = [(0, 2), (1, 1.5), (2, 2.5), (1, 3.5)]  # (chord-tone index, beat within the bar)
for bar in range(int(SEC / BAR) + 1):
    if bar % 2 == 1 or bar * BAR > SEC - 3: continue
    st = bar * BAR; ch = chord_at(st + 0.01)
    for idx, beat in motif_cells:
        m = ch[idx] + 12 + (12 if bar % 4 == 2 and idx == 2 else 0); n = int(1.6 * SR); tt = np.arange(n) / SR
        pl = (np.sin(2 * np.pi * f(m) * tt) + .5 * np.sin(2 * np.pi * 2 * f(m) * tt) * np.exp(-6 * tt) + .2 * np.sin(2 * np.pi * 3 * f(m) * tt) * np.exp(-9 * tt)) * np.exp(-2.8 * tt) * .17
        add(pl, st + beat * BEAT); add(pl * .35, st + beat * BEAT + .375 * BEAT * 1.0); add(pl * .18, st + beat * BEAT + .75 * BEAT)
# 4. ticking hats on offbeats (filtered noise), louder in the second half
for b in np.arange(BEAT / 2, SEC, BEAT / 2):
    n = int(.05 * SR); tick = hp(rng.standard_normal(n), 6000) * np.exp(-np.arange(n) / SR * 90) * (.05 + .05 * min(1, b / SEC))
    if round(b / (BEAT / 2)) % 2 == 1: add(tick, b)
# 5. kick-ish thump on beats 1 and 3 from the second loop on
for b in np.arange(LOOP, SEC - 2, 2 * BEAT):
    n = int(.3 * SR); tt = np.arange(n) / SR; k = np.sin(2 * np.pi * (48 + 90 * np.exp(-30 * tt)) * tt) * np.exp(-12 * tt) * .5; add(k, b)
# 6. riser into the last 10 s, then a hit and a tail
rs = max(0, SEC - 14); n = int(10 * SR); tt = np.arange(n) / SR
noise = rng.standard_normal(n); riser = np.concatenate([lp(noise[i * SR // 2:(i + 1) * SR // 2], 300 + 5000 * ((i + 1) / 20) ** 2) for i in range(20)]) * (tt / 10) ** 2 * .35; add(riser, rs)
hit_t = SEC - 4; n = int(4 * SR); tt = np.arange(n) / SR; root = 38
hit = (np.sin(2 * np.pi * f(root) * tt) + .5 * np.sin(2 * np.pi * f(root + 7) * tt) + .4 * np.sin(2 * np.pi * f(root + 12) * tt)) * np.exp(-1.1 * tt) * .6
hit += lp(rng.standard_normal(n), 1200) * np.exp(-9 * tt) * .5; add(hit, hit_t)
# 7. fade in / out, gentle saturation, stereo widen (pad/pluck haas), normalise
mix *= np.minimum(1, t / 1.5) * np.minimum(1, (SEC - t) / 2.5)
mix = np.tanh(mix * 1.6) / np.tanh(1.6)
L = mix.copy(); R = np.concatenate([np.zeros(int(.011 * SR)), mix[: -int(.011 * SR)]]) * .9 + mix * .1
st = np.stack([L, R], 1); st /= np.max(np.abs(st)) + 1e-9; st *= .89
import wave; w = wave.open(OUT, "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((st * 32767).astype(np.int16).tobytes()); w.close()
print(OUT, f"{SEC:.0f}s")
