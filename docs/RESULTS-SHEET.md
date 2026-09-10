# Results sheet — Ma'aden Aluminium MRO POC

*Generated from `results/` for the full preset · run 072adb7cbc4d · seed 20260909 · 2026-09-10. Every figure below is also on the screens; none was typed by hand.*

## The three headline numbers

1. **Data problems found: 98% of the faults planted in the data, at 98% precision** — 1,278 of 1,302 found, 30 false alarms, graded against a sealed answer key the engine never reads.
2. **Jobs waited 56% fewer days for parts**, on the last year of history replayed under our stock levels against the plant's own — holding +28% more stock, with all costs together -36%.
3. **Dead money found: SAR 382.8m of SAR 391.7m truly dead (98%), at 99% precision** — SAR 5.3m wrongly flagged, one reason per record.

## What is on the shelves

| | |
|---|---|
| Stock on the shelves | SAR 1,460.8m across 24,989 records in 5 storerooms |
| Parts not used in two years | 7,126 — 35% of the catalogue |
| Dead money (answer key) | SAR 391.7m — 27% of stock value |
| Dead money (found by the engine) | SAR 388.1m on 6,623 records |
| Critical parts below their safe level | 2,999, SAR 316.4m to bring back to level |
| Parts needing action today | 8,361, SAR 590.6m to bring back to level |
| Stock that could be moved instead of bought | 60 moves, SAR 6.3m saved |

## The backtest — the last year replayed under both sets of levels

365 days from 2025-09-01, 24,989 records, identical demand and identical delivery delays. The only difference is the levels.

| | The plant's levels | Ours | Change |
|---|---|---|---|
| Days waiting for a part | 855,161 | 377,469 | -56% |
| Units short over the year | 593,970 | 295,510 | -50% |
| Average value on the shelves | SAR 1,376.5m | SAR 1,756.3m | +28% |
| Cost of being short | SAR 1,377.3m | SAR 656.6m | -52% |
| Cost of holding stock | SAR 344.1m | SAR 439.1m | +28% |
| Cost of placing orders | SAR 31.7m | SAR 28.7m | -10% |
| Purchase orders placed | 35,205 | 31,836 | -10% |
| **All three costs together** | SAR 1,753.2m | SAR 1,124.4m | -36% |

**Read this honestly.** Our levels hold *more* stock, not less; the improvement is fewer days waiting and a lower total cost. Releasing cash is the dead-money finding, not the levels. The service-level sweep confirms it: the plant's own policy sits below our lowest sampled service level while holding less capital than any point on the curve (`plant_below_the_sampled_range`).

## Dead money — the engine against the answer key

| | SAR |
|---|---|
| Truly dead (answer key) | SAR 391.7m |
| Found | SAR 382.8m (98%) |
| Wrongly flagged | SAR 5.3m (precision 99%) |
| Missed | SAR 9.0m |

Obsolete materials: 1,555 true, 1,551 found, 4 missed, 122 wrongly flagged.

| Why it is dead | Records | Claimed | Correct |
|---|---|---|---|
| duplicate | 45 | SAR 3.1m | SAR 0.6m |
| excess | 289 | SAR 9.6m | SAR 9.4m |
| never_used | 4,249 | SAR 225.5m | SAR 222.8m |
| obsolete_equipment | 1,918 | SAR 146.1m | SAR 146.1m |
| obsolete_idle | 122 | SAR 3.9m | SAR 3.8m |

Most of the found figure is arithmetic on fields the plant already has — a decommissioned machine is a lookup, not a discovery. What the engine adds is applying one rule consistently across every record with a reason on each. The duplicate category is the weak one and is reported as such.

## Forecast accuracy on the held-out year

| Demand class | Records | Method | MASE, ours | Repeat last year | Always zero |
|---|---|---|---|---|---|
| intermittent | 11,738 | TSB | 0.90 | 1.03 | 0.74 |
| lumpy | 3,078 | TSB | 0.82 | 1.01 | 0.70 |
| smooth | 622 | SimpleExponentialSmoothing | 0.82 | 0.99 | 1.45 |
| erratic | 544 | SimpleExponentialSmoothing | 0.90 | 1.13 | 0.86 |

Lower is better; 1.00 is no better than repeating last year. Losing to "always zero" on sparse parts is expected and is why the levels come from the demand distribution, not the forecast.

## Limits

- Both policies are replayed against the demand that actually happened, which no forecast could have known in full. That is the point — it is the same test for both, and the question is which set of levels copes better with a year neither of them saw.
- Lead times are drawn once and shared, so the same order waits the same time under both. Without that, part of any difference would be luck.
- Unmet demand is treated as waiting, not lost: an MRO job waits for the part rather than cancelling. Days short therefore measures how long the plant waited.
- The service level is a policy — 99% for parts that stop the plant, 95% where production slows, 85% where somebody waits — and the arithmetic may only lower it for an expensive part. Those three figures are ours; the plant should set them.
- For parts that move most months the buffer is read off what actually happened in every stretch of the same length as the delivery time. For parts that move rarely it is simulated from how often and how much they move, and capped at the most the part has ever needed in such a stretch or three times what it is expected to need, whichever is larger.
- Issues against shutdown work orders are left out of the buffer: a planned outage is known months ahead and its parts belong on an order raised against the schedule, not in a permanent safety stock. That order is not raised by this system yet, so in the replayed year our levels are charged for shutdown shortages the schedule would have prevented.
- The curve is sampled at seven service levels and joined by straight lines. The point matched to the plant's own service is interpolated between two of them, and a plant outside the sampled range gets no number rather than an extrapolated one.
- Justified quantity is worked out from three years of observed issues, not from a true demand rate the engine cannot see; a part whose use has genuinely stopped still carries its old rate for a while.
- A duplicate is flagged on the matcher's word. Where the matcher is wrong the money is wrongly flagged, and that shows up in the score.

Synthetic data throughout: the plant is invented, the faults were planted and the answer key sealed. Phase 1 replaces every figure here with the plant's own.
