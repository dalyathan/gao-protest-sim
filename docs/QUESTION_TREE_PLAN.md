# Question-path predictor (plan, 2026-11-13)

**Goal:** predict GAO's ruling and explain it by asking an LLM the right yes/no questions about a
case, in the right order, and stopping when more questions would not change the prediction.

## Formulation
- States = what has been asked and answered so far. Graph is acyclic (knowledge only grows).
- Step weight w(state, q) = lambda - expected information gain(q | state): history-dependent,
  negative when a question is worth asking. "Stop and predict" edge = expected prediction loss.
- Objective: minimise E[log-loss at stop] + lambda x (number of questions).
  This is a stochastic shortest-path / active feature acquisition problem.
- LLM answers are noisy: plain greedy information gain can fail badly (Golovin, Krause & Ray 2010);
  compare against EC2-style noise-robust selection.

## Simplest solutions first (Surafel, 2026-11-13: "the simplest solution can be one question")
The search space MUST include, and the comparison MUST report:
0 questions  - base rate ("always denied" / ~14-16% sustain).
1 question   - the single direct question "Will GAO sustain this ground?" (= single-agent baseline),
               and the best single question from the bank.
Longer paths are only kept if they beat these on the check set by more than noise. lambda makes
extra questions pay for themselves.

## Pipeline
1. Question bank (~60), seeded from GAO doctrine (timeliness, stated criteria, documentation,
   disparate treatment, price/cost, prejudice), factual not conclusory.
2. Training data: HeinOnline decisions, facts-only split, names/B-numbers removed. Private research
   use only (library terms). Labels: overall outcome (per-ground needs a Haiku extraction pass).
3. One call per case answers all questions: answer, confidence, evidence, what is missing
   (metacognition). Model: Sonnet 4.6 (Sonnet 4 is retired). Calibrate stated confidence.
4. Learn on train split; choose between: 0/1-question baselines, single tree, rule list, weighted
   checklist, forest, greedy vs EC2 vs look-ahead question paths, and whether nodes see earlier
   answers / confidence / evidence. Pick on the check split.
5. Freeze; one run on the 66 post-cutoff merits cases alongside the game and single-agent arms.

## Related work
ACT (agentic classification tree), Tree Prompting (EMNLP 2023), GPTree, Balek et al. 2025;
active feature acquisition survey (arXiv 2502.11067), Shim et al. NeurIPS 2018;
Golovin-Krause adaptive submodularity / EC2; Uncertainty of Thoughts, BED-LLM, CA-BED (ICLR 2026).
