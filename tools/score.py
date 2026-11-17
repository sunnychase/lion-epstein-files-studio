#!/usr/bin/env python3
"""score2.py OUT.wav SECONDS -- a dramatic investigative cue, synthesised (no samples, no model). D minor, 100 bpm.
Form: drone + heartbeat (0-8 s) | staccato string ostinato in, low brass swells, taiko hits (8-36 s) | half-time breakdown: clock,
piano motif, tremolo (36-46 s) | final build: ostinato an octave up, snare roll, riser (46-56 s) | the hit and a long tail."""
import sys, numpy as np
from scipy.signal import butter, sosfilt, fftconvolve
OUT, SEC = sys.argv[1], float(sys.argv[2]); SR = 44100; BPM = 100; BEAT = 60 / BPM; BAR = 4 * BEAT; N = int(SEC * SR); T = np.arange(N) / SR
rng = np.random.default_rng(3)
def f(m): return 440 * 2 ** ((m - 69) / 12)
def lp(x, fc, o=2): return sosfilt(butter(o, min(fc, SR / 2 - 100) / (SR / 2), output="sos"), x)
def hp(x, fc, o=2): return sosfilt(butter(o, fc / (SR / 2), btype="high", output="sos"), x)
def adsr(n, a, d, s, r, gate):
    i = np.arange(n) / SR; e = np.where(i < a, i / max(a, 1e-4), np.where(i < a + d, 1 - (1 - s) * (i - a) / max(d, 1e-4), s))
    return e * (1 - np.clip((i - gate) / max(r, 1e-4), 0, 1))
def saw(fr, n, detune=(0, 0.3, -0.3)):
    tt = np.arange(n) / SR; out = np.zeros(n)
    for c in detune:
        fr2 = fr * 2 ** (c / 1200); ph = (tt * fr2) % 1.0; out += 2 * ph - 1
    return out / len(detune)
tracks = {k: np.zeros(N) for k in ("drone", "ost", "brass", "perc", "piano", "fx")}
def add(tr, sig, st):
    i0 = int(st * SR); i1 = min(N, i0 + len(sig))
    if i0 < N: tracks[tr][i0:i1] += sig[: i1 - i0]
