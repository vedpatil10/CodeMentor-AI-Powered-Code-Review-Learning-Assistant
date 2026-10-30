# Offline Regression Rubric

This tiny synthetic dataset checks the deterministic validation path, not model
quality. It contains one supported finding, one clean change that should produce
no finding, and one candidate whose evidence must be rejected. It is not large
or representative enough to support accuracy or product-performance claims.

An accepted finding is a true positive only when its path, changed line, and
category match a labeled expected finding. Other accepted findings are false
positives. Expected findings not matched by accepted output are false negatives.
Rejected candidates are reported by reason and do not count as published
predictions.

Run with `uv run --locked codementor-evaluate-fixtures`. The JSON report includes
case-level counts, precision, recall, and rejection reasons. Expand this dataset
with permitted, human-labeled pull requests before using these metrics to tune a
model, prompt, retrieval strategy, or publication threshold.