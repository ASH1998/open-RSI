"""Independent diagnostic inputs and expected values, plus findings from reading the labels.

These are post-hoc checks on exposed repair-v1 lessons. They do not change scores.
Arguments are positional. Inputs remain within each reviewed task's domain.
"""

# The task number is unique across the two historical sources in this selection.
PROBES = {
    662: [([{"a": [-1, -3, -1], "b": []}], {"a": [-3, -1, -1], "b": []})],
    663: [([4, 1, 1], -1), ([4, 1, 0], 4), ([0, 1, 2], -1)],
    664: [([14], 8)],
    688: [([8, -15], 17.0)],
    694: [([{"a": [0, -2, -2], "b": [-2, -1], "c": []}], [-2, -1, 0])],
    696: [([[[], [0]], [[9], [8], [7]]], [[9], [0, 8]])],
    723: [([[1, 1, 2, 3], [2, 1, 1]], 1)],
    # For the two digit counts missing from the frozen suite, T(k-1) < 10**(n-1) <= T(k).
    739: [([7], 1414), ([8], 4472)],
    744: [([((), False, (None,), None)], True)],
    759: [(["1.00 "], False), ([".01"], False)],
    796: [([{"a": 2, "b": -6, "c": 2}], -2)],
    805: [([[[-5], [-3, -2]]], [-5])],
    811: [([[(1, 2), ()], [(1, 2)]], False)],
    832: [(["09-010.8"], 10)],
    936: [([[(7, 2), (5, 1)], [5, 7, 5]], [(5, 1), (7, 2), (5, 1)])],
    3038: [(["cabbacb"], "c")],
    3041: [([" -7a!E?i"], "7 a e i")],
    3080: [([" A "], [" A ", " A"])],
}

# Notes compare the complete selected answers, including the historical APPS lessons.
NOTES = {
    662: "Both sort each dictionary value and build a plain dictionary.",
    663: "Both return n for x=1 and y>0. Original otherwise computes a residue directly; learned scans down from n.",
    664: "Original averages the range with statistics.mean. Learned repair divides the sum by the actual number of terms. For even n>=2 the mean is integral.",
    688: "Both use hypot on the two components. Original explicitly casts the result to float.",
    694: "Both union all value lists then sort. The learned guard for an empty mapping gives the same empty result.",
    696: "Both concatenate aligned inner lists using zip, stopping at the shorter input.",
    723: "Learned alone selected the positional equality count via zip. This is distinct from unordered count or membership.",
    739: "Original binary-searches triangular numbers; learned uses the inverse quadratic formula. Integer thresholds can be checked on the full stated domain 1..9.",
    744: "Both test top-level identity with None and stop at the first match.",
    759: "Both use a whole-string decimal pattern. The contract restricts the input to single-line ASCII.",
    796: "Both sum dictionary values, including signed integers.",
    805: "Both use max with the sum as key, preserving the first list on ties.",
    811: "Original compares deques; learned compares lengths and lists directly. Both preserve outer and inner order on the stated inputs.",
    832: "Both parse maximal ASCII digit runs and take the maximum integer. The original fallback is unreachable on inputs with at least one digit.",
    936: "Original alone maps each unique key to its row and replays the request order, retaining repeated requests.",
    3038: "Original alone selected a repair that ranks positional span, then alphabetic order. It replaced a frequency heuristic.",
    3041: "Both clean the ASCII sentence, lowercase letters, and split at each vowel. They differ in the order of cleaning and lowercasing.",
    3080: "Learned alone selected a full name and, for length above two, its two-character prefix.",
}
