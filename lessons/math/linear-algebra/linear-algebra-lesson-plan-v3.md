# Introduction to Linear Algebra — Lesson Content Plan

**Platform**: Why Academy (see `why-academy-brief.md` for all platform systems)
**Prerequisites**: Comfortable with derivatives and integrals. No prior linear algebra.
**Entry point**: Standalone — does not require the springs sequence.

## How to read this document

This document provides **lesson content only**. It assumes the build agent has read `why-academy-brief.md` and will execute each lesson using the systems defined there:

- **Lesson phases**: Follow §Core Learning Loop and §Lesson Phases. Every lesson uses the Explore → Predict → Discover → Explain → Derive → Compare → Reconcile → Code → Vary → Connect sequence.
- **Canvas + VLM + SymPy pipeline**: Follow §The Critical Pipeline and §The Handwriting Canvas. Each lesson below specifies what notation the VLM must recognize and what SymPy checks per derivation line.
- **Error pattern templates**: Follow the JSON schema in §Diagnostic Feedback Architecture. Each lesson below provides the problem-specific patterns; the build agent generates the JSON.
- **Diagnostic feedback**: Follow the five principles in §Feedback Principles. All feedback builds on what's right first.
- **Hints**: Follow the three-level system in §The Four Phases → Derive. Each lesson provides hint content; the build agent wires it into the tracking system.
- **Scientific notation**: Follow §Scientific Notation Integration. Each lesson specifies 1–2 checkpoints with order-of-magnitude gates.
- **Spaced repetition**: Follow §Spaced Repetition Model. Misconception tags from error patterns feed the cross-problem tracker.
- **Code**: Follow §Key Design Principles #9 (Pure NumPy) and §Engagement Philosophy → The Builder Drive. Each lesson adds functions to the persistent `linalg_toolkit.py`.
- **Verification pipeline**: Follow §Adaptive Authoring Loop → Key constraint. All derivation steps SymPy-verified, all code blocks run and tested, all error patterns validated before deployment.

Reference the Lesson 1 (The Single Spring) content plan in the brief as the structural template for how each lesson below should be expanded to full detail.

---

## Course narrative thread

The course is organized around five matrix factorizations, each more powerful than the last. Every Connect phase references where we are on this arc:

```
A = CR    → What are the independent columns? (Module 1)
A = LU    → How does elimination solve Ax = b? (Module 2)
A = QR    → What are the orthogonal directions? (Module 4)
A = SΛS⁻¹ → What directions does A stretch? (Module 6)
A = UΣVᵀ  → Complete geometry for ANY matrix. (Module 7)
```

## Persistent codebase: `linalg_toolkit.py`

Each Code phase adds functions. New functions should call earlier ones where possible.

```python
# M1: vec_add, vec_scale, linear_combination, dot, norm, angle_between, mat_vec, mat_mat
# M2: row_reduce, back_substitute, forward_substitute, lu_factor, solve_lu, inverse_2x2
# M3: rref, nullspace, col_space, rank, four_subspaces
# M4: project, least_squares, gram_schmidt, qr_factor
# M5: det_cofactor, det_elimination
# M6: eigenvalues_2x2, diag_factor, power_method, markov_steady, is_positive_definite
# M7: svd_2x2, svd_image_compress, pca
# M8: transform_matrix, change_basis
```

## Module map

```
Module 1: Vectors & Matrices           Lessons 1–4
Module 2: Solving Ax = b / A = LU      Lessons 5–8
Module 3: Four Fundamental Subspaces    Lessons 9–13
Module 4: Orthogonality / A = QR       Lessons 14–18
Module 5: Determinants                  Lessons 19–20
Module 6: Eigenvalues / A = SΛS⁻¹     Lessons 21–25
Module 7: SVD / A = UΣVᵀ              Lessons 26–28
Module 8: Transformations              Lessons 29–30
```

---

## MODULE 1: VECTORS AND MATRICES — FULL DETAIL

### New canvas notation for this module

In addition to basic arithmetic, the VLM must recognize for Module 1:
- Column vector brackets: [a; b] or (a, b) written vertically
- Scalar multiplication: a number adjacent to a vector
- 2×2 matrix notation with square brackets
- Subscripts: v₁, v₂, aᵢⱼ
- The dot product symbol (·)
- Square root (√), fraction bars
- Norm notation ‖v‖
- cos, arccos
- Superscripts (²)

### Structured derive fallback for this module

Menu operations available alongside canvas: "Substitute expression", "Solve for variable", "Add/subtract from both sides", "Multiply/divide both sides", "Expand/distribute", "Factor", "Compute dot product", "Read off column of matrix", "Compute linear combination of columns."

---

### LESSON 1: Vectors, Linear Combinations, and Span

#### Simulation (Explore phase)

2D coordinate plane, range [-6, 6]. Two vectors from origin (draggable endpoints). Two sliders c₁, c₂ ∈ [-3, 3], step 0.1. Result vector c₁v₁ + c₂v₂ in distinct color, updating in real time. "Trace" toggle leaves dot trail showing reachable points.

