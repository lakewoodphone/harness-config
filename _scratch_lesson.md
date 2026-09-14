The collision P132 describes happened for real while this very commit was being merged: SECRATARY and ZABZ-YOGA each allocated `D143` within the same hour. SECRATARY's is the Fios network-record decision; mine was the rebuild-and-carry decision. `git merge` produced an add/add conflict on `journal/entries/decisions/D143.md`.

Resolution: the shared line keeps SECRATARY's D143 (it exists on the other machine and may be cited there), mine was re-filed by the tool as D145, and the citations in NOW.md were updated. Nothing was lost - both files survive - but a cross-reference written between the two allocations ("see D143") is now ambiguous, exactly as the 161 historical collisions were.

Why it is worth a lesson rather than a note: the two commits were small, the machines were on the same branch, and the id ceilings were computed locally with a fetch. That is the steady state, not an accident. Until ids come from one authority (or a lock is held across machines), the ceiling reduces the rate and `check`/`merge` catch the rest; it does not prevent it.

Evidence: git merge output "CONFLICT (add/add): Merge conflict in journal/entries/decisions/D143.md"; the two headings; D145 as the re-filed entry.
