# Why Academy

A free, open-source interactive learning platform that teaches STEM through a **derive-it-yourself** methodology. Students explore interactive simulations, perform stepwise algebraic derivations on a freeform handwriting canvas, estimate answers in scientific notation, implement numerical solutions in Python/NumPy, and explain concepts in their own words. 

Verification is 100% deterministic using SymPy inside the browser. No AI grading, no paywall, near-zero server cost.

🚀 **Live Test Deployment:** [https://why-academy.gainullin.workers.dev/](https://why-academy.gainullin.workers.dev/)

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

### 3. ROOTLOCK
*   *Path:* `rootlock.html`
*   *Concept:* A keyboard-first, endless quadratic puzzle game. Players discover roots through sum-and-product locks, encoded monic quadratics, signed and repeated roots, and discriminant classification.

### 4. Reader
*   *Path:* `reader.html`
*   *Concept:* A PDF reader for papers and textbook chapters, built for iPad and Apple Pencil (the pen writes, fingers scroll and select). Select text or drag a region to highlight, comment, make a flashcard (equations are read into LaTeX by the vision model), queue an "explain this" follow-up, add a todo, or collect a question for journal club. Notes are Markdown plus Pencil ink blocks, linked across papers with `[[Title]]` and to exact passages with `[[@mark]]`; ink converts to LaTeX on demand and SymPy checks each derivation step. The Study view reviews due cards (FSRS) and the explanations waiting to be read. Everything syncs to your passkey account and works offline.

---

## Technical Stack

*   **Frontend Core:** Vanilla JS, no heavy frontend frameworks. High-performance HTML5 Canvas with smooth low-latency pointer events for pencil/stylus/touch writing.
*   **Math Rendering:** KaTeX for fast, lightweight LaTeX typesetting.
*   **Code Editor:** CodeMirror for editing Python numerical scripts directly in the browser.
*   **Real-time Handwriting Transcription (VLM):** Supports vision-language model integration (LM Studio for local models like `qwen2-vl-7b-instruct`, or CloudRouter API keys for cloud models) to transcribe handwritten mathematics on the canvas into LaTeX in real-time.
*   **Symbolic Mathematics Engine:** **SymPy** running inside **Pyodide (WebAssembly Python)** completely client-side. Evaluates algebraic and calculus equivalence of derivations at a line-by-line level.
*   **Performance Optimization:** Lazy-loads Pyodide and uses passkey accounts with no third-party auth script, remaining entirely **bfcache-friendly** (avoiding costly Python/SymPy reload overhead during back/forward navigation).

---

## Run Locally

Since this is a static vanilla JS site, you can host it using any simple local HTTP server:

```bash
python3 -m http.server 8765
```

Then open [http://localhost:8765](http://localhost:8765) in your web browser. Accounts are hidden on a plain static server.

To run with accounts and settings sync (Cloudflare Worker + local D1):

```bash
npm install
npm run db:migrate:local
npm run dev            # http://localhost:8787
```

See [worker/README.md](worker/README.md) for the account model and deployment.

### LLM feature testing

`scripts/feature_test.sh` starts an isolated server (its own D1/R2 state, a seeded account, a fixture paper) and lets a headless Claude test a page in a real browser through Playwright MCP. The tester follows a charter (`.claude/skills/feature-test/charters/<area>.md`), checks results on the server as well as on screen, does an exploratory pass as the charter's persona, and writes a bug list with UX feedback. It has no shell or file tools, only the browser.

```bash
scripts/feature_test.sh --smoke                 # setup check, about $0.30
scripts/feature_test.sh --device ipad           # full reader charter, iPad emulation
OPENROUTER_API_KEY=... scripts/feature_test.sh  # also judges real AI output
```

Reports go to `tests/feature-reports/<run>/` (`report.md`, `findings.json`, `shots/`). In an interactive session, `/feature-test` uses the same method.

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
