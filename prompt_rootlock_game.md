## Core concept: **ROOTLOCK**

The game should not feel like school with points added. It should feel like a minimalist puzzle machine where every quadratic is a compact lock containing two hidden numbers.

A solve should take roughly 10–40 seconds. The next puzzle should appear immediately. No dialogue, no chapter introduction, no “today we will learn…”. The player learns because the same structure keeps reappearing with slight mutations.

The crucial design idea is:

> **Start with the hidden-number puzzle, then reveal that a quadratic equation is just a compressed version of it.**

### The first mechanic

The player sees two empty slots and two constraints:

[
r_1+r_2=5
]

[
r_1r_2=6
]

They place (2) and (3) into the slots.

The lock clicks open.

Next:

[
r_1+r_2=7,\qquad r_1r_2=12
]

They place (3) and (4).

After several rounds, the game presents:

[
x^2-5x+6=0
]

The coefficients physically unfold into:

[
r_1+r_2=5,\qquad r_1r_2=6
]

Now the player understands, without needing a paragraph of explanation, that the quadratic is encoding the same two-number puzzle.

That is the foundation of the entire game.

---

## What solving one puzzle feels like

For

[
x^2-5x+6=0
]

the board contains two root sockets. As the player tries numbers, two live indicators show:

[
\text{sum}=5
]

[
\text{product}=6
]

Placing (2) and (3) causes the equation to fold into:

[
(x-2)(x-3)=0
]

The two factors then separate into two channels:

[
x=2,\qquad x=3
]

The animation should make the structure feel mechanical: two roots were hidden inside one equation, and the player released them.

A clean solve produces a crisp sound, a short visual collapse, and the next equation immediately slides into place. The satisfaction comes from recognition and fluency, not from collecting coins.

Keyboard entry should be supported from the beginning. Once players become fluent, they should be able to solve equations almost as quickly as they can recognize them.

---

# The progression

The game should increase complexity along **one axis at a time**. Never introduce new notation, harder arithmetic, extra steps, and a new concept simultaneously.

## 1. Number-pair locks

No (x) yet.

Find two numbers from their sum and product:

[
r_1+r_2=8,\qquad r_1r_2=15
]

Then introduce:

* negative roots;
* one positive and one negative root;
* repeated roots;
* zero as a root;
* larger numbers.

This establishes the intuition behind Vieta’s formulas before naming them.

## 2. Quadratics as encoded pair locks

Introduce only equations of the form:

[
x^2-Sx+P=0
]

The game visibly maps (S) to the root sum and (P) to the root product.

At first the mapping remains displayed. Then it fades. Eventually the player sees only the equation.

The player gradually begins looking at

[
x^2-11x+24
]

and immediately sensing “3 and 8.”

That recognition is the central pleasure of the early game.

## 3. Factoring

Now the player constructs:

[
(x-r_1)(x-r_2)
]

Factoring is not introduced as another formula. It is presented as the physical act of opening the equation.

Special patterns become recognizable puzzle families:

[
x^2-9
]

[
x^2+6x+9
]

[
x^2-10x+25
]

These become “veins” of related puzzles: a player may encounter several difference-of-squares puzzles in a row, become comfortable with them, and then encounter them mixed with older patterns.

This is similar to the mining-vein structure you described for the endless card game: the player finds a rich structural region and learns to exploit it.

## 4. Leading coefficients

Introduce:

[
2x^2-7x+3=0
]

But do not introduce several methods at once.

The board can first offer a rectangular factor grid:

[
(2x-1)(x-3)
]

The player learns that the leading coefficient changes the possible factor pieces. Only after this feels ordinary should the game introduce splitting the middle term or more difficult coefficient combinations.

## 5. The discriminant scanner

Eventually the player encounters a quadratic that will not factor nicely:

[
x^2-2x-1=0
]

The familiar root sockets no longer accept integer pieces.

A new tool unlocks:

[
D=b^2-4ac
]

The player assembles the discriminant from the equation’s coefficient tiles. The result drives the physical state of the lock:

* (D>0): the lock splits into two channels;
* (D=0): the channels merge into one;
* (D<0): no real channel opens.

This should initially be a **classification mechanic**, not immediately a full quadratic-formula exercise.

