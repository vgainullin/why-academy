# Why Academy — Calculus Course: Lesson Plan for Claude Code

## Scope

Pre-calculus bridge → Single-variable calculus → Multivariable calculus → Differential equations.
Enough to support the Entropy of Everything physics path through quantum mechanics.
Student has solid algebra. Every lesson uses the PDCR cycle (Predict → Derive → Compare → Reconcile).

## Implementation Rules for Claude Code

### Lesson Structure Rules
1. Every lesson follows the **PDCR cycle** defined in why-academy-brief.md: Explore → Predict → Discover → Explain → Derive → Compare → Reconcile → Code → Vary → Connect
2. Every lesson starts with an **EXPLORE phase** (interactive simulation, no equations)
3. Every **PREDICT phase** requires: 
   - Direction (faster/slower/same)
   - Magnitude in **scientific notation**
   - Confidence (just guessing/rough idea/pretty sure)
   - Locked, non-retractable submission
4. Every lesson must include **COMPARE phase** (prediction vs derivation gap analysis)
5. Every lesson must include **RECONCILE phase** (handwritten reflection in student's own words)

### Content Generation Rules
6. Every derivation step needs: starting equation, target equation, valid operation sequence, SymPy verification spec
7. Every prediction prompt needs: 3-5 precomputed error patterns with diagnosis and "build on what's right" feedback
8. Every lesson ends with a CONNECT phase linking to a physics application or surprise domain
9. Every lesson includes a CODE block verifying the derivation numerically in pure NumPy
10. Dimensional analysis check required on every result that has physical units

### Platform Integration Rules
11. Interleave review problems from previous lessons into practice sections (interleaving d = 0.79 effect)
12. **Handwriting canvas** is the primary input. Structured blocks as fallback.
13. All verification is SymPy. No AI grading at runtime.
14. All simulations must be interactive and run client-side (Canvas/WebGL + Pyodide)
15. Scientific notation integration required in all prediction phases

---

## Phase-Based Lesson Structure

### Required Phases (in order):
```
PHASE                | DESCRIPTION                                      | BLOCK TYPES
---------------------------------------------------------------------------------------------------
EXPLORE              | Interactive simulation, no equations              | interactive_simulation
PREDICT              | Locked prediction with scientific notation        | predict (locked)
DISCOVER             | Pattern finding from exploration data            | read + calculate + data_table
EXPLAIN              | Formal explanation after discovery               | read
DERIVE               | Stepwise proof on handwriting canvas             | derive
COMPARE              | Prediction vs derivation gap analysis            | compare
RECONCILE            | Handwritten reflection in student's own words    | reconcile
CODE                 | NumPy implementation and verification            | code
VARY                 | Practice with varied parameters                   | practice (varied_params)
CONNECT              | Surprise link to other domains                   | connect
```

### Phase Requirements:

#### EXPLORE Phase:
- **Interactive simulation** (HTML Canvas/WebGL)
- **No equations or formulas** displayed initially
- **Direct manipulation**: sliders, draggable objects
- **Data collection** for DISCOVER phase
- **Physics hook** relevant to lesson concept

#### PREDICT Phase:
- **Three locked components**:
  1. **Direction**: faster/slower/same (qualitative)
  2. **Magnitude**: numerical estimate in **scientific notation**
  3. **Confidence**: just guessing/rough idea/pretty sure
- **Non-retractable**: Once submitted, cannot be changed
- **Timestamped** for accuracy tracking

#### DISCOVER Phase:
- **Organize exploration data** into tables
- **Pattern identification prompts**: "What do you notice?"
- **Data transformation** (e.g., compute k/m, √(k/m))
- **Student writes observations** on handwriting canvas

#### DERIVE Phase:
- **Handwriting canvas** as primary input
- **Real-time recognition**: VLM → LaTeX → KaTeX rendering
- **SymPy verification**: Green/orange dots per line
- **Stepwise validation**: Starting equation → target equation with operation sequence

#### COMPARE Phase:
- **Side-by-side display**: Prediction vs derivation
- **Gap analysis**: Direction correct? Magnitude correct? Error ratio?
- **Diagnostic feedback**: From precomputed error patterns
- **Reference back**: To simulation, data table, or derivation

#### RECONCILE Phase:
- **Handwritten reflection**: "In your own words, why were you right/wrong?"
- **Not graded**: Required but not evaluated for correctness
- **Stored for review**: For spaced repetition and misconception tracking

#### CODE Phase:
- **Pure NumPy implementation** (no frameworks hiding math)
- **Numerical verification** of algebraic derivation
- **Plotting** on canvas alongside derivation
- **Error analysis**: numerical vs analytical comparison

#### VARY Phase:
- **New parameters**, same concept
- **Prediction accuracy tracking** across variations
- **Confidence calibration** visible to student
- **Interleaving** with previous lesson concepts

#### CONNECT Phase:
- **Surprise domain connection** (unexpected application)
- **Bridge to next lesson**
- **"Wikipedia link energy"**: generates more questions than answers
- **No completion screens** – tension over resolution

---

## Module 0: Pre-Calculus Bridge (2 lessons)

### Lesson 0.1: Functions as Machines

**Physics hook:** A spring's position depends on time. A temperature depends on altitude. These are functions — input/output machines.

**PHASE 1: EXPLORE**
- **Interactive function machine simulation**: Input slot, output slot, function selector
- **Student feeds numbers**, sees outputs
- **Sliders for function parameters**: stretch, shift, compose
- **Discover visually**: composition creates nested machines, inverse runs backwards
- **No equations**: Pure discovery through interaction

**PHASE 2: PREDICT**
- **Prediction prompt**: "If f(x) = x² and g(x) = x+3, predict f(g(5)) and g(f(5)). Are they the same?"
- **Locked predictions**: 
  - Direction: faster/slower/same (qualitative)
  - Magnitude: in scientific notation (e.g., 6.4e1 vs 2.8e1)
  - Confidence: just guessing/rough idea/pretty sure
- **Non-retractable**: Once submitted, cannot be changed

**PHASE 3: DISCOVER**
- **Data table from exploration**: x, f(x), g(x), f(g(x)), g(f(x))
- **Pattern identification**: "What do you notice about f(g(x)) vs g(f(x))?"
- **Student writes observations** on handwriting canvas
- **Data transformation**: Compute differences, ratios

**PHASE 4: EXPLAIN**
- **Formal definition**: Function as process (input → rule → output)
- **Domain, range**: Input/output sets
- **Composition**: f(g(x)) — "nested machine"
- **Decomposition**: Given h(x) = sin(x²), identify outer=sin, inner=x²
- **Inverse functions**: Running the machine backwards

**PHASE 5: DERIVE**
- **On handwriting canvas**: Expand (x+3)² step by step
- **SymPy verification**: Each algebraic manipulation verified
- **Compare with g(f(x))**: x² + 3 derivation
- **Operation sequence**: Starting equation → target equation

**PHASE 6: COMPARE**
- **Side-by-side display**: Prediction vs derivation
- **Gap analysis**: "You predicted f(g(5)) = g(f(5)) = ?"
- **Error pattern feedback**: From precomputed patterns
- **Reference back**: To simulation or data table

**PHASE 7: RECONCILE**
- **Handwritten reflection**: "In your own words: why does f(g(x)) ≠ g(f(x))?"
- **Not graded**: Required but not evaluated
- **Stored for review**: For spaced repetition

**PHASE 8: CODE**
- **Implement compose(f, g, x)** in Python
- **Verify f(g(x)) ≠ g(f(x))** for 100 random x values
- **Numerical verification**: Compare with analytical results

**PHASE 9: VARY**
- **New functions**: f(x)=sin(x), g(x)=x²
- **Predict**: f(g(π/2)), g(f(π/2))
- **Track prediction accuracy**: Improvement across variations
- **Confidence calibration**: Visible to student

**PHASE 10: CONNECT**
- **Chain rule**: "d/dx[f(g(x))] = f'(g(x))·g'(x)"
- **Backpropagation**: "Neural networks use composition"
- **Link to Lesson 1.5**: Chain Rule
- **Surprise connection**: "Same math trains GPT"

**Error Pattern Templates:**
```json
{
  "problem_id": "L0-1-P1",
  "context": "Predict f(g(5)) for f(x)=x², g(x)=x+3",
  "correct_answer": 64,
  "error_patterns": [
    {
      "answer_range": [40, 49],
      "partial_credit": ["correct_variable", "correct_direction"],
      "misconception": "composition_is_multiplication",
      "feedback": "Good — you identified both functions correctly. But composition f(g(5)) means apply g first, then f — not multiply f(5) × g(5).",
      "redirect": "simulation",
      "severity": "moderate"
    },
    {
      "answer_range": [28, 30],
      "partial_credit": ["correct_order"],
      "misconception": "commutativity_assumption",
      "feedback": "You computed g(f(5)) instead of f(g(5)). Good — you applied the functions in the correct order. But the problem asks for f∘g, not g∘f.",
      "redirect": "derivation",
      "severity": "mild"
    }
  ]
}
```

**SymPy verification spec:**
```python
from sympy import symbols, Function, simplify
x = symbols('x')
# Verify student's decomposition: outer(inner(x)) == original(x)
assert simplify(outer.subs(x, inner) - original) == 0
```

---

### Lesson 0.2: Rates of Change (Pre-Derivative Intuition)

**Physics hook:** You're driving. Speedometer reads 60 mph. What does that number actually mean?

**PHASE 1: EXPLORE**
- **Interactive car simulation**: Position vs time graph
- **Student drags points**: See secant line slope change
- **As second point gets closer**: Secant approaches tangent
- **Visual discovery**: Slope represents rate of change
- **No formulas**: Pure graphical intuition

**PHASE 2: PREDICT**
- **Prediction prompt**: "A ball is thrown up. At the very top, what is its velocity? What is its acceleration?"
- **Locked predictions**: 
  - Direction: faster/slower/same
  - Magnitude: in scientific notation (e.g., 0 m/s, 9.8e0 m/s²)
  - Confidence: just guessing/rough idea/pretty sure
- **Common misconception**: velocity=0 → acceleration=0

**PHASE 3: DISCOVER**
- **Data table from simulation**: t, position, secant slopes
- **Pattern identification**: "How does secant slope change as points get closer?"
- **Student writes observations**: On handwriting canvas
- **Data transformation**: Compute average velocities for shrinking Δt

**PHASE 4: EXPLAIN**
- **Average rate of change**: Slope of secant = Δy/Δx
- **Instantaneous rate of change**: Slope of tangent = limit of secant slopes
- **Slope of position-time graph**: Velocity
- **Slope of velocity-time graph**: Acceleration

**PHASE 5: DERIVE**
- **From position table**: Compute average velocities over shrinking intervals
- **On handwriting canvas**: Calculate Δy/Δx for Δt = 0.1, 0.01, 0.001
- **SymPy verification**: Each calculation verified
- **Observe convergence**: Values approach instantaneous velocity

**PHASE 6: COMPARE**
- **Side-by-side display**: Prediction vs derivation
- **Gap analysis**: "You predicted acceleration=0 at top. Why?"
- **Error pattern feedback**: "Good — velocity IS zero at top. But acceleration isn't velocity."
- **Reference back**: To simulation graph

**PHASE 7: RECONCILE**
- **Handwritten reflection**: "In your own words: why is acceleration not zero at top?"
- **Not graded**: Required but not evaluated
- **Stored for review**: For misconception tracking

**PHASE 8: CODE**
- **Given position data array**: Compute finite difference velocities
- **For decreasing Δt**: 0.1, 0.01, 0.001, 0.0001
- **Plot convergence**: Observe approach to instantaneous velocity
- **Numerical verification**: Compare with analytical derivative

**PHASE 9: VARY**
- **New motion**: Parabolic trajectory x(t) = t²
- **Predict**: Velocity at t=2, acceleration at t=2
- **Track prediction accuracy**: Improvement across variations
- **Confidence calibration**: Visible graph of accuracy over time

**PHASE 10: CONNECT**
- **Derivative intuition**: "You just computed a derivative by hand"
- **Link to Lesson 1.1**: The Limit (formal definition)
- **Surprise connection**: "Same math used in stock price analysis"
- **No completion screen**: "Next: formalizing this as the limit"

**Error Pattern Templates:**
```json
{
  "problem_id": "L0-2-P1",
  "context": "Predict acceleration at top of ball's trajectory",
  "correct_answer": 9.8,
  "error_patterns": [
    {
      "answer_range": [0, 0.1],
      "partial_credit": ["correct_velocity"],
      "misconception": "acceleration_is_velocity",
      "feedback": "Good — velocity IS zero at the top. But acceleration isn't velocity. Is gravity turned off at the top?",
      "redirect": "simulation",
      "severity": "significant"
    },
    {
      "answer_range": [4.9, 5.1],
      "partial_credit": ["correct_direction"],
      "misconception": "half_acceleration",
      "feedback": "You correctly identified that acceleration is downward. But gravity doesn't halve at the top — it's constant.",
      "redirect": "data_table",
      "severity": "moderate"
    }
  ]
}
```

---

## Module 1: Limits and Derivatives (6 lessons)

### Lesson 1.1: The Limit

**Physics hook:** The speedometer doesn't wait for you to travel a distance. It gives your speed RIGHT NOW. How?

**EXPLORE:** Interactive graph of f(x) = sin(x)/x. Student drags x toward 0. The function value approaches... what? Student types guess. Plot zooms in.

**Core content:**
- Informal limit definition: "the value f(x) approaches as x approaches a"
- One-sided limits
- Limits that don't exist (oscillation, unbounded)
- Key limits: sin(x)/x → 1, (1-cos(x))/x → 0, (eˣ-1)/x → 1

**PREDICT:** "What is the limit of (x²-1)/(x-1) as x→1? Plug in x=1 and see what happens. Then predict."

**DERIVE:** Factor, cancel, evaluate. Verify with a table of values approaching from both sides.

**Error patterns:**
- Student says "undefined" because direct substitution gives 0/0 → "Right that 0/0 is undefined. But the limit isn't about the value AT x=1. It's about what happens NEAR x=1. Try x=0.999."
- Student says the limit is 0 because the numerator is 0 → "The numerator IS zero at x=1, but so is the denominator. That's why we need limits — 0/0 doesn't have a value, but the ratio approaches one."

**CODE:** Compute f(x) for x = [0.9, 0.99, 0.999, 0.9999, 1.0001, 1.001, 1.01, 1.1]. Print table. Observe convergence.

**CONNECT:** "This 0/0 situation is exactly what happens when you try to compute instantaneous velocity: Δx/Δt as both go to zero. Limits resolve this."

**SymPy verification spec:**
```python
from sympy import limit, Symbol, sin, oo
x = Symbol('x')
# Verify student's limit computation
assert limit(student_expr, x, a) == expected_value
```

---

### Lesson 1.2: The Derivative from First Principles

**Physics hook:** Back to the spring from lesson L1. We know x(t) = A·cos(ωt). What is the velocity at any moment?

**EXPLORE:** Spring simulation with position AND velocity displayed. Student observes: velocity is zero when position is maximum. Velocity is maximum when position is zero. They're shifted copies of each other.

**Core content:**
- Definition: f'(x) = lim_{h→0} [f(x+h) - f(x)] / h
- Compute derivative of f(x) = x² from definition (expand, cancel, take limit)
- Compute derivative of f(x) = x³ from definition
- The power rule pattern emerges from the data

**PREDICT:** "You just found that d/dx(x²) = 2x and d/dx(x³) = 3x². Predict d/dx(x⁴)."

**DERIVE:** Expand (x+h)⁴ using binomial theorem. Show that the h→0 limit kills everything except 4x³. The pattern: d/dx(xⁿ) = nxⁿ⁻¹.

**Error patterns:**
- Student predicts 4x⁴ (exponent doesn't decrease) → "You got the coefficient right — the exponent comes down as a multiplier. But look at x² → 2x¹ and x³ → 3x². The exponent also drops by 1."
- Student predicts 4x² (right answer but can't explain why) → "Correct! Now prove it from the definition. Expand (x+h)⁴ and take the limit."

**CODE:** Implement numerical_derivative(f, x, h) using finite differences. Test against analytical derivative for f(x) = x⁴. Plot both. Show error decreases as h decreases.

**CONNECT:** "You derived the power rule from the limit definition. You'll never need to re-derive it — but because you CAN, you'll never permanently forget it. And the same technique works for every function."

---

### Lesson 1.3: Derivative Rules (Product, Quotient, Chain)

**Physics hook:** Momentum = mass × velocity. If both mass and velocity change (like a rocket burning fuel), what's the rate of change of momentum?

**EXPLORE:** Rocket simulation. Mass decreases (fuel burning), velocity increases (thrust). Momentum = m·v. Student predicts: is d(mv)/dt = (dm/dt)·v or m·(dv/dt) or both?

**Core content:**
- Product rule: d/dx[f·g] = f'·g + f·g' — derived from limit definition
- Quotient rule: derived from product rule + chain rule (or directly)
- **Chain rule** (CRITICAL — gets its own sub-lesson):
  - Teach INSIDE-OUT: d/dx[f(g(x))] = g'(x) · f'(g(x))
  - Start with physical reasoning: if y depends on u depends on x, rates multiply
  - Decompose before differentiating: identify inner and outer functions first
  - Practice decomposition extensively before any differentiation

**PREDICT for chain rule:** "f(x) = (3x+1)⁵. Predict: will the derivative have x⁴ in it, or (3x+1)⁴, or both?"

**Error patterns for chain rule:**
- Student forgets inner derivative: d/dx(sin(3x)) = cos(3x) → "You got the outer derivative right — cos is the derivative of sin. But the input to sin is changing too. How fast is 3x changing?"
- Student applies power rule without chain rule: d/dx(3x+1)⁵ = 5(3x+1)⁴ → "Close! You handled the outer function correctly. But what about the inner function 3x+1? Its derivative is 3, and that needs to multiply in."

**DERIVE:** Product rule from the limit definition. The key step: adding and subtracting f(x+h)g(x) to split the expression. Student does this on canvas, SymPy verifies each line.

**CODE:** Implement product_rule(f, g, x, h) numerically. Verify against SymPy's analytical derivative for f(x)=x², g(x)=sin(x).

**CONNECT:** "Backpropagation — how neural networks learn — is just the chain rule applied hundreds of times. You just learned the algorithm that trains GPT."

---

### Lesson 1.4: Derivatives of Transcendental Functions

**Physics hook:** Radioactive decay: N(t) = N₀·e^{-λt}. How fast are atoms decaying at time t?

**EXPLORE:** Exponential decay simulation. Slider for λ. Student observes: the rate of decay is proportional to how much remains. The function IS its own derivative (up to a constant).

**Core content:**
- d/dx(eˣ) = eˣ — derived from the limit definition using lim(eʰ-1)/h = 1
- d/dx(aˣ) = aˣ·ln(a)
- d/dx(ln x) = 1/x — derived from inverse function theorem
- d/dx(sin x) = cos x — derived from limit definition using sin(x)/x → 1
- d/dx(cos x) = -sin x

**PREDICT:** "e^x is its own derivative. What about 2^x? Will its derivative be 2^x, more than 2^x, or less?"

**DERIVE:** d/dx(eˣ) from the limit definition. Student expands [e^(x+h) - eˣ]/h = eˣ · (eʰ - 1)/h. The limit reduces to eˣ · 1 = eˣ.

**CODE:** Numerically verify d/dx(eˣ) = eˣ at 100 points. Plot function and derivative on same axes — they're identical.

**CONNECT:** "The exponential is the eigenfunction of the derivative operator. When you solve differential equations in the Entropy of Everything project, you'll assume exponential solutions — and now you know why."

---

### Lesson 1.5: Implicit Differentiation and Related Rates

**Physics hook:** A ladder slides down a wall. The top descends at 2 m/s. How fast is the bottom sliding out when the ladder makes a 60° angle?

**EXPLORE:** Ladder simulation. Student drags the top down. The bottom slides out. Speed is NOT constant — it accelerates. Student predicts the speed at various angles.

**Core content:**
- Implicit differentiation: differentiate both sides of x² + y² = L², treating y as a function of x
- Related rates: connect dx/dt, dy/dt via implicit differentiation with respect to t
- Applications: ladder problems, expanding sphere, shadow length

**DERIVE:** From x² + y² = L², differentiate implicitly to get 2x·dx/dt + 2y·dy/dt = 0. Solve for dx/dt. Student does each step on canvas.

**CODE:** Simulate the ladder. At each timestep, compute dx/dt from the formula and from finite differences. They match.

---

### Lesson 1.6: Partial Derivatives (Bridge to Multivariable)

**Physics hook:** Temperature in a room depends on position (x, y, z) AND time. How fast does temperature change if you walk east? If you stand still and wait?

**EXPLORE:** Heat map simulation. Student moves a point, sees temperature change. Slider for time. ∂T/∂x ≠ ∂T/∂t — different rates for different directions.

**Core content:**
- Partial derivative: differentiate with respect to one variable, treating others as constants
- ∂f/∂x, ∂f/∂y notation
- Gradient vector: ∇f = (∂f/∂x, ∂f/∂y) points in the direction of steepest ascent
- Connection to total derivative: df = (∂f/∂x)dx + (∂f/∂y)dy

**PREDICT:** "f(x,y) = x²y. Predict ∂f/∂x. Hint: treat y as a constant."

**DERIVE:** Compute ∂f/∂x and ∂f/∂y for f(x,y) = x²y + sin(xy). Each step verified by SymPy.

**CODE:** Compute numerical partial derivatives using finite differences in 2D. Plot gradient field.

**CONNECT:** "The gradient is the key to optimization — it tells you which way to go to increase a function fastest. It's also how gradient descent trains machine learning models."

---

## Module 2: Integration (5 lessons)

### Lesson 2.1: Integration as Accumulation

**CRITICAL DESIGN NOTE:** Teach integration as accumulation FIRST, not as antidifferentiation. This is the most evidence-backed pedagogical choice in the research.

**Physics hook:** You have a velocity-time graph. How far did you travel?

**EXPLORE:** Car dashboard simulation. Velocity graph (not constant). Student estimates distance by eyeballing. Then: partition into rectangles (Riemann sum). Slider for number of rectangles. As n increases, the approximation improves.

**Core content:**
- Distance = sum of velocity × time for each small interval
- Riemann sums: left, right, midpoint, trapezoidal
- As Δt → 0, the sum becomes the integral: ∫v(t)dt
- The integral is a NUMBER (definite) or a FUNCTION (indefinite)

**PREDICT:** "v(t) = 2t (constant acceleration from rest). After 5 seconds, is the distance exactly 25m, more, or less?"

**DERIVE:** Compute left Riemann sum for v(t) = 2t on [0,5] with n = 5, then n = 10. Student sees convergence to 25.

**CODE:** Implement riemann_sum(f, a, b, n, method='left'). Compare left, right, midpoint, trapezoidal for v=2t. All converge to 25.

**CONNECT:** "You just computed an integral by adding up small pieces. The entire field of numerical analysis is about doing this efficiently for functions where we can't find a formula."

---

### Lesson 2.2: The Fundamental Theorem of Calculus

**Physics hook:** You have velocity v(t). You compute distance by summing up v·Δt. But distance is also the antiderivative of velocity: if d/dt[s(t)] = v(t), then s(t) = ∫v(t)dt. Why are these the same?

**EXPLORE:** Accumulation function simulator. Student sees A(x) = ∫₀ˣ f(t)dt plotted in real time as x moves. When f is positive, A increases. When f is negative, A decreases. The rate of increase of A IS f. That's the FTC.

**Core content:**
- FTC Part 1: d/dx ∫₀ˣ f(t)dt = f(x) — the derivative of the accumulation function is the original function
- FTC Part 2: ∫ₐᵇ f(x)dx = F(b) - F(a) where F' = f
- Why this is profound: accumulation (adding up) and rate of change (derivatives) are inverse operations
- This is NOT a tautology — it connects two independently defined concepts

**PREDICT:** "If f(x) = 3x², predict ∫₀² 3x² dx. Hint: what function has derivative 3x²?"

**Error patterns:**
- Student can find the antiderivative but forgets to evaluate at bounds → "You found F(x) = x³. But the definite integral needs F(b) - F(a), not just F(x)."
- Student confuses the variable of integration with the bound → "The t in ∫₀ˣ f(t)dt is a dummy variable — it disappears after integration. The result is a function of x, not t."

**DERIVE:** Prove FTC Part 1 from the definition of the derivative: d/dx[A(x)] = lim_{h→0} [A(x+h) - A(x)]/h = lim_{h→0} [∫₀^{x+h} f(t)dt - ∫₀ˣ f(t)dt]/h = lim_{h→0} ∫ₓ^{x+h} f(t)dt / h ≈ f(x).

**CODE:** Compute accumulation function numerically (cumulative sum of f·Δx). Take numerical derivative of the result. Compare to original f. They match — FTC verified computationally.

**CONNECT:** "The FTC says that the two operations you've been learning — differentiation and integration — undo each other. This is the deepest single theorem in calculus."

---

### Lesson 2.3: Integration Techniques — Substitution

**Physics hook:** ∫cos(3x)dx. You know ∫cos(u)du = sin(u). But the input to cos is 3x, not x. This is the chain rule running backwards.

**Core content:**
- u-substitution: the reverse chain rule
- Pattern: ∫f(g(x))·g'(x)dx = ∫f(u)du where u = g(x)
- Finding the substitution: identify the inner function and check if its derivative is present

**DERIVE:** u = 3x, du = 3dx, dx = du/3. So ∫cos(3x)dx = (1/3)∫cos(u)du = (1/3)sin(u) + C = (1/3)sin(3x) + C. Verify: d/dx[(1/3)sin(3x)] = (1/3)·cos(3x)·3 = cos(3x). ✓

**CODE:** Numerical integration of cos(3x) on [0, π]. Compare with (1/3)sin(3x) evaluated at bounds.

---

### Lesson 2.4: Integration Techniques — By Parts

**Physics hook:** ∫x·eˣ dx. Neither factor integrates to anything simpler. But if you differentiate x, it simplifies (to 1). If you integrate eˣ, it stays the same.

**Core content:**
- Integration by parts: ∫u dv = uv - ∫v du
- LIATE rule for choosing u: Logs → Inverse trig → Algebraic → Trig → Exponentials
- Tabular integration for repeated application

**DERIVE:** From the product rule: d/dx[uv] = u'v + uv'. Integrate both sides: uv = ∫u'v dx + ∫uv' dx. Rearrange: ∫uv' dx = uv - ∫u'v dx.

---

### Lesson 2.5: Numerical Integration as Understanding

**Physics hook:** Most integrals in real physics don't have closed forms. How do you compute ∫₀¹ e^{-x²} dx?

**Core content:**
- Trapezoidal rule derivation and error analysis
- Simpson's rule from fitting parabolas
- Convergence: how error decreases with n
- When numerical beats analytical (and when it doesn't)

**CODE:** Implement trapezoidal_rule(f, a, b, n) and simpsons_rule(f, a, b, n). Compare convergence rates. Apply to e^{-x²} (the Gaussian integral that appears everywhere in physics).

**CONNECT:** "This Gaussian integral is the foundation of statistical mechanics, quantum mechanics, and error analysis. You'll use it in every phase of the Entropy of Everything project."

---

## Module 3: Multivariable Calculus (4 lessons)

### Lesson 3.1: Gradient, Divergence, Curl — Geometry First

**CRITICAL DESIGN NOTE:** Define these operators geometrically via integral limits FIRST, then derive coordinate expressions. NOT the other way around.

**EXPLORE:** 3D vector field visualization. Student sees arrows. Questions: "Is fluid flowing outward or inward at this point? Is it rotating?"

**Core content:**
- Gradient: direction and magnitude of steepest ascent of a scalar field
- Divergence: net outflow per unit volume (define via flux through shrinking surface)
- Curl: circulation per unit area (define via line integral around shrinking loop)
- Coordinate expressions derived FROM geometric definitions

**CODE:** Compute numerical divergence and curl from their integral definitions (flux and circulation). Verify they match the analytical formulas (∂Fx/∂x + ∂Fy/∂y, etc.).

---

### Lesson 3.2: Line and Surface Integrals

### Lesson 3.3: Green's, Stokes', Divergence Theorems

**Key insight to convey:** These are all the SAME theorem — the generalized Stokes' theorem ∫_M dω = ∫_{∂M} ω. Interior contributions cancel, leaving only the boundary. One theorem, three special cases.

### Lesson 3.4: Coordinate Systems (Cylindrical, Spherical)

**Physics hook:** Gravity, electric fields, and wavefunctions are spherically symmetric. Cartesian coordinates make these ugly. Spherical coordinates make them natural.

---

## Module 4: Differential Equations (5 lessons)

### Lesson 4.1: First-Order ODEs (Separation of Variables)

**Physics hook:** Radioactive decay: dN/dt = -λN. The rate of decay is proportional to how much remains.

### Lesson 4.2: Second-Order Constant-Coefficient ODEs

**Physics hook:** The harmonic oscillator from the springs lessons. mẍ + bẋ + kx = 0. Damped, undamped, driven.

**CONNECT to springs lessons:** "You already solved mẍ = -kx in lesson L1. Now we add friction (damping) and external forces (driving). The characteristic equation is the tool."

### Lesson 4.3: Systems of ODEs and Eigenvalue Methods

**Physics hook:** Coupled oscillators from lesson L2. N masses, N coupled equations. Write as matrix equation. Eigenvalues ARE the normal mode frequencies.

**This lesson directly bridges to Phase 3 of Entropy of Everything (spectral methods/eigendecomposition).**

### Lesson 4.4: Fourier Series and Transforms

**Physics hook:** Any periodic function can be decomposed into sines and cosines. This is how we solve the heat equation, the wave equation, and eventually quantum mechanics.

### Lesson 4.5: PDEs — Heat, Wave, Laplace

**Physics hook:** Three equations that describe most of classical physics: heat flow (diffusion), waves (propagation), equilibrium (Laplace). Solve by separation of variables + Fourier series.

**This lesson directly feeds Phase 4 of Entropy of Everything (field equations).**

---

## Cross-Cutting Implementation Requirements

### Spaced Repetition Integration

Derivative rules (power, product, quotient, chain) must resurface in EVERY subsequent lesson as warm-up exercises with randomized functions. The system generates: "Differentiate f(x) = [random composed function]" and the student works it on canvas. SymPy verifies.

Integration techniques similarly resurface during DE lessons. When a student encounters ∫xe^x dx in the context of a DE, the system should recognize this as a by-parts opportunity and reference back to lesson 2.4 if the student is stuck.

### Dimensional Analysis

Every lesson with physical quantities must include a dimensional analysis verification step. After deriving a formula, the student verifies the dimensions match the expected units. SymPy can check this if units are tracked.

### Worked Example Fading

First encounter with a concept: full worked derivation with explanations at every step.
Second encounter (review): some steps blanked out, student fills them in.
Third encounter: only starting and ending equations given, student reconstructs the full derivation.
This is Renkl's fading principle, implemented through the spaced repetition system.

### Error Pattern Templates

For EVERY prediction prompt and derivation step, Claude Code must generate comprehensive error pattern templates:

```json
{
  "problem_id": "L0-1-P1",
  "context": "Predict f(g(5)) for f(x)=x², g(x)=x+3",
  "correct_answer": 64,
  "error_patterns": [
    {
      "answer_range": [40, 49],
      "partial_credit": ["correct_variable", "correct_direction"],
      "misconception": "composition_is_multiplication",
      "feedback": "Good — you identified both functions correctly. But composition f(g(5)) means apply g first, then f — not multiply f(5) × g(5).",
      "redirect": "simulation",
      "severity": "moderate"
    },
    {
      "answer_range": [28, 30],
      "partial_credit": ["correct_order"],
      "misconception": "commutativity_assumption",
      "feedback": "You computed g(f(5)) instead of f(g(5)). Good — you applied the functions in the correct order. But the problem asks for f∘g, not g∘f.",
      "redirect": "derivation",
      "severity": "mild"
    },
    {
      "answer_range": [70, 80],
      "partial_credit": ["correct_concept"],
      "misconception": "magnitude_overestimate",
      "feedback": "You correctly identified that f(g(5)) should be larger than f(5)=25. But check your calculation: g(5)=8, then f(8)=64.",
      "redirect": "data_table",
      "severity": "mild"
    }
  ]
}
```

**Error Pattern Requirements:**

1. **3-5 patterns per prediction**: Identify most common wrong answers
2. **Answer ranges**: Numeric intervals covering plausible wrong answers
3. **Partial credit**: List what student got right ("build on what's right")
4. **Named misconceptions**: Standardized names (e.g., "composition_is_multiplication")
5. **Feedback structure**: "Good — you knew X. But notice Y."
6. **Redirect options**: simulation | data_table | derivation | previous_lesson
7. **Severity levels**: mild | moderate | significant (for spaced repetition weighting)
8. **Misconception tracking**: Frequency tracked across problems for targeted remediation

**Feedback Principles:**

1. **Always build on what's right first**: "Good — you knew X" before "But notice Y"
2. **Never just give the answer**: Point student back to their own data/simulation/derivation
3. **Reference student's specific reasoning**: Not generic explanations
4. **Redirect appropriately**: 
   - Direction errors → simulation
   - Magnitude errors → data table
   - Algebraic errors → derivation
5. **Track misconceptions**: If named misconception appears 3+ times, generate targeted mini-lesson

### Handwriting Canvas Workflow

**Handwriting → Recognition → Verification Pipeline:**

```
Handwriting → Recognition → Verification → Feedback
----------------------------------------------------------------
1. Student writes on canvas (graph paper background, <50ms latency)
2. VLM recognizes handwriting → converts to LaTeX
3. Clean KaTeX version appears alongside handwriting
4. SymPy verifies algebraic correctness
5. System shows green/orange dot per line
6. Diagnostic feedback appears in margins (from error patterns)
```

**Canvas Requirements:**

1. **Feels like paper**: Low latency (<50ms pen-to-ink), smooth strokes, graph paper background
2. **Multi-input**: Apple Pencil, Wacom stylus, finger, mouse
3. **Real-time recognition**: VLM converts handwriting to LaTeX as student writes
4. **Non-destructive**: Handwriting preserved alongside recognized/rendered version
5. **Scrollable history**: All work accumulates on canvas
6. **System annotations**: Verification dots (green/orange), diagnostic feedback appear in distinct color in margins

**Fallback System:**

Until handwriting recognition pipeline is rock-solid, structured derive blocks serve as scaffolding:
- Canvas for freeform work
- Structured blocks for guided derivation when student is stuck or learning new technique

### Scientific Notation Integration

**Every PREDICT phase must include:**

1. **Magnitude in scientific notation**: 1.5e2 instead of 150
2. **Order-of-magnitude gates**: Predictions must be within one order of magnitude
3. **Unit conversion drills**: "Express k = 15000 g/s² in SI scientific notation"
4. **System checks**: Mantissa and exponent separately
5. **Progress tracking**: Prediction vs derivation accuracy for scientific notation

**Implementation:**

- Scientific notation practice woven throughout, not separate module
- Order-of-magnitude validation before proceeding to derivation
- Unit conversion integrated into dimensional analysis

### Interleaving Rules

Once Module 2 begins, practice sections must mix derivative and integral problems (never all one type). Once Module 3 begins, mix in single-variable problems. This is non-negotiable — the research shows d = 0.79 effect on delayed retention.

### Lesson Validation Checklist

**Each lesson must pass these checks:**

- [ ] **PDCR sequence**: Explore→Predict→Discover→Explain→Derive→Compare→Reconcile→Code→Vary→Connect
- [ ] **EXPLORE phase**: Interactive simulation before equations
- [ ] **PREDICT phase**: Locked predictions with scientific notation
- [ ] **COMPARE phase**: Prediction vs derivation gap analysis
- [ ] **RECONCILE phase**: Handwritten reflection in student's own words
- [ ] **Error patterns**: 3-5 precomputed error patterns per prediction
- [ ] **CONNECT phase**: Surprise domain link at end
- [ ] **CODE phase**: NumPy verification of derivation
- [ ] **Dimensional analysis**: For physical quantities
- [ ] **Scientific notation**: In all predictions
- [ ] **Canvas integration**: Handwriting canvas for derivations
- [ ] **Spaced repetition hooks**: Links to previous/future lessons
- [ ] **Physics-first**: Concept introduced through physical motivation

### Physics-First Rule

No calculus concept is introduced without a physical motivation. The concept enters through a physics door, gets formalized mathematically, then returns to physics for verification. This is the PDCR cycle applied at the curriculum level.
