# KPI catalog for small businesses and products

Standard definitions to start from. Adapt the filters to the business and write them down.

## Sales (e-commerce, retail, F-commerce)

| KPI | Formula | Unit / grain | Traps |
| --- | --- | --- | --- |
| Gross revenue | sum(order total) for paid orders | currency / day-month | Decide: with or without shipping, VAT, discounts. Cash-on-delivery orders are not revenue until delivered |
| Net revenue | gross revenue - refunds - returns | currency / month | Refunds dated by refund date vs order date give different months |
| Orders | count_distinct(order_id) | count / day | Line-item exports repeat the order id; count distinct |
| Average order value (AOV) | net revenue / orders | currency / month | Median order value is more robust when a few wholesale orders exist |
| Units per order | units / orders | ratio / month | |
| Customers | count_distinct(customer_id) | count / month | Guest checkouts: phone or email as id; normalise phone format (+880 vs 0) first |
| Repeat customer rate | customers with >= 2 orders / customers | percent / month or quarter | Depends on window length; always state it |
| New customer revenue share | revenue from first orders / revenue | percent / month | |
| Cancellation rate | cancelled orders / all orders | percent / week | Include orders cancelled before payment? |
| Return/RTO rate | returned (or returned-to-origin) orders / delivered + returned | percent / week | Key for COD in Bangladesh: courier RTO costs both ways |
| Gross margin | (net revenue - COGS) / net revenue | percent / month | Needs product cost; often missing in exports |

## Marketing and website (GA4)

| KPI | Formula | Unit / grain | Traps |
| --- | --- | --- | --- |
| Sessions | count of sessions | count / day | GA4 sessions differ from Universal Analytics; do not compare across the switch |
| Engagement rate | engaged sessions / sessions | percent / week | Engaged = 10s+, 2+ page views, or a key event |
| Session conversion rate | sessions with a key event / sessions | percent / week | GA4 "key events" counts events, not sessions; a user can trigger several |
| Revenue per session | revenue / sessions | currency / month | |
| Cost per acquisition (CPA) | ad spend / new customers | currency / month | Use the same attribution window as the ad platform, or say it differs |
| ROAS | attributed revenue / ad spend | ratio / campaign-month | Platform-reported ROAS double counts across platforms |

## Product (apps, SaaS)

| KPI | Formula | Unit / grain | Traps |
| --- | --- | --- | --- |
| Daily / monthly active users | count_distinct(user_id) with a qualifying event | count / day, month | Define "active" (login? key action?) |
| Stickiness | DAU / MAU | ratio / day | |
| Activation rate | users reaching the activation event within N days / signups | percent / week cohort | Fix N |
| Month-N retention | active in month N / cohort size | percent / monthly cohort | See `cohort-retention`; partial months are not zero |
| Churn rate (subscriptions) | subscriptions cancelled in month / active at start of month | percent / month | Exclude involuntary churn (failed payments) or report it separately |
| MRR | sum(monthly recurring amount) of active subscriptions | currency / month | Annual plans: divide by 12 |
| Trial conversion | trials converting to paid / trials ending | percent / week cohort | Date by trial end, not start |

## Field rules used by the validator

- `id`: snake_case, unique across inputs and KPIs.
- `unit`: count, currency, percent, ratio, seconds, minutes, hours, days. Store percent as a fraction (0.25).
- `grain`: event, order, user, customer, session, day, week, month, quarter, year.
- `direction`: up, down or neutral.
- `zero_division`: what to show when the denominator is 0 (`null` or `0`); required (warning) for any division.
- Optional and encouraged: `currency`, `target`, `filters`, `source`, `notes`, `tags`.