Labels: "Vector 1", "Vector 2", "Slider 1", "Slider 2", "Result." No variable names, no equations.

Config 1: v₁ = [2,1], v₂ = [1,2]. Trace fills the plane.
Config 2 (button): v₁ = [2,1], v₂ = [4,2]. Trace fills only a line.

Discovery prompt: "What's different? When can you reach every point?"

#### Predict

v₁ = [2,1], v₂ = [1,3], target b = [7,11] shown as red dot.

"What slider values land on the red dot? Write c₁ and c₂ on the canvas."

#### Discover

| v₁ | v₂ | Parallel? | Trace fills... |
|----|----|-----------|---------------|
| [2,1] | [1,2] | No | Entire plane |
| [2,1] | [4,2] | Yes | A line |
| [1,0] | [0,1] | No | Entire plane |
| [3,1] | [6,2] | Yes | A line |

Canvas prompt: "What pattern? When can you reach every point?"

System follow-up adds column: "v₂ as multiple of v₁?" → Yes for parallel cases, No otherwise.

#### Explain

"A **linear combination** c₁v₁ + c₂v₂: all such combinations form the **span**. Non-parallel vectors span ℝ². Parallel vectors span a line."

"Finding c₁, c₂ to reach target b means solving c₁v₁ + c₂v₂ = b — a system of linear equations:"

c₁[2;1] + c₂[1;3] = [7;11] → 2c₁ + c₂ = 7, c₁ + 3c₂ = 11

#### Derive — Operation tree

Starting system: 2c₁ + c₂ = 7, c₁ + 3c₂ = 11

| Step | Valid moves | SymPy check | Common errors |
|------|------------|-------------|---------------|
| 1. Isolate a variable | c₁ = 11 - 3c₂ (from eq2) OR c₂ = 7 - 2c₁ (from eq1) | `Eq(c1, 11 - 3*c2)` | Sign error: c₁ = 11 + 3c₂. Tag: `sign_error_isolation` |
| 2. Substitute | 2(11-3c₂) + c₂ = 7 | After expand: `Eq(22 - 5*c2, 7)` | Distribution error: 22 - 3c₂ + c₂ (forgot to multiply -3 by 2). Tag: `distribution_error` |
| 3. Solve | c₂ = 3 | `Eq(c2, 3)` | Sign error on division: -5c₂ = -15 → c₂ = -3. Tag: `sign_error_division` |
| 4. Back-substitute | c₁ = 11 - 9 = 2 | `Eq(c1, 2)` | — |
| 5. Verify | 2[2,1] + 3[1,3] = [7,11] ✓ | `Eq(2*Matrix([2,1]) + 3*Matrix([1,3]), Matrix([7,11]))` | — |

Hints:
1. "Two equations, two unknowns. Can you isolate one variable from one equation?"
2. "Try solving equation 2 for c₁, then substituting into equation 1."
3. "From eq 2: c₁ = 11 - 3c₂. Replace c₁ in eq 1: 2(11 - 3c₂) + c₂ = 7."

#### Error patterns (Predict phase)

| Student answer | Diagnosis | Partial credit | Misconception tag | Feedback |
|---------------|-----------|---------------|-------------------|----------|
| c₁≈3, c₂≈2 | Swapped coefficients | correct_method, correct_arithmetic | `coefficient_swap` | "Good — your algebra works. But check which slider goes with which vector. Plug in: does 3·[2,1] + 2·[1,3] = [7,11]?" |
| c₁≈3.5, c₂≈0 | Divided target by v₁ only, ignored v₂ | engaged | `ignore_second_vector` | "You used mostly Vector 1. But 3.5·[2,1] = [7, 3.5] — the second component is way off. You need Vector 2 to push it up to 11." |
| c₁=7, c₂=11 | Used target components as coefficients | — | `target_as_coefficients` | "Those are the target coordinates, not the slider values. Try it: set Slider 1 to 7 in the simulation. 7·[2,1] = [14,7] — already past the target." |

#### Code

Adds to `linalg_toolkit.py`: `vec_add(v, w)`, `vec_scale(c, v)`, `linear_combination(coeffs, vectors)`.

Verification exercise: stack v₁, v₂ as columns of matrix A, solve Ac = b with `np.linalg.solve`, confirm c = [2, 3].

Test cases:
```python
assert np.allclose(linear_combination([2, 3], [np.array([2,1]), np.array([1,3])]), np.array([7, 11]))
```

#### Vary

1. v₁=[1,2], v₂=[3,1], b=[5,5] → c₁=2, c₂=1
2. v₁=[3,-1], v₂=[1,2], b=[5,5] → c₁=15/7, c₂=20/7 (tests fractions)
3. RGB: v₁=[1,0,0], v₂=[0,1,0], v₃=[0,0,1], target [255,128,0] (orange) — extends to 3D

Build agent: generate error patterns for variations 1–2 per the schema.

#### Sci notation

"256 values per RGB channel. Total colors = 256³ = ?" → 1.68 × 10⁷. Gate: 10⁶–10⁸.

