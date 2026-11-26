# Interpreting A/B test results

## Formulas used

- Rates: `p = conversions / visitors` per group.
- Lift: absolute `p_B - p_A` (percentage points), relative `(p_B - p_A) / p_A`.
- Pooled two-proportion z-test: `p = (x_A + x_B) / (n_A + n_B)`,
  `z = (p_B - p_A) / sqrt(p (1 - p) (1/n_A + 1/n_B))`; two-sided p-value `2 (1 - Phi(|z|))`,
  `--alternative greater` gives `1 - Phi(z)` (only if this direction was decided before the test).
- Confidence interval for the difference (unpooled Wald):
  `(p_B - p_A) +/- z_(1-alpha/2) sqrt(p_A (1-p_A)/n_A + p_B (1-p_B)/n_B)`.
- Several variants: each is compared with the control at `alpha / (number of variants)`
  (Bonferroni), and the CI uses the same adjusted level.
- SRM: chi-square goodness of fit of visitor counts against the planned split; mismatch if
  p < 0.001.
- Sample size per group (two-sided):
  `n = (z_(1-alpha/2) sqrt(2 pbar (1-pbar)) + z_(1-beta) sqrt(p1 (1-p1) + p2 (1-p2)))^2 / (p2 - p1)^2`
  with `pbar = (p1 + p2) / 2`. Baseline 5%, +10% relative, alpha 0.05, power 0.8 gives 31,234.

## Decision table

| SRM | p-value | Sample reached planned size | Decision |
| --- | --- | --- | --- |
| mismatch | any | any | Stop. Fix assignment/tracking (bots, redirects, caching, filters applied to one arm). Rerun |
| ok | < alpha, CI above 0 | yes | Ship if the lower CI bound is worth the cost |
| ok | < alpha | no (stopped early) | Treat as a hint only; early stopping inflates false positives. Continue to plan or rerun |
| ok | >= alpha | yes | No detectable effect of the planned size. Keep the simpler version; test something bolder |
| ok | >= alpha | no | Keep running to the planned size |

## Common mistakes to point out

- **Peeking**: checking daily and stopping at the first p < 0.05 makes the false positive
  rate several times higher than 5%. Fix the sample size in advance.
- **Wrong unit**: users were randomised but sessions or page views are counted; the test
  assumes independent units.
- **Novelty and weekday effects**: run whole weeks; very short tests over-weight the launch days.
- **Many metrics**: if ten metrics are checked, one will look significant by chance. Pick a
  primary metric before the test.
- **Tiny counts**: with fewer than ~10 conversions per group the normal approximation is
  rough; collect more data (an exact test is a good first issue).
- **Relative lift on tiny rates**: +50% of 0.2% is 0.1 points; report both.
- **"No significant difference" is not "no difference"**: quote the CI.
