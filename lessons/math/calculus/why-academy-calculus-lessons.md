# Why Academy — Calculus Course: Lesson Plan for Claude Code

## Scope

Pre-calculus bridge → Single-variable calculus → Multivariable calculus → Differential equations.
Enough to support the Entropy of Everything physics path through quantum mechanics.
Student has solid algebra. Every lesson uses the PDCR cycle (Predict → Derive → Compare → Reconcile).

## Implementation Rules for Claude Code

1. Every lesson follows the PDCR cycle defined in why-academy-brief.md
2. Every lesson starts with an EXPLORE phase (interactive simulation, no equations)
3. Every derivation step needs: starting equation, target equation, valid operation sequence, SymPy verification spec
4. Every prediction prompt needs: 3-5 precomputed error patterns with diagnosis and "build on what's right" feedback
5. Every lesson ends with a CONNECT phase linking to a physics application or surprise domain
6. Every lesson includes a CODE block verifying the derivation numerically in pure NumPy
7. Dimensional analysis check required on every result that has physical units
8. Interleave review problems from previous lessons into practice sections
9. Handwriting canvas is the primary input. Structured blocks as fallback.
10. All verification is SymPy. No AI grading at runtime.

---

## Module 0: Pre-Calculus Bridge (2 lessons)

### Lesson 0.1: Functions as Machines

**Physics hook:** A spring's position depends on time. A temperature depends on altitude. These are functions — input/output machines.

**EXPLORE:** Interactive function machine. Student feeds in numbers, sees outputs. Slider changes the function. Student discovers: stretching, shifting, composing.

**Core content:**
- Function as process (input → rule → output), not static equation
- Domain, range, composition: f(g(x)) — the "nested machine"
- Decomposition: given h(x) = sin(x²), identify outer = sin, inner = x²
- Inverse functions: running the machine backwards

**PREDICT:** "If f(x) = x² and g(x) = x+3, predict f(g(5)) and g(f(5)). Are they the same?"

**Error patterns:**
- Student computes f(g(5)) = f(5) · g(5) → misconception: composition is multiplication
- Student gets f(g(5)) right but assumes g(f(5)) is the same → misconception: composition commutes

**CODE:** Implement compose(f, g, x) in Python. Verify f(g(x)) ≠ g(f(x)) for 100 random x values.

**CONNECT:** "The chain rule — the hardest part of calculus — is just differentiating a composed function. If you can decompose h(x) into inner and outer, you can do the chain rule. That's lesson 1.5."

**SymPy verification spec:**
```python
from sympy import symbols, Function, compose
x = symbols('x')
# Verify student's decomposition: compose(outer, inner) == original
assert simplify(outer.subs(x, inner) - original) == 0
```

---

### Lesson 0.2: Rates of Change (Pre-Derivative Intuition)

**Physics hook:** You're driving. Speedometer reads 60 mph. What does that number actually mean?

**EXPLORE:** Interactive car simulation. Position vs time graph. Student drags a point, sees the slope of the secant line. As the second point gets closer, the secant approaches the tangent.

**Core content:**
- Average rate of change = slope of secant = Δy/Δx
- Instantaneous rate of change = slope of tangent = limit of secant slopes
- Slope of position-time graph = velocity
- Slope of velocity-time graph = acceleration

**PREDICT:** "A ball is thrown up. At the very top, what is its velocity? What is its acceleration?"
- Common error: velocity = 0 so acceleration = 0 → "Good — velocity IS zero at the top. But acceleration isn't velocity. Is gravity turned off at the top?"

**DERIVE:** From a table of position values, compute average velocities over shrinking intervals. Student sees the values converge. This IS the limit — before we call it that.

**CODE:** Given position data as an array, compute finite difference velocities for decreasing Δt. Plot and observe convergence.

**CONNECT:** "You just computed a derivative by hand. In lesson 1.1, we'll give this process a name and a formula."

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

For EVERY prediction prompt and derivation step, Claude Code must generate:
```json
{
  "correct_answer": "...",
  "error_patterns": [
    {
      "answer_range": [...],
      "partial_credit": ["what student got right"],
      "misconception": "named_misconception",
      "feedback": "Good — you knew X. But notice Y.",
      "redirect": "simulation|data_table|derivation|previous_lesson"
    }
  ]
}
```

### Interleaving Rules

Once Module 2 begins, practice sections must mix derivative and integral problems (never all one type). Once Module 3 begins, mix in single-variable problems. This is non-negotiable — the research shows d = 0.79 effect on delayed retention.

### Physics-First Rule

No calculus concept is introduced without a physical motivation. The concept enters through a physics door, gets formalized mathematically, then returns to physics for verification. This is the PDCR cycle applied at the curriculum level.