#### Connect

"You solved c₁v₁ + c₂v₂ = b. For 100 vectors, you can't do this by substitution. When you stacked v₁, v₂ as columns and wrote Ac = b, you entered the world of matrices. The dot product v₁·v₂ tells you the angle between them — and that angle controls how easy the system is to solve."

---

### LESSON 2: Dot Products, Lengths, and Angles

#### Simulation

2D plane, two vectors from origin (draggable). Live display: "v · w = [number]" — no formula, just the value. Green glow when positive, red when negative, golden flash near zero. Angle arc with degrees.

#### Predict

Fixed v = [3,1]. Three cases:
1. w = [1,3]: acute/right/obtuse? Estimate degrees.
2. w = [-1,3]: same.
3. w = [-3,-1]: same.

#### Discover

| v | w | v·w | ‖v‖ | ‖w‖ | Angle | (v·w)/(‖v‖‖w‖) |
|---|---|-----|-----|-----|-------|----------------|
| [3,1] | [1,3] | 6 | √10 | √10 | 53.1° | 0.60 |
| [3,1] | [-1,3] | 0 | √10 | √10 | 90° | 0.00 |
| [3,1] | [-3,-1] | -10 | √10 | √10 | 180° | -1.00 |
| [1,1] | [1,0] | 1 | √2 | 1 | 45° | 0.707 |

Canvas prompt: "The last column — recognize those numbers?"

#### Explain

cos θ = (v·w)/(‖v‖‖w‖). Comes from the law of cosines. "Let's prove it."

#### Derive — Operation tree

| Step | Valid moves | SymPy check | Common errors |
|------|------------|-------------|---------------|
| 1. Expand ‖v-w‖² | (v₁-w₁)² + (v₂-w₂)² | Expand to `v1**2 - 2*v1*w1 + w1**2 + v2**2 - 2*v2*w2 + w2**2` | Write (a-b)² = a²-b² instead of a²-2ab+b². Tag: `square_of_difference_error` |
| 2. Group | = ‖v‖² + ‖w‖² - 2(v₁w₁+v₂w₂) = ‖v‖² + ‖w‖² - 2(v·w) | Identification of grouped terms | — |
| 3. Compare to law of cosines | ‖v‖² + ‖w‖² - 2(v·w) = ‖v‖² + ‖w‖² - 2‖v‖‖w‖cos θ | Match terms | — |
| 4. Identify | v·w = ‖v‖‖w‖cos θ → cos θ = (v·w)/(‖v‖‖w‖) | `Eq(cos(theta), dot(v,w)/(norm_v*norm_w))` | — |

Hints:
1. "Start by expanding ‖v-w‖² in components."
2. "(v₁-w₁)² = v₁² - 2v₁w₁ + w₁². Expand both squared terms."
3. "Group: v₁²+v₂² is ‖v‖². The -2v₁w₁-2v₂w₂ part is -2(v·w)."

#### Error patterns (Predict: angle between [3,1] and [1,3])

| Student answer | Diagnosis | Tag | Feedback |
|---------------|-----------|-----|----------|
| 45° | Visual symmetry — both seem equally tilted from diagonal | `visual_symmetry` | "Good — it IS acute and 45° is close. But v makes ~18° with x-axis, w makes ~72°. Difference: ~54°. Your formula gives 53.1°." |
| 90° | Swapped components → must be perpendicular | `swapped_means_perp` | "Swapping components doesn't make vectors perpendicular. Check: [3,1]·[1,3] = 3+3 = 6, not zero. For perpendicular you'd need [3,1]·[-1,3] = 0." |

#### Code

Adds: `dot(v, w)`, `norm(v)`, `angle_between(v, w)`.
Reuses: nothing new yet — these become building blocks.
Tests: `dot([3,1],[1,3]) == 6`, `norm([3,4]) == 5`, `angle_between([1,0],[0,1]) == π/2`.

#### Vary

1. v=[4,3], w=[-3,4] → 90° (both length 5 — 3-4-5 triangle hiding)
2. v=[1,1,1], w=[1,-1,0] → 90° in 3D (not visually obvious)
3. v=[1,0], w=[-1,0] → 180° (opposite directions)

#### Sci notation

"Google: ~10⁵ queries/sec, each computing cosine similarity against ~10⁹ pages. At 1 ns per similarity: how many seconds of compute per query?" → ~1 second. Gate: 10⁻¹–10¹.

#### Connect

"Cosine similarity = your formula, but in 100,000 dimensions. Document = word-count vector. Similar documents → small angle. This is how search engines work."

"And here's the deeper thread: ∫f(x)g(x)dx is a dot product for functions. When it's zero, the functions are 'perpendicular.' Fourier series = orthogonal decomposition. Same math, infinite dimensions. That's Module 4."

---

### LESSON 3: Matrices as Transformations

#### Simulation (the key visual for the entire course)

2D grid, unit square shaded. Basis vectors î (red), ĵ (blue). Four sliders: a, b, c, d for [[a,b],[c,d]], range [-3,3]. As sliders change, the entire grid deforms. Grid lines stay straight and evenly spaced.