The player repeatedly answers only:

> Two real roots, one repeated root, or no real roots?

That keeps the new mechanic small.

## 6. Quadratic formula assembly

Once discriminant classification is automatic, the rest of the formula becomes a construction puzzle:

[
x=\frac{-b\pm\sqrt D}{2a}
]

The player builds three components:

[
-b,\qquad \sqrt D,\qquad 2a
]

Then the board splits at the (\pm) symbol and produces two roots.

At first, every number simplifies cleanly. Radicals and fractions are introduced later, one at a time.

The player should never have to read two pages explaining the formula. The interface teaches where each coefficient goes by making the player place it.

## 7. Completing the square

The equation becomes a geometric packing puzzle.

For

[
x^2+6x
]

the player arranges an (x^2) square and two (3x) strips. A missing (3\times3) corner remains. Filling it creates:

[
(x+3)^2
]

The game then automatically compensates on the other side of the equation.

This turns “completing the square” from an arbitrary symbolic ritual into a literal spatial operation.

After enough repetition, the visual board can gradually disappear and leave only the algebra.

## 8. Parabolas and vertices

The completed-square form:

[
(x-h)^2+k
]

physically rotates into a graph. The center of the packed square becomes the vertex:

[
(h,k)
]

The new puzzles ask for:

* the vertex;
* the axis of symmetry;
* maximum or minimum;
* whether the graph intersects the axis;
* how many roots it has.

This is where the discriminant, factoring, and geometry begin reinforcing one another instead of existing as separate lessons.

## 9. Quadratic inequalities

The roots fall onto a number line as boundary markers.

For:

[
x^2-5x+6>0
]

the player first finds (2) and (3). The parabola then shows which intervals are above zero, and the player selects:

[
x<2\quad\text{or}\quad x>3
]

The new mechanic is only interval selection. Solving the quadratic remains familiar.

## 10. Parameter puzzles

Now the equation contains a control dial:

[
x^2+kx+4=0
]

The player moves (k) and watches two roots approach, merge, or disappear.

The objective might be:

> Find all values of (k) that produce two distinct real roots.

The discriminant has now become a puzzle about an entire family of equations:

[
k^2-16>0
]

This is a major conceptual step, but the player already knows every component. The complexity comes from recombination, not from a sudden dump of new material.

---

# How new mechanics should be taught

Every mechanic should follow the same rhythm:

1. **One silent demonstration.** A ghost hand performs one move.
2. **Three nearly identical imitation puzzles.**
3. **A run of simple variations.**
4. **Interleaving with old mechanics.**
5. **A synthesis puzzle using two familiar ideas together.**

No tutorial should take longer than a few seconds. Detailed explanations can exist behind a help button, but they should never interrupt play.

A useful content ratio is approximately:

* 70% comfortable patterns;
* 20% slightly altered patterns;
* 10% genuinely challenging puzzles.

That creates the feeling of flow. The player is usually succeeding, occasionally thinking, and rarely lost.

---

# The endless structure

The primary mode should be an infinite worksheet that behaves more like a good arcade puzzle game.

An equation slides in. The player solves it. It collapses. The next one arrives.

There does not need to be a harsh clock. The core reward is the uninterrupted run.

The game can track:

* clean solves without incorrect operations;
* recognition time before the first move;
* number of transformations;
* consecutive correct discriminant predictions;
* successful use of multiple valid methods;
* mastery of specific structural families.

A player might develop a streak in perfect-square trinomials, difference-of-squares equations, repeated roots, mixed-sign roots, or non-monic factorization.

The difficulty system should notice specific weaknesses. Someone repeatedly making sign errors should receive a short cluster of mixed-sign puzzles, not be sent back through an entire chapter.

---

# Procedural generation

Quadratic puzzles are unusually suitable for controlled generation because the game can generate them **backward from their roots**.

Choose:

[
r_1,\quad r_2,\quad a
]

Then construct:

[
a(x-r_1)(x-r_2)=0
]

and expand it:

[
ax^2-a(r_1+r_2)x+ar_1r_2=0
]

This guarantees that the puzzle has the intended answer and lets the generator precisely control:

