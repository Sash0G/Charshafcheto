# Чаршафчето — online store (dropshipping)

A production-ready e-commerce store built with Django 5.2. It keeps the visual design of the original prototype, which is kept in `prototype/` for reference.

## Quick start (local development)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo "DJANGO_DEBUG=1" > .env
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo --admin-password admin12345   # demo catalog, orders, admin
.venv/bin/python manage.py runserver
```

- Store: http://localhost:8000
- Admin panel: http://localhost:8000/dashboard/ (`admin@charshafcheto.bg` / `admin12345`)
- Demo customer: `maria@example.com` / `demo-pass-123`
- In development, emails are printed to the terminal.

Run the tests with `DJANGO_DEBUG=1 .venv/bin/python manage.py test`.

## What's included

**Storefront**: home page, catalog with categories, search, filters (price, material, in stock), sorting and pagination. Product pages have a gallery, size variants, stock levels, reviews (verified buyers, moderated) and related products. Also a wishlist, a slide-out cart drawer plus a full cart page, promo codes, and a free-shipping progress bar.

**Checkout**: guest or logged-in checkout. Delivery by Speedy or Econt to an office or an address. Payment by cash on delivery, card (Stripe) or bank transfer. Company invoice details (ЕИК/МОЛ), terms acceptance, stock locking so items can't be oversold, and a confirmation page and email. Customers can track an order by number and email, cancel it while it's still new, and print an order confirmation.

**Customer accounts**: registration with email verification, login with lockout after repeated failures, and password reset and change. Customers get an order history, saved addresses, and a profile page. GDPR tools let them export their data (JSON) and delete their account. Guest orders are attached to an account only after its email is verified.

**Admin panel (`/dashboard/`)**:
- Dashboard: revenue, profit and margin, plus a sales chart and a low-stock list.
- Orders: status workflow with customer emails, tracking numbers, payments, and a printable proforma and packing slip.
- Products: variants, multiple images, CSV import and export.
- Catalog and customers: categories, suppliers, customers, coupons, review moderation, shipping methods, and editable pages (delivery, returns, terms, privacy).
- Inbox: contact messages and newsletter subscribers.
- Store settings: currency, free-shipping threshold, company and bank details.
- Team management and an audit log of every admin change.

**Dropshipping**: each product has a supplier, a supplier SKU and a cost price. Margin is tracked per product and per order. When an order is confirmed, its items are grouped per supplier and emailed to each supplier, either automatically (`auto_forward`) or with one click. Each supplier order has its own status, reference and tracking number.

**SEO and other basics**: clean Latin slugs (transliterated Bulgarian), sitemap.xml, robots.txt, Open Graph tags, Product JSON-LD, canonical URLs and a cookie notice. Prices are shown in both EUR and BGN at the fixed rate; this can be switched off in Settings.

## Production deployment

```bash
cp .env.example .env        # fill in the secret key, domain, DB password, SMTP and Stripe keys
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

This starts PostgreSQL, the Django app (gunicorn), Caddy (automatic HTTPS, and serves uploaded images), and a worker. Every 15 minutes the worker cancels card orders that were never paid and releases their stock.

**Stripe**: set the keys in `.env`, then add a webhook endpoint at `https://<domain>/checkout/stripe/webhook/` for the events `checkout.session.completed`, `checkout.session.expired`, `checkout.session.async_payment_succeeded` and `checkout.session.async_payment_failed`. Card payment stays hidden at checkout until the keys are set. Bank transfer appears once an IBAN is entered in Settings.

## Before going live

- Replace the placeholder text of **Общи условия** and **Политика за поверителност** (Dashboard → Страници) with versions reviewed by a lawyer.
- Fill in the company name, ЕИК and IBAN in Dashboard → Настройки.
- Real product photos: upload JPG or PNG files; they are resized and converted to WebP automatically.
- Set up backups of the `pgdata` and `media` Docker volumes.
- Invoices: the system produces order confirmations and proformas. Legally numbered invoices should come from your accounting software.