Preset buttons: "Scale ×2" [[2,0],[0,2]], "Flip" [[1,0],[0,-1]], "Rotate 90°" [[0,-1],[1,0]], "Shear" [[1,1],[0,1]], "Squeeze" [[2,0],[0,0.5]].

Discovery prompt: "Where do the red and blue arrows end up? Compare to the matrix entries."

#### Predict

A = [[2,1],[0,3]]. Blue dots at [1,0], [0,1], [1,1].

1. "Where does [1,0] go?"
2. "Where does [0,1] go?"
3. "Where does [1,1] go? (It's [1,0]+[0,1]. Does that help?)"

#### Discover

| Matrix | î goes to | Col 1 | ĵ goes to | Col 2 |
|--------|----------|-------|----------|-------|
| [[2,0],[0,2]] | [2,0] | [2,0] | [0,2] | [0,2] |
| [[0,-1],[1,0]] | [0,1] | [0,1] | [-1,0] | [-1,0] |
| [[2,1],[0,3]] | [2,0] | [2,0] | [1,3] | [1,3] |

"Where î goes is always _____ of A. Where ĵ goes is always _____."

"So [c₁,c₂] = c₁î + c₂ĵ goes to c₁(col 1) + c₂(col 2). This IS the matrix-vector product."

#### Explain

"Av = v₁(column 1 of A) + v₂(column 2 of A). Also: (Av)ᵢ = (row i)·v. Same result, different insight."

#### Derive — Operation tree

Compute Av for A = [[2,1],[0,3]], v = [4,-1] using BOTH pictures:

| Step | SymPy check | Common errors |
|------|-------------|---------------|
| Column: Av = 4·[2,0] + (-1)·[1,3] | `4*Matrix([2,0]) + (-1)*Matrix([1,3])` | Pair v₁ with col 2 instead of col 1. Tag: `column_pairing_error` |
| = [8,0] + [-1,-3] | | (-1)·[1,3] = [-1,3] — only negated first component. Tag: `scalar_multiply_partial` |
| = [7,-3] | `Eq(Matrix([[2,1],[0,3]])*Matrix([4,-1]), Matrix([7,-3]))` | |
| Row: [2,1]·[4,-1]=7, [0,3]·[4,-1]=-3 | Same result | [0,3]·[4,-1] = 3 (dropped negative). Tag: `sign_drop` |

Hints:
1. "Column picture: Av = v₁ × (col 1) + v₂ × (col 2). What is v₁? What is col 1?"
2. "4 × [2,0] = [8,0]. Now compute (-1) × [1,3]."
3. "[8,0] + [-1,-3] = ?"

#### Error patterns (Predict: where does [1,1] go under [[2,1],[0,3]]?)

Correct: [3, 3] (col 1 + col 2 = [2,0]+[1,3]).

| Student answer | Tag | Feedback |
|---------------|-----|----------|
| [2,1] | `elementwise_multiply` | "You multiplied entry-by-entry: 2·1, 1·1. That's not how matrices work. The column picture: [1,1] = 1·î + 1·ĵ, so it goes to 1·(col 1) + 1·(col 2) = [2,0]+[1,3]." |
| [2,3] | `row_dot_only_one` | "You got the first component right (row 1 · [1,1] = 3... wait, [2,1]·[1,1] = 3). Check both rows." |

#### Code

Adds: `mat_vec(A, v)` — implemented as column linear combination using a loop, NOT `@` or `np.dot`.
Reuses: `vec_scale` from L1.
Tests: `mat_vec([[2,1],[0,3]], [4,-1]) == [7,-3]`.

#### Vary

1. Rotation R(60°) applied to [1,0] → predict landing point
2. Projection [[1,0],[0,0]] applied to [3,5] → y vanishes
3. A 3×2 matrix applied to a 2-vector → "matrices can change dimension"

#### Sci notation

"4K video: 3840×2160 pixels × 3 channels × 4 multiplications per pixel for a rotation. Total multiplications per frame?" → ~10⁸. Gate: 10⁷–10⁹.

#### Connect

"Every Pixar frame is matrix × vertices. But translation (sliding sideways) ISN'T a matrix multiplication in 2D. To make it linear, you go up one dimension — homogeneous coordinates. All of computer graphics was unlocked by a dimension trick."

"Next: applying two transformations in sequence = one matrix (the product). But AB ≠ BA."

---

### LESSON 4: Matrix Multiplication and A = CR

#### Simulation

Grid transformer from L3, but with TWO matrices A, B. Three views: "After B", "After A", "After AB." Toggle: "B then A" vs "A then B." Product matrices AB and BA shown numerically — highlight differences.

Default: A = [[2,0],[0,1]] (stretch), B = [[0,-1],[1,0]] (rotation).

#### Predict

A = [[1,1],[0,1]] (shear), B = [[0,-1],[1,0]] (rotation).

1. "Is AB = BA?" (No.)
2. "B then A on [1,0]: predict final position."
3. "A then B on [1,0]: predict final position."

