"""Study-specific reviewed contracts. Each boundary is (name, positional arguments, answer).

Answers below were worked out from the stated contracts before reference execution.
Python literals are converted to the production typed representation by prepare.py.
"""

# A source ID appears exactly once. Role is independent of the dataset-native split.
# Cases are private to the trusted verifier; the reworded descriptions are public.
CONTRACTS = {
    626: ("numeric", "Given an integer radius r, return the maximum area of a triangle inscribed in a semicircle of that radius. For a negative radius return the integer -1. Return an integer.",
          [("negative", [-3], -1), ("unit", [1], 1), ("larger", [5], 25)]),
    644: ("collections", "Given a nonempty list and a count k between 1 and its length inclusive, return a list with the first k items in reverse order and the remaining items in their original order.",
          [("one", [[5, 6], 1], [5, 6]), ("whole", [[0, 2, 1], 3], [1, 2, 0]), ("ties", [[1, 1, 4, 8], 3], [4, 1, 1, 8])]),
    662: ("collections", "Given a dictionary mapping string keys to lists of integers, return a dictionary with the same keys and a sorted ascending list for each key. Retain repetitions.",
          [("empty", [{}], {}), ("empty_values", [{"q": []}], {"q": []}), ("signed_ties", [{"b": [2, -4, 2], "a": [1]}], {"b": [-4, 2, 2], "a": [1]})]),
    663: ("numeric", "For nonnegative integers n and y and a positive integer x, return the largest integer k between 0 and n inclusive with remainder y when divided by x. Return -1 if there is no such k.",
          [("zero", [0, 2, 0], 0), ("no_residue", [8, 4, 4], -1), ("beyond_bound", [2, 9, 4], -1), ("before_endpoint", [14, 5, 1], 11)]),
    664: ("numeric", "Given an even integer n of at least 2, return the arithmetic mean of the even integers from 2 through n inclusive as an integer.",
          [("three_terms", [6], 4), ("four_terms", [8], 5), ("larger", [50], 26)]),
    679: ("collections", "Given a nonempty dictionary with string keys, and an integer index valid for its length, return the key at that index in dictionary insertion order. Use Python zero-based indexing, including negative indices from the end.",
          [("negative", [{"z": 9, "a": 0}, -1], "a"), ("single", [{"x": 0}, 0], "x"), ("start", [{"z": -1, "a": 2}, -2], "z")]),
    688: ("numeric", "Given two integers representing the real and imaginary parts of a complex number, return its magnitude as a float.",
          [("origin", [0, 0], 0.0), ("negative_axis", [-7, 0], 7.0), ("both_negative", [-5, -12], 13.0)]),
    694: ("collections", "Given a dictionary mapping strings to lists of integers, return a single ascending list of the distinct integers appearing in any value.",
          [("empty_dict", [{}], []), ("empty_lists", [{"a": [], "b": []}], []), ("shared_values", [{"a": [4, -1], "b": [4, 0, -1]}], [-1, 0, 4])]),
    696: ("collections", "Given two lists of lists, concatenate each left inner list with the right inner list at the same index. Return a list of those concatenations, stopping when either outer list runs out.",
          [("empty_left", [[], [[1]]], []), ("unequal", [[[1], [2]], [[3]]], [[1, 3]]), ("empty_sublists", [[[], [1]], [[], []]], [[], [1]])]),
    717: ("numeric", "Given a list of integers, return their sample standard deviation as a float, using the sum of squared deviations divided by the number of values minus one under the square root. Return 0.0 for zero or one value.",
          [("empty", [[]], 0.0), ("constant", [[3, 3, 3]], 0.0), ("symmetric", [[-2, 0, 2]], 2.0)]),
    723: ("collections", "Given two lists of integers, return the number of positions where both lists have an element and the two values at that position are equal. Ignore any unpaired tail.",
          [("empty", [[], [2]], 0), ("do_not_reorder", [[1, 2], [2, 1]], 0), ("partial_match", [[4, 4, 5], [4, 3, 5, 4]], 2)]),
    739: ("numeric", "Given a decimal digit count n from 1 to 9, return the smallest positive index k such that the triangular number k*(k+1)//2 has n decimal digits. The first triangular number has index 1.",
          [("one_digit", [1], 1), ("five_digits", [5], 141), ("six_digits", [6], 447), ("nine_digits", [9], 14142)]),
    744: ("collections", "Given a tuple, return a Boolean indicating whether any top-level element is None. Other false-valued elements and nested occurrences of None do not count.",
          [("empty", [()], False), ("falsy", [(False, 0, "")], False), ("nested", [((None,),)], False), ("only_none", [(None,)], True)]),
    759: ("text", "Given a single-line ASCII string, return True exactly when it consists of one or more decimal digits optionally followed by a decimal point and one or two more digits. No sign, whitespace, or exponent is allowed. Leading zeros are allowed.",
          [("integer_form", ["007"], True), ("one_fraction_digit", ["0.2"], True), ("dangling_point", ["5."], False), ("empty", [""], False), ("sign", ["-1.25"], False)]),
    780: ("collections", "Given a list of pairs of integers, return the coordinatewise sum for each two different positions i < j as a tuple. Return a list ordered first by i then by j, retaining repeated results.",
          [("empty", [[]], []), ("single_pair", [[(1, 2)]], []), ("repeated_pairs", [[(1, -1), (1, -1), (0, 2)]], [(2, -2), (1, 1), (1, 1)])]),
    796: ("collections", "Given a dictionary whose values are integers, return the sum of its values. Return the integer zero for an empty dictionary.",
          [("empty", [{}], 0), ("negative", [{"a": -3}], -3), ("cancel", [{"x": 3, "y": -3, "z": 0}], 0)]),
    805: ("collections", "Given a nonempty list of lists of integers, return the first inner list with the greatest sum. The sum of an empty inner list is zero. Return the list itself.",
          [("tie", [[[3], [1, 2]]], [3]), ("negative", [[[-5], [-4]]], [-4]), ("empty_inner", [[[-2], []]], [])]),
    811: ("collections", "Given two lists of tuples of integers, return True if the lists have equal lengths and contain equal tuples at all corresponding positions. Tuple element order and outer list order both matter.",
          [("empty", [[], []], True), ("outer_order", [[(1,), (2,)], [(2,), (1,)]], False), ("tuple_order", [[(1, 2)], [(2, 1)]], False), ("length", [[(1,)], []], False)]),
    830: ("numeric", "Given a finite number a and a nonnegative number of decimal places digits, round a upward toward positive infinity at that decimal place and return the resulting number. Inputs stay away from decimal boundaries except for integers and exactly representable binary fractions.",
          [("negative", [-1.25, 1], -1.2), ("no_change", [3.5, 1], 3.5), ("zero_places", [-1.25, 0], -1)]),
    832: ("text", "Given an ASCII string containing at least one digit, find the largest integer represented by a maximal consecutive run of decimal digits. Treat punctuation, signs and letters as separators, and read runs with leading zeros as decimal integers.",
          [("zero_runs", ["00q000"], 0), ("longer_not_larger", ["0012z99"], 99), ("sign_separator", ["a-17b+8"], 17), ("one_run", ["400"], 400)]),
    910: ("numeric", "Given a month, day and year, each an integer or its unsigned ASCII decimal representation, return whether they form a valid proleptic Gregorian date. The year must be between 1 and 9999 inclusive. Apply the century exception to the leap-year rule.",
          [("common_century", [2, 29, 1900], False), ("leap_century", ["02", "29", "2000"], True), ("short_month", [4, 31, 2024], False), ("year_zero", [1, 1, 0], False)]),
    915: ("collections", "Given a list of small integers, return the positives in ascending order, then all zeros, then the negatives in ascending numerical order. Retain repeated values.",
          [("empty", [[]], []), ("mixed_with_zeros", [[-1, 0, 2, -4, 1, 0]], [1, 2, 0, 0, -4, -1]), ("repeats", [[-2, -2, 3, 3]], [3, 3, -2, -2])]),
    936: ("collections", "The first list contains integer (key, value) tuples with unique keys. For each key in the second list, return its corresponding (key, value) tuple. All requested keys exist. The result is a list in request order, including repeated requests.",
          [("no_requests", [[(1, 3)], []], []), ("repeat_request", [[(2, 4), (1, 9)], [1, 1]], [(1, 9), (1, 9)]), ("subset", [[(3, 4), (0, 9)], [0]], [(0, 9)])]),
    938: ("collections", "Given three nonempty ascending integer lists A, B, C and their respective lengths p, q, r, choose one value from each list to minimize the difference between the largest and smallest chosen values. Return the tuple in A, B, C order. If several value tuples attain the same minimum, choose the lexicographically smallest one.",
          [("singleton_lists", [[-2], [4], [0], 1, 1, 1], (-2, 4, 0)), ("common_value", [[1, 5], [5], [3, 5], 2, 1, 2], (5, 5, 5)), ("later_best", [[-8, 2], [3, 10], [4], 2, 2, 1], (2, 3, 4)), ("tie", [[0], [3], [1, 2], 1, 1, 2], (0, 3, 1))]),
    943: ("collections", "Given two nondecreasing lists of integers, merge their elements into a single nondecreasing list. Preserve every occurrence, including duplicates across the two inputs.",
          [("empty", [[], []], []), ("one_empty", [[], [-2, 4]], [-2, 4]), ("ties_across", [[-1, 2, 2], [-1, 2]], [-1, -1, 2, 2, 2])]),
    950: ("numeric", "Return the Chinese zodiac sign for an integer year using a repeating 12-year cycle. Starting at year 2000, the signs in order are Dragon, Snake, Horse, sheep, Monkey, Rooster, Dog, Pig, Rat, Ox, Tiger, Hare. Preserve the stated spelling and capitalization.",
          [("anchor", [2000], "Dragon"), ("cycle_repeat", [2012], "Dragon"), ("step_before", [1999], "Hare"), ("mixed_case", [1980], "Monkey")]),
    972: ("collections", "Given two tuples, return one tuple containing all elements of the first followed by all elements of the second. Elements that are themselves tuples must remain intact.",
          [("both_empty", [(), ()], ()), ("nested", [((1, 2),), (3,)], ((1, 2), 3)), ("preserve_duplicates", [(1,), (1,)], (1, 1))]),
}

