# Evolution Log

Append-only audit trail of every evolution agent run. Each entry records what
the agent did, which feedback issues it addressed, and how validation went.
The agent reads this on every run so it doesn't repeat work.

Format per entry:
```
## YYYY-MM-DDTHH:MM:SSZ
- Action: patch | new-block | new-lesson
- Issues: #N, #M
- Files: path/to/file.json (modified|created)
- Summary: one or two sentences on what was done
- Commit: <hash>
```

---

## 2026-04-06T00:00:00Z
- Action: patch
- Issues: #2
- Files: lessons/lesson1.json (modified)
- Summary: Expanded L1-B2 to explicitly teach Newton's dot notation (one dot = velocity, two dots = acceleration, ẍ ≡ d²x/dt²) in response to "why double dots above x?". Inserted new Read block L1-B7B "Why Stiffer Means Faster" before the L1-B8 explain block, scaffolding the conceptual question with a worked numerical comparison (k=10 vs k=100 at the same displacement) and explaining why m sits in the denominator and why the square root appears. The L1-B8 flag was likely caused by the lesson testing intuition it never explicitly taught — this fixes that.
- Validator: PASSED (1 lesson)