#### Discover

"Column j of AB = A × (column j of B). Matrix multiplication = repeated matrix-vector multiplication."

Animated: column 1 of B feeds through the L3 grid transformer for A.

Data table: (AB)ᵢⱼ = (row i of A)·(column j of B).

#### Explain

Three views of AB:
1. (AB)ᵢⱼ = (row i of A)·(column j of B)
2. Column j of AB = A × (column j of B)
3. AB = Σₖ (col k of A)(row k of B) — sum of rank-1 outer products → leads to A = CR

#### Derive — Operation tree

Compute AB for A = [[1,2],[3,4]], B = [[5,6],[7,8]]:

| Step | SymPy check | Common errors |
|------|-------------|---------------|
| Col 1 of AB = A×[5,7] = 5[1,3]+7[2,4] | `Eq(A*Matrix([5,7]), Matrix([19,43]))` | Hadamard (entry-wise): [[1·5,2·6],[3·7,4·8]]. Tag: `hadamard_not_matmul` |
| = [5,15]+[14,28] = [19,43] | | Arithmetic: 15+28 = 47. Tag: `arithmetic_error` |
| Col 2 of AB = A×[6,8] = [22,50] | `Eq(A*Matrix([6,8]), Matrix([22,50]))` | |
| AB = [[19,22],[43,50]] | `Eq(A*B, Matrix([[19,22],[43,50]]))` | Computed BA instead: [[23,34],[31,46]]. Tag: `order_swap` |
| Verify BA ≠ AB | `Not(Eq(A*B, B*A))` | |

Hints:
1. "Column 1 of AB = A times column 1 of B. What is column 1 of B?"
2. "A × [5,7] = 5 × (col 1 of A) + 7 × (col 2 of A). Use mat_vec from Lesson 3."
3. "5×[1,3] = [5,15]. 7×[2,4] = [14,28]. Add them."

#### Error patterns (Predict: Is AB = BA?)

| Answer | Tag | Feedback |
|--------|-----|----------|
| Yes | `commutativity_assumption` | "For numbers, 3×5 = 5×3. Matrices are different: shear-then-rotate ≠ rotate-then-shear. Toggle between the two orders in the simulation." |

#### Code

Adds: `mat_mat(A, B)` — loop over columns of B, call `mat_vec(A, col)` for each. Reuses `mat_vec` from L3.
Tests: `mat_mat(A,B) == [[19,22],[43,50]]`, `not allclose(mat_mat(A,B), mat_mat(B,A))`, `mat_mat(A, I) == A`.

#### Vary

1. R(30°) × R(60°) = R(90°). "Is AB = BA for rotations?" → Yes (surprise!)
2. (3×2) × (2×4) = 3×4. Predict output shape. "Dimensions match like dominoes."
3. A × A⁻¹ = I. Preview of inverses.

#### Sci notation

"A GPT layer: 12288×12288 matrix × 12288 vector. Multiplications per layer?" → ~1.5 × 10⁸. Gate: 10⁷–10⁹.

#### Connect

"A = [[1,2,3],[2,4,6]] — column 2 is 2×col 1, column 3 is 3×col 1. The 'true content' is one column."

"A = CR: C = independent columns, R = the recipe for the rest. The number of independent columns is the **rank** — the true dimensionality."

"A 1000-column dataset with rank 5 has only 5 real pieces of information. Finding those directions is the second half of this course."

"Next: systematic elimination for 3, 100, or a million equations → A = LU."

---

## MODULES 2–8: LESSON OUTLINES

Each outline below follows the same structure as Module 1 lessons. The build agent expands each to full detail: simulation spec, prediction prompts with expected values, operation tree for derive (with per-line SymPy checks and common errors tagged), error pattern templates (3–5 per prediction, 2–3 per derivation branch point), code additions with test cases, and connect hooks.

### New canvas notation by module

| Module | New notation VLM must recognize |
|--------|---------------------------------|
| 2 | Augmented matrix [A\|b], row operation notation (R₂←R₂-3R₁), upper/lower triangular matrices, the ≡ symbol |
| 3 | Parametric solution notation (x = xₚ + c₁s₁ + c₂s₂), span{} notation, dim(), subspace symbols C(A), N(A), C(Aᵀ), N(Aᵀ), the ∈ and ⊂ symbols |
| 4 | Projection hat notation (x̂), the ⊥ symbol, QR with orthonormal columns, summation with inner products ⟨u,v⟩ |
| 5 | Determinant bars \|A\|, cofactor notation Cᵢⱼ, cross product ×, 3×3 determinant expansion |
| 6 | Eigenvalue λ, characteristic polynomial det(A-λI), diagonal matrix Λ, complex numbers (a+bi), matrix exponential eᴬᵗ |
| 7 | Sigma Σ for singular values, transpose Vᵀ, rank-k approximation Aₖ, the ≈ symbol |
| 8 | Function notation T(v), composition T∘S, similarity P⁻¹AP |

---

