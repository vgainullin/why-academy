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
