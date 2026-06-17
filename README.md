# Why Academy

A free, open-source interactive learning platform that teaches STEM through a **derive-it-yourself** methodology. Students explore interactive simulations, perform stepwise algebraic derivations on a freeform handwriting canvas, estimate answers in scientific notation, implement numerical solutions in Python/NumPy, and explain concepts in their own words. 

Verification is 100% deterministic using SymPy inside the browser. No AI grading, no paywall, near-zero server cost.

🚀 **Live Test Deployment:** [https://vgainullin.github.io/why-academy/](https://vgainullin.github.io/why-academy/)

---

## Existing Functionality & Features

### 1. Interactive Lessons
The platform features four fully implemented interactive lessons spanning physics, mathematics, and statistics:
*   **L1: The Single Spring (Physics &middot; Oscillations)**
    *   *Path:* `lesson.html?lesson=lessons/physics/oscillations/01-single-spring.json`
    *   *Concept:* Explore Hooke's Law and harmonic motion, derive $\omega = \sqrt{\frac{k}{m}}$ from Newton's second law, and verify it numerically in NumPy.
*   **C0.1: Functions as Machines (Math &middot; Calculus &middot; Pre-Calculus Bridge)**
    *   *Path:* `lesson.html?lesson=lessons/math/calculus/precalculus/01-functions-as-machines.json`
    *   *Concept:* Interactive compositions, decompositions, and inversions of function machines. Serves as the conceptual foundation for the chain rule.
*   **B1: The Unknown Planet (Math &middot; Bayesian Statistics)**
    *   *Path:* `lesson.html?lesson=lessons/math/bayesian-statistics/01-the-unknown-planet.json`
    *   *Concept:* Discover Bayesian inference, learn how beliefs sharpen following a $1/\sqrt{N}$ law of uncertainty, and derive Bayes' theorem.
*   **L-LOOP: How High to Start? (Physics &middot; Mechanics)**
    *   *Path:* `lesson.html?lesson=lessons/physics/oscillations/02-loop-the-loop.json`
    *   *Concept:* Combine energy conservation with centripetal force constraints to derive the minimum drop height ($2.5R$) for a loop-the-loop.

### 2. Hand Derivation Playground
*   *Path:* `playground.html`
*   *Concept:* A standalone equation sandbox allowing students to practice deriving mathematical and physical identities on a freeform canvas. Includes a library of **15+ classic equations** across algebra, calculus, physics, and statistics, complete with progressive hints.

---

## Technical Stack

*   **Frontend Core:** Vanilla JS, no heavy frontend frameworks. High-performance HTML5 Canvas with smooth low-latency pointer events for pencil/stylus/touch writing.
*   **Math Rendering:** KaTeX for fast, lightweight LaTeX typesetting.
*   **Code Editor:** CodeMirror for editing Python numerical scripts directly in the browser.
*   **Real-time Handwriting Transcription (VLM):** Supports vision-language model integration (LM Studio for local models like `qwen2-vl-7b-instruct`, or CloudRouter API keys for cloud models) to transcribe handwritten mathematics on the canvas into LaTeX in real-time.
*   **Symbolic Mathematics Engine:** **SymPy** running inside **Pyodide (WebAssembly Python)** completely client-side. Evaluates algebraic and calculus equivalence of derivations at a line-by-line level.
*   **Performance Optimization:** Lazy-loads Pyodide and defers Google Identity Services (GIS) auth script loading to remain entirely **bfcache-friendly** (avoiding costly Python/SymPy reload overhead during back/forward navigation).

---

## Run Locally

Since this is a static vanilla JS site, you can host it using any simple local HTTP server:

```bash
python3 -m http.server 8765
```

Then open [http://localhost:8765](http://localhost:8765) in your web browser.

### Adding Lessons
Lessons are authored as structured JSON files inside `lessons/`. You can load a custom lesson by passing it as a query parameter:
`http://localhost:8765/lesson.html?lesson=lessons/physics/oscillations/01-single-spring.json`

---

## Derivation Distillation

The `derivations/` pipeline is offline research infrastructure for turning unreliable generated derivations into verified curriculum artifacts and labeled failure data.

It fits the project by keeping student-facing verification deterministic while using LLMs only as proposal engines. Accepted graphs can become lesson material; rejected graphs become evidence for better rules, prompts, and validators.

```bash
scripts/distill.sh frontier
scripts/distill.sh jobs --limit 10
scripts/distill.sh summarize-batch <batch_id>
```

See `derivations/README.md` for the problem statement and current blockers, and `derivations/DISTILLATION.md` for the pipeline contract.