### MODULE 2: Solving Ax = b / A = LU (Lessons 5–8)

**Lesson 5: Elimination — Row and Column Pictures**
- Explore: 3D — three planes intersecting at a point. Drag coefficients; intersection moves. Toggle between row picture (planes) and column picture (column combination reaching b).
- Predict: "Change b₃ from 9 to 10. Will the solution point move up, down, or sideways?"
- Derive: 3×3 Gaussian elimination by hand. Each row operation is a tree node. SymPy checks the reduced system at each step.
- Common errors: sign errors in row subtraction (tag: `row_op_sign`), forgetting to apply operation to RHS (tag: `rhs_forgotten`).
- Code: `row_reduce(A_augmented)`, `back_substitute(U, b)`. Reuses `dot` from L2.
- Connect: Balancing chemical equations = solving a homogeneous system. The "recipe" is a nullspace vector.
- Sci notation: Weather simulation — 10⁶ × 10⁶ sparse system per time step.

**Lesson 6: Elimination Matrices and Inverses**
- Explore: Each elimination step visualized as multiplication by Eᵢⱼ. Student sees the matrix and watches it zero out an entry.
- Predict: "E₂₁ subtracts 3×row1 from row2. What does E₂₁⁻¹ do?" (Adds it back.)
- Derive: 2×2 inverse via ad-bc formula. Verify AA⁻¹ = I. Also: [A|I] → [I|A⁻¹] by elimination.
- Common errors: sign error in ad-bc (tag: `det_sign`), forgetting to divide by det (tag: `missing_det_division`).
- Code: `inverse_2x2(A)`. Reuses `det_elimination` (preview — manual formula for now).
- Connect: Hill cipher — encryption = matrix multiply mod 26, decryption = inverse.

**Lesson 7: A = LU Factorization**
- Explore: Elimination builds L and U simultaneously. Multipliers fill L below diagonal; pivots fill U. Animated side-by-side emergence.
- Predict: "4×4 system: how many multiplications?" (Estimate before seeing 2n³/3.)
- Derive: Full LU on 3×3. Verify A = LU. SymPy checks every multiplier stored in L.
- Common errors: wrong multiplier sign in L (tag: `multiplier_sign`), pivot confusion with zero (tag: `zero_pivot_unhandled`).
- Code: `lu_factor(A)` → L, U. `forward_substitute(L, b)`, `solve_lu(A, b)`. Reuses `mat_mat` from L4.
- Connect: Timing: `np.linalg.solve` on 1000×1000 in ms vs Cramer's rule (n! operations — more than atoms in universe for n=25).

**Lesson 8: PA = LU, Transposes, Symmetric Matrices**
- Explore: Matrix with zero pivot — elimination fails until row swap. Permutation matrix P shown.
- Predict: "If A = Aᵀ, are L and U related?" (U = DLᵀ → A = LDLᵀ.)
- Derive: PA = LU for a system needing a swap. Then symmetric case: A = LDLᵀ.
- Code: Extend `lu_factor` to handle pivoting.
- Connect: Cholesky (A = LLᵀ) — financial risk models, correlated random variable generation.

---

### MODULE 3: Four Fundamental Subspaces (Lessons 9–13)

**Lesson 9: Vector Spaces and Subspaces**
- Explore: Plane through origin in 3D. Test closure: add two vectors → stays on plane. Scale → stays. Plane NOT through origin: closure fails.
- Predict: "Is {[x,y] : x + y = 1} a subspace?" (No — zero not included.)
- Derive: Prove subspace conditions for column space of a specific matrix.
- Code: `is_in_span(vectors, target)`.
- Connect: Conservation laws define subspaces.

**Lesson 10: The Nullspace — Solving Ax = 0**
- Explore: A acting on vectors. Nullspace vectors collapse to zero; others don't. "Nullspace detector" highlights.
- Predict: "3×5 matrix, rank 3. How many free variables?" (2.)
- Derive: RREF → pivot/free variables → special solutions. Full operation tree for RREF procedure.
- Code: `rref(A)`, `nullspace(A)`.
- Connect: Error-correcting codes — codewords = nullspace of parity-check matrix.

**Lesson 11: Complete Solution to Ax = b**
- Explore: x = xₚ + xₙ in 3D — solution set as shifted subspace.
- Predict: "Add a nullspace vector to a solution — still a solution?" (Yes.)
- Derive: Find complete solution for a specific system.
- Code: `complete_solution(A, b)`. Reuses `rref`, `nullspace`.
- Connect: Network flows — feasible flows = affine subspace.

**Lesson 12: Independence, Basis, and Dimension**
- Explore: Two vectors in ℝ³ (span = plane). Add third: independent → dimension jumps to 3. Dependent → falls onto the plane.
- Predict: "Can 4 vectors in ℝ³ be independent?" (No.)
- Derive: Independence test via elimination.
- Code: `rank(A)`, `col_space(A)`. Reuses `rref`.
- Connect: Degrees of freedom in mechanisms.