* root size;
* root signs;
* repeated versus distinct roots;
* integer, rational, irrational, or complex roots;
* leading coefficient;
* coefficient size;
* common factors;
* whether factoring is obvious or disguised;
* discriminant size;
* number of necessary transformations.

The game should have a measurable **complexity budget**. For example, increasing root magnitude should not happen in the same puzzle where fractions and a new factoring structure are first introduced.

---

# Avoid a common mistake: forcing one approved method

The player should generally be allowed to solve an equation by any valid unlocked method.

A factorable equation may be solved by:

* inspection;
* factoring;
* completing the square;
* quadratic formula;
* graph reasoning.

The game can occasionally create a challenge that says “solve without the formula” or “solve using completing the square,” but those should be special drills rather than arbitrary restrictions everywhere.

Once players become proficient, choosing the most efficient method becomes part of the game:

[
x^2-49=0
]

should immediately suggest difference of squares, while:

[
3x^2-2x-7=0
]

may suggest the quadratic formula.

The real advanced skill is not merely performing an algorithm. It is recognizing which tool makes the equation collapse fastest.

---

# How calculus enters without a complexity explosion

The calculus branch begins with the parabola the player already understands.

For:

[
f(x)=x^2-6x+5
]

the player already knows the vertex lies at (x=3). Now a movable tangent line is added. As the player moves along the parabola, a slope meter changes.

At the vertex, the slope becomes zero.

Only then does the game reveal:

[
f'(x)=2x-6
]

and:

[
2x-6=0
]

The derivative is initially just another familiar linear equation that locates the vertex.

Progression can then move through:

* finding where slope equals zero;
* finding maximum or minimum values;
* rectangle-area optimization;
* projectile height;
* minimizing distance;
* comparing multiple local extrema in higher-degree functions.

Calculus enters as a new **question asked about a familiar shape**, not as an entirely new symbolic universe.

---

# How linear algebra enters

The linear-algebra branch begins with systems:

[
x+y=7
]

[
xy=10
]

The player recognizes that (x) and (y) are the two roots of:

[
t^2-7t+10=0
]

Then introduce genuinely linear systems:

[
\begin{cases}
2x+y=7\
x-y=2
\end{cases}
]

The same balancing and transformation gestures used on equations now operate on entire rows.

Matrices appear only as a compact way of packaging those rows:

[
\begin{pmatrix}
2&1\
1&-1
\end{pmatrix}
\begin{pmatrix}
x\y
\end{pmatrix}
=============

\begin{pmatrix}
7\2
\end{pmatrix}
]

The player already understands the operations before the matrix notation appears.

Much later, the two branches converge in a quadratic surface:

[
f(x,y)=3x^2+2xy+2y^2
]

Calculus supplies the gradient. Linear algebra supplies the matrix, eigenvectors, and principal directions. But by then, each piece has been drilled independently.

---

# The game’s larger structure

I would use three layers:

### **Flow**

An endless, low-pressure stream of short equations. This is the core experience and should feel good even without progression rewards.

### **Veins**

Focused runs centered on one structural family: repeated roots, mixed signs, perfect squares, discriminant classification, parameter thresholds, and so on. These develop intuition through concentrated repetition.

### **Locks**

Occasional longer puzzles that recombine familiar mechanics. These are not traditional bosses with inflated difficulty. They are compact synthesis problems that ask the player to recognize a path.

For example, a lock might require:

1. rearranging an equation into standard form;
2. predicting the number of roots;
3. solving it;
4. placing the roots on a number line;
5. selecting the interval where the expression is negative.

No new rule appears during the lock. It only tests whether old mechanics have fused into intuition.

---

# The MVP

The first playable version should contain only:

1. sum-and-product root pairs;
2. monic factorable quadratics;
3. positive, negative, and repeated roots;
4. discriminant classification;
5. an endless generated sequence;
6. immediate keyboard controls and satisfying solve feedback.

That is enough to answer the most important question:

> Is it enjoyable to solve 100 of these in one sitting?

Do not begin with a story, skill tree, character upgrades, calculus, matrices, or a large visual world. First make the act of opening one quadratic feel good. Everything else can grow from that.

The strongest design is essentially **Tetris for algebraic recognition**: a tiny rule set, instant repetition, increasingly compressed perception, and the gradual experience of seeing structure before consciously calculating it.

