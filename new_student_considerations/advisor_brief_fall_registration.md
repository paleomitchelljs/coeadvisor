# Fall Registration: Advisor Decision Brief

**Audience**: Freshman advisors at fall registration.
**Goal**: A small number of unobtrusive yes/no questions that shape concrete scheduling choices. Drawn from N = 1,405 freshmen across cohorts 2020–2025.

---

## Framing: triage, not steering

The strongest result in the data is that **failing a fall course in the student's stated interest department hits retention roughly 2.5× harder than failing outside it** (brms contrast +0.52 log-odds, posterior probability 0.95; aligned fail ≈ 1.2 SD of HS GPA worth of retention risk).

But a counterfactual analysis shows the expected benefit of *prophylactically* steering a weak-but-interested student out of an aligned hard course is tiny — under 1 percentage point even when the fail rate is 20%. So these questions are **not** prescriptions to re-route students. They are questions that:

1. Identify which students need the **sharpest midterm monitoring**.
2. Identify schedule-composition choices where a small edit has real leverage.

---

## The five questions

You already ask (1). Questions (2)–(5) below are proposed additions.

### 1. "Is the student strong or weak in science/math?" *(existing)*
Maps to: BIO 120 vs BIO 155; MTH 135 vs no math.

### 2. "Is a hard-landing course in the student's stated interest area?"
*Hard-landing courses*: **BIO 145, MTH 135, CS 125, PHY 185, CHM 121.**

- **Yes** → flag the student for priority midterm-F monitoring in that course. Do **not** re-route them out of it (EV of steering < 1 pp). At midterm, an **F** in this course is the single sharpest retention signal we measured.
- **No** → standard monitoring.

*Evidence*: aligned fail β = +0.76 [0.28, 1.34]; unaligned fail β = +0.24 [−0.01, 0.48]. See `real_out/interest_aligned/figures/fig_interest_aligned_fail.png`.

### 3. "Is the student declared in Education, Physics, Engineering Physics, or Biochemistry?"
These four departments have aligned-fail penalties whose posterior CrIs credibly exceed zero (1.06 to 1.49 log-odds, vs. pooled mean 0.76). In declared-CS and -Nursing students, the slope is near zero — so the "aligned hard course" flag from Q2 is much sharper for these four programs than for others.

- **Yes** → apply Q2 and Q4 strictly. A declared-Education student taking EDU 101 in fall is the clearest single triage case in the freshman class.
- **No** → standard application of Q2.

*Evidence*: per-dept forest, `real_out/interest_aligned/brms/fig_per_interest_aligned_fail.png`.

### 4. "Does the fall schedule have at least one course outside the interest area?"

- **No (all in-dept)** → add one breadth course.
- **Yes** → no action.

*Why*: (a) weak students benefit specifically from schedule diversity (diversity × low-GPA interaction β = −0.21, p = 0.003); (b) spring non-retention rises sharply for students who leave the interest dept entirely (spring pivot β = +0.74 [0.38, 1.10]), which suggests that having *any* in-dept engagement protects retention, but also that over-concentration now may push pivoting later. A one-course anchor outside the interest area keeps both levers available.

### 5. "Does the fall schedule contain 2+ hard-landing courses, or MTH 135 paired with another hard-landing course?"

- **Yes** → unstack. Move one hard-landing course to spring.
- **No** → no action.

*Why*: MTH 135 carries documented co-enrollment drag (β = −0.263 on co-enrolled course GPA in the partial-pooled model), plus it is itself a hard-landing course. Compound hard-landings multiply risk.

---

## Decision flow

```
  Q1 (existing)   Strong/weak?               ─►  BIO 120 vs 155, MTH 135 or not

  Q2              Hard course in interest?   ─►  Flag for midterm-F monitoring
  Q3              Interest = EDU/PHY/EP/BCM? ─►  Stricter Q2 + Q4
  Q4              Any breadth course?        ─►  If no, add one
  Q5              2+ hard OR MTH 135 + hard? ─►  If yes, unstack
```

At most three concrete schedule edits emerge: add a breadth course, unstack hard-landings, and mark a midterm-F triage flag in the advising record.

---

## Midterm protocol (what happens if Q2 fires)

The midterm extension of the analysis showed that the triage threshold is **F, not D**:

| Midterm grade | In aligned dept | In unaligned dept |
|---|---|---|
| D+ / D / D- | Monitor — recovery rate 45% | Support — recovery rate 31% |
| **F** | **Aggressive intervention.** This is the triage case. | Standard academic support. |

Counterintuitively, an aligned **D** at midterm recovers *better* than an unaligned D (44.7% vs 31.4% to C-or-better by finals). The identity investment in the interest department appears to help at the warning-grade level. The retention penalty emerges only when the grade actually tips to F.

---

## Effect magnitudes at a glance

Baseline typical student: **P(not retained to spring) = 6.0%**.

| Scenario | P(not retained) | Δ vs baseline |
|---|---|---|
| +1 unaligned fail | 7.4% [5.6, 9.8] | +1.4 pp |
| +1 aligned fail | **10.4% [7.5, 14.4]** | **+4.4 pp** |
| +2 aligned fails | 17.5% [9.9, 29.0] | +11.4 pp |
| 1 SD lower HS GPA | 9.5% [7.5, 12.0] | +3.5 pp |
| Weak student (HS −1 SD, commit −1 SD) | 12.3% [9.4, 16.0] | +6.3 pp |
| Weak student + 1 aligned fail | **20.4% [14.6, 27.7]** | **+14.3 pp** |

Lever equivalence:
- 1 aligned fail ≈ 1.21 SD of HS GPA
- 1 unaligned fail ≈ 0.46 SD of HS GPA

See `real_out/interest_aligned/brms/fig_advising_magnitudes_brms.png`.

---

## What this brief is **not**

- **Not a steering rule.** EV of moving a weak-but-interested student out of an aligned hard course is < 1 pp even when the fail rate is 20%. Don't re-route them.
- **Not a prophylactic screen.** These questions identify students who deserve sharper midterm attention, not students who should be told to take different courses before they see a grade.
- **Not a spring rescue plan.** The aligned-fail signal is fall-specific; by sophomore transition it is washed out (brms contrast +0.05, p_posterior 0.41). No specific spring intervention rescues aligned fall-failers more than it helps anyone else. Spring commit-building (shift_commit β = −0.46) helps *everyone*.
- **Not a reason to remove students from their stated interest.** Students who end up with zero in-dept exposure by spring leave at much higher rates (pivoted β = +0.74). Keep the interest anchor; just make sure it is not the student's *only* anchor.

---

## Source files

| Artifact | Path |
|---|---|
| Full pooled-model results (frequentist + brms) | `real_out/interest_aligned/interest_aligned_fail_results.txt`, `.../brms/brms_results.txt` |
| Per-interest-area forest | `.../brms/fig_per_interest_aligned_fail.png` |
| Absolute-magnitude scenario forest | `.../brms/fig_advising_magnitudes_brms.png` |
| Midterm triage results | `.../midterm/midterm_results.txt` |
| Scenario table | `.../advising_magnitudes_table.txt` |
| Script | `code/x01_clean_data/interest_aligned_fail_test.R` |