**Lesson 13: The Four Fundamental Subspaces**
- Explore: INTERACTIVE Strang two-panel diagram. Input matrix → all four subspaces computed and drawn. A maps row space → column space, nullspace → {0}.
- Predict: "A is 5×3, rank 2. Dimensions of all four subspaces?" (C(A)=2, N(A)=1, C(Aᵀ)=2, N(Aᵀ)=3.)
- Derive: Prove dim C(A) + dim N(A) = n and dim C(Aᵀ) + dim N(Aᵀ) = m.
- Code: `four_subspaces(A)`. Reuses everything from M3.
- Connect: Kirchhoff's laws — incidence matrix subspaces = currents, voltages, loops, nodes.

---

### MODULE 4: Orthogonality / A = QR (Lessons 14–18)

**Lesson 14: Orthogonality of Vectors and Subspaces**
- Explore: Two orthogonal complement subspaces in ℝ³. Test: every vector in one ⊥ every vector in the other.
- Predict: "Why are N(A) and C(Aᵀ) orthogonal?" (From Ax = 0: each row dotted with x = 0.)
- Derive: Prove N(A) ⊥ C(Aᵀ).
- Connect: Fourier series = orthogonal decomposition of functions. Same dot product, infinite dimensions.

**Lesson 15: Projections onto Subspaces**
- Explore: 3D — vector b, subspace (plane). Projection p = closest point. Error e = b-p perpendicular to plane. Drag b; p and e update.
- Predict: "b=[1,1,1], subspace = xy-plane. Projection?" ([1,1,0].)
- Derive: P = A(AᵀA)⁻¹Aᵀ from Aᵀ(b-Ax̂) = 0.
- Code: `project(A, b)`.
- Connect: Linear regression = projection.

**Lesson 16: Least Squares**
- Explore: Scatter plot + best-fit line. Slider for noise. Residuals shown as vertical lines.
- Predict: "One extreme outlier. How much does the line shift?"
- Derive: Normal equations AᵀAx̂ = Aᵀb for a line fit.
- Code: `least_squares(A, b)`. Reuses `project`.
- Connect: GPS — 4+ satellites → overdetermined → least squares.

**Lesson 17: Gram-Schmidt and A = QR**
- Explore: Two non-orthogonal vectors. Step-by-step: subtract projection, normalize. Vectors become perpendicular.
- Predict: "After orthogonalizing, does the span change?" (No.)
- Derive: Full Gram-Schmidt on 3 vectors. Verify pairwise orthogonality. Assemble Q, R.
- Code: `gram_schmidt(A)`, `qr_factor(A)`. Reuses `project`, `norm` from L2.
- Connect: QR algorithm for eigenvalues (preview).

**Lesson 18: The Pseudoinverse**
- Explore: Non-square matrix. A⁺ = minimum-norm least-squares solution.
- Predict: "A is 3×2, full column rank. A⁺b exact or approximate?"
- Derive: A⁺ = (AᵀA)⁻¹Aᵀ for full column rank.
- Code: `pseudoinverse(A)`. Compare `np.linalg.pinv`.
- Connect: Control theory — minimum-energy input.

---

### MODULE 5: Determinants (Lessons 19–20)

**Lesson 19: Properties and Computation**
- Explore: Parallelogram (2D) / parallelepiped (3D) from columns. Area/volume = |det|. Swap columns → sign flips. Scale column → det scales.
- Predict: "Swap two rows. What happens to det?" (Sign flips.) "Scale one row by 5?" (det×5.)
- Derive: Cofactor expansion 3×3. Three properties. Det from elimination = product of pivots.
- Code: `det_cofactor(A)` (recursive), `det_elimination(A)` (pivot product).
- Connect: Jacobian — area distortion under coordinate change.

**Lesson 20: Cofactors, Cramer's Rule, Volumes**
- Explore: Cramer's rule — replacing columns of A with b; parallelogram changes.
- Predict: "det(A)=0. Can you solve Ax=b for every b?" (No.)
- Derive: Cramer's rule 3×3. Cross product as determinant.
- Code: `cramers_rule(A, b)`. Show it's O(n·n!).
- Connect: Torque, magnetic force F=qv×B, triple product.

---

### MODULE 6: Eigenvalues / A = SΛS⁻¹ (Lessons 21–25)

**Lesson 21: Eigenvalues — Ax = λx**
- Explore: Vector x on unit circle. Ax drawn for each x. Flash when Ax ∥ x — that's an eigenvector. Hunt for the special directions.
- Predict: "How many eigenvectors for this 2×2?" / "Where approximately?"
- Derive: det(A-λI) = 0 → characteristic polynomial → eigenvalues. Then (A-λI)x = 0 → eigenvectors.
- Code: `eigenvalues_2x2(A)`. Reuses `det_elimination`.
- Connect: Vibration modes — eigenvalues = natural frequencies. Tacoma Narrows.

