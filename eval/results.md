# Categorisation evaluation

- Model: `gpt-6.1-terra`
- Date: 2026-11-25 14:36 UTC
- Runs per set: 3
- Target per set: at least 90% matching and exact totals

## Summary

| Set | Statement | Transactions | Matching the hand labels | Same category in all runs | Runs whose totals add up | Target |
|---|---|---|---|---|---|---|
| Easy set | `sample_sept` | 25 | 100.0% (75/75) | 100.0% (25/25) | 3/3 | met |
| Realistic set | `demo_nov` | 70 | 94.3% (198/210) | 100.0% (70/70) | 3/3 | met |

## Easy set: sample_sept

`data/sample_sept.csv` (25 transactions), 3 runs, compared with `data/sample_sept_labels.csv`.

- Matching the hand labels (all runs): 100.0% (75/75)
- Same category in all 3 runs: 100.0% (25/25)
- Runs whose totals add up: 3/3
- Target: met

### Per run

| Run | Matching | Needs review amount | Totals add up |
|---|---|---|---|
| 1 | 100.0% (25/25) | -37.90 | yes (-127.18 = -127.18) |
| 2 | 100.0% (25/25) | -37.90 | yes (-127.18 = -127.18) |
| 3 | 100.0% (25/25) | -37.90 | yes (-127.18 = -127.18) |

### Per category (hand label, all runs pooled)

| Category | Matching |
|---|---|
| Rent | 100.0% (3/3) |
| Groceries | 100.0% (18/18) |
| Eating out | 100.0% (21/21) |
| Transport | 100.0% (9/9) |
| Subscriptions | 100.0% (3/3) |
| Shopping | 100.0% (6/6) |
| Income | 100.0% (3/3) |
| Transfer to own account | 100.0% (3/3) |
| Other | n/a |
| Needs review | 100.0% (9/9) |

### Mismatches

None.

## Realistic set: demo_nov

`data/demo_nov.csv` (70 transactions), 3 runs, compared with `data/demo_nov_labels.csv`.

- Matching the hand labels (all runs): 94.3% (198/210)
- Same category in all 3 runs: 100.0% (70/70)
- Runs whose totals add up: 3/3
- Target: met

### Per run

| Run | Matching | Needs review amount | Totals add up |
|---|---|---|---|
| 1 | 94.3% (66/70) | -48.00 | yes (-410.06 = -410.06) |
| 2 | 94.3% (66/70) | -48.00 | yes (-410.06 = -410.06) |
| 3 | 94.3% (66/70) | -48.00 | yes (-410.06 = -410.06) |

### Per category (hand label, all runs pooled)

| Category | Matching |
|---|---|
| Rent | 100.0% (3/3) |
| Groceries | 100.0% (42/42) |
| Eating out | 100.0% (72/72) |
| Transport | 100.0% (24/24) |
| Subscriptions | 100.0% (6/6) |
| Shopping | 100.0% (21/21) |
| Income | 100.0% (3/3) |
| Transfer to own account | 100.0% (3/3) |
| Other | 55.6% (15/27) |
| Needs review | 100.0% (9/9) |

### Mismatches

| Date | Description | Hand label | Run 1 | Run 2 | Run 3 |
|---|---|---|---|---|---|
| 2025-11-10 | PALESTRA FITACTIVE MILANO ABBONAMENTO | Other | Subscriptions | Subscriptions | Subscriptions |
| 2025-11-13 | FARMACIA COMUNALE MILANO CARTA 5555555555554444 | Other | Shopping | Shopping | Shopping |
| 2025-11-16 | BONIFICO DA ROSSI MARIO CAUSALE REGALO | Other | Income | Income | Income |
| 2025-11-24 | FIORERIA NAVIGLI REGALO COMPLEANNO | Other | Shopping | Shopping | Shopping |
