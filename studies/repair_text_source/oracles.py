"""Handwritten independent functions for calibration. No imported dataset code."""

from collections import Counter
from string import ascii_lowercase


def widest_span(st):
    return min(set(st), key=lambda ch: (-(st.rindex(ch) - st.index(ch)), ch))


def vowel_words(st):
    words = []
    for ch in st.lower():
        if ch.isalnum():
            if not words or ch in "aeiou":
                words.append("")
            words[-1] += ch
    return " ".join(words)


def trailing_marks(s):
    prefix = s.rstrip("!")
    return prefix.replace("!", "") + s[len(prefix):]


def full_and_short(name):
    return [name] if len(name) <= 2 else [name, name[:2]]


def ascii_winner(a, b):
    return max((a, b), key=lambda text: sum(map(ord, text)))


def increment_version(version):
    parts = list(map(int, version.split(".")))
    for i in reversed(range(len(parts))):
        parts[i] += 1
        if i == 0 or parts[i] < 10:
            break
        parts[i] = 0
    return ".".join(map(str, parts))


def uniform_counts(word):
    return len(set(Counter(word.lower()).values())) == 1


def insert_missing(st):
    pieces = []
    for i, current in enumerate(st):
        pieces.append(current)
        if st.index(current) == i:
            pieces.extend(ch.upper() for ch in ascii_lowercase if ch > current and ch not in st)
    return "".join(pieces)


ORACLES = {3038: widest_span, 3041: vowel_words, 3052: trailing_marks, 3080: full_and_short,
           4189: ascii_winner, 4194: increment_version, 4211: uniform_counts, 4256: insert_missing}
