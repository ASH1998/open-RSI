"""Independent wording and hand-computed typed test values for native APPS calls."""

REVIEWS = {
    3038: (
        "Given a nonempty string of lowercase English letters, return the letter whose last and first positions are farthest apart. Break ties by choosing the alphabetically earliest letter.",
        "Compare spans, not occurrence counts. Several letters may share a maximal span.",
        [("single", ["q"], "q"), ("all_distinct", ["zyx"], "x"),
         ("tie_not_first_seen", ["dbdb"], "b"), ("span_beats_frequency", ["zaaabz"], "z")],
    ),
    3041: (
        "Given an ASCII sentence, discard every character except letters and decimal digits, and lowercase the letters. Keep that order and start a new word at every a, e, i, o, or u, even when vowels are consecutive. Separate words with one space. Any initial consonants or digits begin the first word.",
        "Punctuation and prior spaces disappear before vowel segmentation. No leading or trailing separator.",
        [("vowels_only", ["U--Ai"], "u a i"), ("digits_first", ["2 !! A3_E"], "2 a3 e"),
         ("no_vowels", ["B-9 y"], "b9y"), ("nothing_left", [" #!"], "")],
    ),
    3052: (
        "Given an ASCII string, retain its entire trailing run of exclamation marks. Remove every other exclamation mark. Return the resulting string with all other characters in their original positions relative to each other, including spaces.",
        "A trailing space ends the suffix. Keeping all marks or dropping the final suffix both fail.",
        [("marks_only", ["!!!"], "!!!"), ("space_at_end", ["X!! "], "X "),
         ("internal_and_suffix", ["!!a!b!!!"], "ab!!!"), ("empty", [""], "")],
    ),
    3080: (
        "Given a name as an ASCII string, return a list beginning with the full name. If it has more than two characters, append its first two characters as a second item. Preserve case and spaces.",
        "The length threshold is strict. For a short name the list contains just one item.",
        [("exactly_two", ["Qz"], ["Qz"]), ("length_three", ["aBc"], ["aBc", "aB"]),
         ("multiword", ["Jo Li"], ["Jo Li", "Jo"]), ("one_character", ["X"], ["X"])],
    ),
    4189: (
        "Given two ASCII strings a and b, independently sum the character codes in each. Return the original string with the larger sum. If the sums are equal, return a.",
        "Use all characters including punctuation, break ties by argument order, and return a string.",
        [("equal_distinct", ["BA", "AB"], "BA"), ("empty_first", ["", "!"], "!"),
         ("shorter_wins", ["z", "!!"], "z"), ("spaces_count", ["   ", "A"], "   ")],
    ),
    4194: (
        "A version is a string of decimal components separated by dots. The first is a nonnegative integer written without redundant leading zeros. Every later component is a single digit. Increment the last component. Each non-first component that reaches ten becomes zero and carries one to its left. The first component can grow freely. Return the updated text with the same number of components.",
        "Only trailing nines propagate a carry. Increment may extend the first component's digit count.",
        [("one_component", ["99"], "100"), ("partial_carry", ["12.3.9.9"], "12.4.0.0"),
         ("full_carry", ["19.9.9"], "20.0.0"), ("no_carry", ["0.0.8"], "0.0.9")],
    ),
    4211: (
        "Given a string of 1 to 99 printable non-space ASCII characters, return a boolean indicating whether all distinct characters occur equally often. Treat uppercase and lowercase forms of the same letter as one character. Digits and punctuation count as characters.",
        "Ignore letter case but count every occurrence, including nonletters. A single distinct character qualifies.",
        [("one_distinct", ["AaA"], True), ("case_merge", ["aAXx"], True),
         ("symbol_imbalance", ["pP!!2"], False), ("singleton_symbol", ["#"], True)],
    ),
    4256: (
        "Given a string of 1 to 50 lowercase English letters, preserve its characters in order. Immediately after the first occurrence of each letter, insert in uppercase and alphabetical order every letter later in the alphabet that is absent from the entire input. Insert nothing after repeat occurrences of the same original letter.",
        "Determine absence over the whole input, then insert after the earliest occurrence only.",
        [("last_letter_repeated", ["zz"], "zz"), ("one_missing_after_y", ["yy"], "yZy"),
         ("skip_later_present", ["xz"], "xYz"), ("later_absence_and_repeat", ["wyw"], "wXZyZw")],
    ),
}
