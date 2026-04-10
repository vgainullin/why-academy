# Bayesian Statistics Lesson 1: The Unknown Planet
## Why Academy — Implementation Spec for Build Agent

---

## What this lesson must accomplish

The student has never encountered Bayesian inference. By the end of this lesson, they should have:

1. Discovered through direct manipulation that more data → sharper beliefs, and that the sharpening follows a square root relationship (width ∝ 1/√N) — not a linear one
2. Committed quantitative predictions (in scientific notation) about posterior width and gotten them wrong in a specific, diagnosable way
3. Derived Bayes' theorem from conditional probability (4 steps on the canvas)
4. Derived WHY the width shrinks as 1/√N from the curvature of the log-likelihood (4 steps on the canvas)
5. Verified both derivations numerically in pure NumPy (grid approximation)
6. Written, in their own words, why their prediction was wrong and what the square root relationship means

This lesson is the Bayesian analog of the Single Spring lesson. The square root discovery is the same. The linear-assumption error is the same. The "second derivative explains the square root" structure is the same.

---

## Learning objectives

- Discover through simulation that beliefs sharpen with data, and that the prior matters less as data accumulates
- Predict the posterior width after more data and track prediction accuracy
- Discover the 1/√N width relationship from a self-generated data table before being told the formula
- Derive Bayes' theorem: posterior ∝ likelihood × prior, by hand from conditional probability
- Derive the width formula: SD = √[p̂(1−p̂)/n] from the log-likelihood curvature, by hand
- Verify both derivations numerically in code
- Connect to medical testing (where Bayesian reasoning saves lives)
- Build the magnitude intuition that makes posterior estimation automatic

---

## Lesson flow

### 1. EXPLORE: The unknown planet

A planet floats in the center of the screen. You can't see its surface — it's shrouded in clouds. You can only learn about it by tossing a ball: where the ball lands, a dot appears through the clouds. Blue dot = water. Brown dot = land. Each toss reveals one pixel of truth.

**Simulation spec:**
- A circle representing the planet, with an opaque cloud layer
- Button: "Toss" — a dot appears at a random location on the planet surface. The dot is blue (water) or brown (land), determined by the hidden true water fraction p_true
- Slider: "True water fraction" — controls p_true. **Hidden by default.** The student doesn't know the true value. Revealed only after the Compare phase.
- Live counter: "Tosses: 0 | Water: 0 | Land: 0"
- Live display: A **belief curve** — a density plot over p ∈ [0, 1]. Starts as a flat line (uniform prior = "I have no idea how much water there is"). After each toss, the curve updates via grid approximation (1000-point grid, computed client-side). The curve sharpens and shifts.
- Slider: "Tosses per click" — 1, 10, 100. Allows fast exploration.
- No equations anywhere. Labels: "water fraction" on x-axis, "belief strength" on y-axis. No mention of "posterior," "likelihood," or "prior" yet.

**What the student discovers through play (canvas prompt between explorations):**

After ~5 minutes of play, the system prompts:

> "Write on the canvas: what happens to the belief curve as you toss more? What happens if you start with a different shape? Write at least two observations."

Expected discoveries:
- More tosses → curve gets **taller and narrower** (belief sharpens)
- The peak of the curve moves toward the true fraction (if the student has peeked by revealing p_true)
- If you change the starting curve shape (see below), it matters a lot early on but barely matters after many tosses
- The curve shape looks like a "hill" — symmetric when p_true ≈ 0.5, skewed when p_true is near 0 or 1

**Prior control (second exploration phase):**
After the student has explored with a flat starting curve, a new control appears:

- Slider: "Starting belief center" — moves the peak of the initial curve (sets a Beta prior's mean)
- Slider: "Starting belief strength" — controls how narrow/wide the initial curve is (sets the Beta prior's concentration: low = wide/vague, high = narrow/strong)

The system prompts:

> "Set your starting belief far from the truth. Toss 10 times. Then toss 100 times. Write on the canvas: when does the starting belief stop mattering?"

Expected discovery: **the starting belief fades with data.** Even a strong wrong initial belief gets overwhelmed by enough evidence.


### 2. PREDICT: First quantitative prediction

The simulation resets. The system sets a specific scenario:

> "With a flat starting belief and 9 tosses, 6 land on water. The belief curve is displayed. Read off the curve: the 89% interval (the range covering 89% of the area under the curve) has a **width of about 0.35**."

The system highlights the 89% interval as a shaded band under the curve and displays the width numerically: **W₉ = 0.35.**

> "Now imagine collecting 9× more data: 81 tosses, with the same 2/3 water rate (54 water, 27 land). **Predict the new width of the 89% interval.** Write your answer on the canvas in scientific notation."

**Prediction components (all locked, non-retractable):**
- **Direction:** narrower / wider / same
- **Magnitude:** a specific number, written in scientific notation on the canvas (e.g., "3.9 × 10⁻²")
- **Confidence:** just guessing / rough idea / pretty sure

**Order-of-magnitude gate:** The correct answer is W₈₁ ≈ 0.12 = 1.2 × 10⁻¹. The most common wrong answer (linear assumption) is 0.35/9 ≈ 0.039 = 3.9 × 10⁻². These differ by an **order of magnitude** (10⁻¹ vs 10⁻²). The gate fires: if the student's exponent is wrong, redirect to the data table before proceeding.


### 3. EXPLORE: Test the prediction

> "Now toss 81 times with 54 water. Watch the belief curve."

The student clicks "Toss" with "Tosses per click" set to 81. The curve sharpens. The 89% interval is highlighted. The system displays:

> "Your prediction: [student's answer]. Actual width: 0.12."

The system does NOT explain why yet. Just the gap.


### 4. DISCOVER: Data table and pattern finding

The system prompts:

> "Let's collect more data points. Reset the simulation to a flat starting belief and p_true = 2/3. Record the 89% interval width at each data size."

The student runs the simulation at N = 3, 9, 27, 81, 243 (always with 2/3 water rate). For each N, they read the interval width off the curve and write it in a table on the canvas. The system assists by displaying the width numerically after each run.

System-generated table (from student's explorations):

| N tosses | k water | Belief center | 89% interval width | ??? |
|----------|---------|--------------|--------------------|----|
| 3        | 2       | 0.60         | 0.58               |    |
| 9        | 6       | 0.636        | 0.35               |    |
| 27       | 18      | 0.655        | 0.19               |    |
| 81       | 54      | 0.663        | 0.12               |    |
| 243      | 162     | 0.665        | 0.063              |    |

> "Can you spot the pattern? Each time N triples, the width changes by a factor. What factor? Write what you notice on the canvas."

The student writes their observation. Most won't see the square root. That's fine — productive failure.

The system adds a column:

| N tosses | Width | Width × √N | 1/√N  |
|----------|-------|-----------|-------|
| 3        | 0.58  | 1.00      | 0.577 |
| 9        | 0.35  | 1.05      | 0.333 |
| 27       | 0.19  | 0.99      | 0.192 |
| 81       | 0.12  | 1.08      | 0.111 |
| 243      | 0.063 | 0.98      | 0.064 |

> "Width × √N is nearly constant. **Width ≈ C / √N**, where C ≈ 1.0. Every time."
>
> "This is the same square root relationship you'll see throughout this course. 9× more data doesn't make your belief 9× sharper — it makes it √9 = 3× sharper."


### 5. EXPLAIN: Why 1/√N?

> "You've seen that the belief width shrinks as 1/√N. Now let's prove WHY — and along the way, derive the fundamental rule of Bayesian reasoning."

**Notation introduction (Read block):**
Before any equations, introduce notation the student needs. Following the brief's rule: "Students are never shown notation they haven't been explicitly taught."

> **New notation:** We write P(A|B) to mean "the probability of A given that B is true." The vertical bar "|" means "given." For example, P(water | p = 0.7) means "the probability of landing on water, given that 70% of the planet is water" — which is just 0.7.
>
> We'll use these terms:
> - **p** — the fraction of the planet that's water (what we're trying to learn)
> - **data** — the sequence of tosses we've observed (e.g., 6 water in 9 tosses)
> - **P(p | data)** — our belief about p after seeing the data. This is what the belief curve shows.
> - **P(data | p)** — the probability of getting this data if we knew p. If p = 0.7 and we toss 9 times, P(6 water | p = 0.7) is a specific number we can compute.


### 6. DERIVE (Part A): Posterior ∝ likelihood × prior

**This is the foundational derivation. 4 steps on the canvas, SymPy-verified.**

```
Step 1: Write the definition of conditional probability
  input:  P(p | data) = P(p and data) / P(data)
  operation: Write the definition (this was just introduced in the Read block)
  output: P(p | data) = P(p ∩ data) / P(data)
  sympy_check: Axiom (accepted as given)
  hints:
    1: "What does P(A|B) equal? You just learned this definition."
    2: "P(A|B) = P(A and B) / P(B). Now substitute A = p, B = data."
  common_errors: None (this is the starting point)

Step 2: Rewrite the joint probability using the OTHER direction
  input:  P(p ∩ data) = P(data | p) × P(p)
  operation: Apply the same definition of conditional probability, but rearranged.
             P(data | p) = P(data ∩ p) / P(p), so P(data ∩ p) = P(data | p) × P(p).
  output: P(p ∩ data) = P(data | p) × P(p)
  sympy_check: sympy.Eq(P_joint, P_data_given_p * P_p)
  hints:
    1: "P(data ∩ p) is the same as P(p ∩ data). Can you write this joint probability using the conditional probability in the OTHER direction — P(data | p)?"
    2: "P(data | p) = P(data ∩ p) / P(p). Rearrange: P(data ∩ p) = P(data | p) × P(p)."
  common_errors:
    - error: Student writes P(p ∩ data) = P(p | data) × P(data) — true but circular
      diagnosis: "Used the same direction as Step 1 instead of switching."
      partial_credit: ["correct_algebra"]
      misconception: "direction_confusion"
      feedback: "That's algebraically correct — but it just gives you Step 1 rearranged. You need the OTHER conditional: P(data | p), not P(p | data). The whole point is to relate the one you WANT, P(p|data), to the one you CAN COMPUTE, P(data|p)."
      severity: "moderate"

Step 3: Substitute into Step 1
  input:  P(p | data) = P(p ∩ data) / P(data) and P(p ∩ data) = P(data | p) × P(p)
  operation: Replace P(p ∩ data) in Step 1 with the expression from Step 2
  output: P(p | data) = P(data | p) × P(p) / P(data)
  sympy_check: sympy.Eq(P_p_given_data, P_data_given_p * P_p / P_data)
  hints:
    1: "You have two expressions for P(p ∩ data). Substitute one into the other."
  common_errors:
    - error: Student writes P(p | data) = P(data | p) × P(data) / P(p) — inverted
      diagnosis: "Swapped numerator and denominator"
      partial_credit: ["attempted_substitution"]
      misconception: "fraction_inversion"
      feedback: "Check your substitution. Step 1 says P(p|data) = P(p ∩ data) / P(data). Step 2 says P(p ∩ data) = P(data|p) × P(p). The denominator stays P(data). What goes in the numerator?"
      severity: "moderate"

Step 4: Name the pieces
  input:  P(p | data) = P(data | p) × P(p) / P(data)
  operation: Identify each term
  output:
    P(p | data) = belief about p after seeing data     → "posterior"
    P(data | p) = probability of this data if p is known → "likelihood"
    P(p)        = belief about p before seeing data      → "prior"
    P(data)     = total probability of the data          → "evidence" (a normalizing constant)

    BAYES' THEOREM: posterior = likelihood × prior / evidence
    Or equivalently: posterior ∝ likelihood × prior
  sympy_check: N/A (naming, not algebraic)
  hints:
    1: "Label each piece. Which one is the belief curve BEFORE you saw any data? Which one is the belief curve AFTER?"
  common_errors:
    - error: Student swaps likelihood and prior labels
      diagnosis: "Confused which is the function of p given fixed data vs. which is the belief before data"
      partial_credit: ["knows_the_formula"]
      misconception: "likelihood_prior_swap"
      feedback: "The likelihood P(data|p) asks: 'If I KNEW the water fraction was p, how likely is this data?' It's a function of p with the data held fixed. The prior P(p) is your belief BEFORE seeing any data. Which is which in your labels?"
      severity: "mild"
```

**Canvas annotation after Derive Part A:**
> "This is Bayes' theorem. Everything in this course follows from it. Your belief after seeing data equals your belief before seeing data, multiplied by how well the data fits each possible value of p, and then rescaled to sum to 1."


### 7. DERIVE (Part B): Why width ∝ 1/√N

**The second derivation explains the pattern from the data table. 4 steps on the canvas. This is the Bayesian analog of deriving ω = √(k/m) from Newton's second law — it explains the square root.**

**Notation introduction (Read block):**
> **New notation:** log means the natural logarithm (ln). We write ℓ(p) = log P(data|p) for the log-likelihood — the logarithm of the likelihood function. Taking logs turns products into sums, which makes calculus easier.

```
Step 1: Write the log-likelihood for the globe tossing data
  input:  k water in n tosses. P(data|p) = p^k × (1−p)^(n−k).
  operation: Take the natural log.
  output: ℓ(p) = k log p + (n−k) log(1−p)
  sympy_check: simplify(log(p**k * (1-p)**(n-k))) == k*log(p) + (n-k)*log(1-p)
  hints:
    1: "P(data|p) = p^k × (1−p)^(n−k). What rules do you use to take the log of a product? Of a power?"
    2: "log(a × b) = log a + log b. log(a^n) = n log a."
  common_errors:
    - error: Student writes log(p^k) = k × p instead of k × log(p)
      diagnosis: "Confused log of a power with multiplication"
      partial_credit: ["attempted_log"]
      misconception: "log_power_rule"
      feedback: "The log rule for powers: log(a^n) = n × log(a), not n × a. log(p^k) = k × log(p). Try checking: if p = 0.5 and k = 6, does k × log(0.5) = 6 × (−0.693) = −4.16 match log(0.5^6) = log(1/64) = −4.16? Yes."
      severity: "moderate"

Step 2: Find the peak — differentiate and set to zero
  input:  ℓ(p) = k log p + (n−k) log(1−p)
  operation: dℓ/dp = k/p − (n−k)/(1−p). Set equal to zero and solve for p.
  output: k/p = (n−k)/(1−p)  →  k(1−p) = p(n−k)  →  k − kp = pn − pk  →  k = pn  →  p̂ = k/n
  sympy_check: solve(k/p - (n-k)/(1-p), p) == [k/n]
  hints:
    1: "Differentiate each term. What is d/dp of log(p)? Of log(1−p)?"
    2: "d/dp log(p) = 1/p. d/dp log(1−p) = −1/(1−p). Set the sum to zero."
    3: "Cross-multiply k/p = (n−k)/(1−p) and solve for p."
  common_errors:
    - error: Student writes d/dp log(1−p) = 1/(1−p) (missing the negative from chain rule)
      diagnosis: "Forgot the chain rule on log(1−p)"
      partial_credit: ["correct_log_derivative_base"]
      misconception: "chain_rule_omission"
      feedback: "d/dp log(1−p) requires the chain rule. Let u = 1−p, then d/dp log(u) = (1/u) × (du/dp) = (1/(1−p)) × (−1) = −1/(1−p). The minus sign matters!"
      severity: "moderate"
    - error: Student gets p̂ = (n−k)/n instead of k/n
      diagnosis: "Algebraic error in solving"
      partial_credit: ["correct_derivative", "correct_setup"]
      misconception: "algebra_error"
      feedback: "Check your algebra from k/p = (n−k)/(1−p). Cross multiply: k(1−p) = p(n−k). Expand both sides carefully. You should get k on the left with no p, and pn on the right."
      severity: "mild"

Step 3: Find the curvature — second derivative at the peak
  input:  dℓ/dp = k/p − (n−k)/(1−p)
  operation: d²ℓ/dp² = −k/p² − (n−k)/(1−p)². Evaluate at p = p̂ = k/n.
  output: d²ℓ/dp²|_{p=p̂} = −k/(k/n)² − (n−k)/((n−k)/n)²
         = −k × n²/k² − (n−k) × n²/(n−k)²
         = −n²/k − n²/(n−k)
         = −n² × [1/k + 1/(n−k)]
         = −n² / [k(n−k)/n]
         = −n³ / [k(n−k)]
         = −n / [p̂(1−p̂)]
  sympy_check: Substitute p=k/n into -k/p**2 - (n-k)/(1-p)**2, simplify to -n/(p_hat*(1-p_hat))
  hints:
    1: "Differentiate dℓ/dp = k/p − (n−k)/(1−p) one more time. What is d/dp of 1/p?"
    2: "d/dp (1/p) = −1/p². d/dp (1/(1−p)) = 1/(1−p)². Apply these."
    3: "Now plug in p = k/n and simplify. Factor out n."
  common_errors:
    - error: Student writes d/dp [−(n−k)/(1−p)] = (n−k)/(1−p)² but forgets the sign from chain rule, getting +(n−k)/(1−p)² in the second derivative instead of −(n−k)/(1−p)²
      diagnosis: "Sign error on second derivative of log(1−p) term"
      partial_credit: ["correct_first_term"]
      misconception: "sign_error_chain_rule"
      feedback: "d/dp [−(n−k)/(1−p)] — be careful. Write it as −(n−k) × (1−p)^(−1). Then d/dp = −(n−k) × (−1)(1−p)^(−2) × (−1) = −(n−k)/(1−p)². Both minus signs cancel WITH the chain rule sign, leaving NEGATIVE. Check: the log-likelihood is concave (curves DOWN), so the second derivative must be negative everywhere."
      severity: "moderate"
    - error: Student can't simplify −k/(k/n)² to −n²/k
      diagnosis: "Fraction simplification error"
      partial_credit: ["correct_derivative"]
      misconception: "fraction_algebra"
      feedback: "k/(k/n)² = k / (k²/n²) = k × n²/k² = n²/k. Take it step by step: (k/n)² = k²/n². Dividing by a fraction means multiplying by its reciprocal."
      severity: "mild"

Step 4: Read off the width
  input:  d²ℓ/dp² at peak = −n/[p̂(1−p̂)]
  operation: A function with second derivative −A at its peak, when exponentiated, gives a
             Gaussian with variance 1/A. So the belief curve is approximately Gaussian with
             variance σ² = p̂(1−p̂)/n.
  output: SD = √[p̂(1−p̂)/n] ∝ 1/√n.
          Width of the 89% interval ≈ 2 × 1.6 × SD = 3.2 × √[p̂(1−p̂)/n] ∝ 1/√n.

          "The square root comes from the curvature of the log-likelihood.
           Each data point adds the same amount of curvature (−1/[p̂(1−p̂)] per point).
           n points → n times the curvature → variance = 1/(n × curvature per point).
           SD = 1/√(n × curvature) ∝ 1/√n."
  sympy_check: For k=6, n=9: SD = sqrt(6/9 * 3/9 / 9) = sqrt(2/81) ≈ 0.157.
               89% interval width ≈ 3.2 × 0.157 ≈ 0.50.
               (Actual from grid: 0.35. Approximation is rough for n=9 but improves with n.)
               For k=54, n=81: SD = sqrt(0.667 * 0.333 / 81) ≈ 0.052. Width ≈ 0.17. Actual ≈ 0.12.
               For k=162, n=243: SD ≈ 0.030. Width ≈ 0.097. Actual ≈ 0.063.
               The approximation tightens as n grows. Note this for Compare phase.
  hints:
    1: "If log f(x) ≈ C − (A/2)(x−x₀)², then f(x) ≈ e^C × exp[−(A/2)(x−x₀)²]. What distribution has that shape?"
    2: "A Gaussian N(x₀, σ²) has exponent −(x−x₀)²/(2σ²). Match this to −(A/2)(x−x₀)² to get σ² = 1/A."
    3: "Your A = n/[p̂(1−p̂)]. So σ² = p̂(1−p̂)/n and SD = √[p̂(1−p̂)/n]. What does this tell you about how SD depends on n?"
  common_errors:
    - error: Student writes σ² = n/[p̂(1−p̂)] instead of p̂(1−p̂)/n (inverted)
      diagnosis: "Confused curvature with variance (they're inverses)"
      partial_credit: ["found_curvature", "recognized_gaussian"]
      misconception: "curvature_variance_inversion"
      feedback: "Sharper curvature (bigger |d²ℓ/dp²|) means a NARROWER peak — smaller variance, not bigger. Variance = 1/curvature, not curvature. More data → more curvature → LESS variance. Check: does your formula predict wider or narrower beliefs with more data?"
      severity: "moderate"
    - error: Student gets SD ∝ 1/n instead of 1/√n
      diagnosis: "Forgot to take the square root of variance to get SD"
      partial_credit: ["correct_variance"]
      misconception: "sd_variance_confusion"
      feedback: "You correctly found that the variance = p̂(1−p̂)/n, which IS proportional to 1/n. But the WIDTH of the belief curve is the standard deviation — the SQUARE ROOT of the variance. SD = √(variance) ∝ √(1/n) = 1/√n."
      severity: "mild"
```


### 8. COMPARE: Prediction vs derivation

The system displays side by side:

> **Your prediction:** W₈₁ = [student's answer]
> **Your derivation:** Width ∝ 1/√N. W₈₁ = W₉ × √(9/81) = 0.35 × √(1/9) = 0.35/3 ≈ **0.12**

**Error pattern JSON for the prediction:**

```json
{
  "problem_id": "B1-P1",
  "context": "Predict 89% interval width at N=81 given width 0.35 at N=9",
  "correct_answer": 0.12,
  "error_patterns": [
    {
      "answer_range": [0.03, 0.05],
      "diagnosis": "Correct direction (narrower), assumed linear relationship: 0.35 / 9 ≈ 0.039",
      "partial_credit": ["correct_direction"],
      "misconception": "linear_assumption",
      "feedback": "Good — you knew more data means a narrower belief. But look at your data table: when N went from 9 to 27 (3× more data), did the width shrink to 1/3? What's the ratio of 0.35 to 0.19? The width shrank by about 1/√3, not 1/3.",
      "severity": "mild"
    },
    {
      "answer_range": [0.005, 0.015],
      "diagnosis": "May have divided by 81 instead of by √81 or by 9",
      "partial_credit": ["correct_direction"],
      "misconception": "excessive_shrinkage",
      "feedback": "You predicted the width shrinks dramatically — more than it actually does. Go back to your data table: does the width ever shrink by a factor of 81? The actual factor for 9× more data is √9 = 3, not 9 or 81.",
      "severity": "moderate"
    },
    {
      "answer_range": [0.30, 0.38],
      "diagnosis": "Predicted little or no change — may not have connected data amount to width",
      "partial_credit": [],
      "misconception": "width_insensitivity",
      "feedback": "You predicted the width barely changes. Go back to the simulation: toss 9 times, note the width. Then toss 81 times. Does the belief curve look the same? Try it now.",
      "severity": "significant"
    },
    {
      "answer_range": [0.08, 0.15],
      "diagnosis": "Approximately correct — may have used the square root relationship or estimated well from the simulation",
      "partial_credit": ["correct_direction", "correct_magnitude"],
      "misconception": null,
      "feedback": "Strong intuition — you're within the right range. Your derivation confirms: width ∝ 1/√N, so W₈₁ ≈ W₉/√9 = 0.35/3 ≈ 0.12.",
      "severity": "none"
    }
  ]
}
```

**Compare display:**

> "You predicted [student answer]. You derived 0.12."
>
> If misconception = "linear_assumption":
> "You assumed 9× more data → 9× narrower. But the width goes as 1/√N, not 1/N. The square root comes from the curvature of the log-likelihood: each data point adds a fixed amount of curvature (like adding springs in parallel — each one stiffens the system, but stiffness adds, not force). SD = 1/√(total curvature) = 1/√N."
>
> The system shows the springs connection explicitly:
> "This is the SAME square root that appears in the spring lesson: ω = √(k/m). Both come from a second derivative."


### 9. RECONCILE

> "In your own words, write on the canvas: (1) why more data makes beliefs sharper, (2) why the sharpening follows a square root law, not a linear one, and (3) what role the 'starting belief' plays when you have a lot of data."

Student writes on the canvas. Stored, not graded. Required before proceeding.


### 10. CODE: Grid approximation in pure NumPy

```python
import numpy as np
import matplotlib.pyplot as plt

# ---- Grid approximation: your first Bayesian computation ---- #

# 1. Define a grid of possible water fractions
p_grid = np.linspace(0, 1, 1000)
dp = p_grid[1] - p_grid[0]  # Grid spacing

# 2. Define the prior: flat (uniform) — "I have no idea"
prior = np.ones(1000)

# 3. Define the likelihood: 6 water in 9 tosses
k, n = 6, 9
likelihood = p_grid**k * (1 - p_grid)**(n - k)

# 4. Bayes' theorem: posterior ∝ likelihood × prior
posterior = likelihood * prior
posterior = posterior / (posterior.sum() * dp)  # Normalize so it integrates to 1

# 5. Verify: the posterior IS the belief curve from the simulation
plt.plot(p_grid, posterior)
plt.xlabel("Water fraction p")
plt.ylabel("Belief density")
plt.title("Posterior after 6 water in 9 tosses")

# ---- Student tasks ---- #

# TASK 1: Find the peak (MAP estimate). Should be close to k/n = 6/9 ≈ 0.667.
p_map = p_grid[np.argmax(posterior)]
print(f"Peak of belief curve: {p_map:.3f}")  # Student predicts this first

# TASK 2: Compute the 89% interval width. Compare to your data table.
cumulative = np.cumsum(posterior * dp)
lo = p_grid[np.searchsorted(cumulative, 0.055)]
hi = p_grid[np.searchsorted(cumulative, 0.945)]
print(f"89% interval: [{lo:.3f}, {hi:.3f}], width = {hi - lo:.3f}")

# TASK 3: Change k, n to 54, 81. Verify width ≈ 0.12.

# TASK 4: Change k, n to 162, 243. Verify width ≈ 0.063.

# TASK 5: Plot width vs N for N = 3, 9, 27, 81, 243.
#         Overlay the theoretical curve: width = C / sqrt(N).
#         Verify they match.
```

**Code verification task:**

The student must produce a plot of width vs N and verify the 1/√N relationship numerically. The expected output:

```
N=3:   width=0.577   C = width × √3 = 1.00
N=9:   width=0.350   C = width × √9 = 1.05
N=27:  width=0.192   C = width × √27 = 1.00
N=81:  width=0.118   C = width × √81 = 1.06
N=243: width=0.063   C = width × √243 = 0.98
```

C ≈ 1.0 throughout. The student sees: **width × √N = constant**. This numerically confirms the hand derivation.

**Code error pattern:**
```json
{
  "problem_id": "B1-CODE-1",
  "context": "Normalizing the posterior on a grid",
  "correct_answer": "posterior / (posterior.sum() * dp)",
  "error_patterns": [
    {
      "answer_pattern": "posterior / posterior.sum()",
      "diagnosis": "Forgot the grid spacing dp. The posterior will integrate to dp, not 1.",
      "partial_credit": ["knows_to_normalize"],
      "misconception": "discrete_vs_continuous",
      "feedback": "Good — you know the posterior must be normalized. But posterior.sum() gives you a Riemann sum WITHOUT the dx term. For the integral to equal 1, divide by posterior.sum() × dp. Try it: what does np.trapz(posterior, p_grid) give before and after your normalization?",
      "severity": "mild"
    },
    {
      "answer_pattern": "likelihood / likelihood.sum()",
      "diagnosis": "Normalized the likelihood instead of likelihood × prior",
      "partial_credit": ["knows_to_normalize"],
      "misconception": "forgot_prior",
      "feedback": "You're normalizing the likelihood alone. Bayes' theorem says posterior ∝ likelihood × prior. With a uniform prior, the prior = 1 everywhere, so it doesn't change the shape — but you should still include it. What if the prior weren't uniform?",
      "severity": "mild"
    }
  ]
}
```


### 11. VARY: Three variations with prediction

**Variation 1: Different data, same question**

> "New scenario: 20 water in 30 tosses. Predict the 89% interval width. Write your answer in scientific notation."

Correct: SD = √(0.667 × 0.333 / 30) ≈ 0.086. Width ≈ 3.2 × 0.086 ≈ 0.28. Actual from grid: ~0.27.

Student's prediction accuracy should improve — they now know the 1/√N rule.

**Variation 2: Prior that disagrees with data**

> "Your starting belief is strong: 'I think only 30% of this planet is water' (peaked curve centered at 0.3). You toss 9 times: 6 water, 3 land. Predict: will the belief center be at 0.3 (prior wins), 0.667 (data wins), or somewhere in between? Write a specific number."

Correct: with a Beta(3, 7) prior and 6W/3L data, posterior is Beta(9, 10). Mean = 9/19 ≈ 0.474. It's between the prior mean (0.3) and the data fraction (0.667), pulled toward the prior because 9 tosses is not much more data than the prior's "equivalent sample size" of 10.

**Error pattern:**
```json
{
  "problem_id": "B1-P3",
  "context": "Posterior mean with informative prior Beta(3,7) and data 6W/3L",
  "correct_answer": 0.47,
  "error_patterns": [
    {
      "answer_range": [0.60, 0.70],
      "diagnosis": "Ignored the prior entirely, used the data fraction k/n = 0.667",
      "partial_credit": [],
      "misconception": "prior_irrelevance",
      "feedback": "You predicted the data fraction (0.667) as if the starting belief doesn't matter. But go back to the simulation: set a strong starting belief at 0.3 and toss only 9 times. Does the curve center at 0.667? The prior pulls the answer toward 0.3 because 9 tosses isn't enough to overwhelm a strong prior.",
      "severity": "moderate"
    },
    {
      "answer_range": [0.27, 0.35],
      "diagnosis": "Thinks the prior dominates regardless of data",
      "partial_credit": [],
      "misconception": "prior_dominance",
      "feedback": "You predicted near the prior mean (0.3), as if the data barely matters. But 6 out of 9 tosses landed on water — that IS informative. The belief center should be BETWEEN the prior mean and the data fraction. Try the simulation: the curve clearly shifts away from 0.3 after seeing the data.",
      "severity": "moderate"
    },
    {
      "answer_range": [0.40, 0.55],
      "diagnosis": "Correctly predicted a value between prior and data — good intuition",
      "partial_credit": ["correct_direction", "weighted_average_intuition"],
      "misconception": null,
      "feedback": "Excellent — you correctly intuited that the answer is a compromise between the prior (0.3) and the data (0.667). The exact answer from the derivation is 0.474: a precision-weighted average where the prior gets weight proportional to its 'equivalent sample size' (10) and the data gets weight proportional to actual sample size (9).",
      "severity": "none"
    }
  ]
}
```

**Variation 3: Extreme data — scientific notation practice**

> "You toss 10,000 times. 6,700 land on water. Predict the 89% interval width in scientific notation."

Correct: SD = √(0.67 × 0.33 / 10000) ≈ 0.0047. Width ≈ 3.2 × 0.0047 ≈ 0.015 = 1.5 × 10⁻².

Order-of-magnitude gate: if student writes 10⁻³ or 10⁻¹, redirect to the formula.

> "With 10,000 tosses, you know the water fraction to within ±0.008. That's precise enough to distinguish p = 0.67 from p = 0.68. Earth's actual water fraction is 0.71 — could you detect this from 10,000 tosses? What about from 100?"

This connects the abstraction to a real quantity the student can relate to.


### 12. CONNECT: The medical test

> "You just learned to update beliefs about one number (water fraction) from data (globe tosses). Here's where this matters in real life:"

> "A medical test for a rare disease is 99% accurate. A patient tests positive. Most doctors — and most patients — believe there's a 99% chance the patient has the disease. They're wrong."

> "Suppose 1 in 10,000 people has the disease. Out of 10,000 people:
> - 1 truly sick person tests positive (99% accuracy).
> - 9,999 healthy people: 1% false positive rate → ~100 test positive.
> - Total positive tests: 101. Only 1 is truly sick.
> - P(sick | positive test) = 1/101 ≈ **1%**, not 99%."

> "Bayes' theorem handles this automatically: the prior (1 in 10,000 has the disease) overwhelms the likelihood (99% test accuracy) because the disease is so rare. This is exactly what you derived: posterior ∝ likelihood × prior. Without the prior, you'd tell 100 healthy people they're dying."

> "But wait — what if the patient tests positive TWICE, on independent tests? Does P(sick | two positives) go up to 50%? 90%? 99%? You now have the tools to compute this. Next lesson: working with the posterior. Point estimates, intervals, predictions, and the question that connects everything: **when your model says one thing and reality says another, who do you believe?**"

No completion screen. The next lesson title is visible: **"What Can You Do with a Posterior?"**

---

## Equation practice drills (generated for spaced repetition)

Introduced alongside this lesson. Each resurfaces at expanding intervals.

**Drill 1: Log rules**
> "Simplify: log(a^3 × b^2) − log(a × b^5)"
> Answer: 3 log a + 2 log b − log a − 5 log b = 2 log a − 3 log b
> SymPy check: simplify(3*log(a) + 2*log(b) - log(a) - 5*log(b)) == 2*log(a) - 3*log(b)

**Drill 2: Derivative of log**
> "Differentiate: f(p) = k log(p) + m log(1 − p). Find df/dp."
> Answer: k/p − m/(1−p)
> SymPy check: diff(k*log(p) + m*log(1-p), p) == k/p - m/(1-p)

**Drill 3: Exponent manipulation**
> "Simplify: p^a × p^b × (1−p)^c × (1−p)^d"
> Answer: p^(a+b) × (1−p)^(c+d)
> SymPy check: simplify(p**a * p**b * (1-p)**c * (1-p)**d) == p**(a+b) * (1-p)**(c+d)

These drills practice exactly the algebraic skills needed for the Beta-Binomial conjugacy derivation in Lesson 2.

---

## Implementation notes for the build agent

### Simulation (Explore phase)
- Vanilla JS + HTML Canvas. No frameworks.
- The planet visualization is optional polish — the core element is the **belief curve** that updates after each toss. This is a line chart over p ∈ [0,1], recomputed via grid approximation (1000 points) after each toss. Use `requestAnimationFrame` for smooth curve animation.
- All computation is client-side. Grid approximation in JS is trivial: `posterior[i] = prior[i] * Math.pow(p[i], k) * Math.pow(1-p[i], n-k); normalize();`
- Prior sliders map to Beta(α, β) parameters. "Starting belief center" = α/(α+β), "Starting belief strength" = α+β. Convert slider values to (α, β) before computing.
- The 89% interval is computed from the cumulative sum of the grid posterior. Highlight as a shaded region.
- iPad-first: all interactions via pointer events. The toss button must be large and responsive on touch. The belief curve must render at ≥30fps on iPad.

### Canvas (Derive phase)
- The 8 derivation steps (4 + 4) are the primary content. Each step is written by the student on the handwriting canvas.
- VLM recognizes → LaTeX → KaTeX renders alongside → SymPy verifies.
- Green dot per correct step, orange dot per incorrect step. Student can tap for details.
- Hint system: three progressive hints per step. Hints used are tracked for spaced repetition weighting.
- Structured derive block (select operations from a menu) available as fallback.

### Error patterns
- All JSON in this document is ready for deployment as static files. The build agent should:
  1. Create one JSON file per problem (B1-P1.json, B1-P3.json, B1-CODE-1.json, etc.)
  2. Place in the lesson's `error_patterns/` directory
  3. Verify all `correct_answer` values against SymPy before deploying

### Data table (Discover phase)
- The table is partially student-generated: the student runs the simulation at specified N values and records the width. The system assists by displaying the computed width numerically.
- The "???" column (asking the student to spot the pattern) is a canvas prompt — the student writes their observation.
- The system reveals the √N column ONLY after the student has written their observation. This is the "time for telling" — explanation after attempted invention.

### Spaced repetition
- Flag all 4+4 derivation steps for review.
- On second encounter: provide Steps 1–2 completed; student derives Steps 3–4.
- On third encounter: provide only "Derive Bayes' theorem from the definition of conditional probability" — student reconstructs all 4 steps.
- For Derive Part B: same fading. Third encounter provides only "Show that the posterior width is proportional to 1/√N."
- Track the `linear_assumption` misconception tag across lessons. If it appears 3+ times (including in the springs course), generate a targeted mini-lesson on square root relationships.

### Scientific notation
- Every Predict phase requires the magnitude in scientific notation.
- System checks mantissa and exponent separately.
- Order-of-magnitude gate: if exponent is wrong (e.g., 10⁻² when answer is 10⁻¹), redirect to dimensional analysis / data table review before proceeding.
- Variation 3 (N=10,000) specifically tests scientific notation fluency with small numbers.

### Progress data (Google Sheets)
Each interaction logs:
```
timestamp | user_id | lesson_id=B1 | problem_id | phase |
prediction_direction | prediction_magnitude | prediction_confidence |
derived_answer | prediction_correct_direction | prediction_correct_magnitude |
prediction_error_ratio | misconception_tags |
hints_used | time_spent_seconds |
reconciliation_text_length | diagnostic_feedback_given
```