**Lesson 22: Diagonalization and Powers**
- Explore: A = SΛS⁻¹ animated: change to eigenbasis → scale → change back. Aⁿ = SΛⁿS⁻¹.
- Predict: "Eigenvalues 0.5 and 2. After 100 multiplications, which direction dominates?"
- Derive: A = SΛS⁻¹, Aⁿ = SΛⁿS⁻¹. Fibonacci via [[1,1],[1,0]]ⁿ.
- Code: `diag_factor(A)`. Reuses `eigenvalues_2x2`, `inverse_2x2`.
- Connect: Population dynamics — Leslie matrices.

**Lesson 23: Markov Matrices and Steady States**
- Explore: Random walk on 5-node graph, 1000 steps. Distribution converges regardless of start.
- Predict: "All probability at node 1. After 10⁶ steps, what fraction at each node?"
- Derive: Prove column-stochastic → eigenvalue 1. Find steady-state eigenvector.
- Code: `power_method(A, x0, n)`, `markov_steady(P)`. Reuses `mat_vec`, `norm`.
- Connect: PageRank — the $25 billion eigenvector. Build a 5-page mini-web.

**Lesson 24: Symmetric Matrices and Spectral Theorem**
- Explore: Symmetric → eigenvectors always perpendicular, eigenvalues always real. Constrain sliders (a₁₂=a₂₁).
- Predict: "Symmetric 3×3, eigenvalues 1,2,3. det? trace?" (6, 6.)
- Derive: Prove eigenvalues real, eigenvectors orthogonal for distinct eigenvalues.
- Code: Verify A = QΛQᵀ.
- Connect: Quantum mechanics — Hermitian = real eigenvalues = measurement outcomes.

**Lesson 25: Positive Definite Matrices**
- Explore: f(x) = xᵀAx as 3D surface. PD → bowl. Indefinite → saddle. Sliders morph.
- Predict: "A = [[4,2],[2,1]]. Bowl or saddle?" (det=0, degenerate.)
- Derive: Five equivalent tests for positive definiteness.
- Code: `is_positive_definite(A)`.
- Connect: Hessian PD ↔ local minimum. Every gradient descent cares.

---

### MODULE 7: SVD / A = UΣVᵀ (Lessons 26–28)

**Lesson 26: Singular Values and Singular Vectors**
- Explore: Three-step animation: Vᵀ rotates → Σ stretches → U rotates. Unit circle → ellipse. σᵢ = semi-axis lengths.
- Predict: "3×2, rank 2. How many nonzero singular values?" (2.)
- Derive: SVD of 2×2: compute AᵀA → eigenvalues (σ²) → V → U = AV/σ.
- Code: `svd_2x2(A)`. Reuses `eigenvalues_2x2`.
- Connect: Eckart-Young — truncated SVD = best rank-k approximation.

**Lesson 27: Image Compression via Truncated SVD**
- Explore: Grayscale image as matrix. Rank slider k: details emerge. Compression ratio k(m+1+n)/(mn) updates.
- Predict: "512×512 image, rank 10. Storage?" (10,250 vs 262,144.)
- Derive: ‖A - Aₖ‖ = σₖ₊₁.
- Code: `svd_image_compress(img, k)`. Student compresses their own photo.
- Connect: Netflix — user×movie matrix, low-rank factorization powers recommendations.

**Lesson 28: PCA**
- Explore: 2D scatter, clear principal direction. Rotate projection axis via slider; variance readout changes.
- Predict: "100 features, 3D subspace. PCs for 95% variance?" (~3.)
- Derive: PCA = eigendecomposition of covariance matrix.
- Code: `pca(X, k)`. Apply to real dataset.
- Connect: Eigenfaces, genomics PCA → world map from DNA.

---

### MODULE 8: Transformations (Lessons 29–30)

**Lesson 29: Linear Transformations and Their Matrices**
- Explore: A function T: ℝ²→ℝ². Test linearity: T(u+v)=T(u)+T(v)? T(cv)=cT(v)? Pass → has matrix.
- Predict: "Is T(x) = x + [1,0] linear?" (No — T(0) ≠ 0.)
- Derive: Find matrix by computing T(e₁), T(e₂), stacking as columns.
- Code: `transform_matrix(T, n)`.
- Connect: Neural net without activations = single matrix. Why nonlinearities are essential.

**Lesson 30: Change of Basis and the Five Factorizations**
- Explore: Same transformation in two coordinate systems. Different matrix, same transformation.
- Predict: "Eigenvalues 2, 3 in standard basis. In another basis?" (Same.)
- Derive: B = P⁻¹AP. Diagonalization = change to eigenbasis.
- Code: `change_basis(A, P)`.
- Connect: Five factorizations unified:
  - CR: independent columns
  - LU: elimination
  - QR: orthogonality
  - SΛS⁻¹: eigenstructure
  - UΣVᵀ: complete geometry

  Post-quantum cryptography: lattice problems = hard linear algebra in high dimensions.

  "You have the language. Every differential equation, dataset, quantum state, neural network, search engine, and encrypted message — linear algebra is the operating system underneath."

  No completion screen. Open question: "You factored matrices (2 indices). What about tensors (3+ indices)? That's where deep learning, quantum entanglement, and general relativity live."
