# Why Academy

A free, open-source interactive learning platform that teaches STEM through a derive-it-yourself methodology. Students perform stepwise algebraic derivations, estimate answers in scientific notation, implement solutions in code, and explain concepts — all verified deterministically. No AI grading, no paywall.

## Status

Phase 1 — MVP. Lesson 1 (The Single Spring) implements all six block types:

- **Read** — narrative with interactive simulations and KaTeX equations
- **Derive** — stepwise derivation with full history and back/forward navigation
- **Calculate** — predict-then-verify with scientific notation
- **Code** — Python (NumPy, matplotlib) running in-browser via Pyodide
- **Practice** — randomized parameter problems
- **Explain** — multiple choice with misconception feedback

Every block has an inline feedback toolbar so students can flag confusion, ask questions, and comment on specific text.

## Stack

Vanilla JS, no frameworks. KaTeX for equations, CodeMirror for the code editor, Pyodide (WebAssembly Python) for in-browser execution. Hosted as a static site on GitHub Pages.

## Run locally

```bash
python3 -m http.server 8765
```

Then open http://localhost:8000

## Adding lessons

Lessons are JSON files in `lessons/`. Load a different lesson with `?lesson=lessons/your-lesson.json`.