# harmony: Dm | Dm | Bb | Bb | Gm | Gm | A(sus) | A   (i i VI VI iv iv V V), 8-bar loop
PROG = [(50, 53, 57), (50, 53, 57), (46, 50, 53), (46, 50, 53), (43, 46, 50), (43, 46, 50), (45, 50, 52), (45, 49, 52)]
def chord(t): return PROG[int((t // BAR) % 8)]
# 1 drone: low D with slow filter movement, whole piece
dr = saw(f(38), N, (0, 4, -4, 7)) * .5 + np.sin(2 * np.pi * f(26) * T) * .6
tracks["drone"] += lp(dr, 160) * (0.9 + 0.1 * np.sin(2 * np.pi * .07 * T)) * .35
# 2 heartbeat kick: two thumps a bar, whole piece (softer at the start)
for b in np.arange(0, SEC, BAR):
    for off, g in ((0, 1.0), (BEAT * .62, .7)):
        n = int(.35 * SR); tt = np.arange(n) / SR; k = np.sin(2 * np.pi * (44 + 110 * np.exp(-28 * tt)) * tt) * np.exp(-10 * tt) * g * (.55 if b < 8 else .8)
        add("perc", k, b + off)
# 3 staccato string ostinato: 16ths, chord tones in a 1-5-8-b7 cell, from bar 2 (8 s) to the end; octave up in the build
def ost(t0, t1, octave):
    step = BEAT / 4; k = 0
    for t in np.arange(t0, t1, step):
        c = chord(t); cell = [c[0], c[2], c[0] + 12, c[0] + 10, c[0], c[2] + 12, c[0] + 12, c[2]]; m = cell[k % 8] + octave; k += 1
        n = int(step * SR * 1.1); s = saw(f(m), n, (0, 6, -6)); s = lp(s, 1400 + 900 * min(1, (t - t0) / 20)) * adsr(n, .004, .05, .5, .03, step * .55) * (.16 if m < 62 else .13)
        add("ost", s, t)
ost(8, 36, 0); ost(46, 56, 12)
# 4 low brass swells on each chord change (bars), from bar 3; bigger in the build
for bar in range(2, int(SEC / BAR)):
    st = bar * BAR
    if 36 <= st < 46: continue
    c = chord(st + .01); n = int(BAR * SR + SR); br = np.zeros(n)
    for m, g in ((c[0] - 12, 1.0), (c[0], .7), (c[1], .5), (c[2], .5)):
        br += saw(f(m), n, (0, 8, -8)) * g
    tt = np.arange(n) / SR; cut = 250 + 900 * np.clip(tt / BAR, 0, 1) ** 2 * (1.5 if st >= 46 else 1)
    br = np.concatenate([lp(br[i * SR // 4:(i + 1) * SR // 4], cut[min(n - 1, i * SR // 4)]) for i in range(int(np.ceil(n / (SR / 4))))])[:n]
    add("brass", br * adsr(n, 1.2, .3, .9, .8, BAR) * (.12 if st < 46 else .17), st)
# 5 taiko hits: beat 1 of every other bar from 16 s, every bar from 46 s; layered noise burst + low sine
for b in list(np.arange(16, 36, 2 * BAR)) + list(np.arange(46, 56, BAR)):
    n = int(.9 * SR); tt = np.arange(n) / SR
    hit = np.sin(2 * np.pi * (58 + 60 * np.exp(-18 * tt)) * tt) * np.exp(-5 * tt) * 1.0 + lp(rng.standard_normal(n), 900) * np.exp(-14 * tt) * .9
    add("perc", hit * .8, b)
# 6 snare-ish roll into the breakdown (34-36 s) and through the build (50-56 s)
def roll(t0, t1, g0, g1):
    for i, t in enumerate(np.arange(t0, t1, BEAT / 4)):
        n = int(.09 * SR); tt = np.arange(n) / SR; sn = (hp(rng.standard_normal(n), 1800) * np.exp(-40 * tt) + np.sin(2 * np.pi * 190 * tt) * np.exp(-30 * tt) * .5)
        add("perc", sn * (g0 + (g1 - g0) * (t - t0) / (t1 - t0)) * .5, t)
roll(34, 36, .2, .6); roll(50, 56, .2, .9)
# 7 breakdown 36-46: ticking clock on 8ths, a piano motif (D F A G F E D), tremolo pad
for t in np.arange(36, 46, BEAT / 2):
    n = int(.04 * SR); tk = hp(rng.standard_normal(n), 5000) * np.exp(-np.arange(n) / SR * 120) * .18; add("fx", tk, t)
motif = [(62, 0), (65, 1), (69, 2), (67, 3), (65, 4), (64, 5.5), (62, 6.5), (57, 8)]
for m, bt in motif:
    n = int(2.2 * SR); tt = np.arange(n) / SR
    pk = sum(np.sin(2 * np.pi * f(m) * h * tt) * g * np.exp(-(2.2 + 2.5 * h) * tt) for h, g in ((1, 1), (2, .45), (3, .2), (4, .1)))
    add("piano", pk * .22, 36 + bt * BEAT); add("piano", pk * .08, 36 + bt * BEAT + .9)
n = int(10 * SR); tt = np.arange(n) / SR; trem = (0.55 + 0.45 * np.sign(np.sin(2 * np.pi * 7 * tt)))
pad = sum(saw(f(m), n, (0, 5, -5)) for m in (50, 53, 57, 62)); add("brass", lp(pad, 700) * trem * adsr(n, 2.0, 0, 1, 2.0, 8) * .07, 36)
# 8 riser 48-56, the final hit at 56, and a long low tail
n = int(8 * SR); tt = np.arange(n) / SR; nz = rng.standard_normal(n)
riser = np.concatenate([lp(nz[i * SR // 4:(i + 1) * SR // 4], 200 + 6000 * ((i + 1) / 32) ** 2) for i in range(32)])[:n] * (tt / 8) ** 2.2 * .6
sweep = np.sin(2 * np.pi * np.cumsum(f(50) * 2 ** (tt / 8 * 2)) / SR) * (tt / 8) ** 3 * .12
add("fx", riser + sweep, 48)
n = int(6 * SR); tt = np.arange(n) / SR
hit = (np.sin(2 * np.pi * f(38) * tt) + .6 * np.sin(2 * np.pi * f(45) * tt) + .5 * np.sin(2 * np.pi * f(50) * tt)) * np.exp(-.9 * tt) * .9
hit += lp(rng.standard_normal(n), 1500) * np.exp(-7 * tt) * .9 + np.sin(2 * np.pi * (50 + 80 * np.exp(-20 * tt)) * tt) * np.exp(-6 * tt)
add("perc", hit * .9, 56)
# 9 mix: reverb on strings/brass/piano/perc (exponential noise IR), gentle bus compression by tanh, fades
ir = rng.standard_normal(int(1.9 * SR)) * np.exp(-np.arange(int(1.9 * SR)) / SR * 2.6); ir = lp(ir, 5000); ir /= np.abs(ir).sum() / 2.2
def verb(x, wet): return x + wet * fftconvolve(x, ir)[: len(x)]
mix = tracks["drone"] + verb(tracks["ost"], .35) + verb(tracks["brass"], .5) + verb(tracks["perc"], .3) + verb(tracks["piano"], .6) + tracks["fx"]
mix *= np.minimum(1, T / 2.0) * np.minimum(1, (SEC - T) / 3.0)
mix = np.tanh(mix * 1.4) / np.tanh(1.4)
d = int(.012 * SR); L = mix; R = np.concatenate([np.zeros(d), mix[:-d]]) * .85 + mix * .15
st = np.stack([L, R], 1); st /= np.max(np.abs(st)) + 1e-9; st *= .9
import wave; w = wave.open(OUT, "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((st * 32767).astype(np.int16).tobytes()); w.close(); print(OUT, f"{SEC:.0f}s")
