# Orders export columns by platform

Auto-detection matches these normalised names (lowercase, spaces to `_`):

| Role | Detected names (first match wins) |
| --- | --- |
| order | order_id, order_number, order_no, order, invoice_id, invoice, name, id |
| date | order_date, date, created_at, created, ordered_at, paid_at, timestamp, datetime |
| customer | customer_id, customer, customer_email, email, phone, user_id, buyer, client |
| product | product, product_name, item, item_name, sku, lineitem_name, title, product_title |
| quantity | quantity, qty, units, lineitem_quantity, item_quantity |
| price (unit) | unit_price, price, lineitem_price, item_price, rate |
| amount (row total) | line_total, amount, total, revenue, sales, net_sales, subtotal, grand_total, value |
| status | status, order_status, financial_status, payment_status, state |

If both a unit price and a quantity exist, revenue per row = price x quantity; otherwise the
amount column is used. `--amount-col` forces the amount column.

## Shopify (Orders > Export)

One row per line item. Order-level fields (Total, Financial Status) are filled only on the
first line of each order.

```bash
python3 scripts/sales_report.py orders_export.csv --order-col Name --date-col "Created at" \
  --customer-col Email --product-col "Lineitem name" --quantity-col "Lineitem quantity" \
  --price-col "Lineitem price" --status-col "Financial Status"
```

Line prices exclude shipping and order-level discounts, so revenue is slightly higher than
"Total sales" in Shopify Analytics. Say so.

## WooCommerce (Analytics > Orders > Download, or an export plugin)

Usually one row per order: `Order ID`, `Date`, `Status`, `Customer`, `Net Sales` /
`Order Total`, `Product(s)`. Use `--amount-col "Net Sales"`. Statuses look like
`completed`, `processing`, `cancelled`, `refunded`, `failed`, `on-hold`, `pending`;
consider `--exclude-status cancelled,refunded,failed,pending,on-hold`.

## Daraz Seller Center (Orders export)

One row per item: `Order Number`, `Created at`, `Item Name`, `Unit Price`, `Status`
(`delivered`, `canceled`, `returned`, `shipped`). Customer ids are usually absent, so repeat
metrics are not available; the script reports orders without customer id.

## Facebook/Instagram shops kept in Google Sheets

Typical manual columns: `Date`, `Customer Name`, `Phone`, `Product`, `Qty`, `Price`,
`Delivery Charge`, `Status`. Normalise phone numbers and dates with `data-cleaning`
(`--ascii-digits` for Bangla digits in phone numbers) and use `--customer-col Phone`.

## POS / accounting exports

Often daily totals only (no order id): each row becomes one "order", so AOV is meaningless.
Use `anomaly-alerts` for the daily series instead.