# One reason for every fresh, convertible, non-selected row not already covered
# by the frozen v1 domain review. Keys are MBPP full IDs, independent of role.
QUARANTINE = {
    622: "Median of two sorted arrays reduces to averaging two adjacent ranks of the same merged sequence as exposed 597.",
    650: "The multiset-equality reference ignores the last elements after sorting, accepting unequal singleton arrays.",
    698: "Dictionary equality in the grader cannot distinguish the requested key iteration order from an unsorted mapping.",
    754: "Three-way aligned equality and value extraction is close to 723's aligned-equality count. Retain one representative.",
    769: "Symmetric difference is close to exposed 579, and list output order depends on set iteration.",
    829: "Second frequency rank projects the ranked counts of exposed 862 and 946. Ties alone do not establish freshness.",
    833: "Returning keys in insertion order is too close to indexed key selection in 679. Retain one representative.",
    836: "Maximum-sum contiguous subarray matches the core optimization target of exposed 559.",
    840: "Same quadratic-root relationship template, signature and result type as exposed 636, with only the coefficient predicate changed.",
    900: "A fixed leading digit specializes the exposed prefix-match task 823.",
    902: "Pinned reference returns a Counter, not the dictionary in the native assertions. Its addition also drops nonpositive totals.",
}

VALIDATION_REVIEW = {
    518: "Square root of perfect squares overlaps the inverse computation of exposed 803. Native references return float for int expectations.",
    531: "Minimum coin count differs from exposed 918's number of combinations. Possible native-validation candidate if restricted to reachable sums and calibrated separately.",
    532: "Permutation predicate overlaps exposed anagram task 861. Reference can accept strings differing only in their last sorted letter.",
    550: "Rotated-sorted-array pivot closely overlaps exposed rotation-count task 802. The source also tests [3,4,5,2,1], outside the stated input class.",
    560: "Returns a tuple built from a set. Required tuple order depends on set iteration.",
    575: "Possible native-validation candidate with a guaranteed Nth nonmultiple inside [L,R]; not calibrated or used here.",
}
