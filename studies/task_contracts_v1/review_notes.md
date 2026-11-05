# Review of the 20 exposed recovery tasks

November 5, 2026. The review file is an ordered JSON array. Each record binds its clarified prompt and proposed boundaries to the digest of the exact task in `data/successor-recovery-v3/audited-dataset.json` under `train`. Each public prompt retains its historical instructions and function declaration. Private review notes and typed expectations are separate fields.

The review adds 73 distinct calls to the 20 tasks. All 273 historical test cases remain the prefix of the respective derived tasks. These tasks have prior model exposure and are suitable for a prospective diagnostic of contract wording and coverage.

| Task | Decision affecting the proposed checks |
| --- | --- |
| 675 | Specify the half-open interval. For `[5,9)`, sums 4, 5, 8, 9 and 10 must return 4, 20, 20, 9 and 10. The excluded endpoint differs from the special return value 20, so the test exposes the endpoint error. |
| 757 | Specify decimal-string output and count each unordered pair once. The old review covered distinct nonpalindromic words. Preserve that domain because the source also counts self-pairs for palindromes, which the original assertions leave ambiguous. Test no partner, one partner, and two disjoint pairs. |
| 885 | Require a bijection of characters by position. Check repeated consistent mappings, splitting, merging, equal frequencies with different positions, unequal lengths, and two empty strings. |
| 619 | Specify stable ordering of both groups for ASCII input. Two interleaved cases check the order of digits and nondigits, including repeated zeros, spaces, punctuation and case. |
| 916 | The source returns the values at the lexicographically first matching index triple. Its missing-solution branch returns `False`. The clarified task retains the previously reviewed domain in which a solution exists. Test ties and repeated values at distinct positions. |
| 641 | Specify a one-based integer sequence term and bound the index at 1000. At this bound the intermediate arithmetic in the source reference is exact. |

The remaining item-level review notes record the relevant input domains, indexing conventions, expected output types, and reasons for the chosen boundaries. In particular, the note on 687 distinguishes a request for recursion from the observable numerical result that these output tests can check.

The evidence check covered the pinned native training file, all 20 source-row digests, extracted reference hashes, the ordered training registry in the historical protocol, and the preserved prompt and signature wrappers. Static compilation checks each call against its entry point and existing typed encoding. Independent calculations agreed with all 346 historical and proposed expected values. For example, the check for 661 enumerated allowed subsets of positions, and the check for 734 enumerated contiguous slices. These checks used decoded arguments and independently written calculations. Reference and candidate programs were read as data.

| Artifact | Digest |
| --- | --- |
| Historical training list, canonical JSON | `764949f038295e2ab0e8e0abdef6f70b9c141e2432f74038d82184be14e847c7` |
| Reviews, canonical JSON | `8934dd3d836911790e703a8f32a4a97140df9d48dfe7a51eaf32ee42ed65e300` |
| `reviews.json`, file bytes | `f80db7a8a981c21de2fc8f1579c6ee4575c0324688e50823bc535da661dfbd91` |

The current task-contract API applied and replayed all records in memory. The next integration check is to compare the pinned reference checker’s results with the independently specified expectations and record any disagreements before using the derived diagnostic.
