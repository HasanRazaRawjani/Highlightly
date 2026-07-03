# Highlightly Netlify + Supabase Deploy

This folder is ready for `highlightly.xyz`.

## Supabase setup

1. Open your Supabase project.
2. Go to **Settings > API Keys**.
3. Copy the **Project URL** and the **publishable key**. Do not use the secret key in browser code.
4. Open `supabase-config.js`.
5. Replace:

```js
export const SUPABASE_URL = "YOUR_SUPABASE_PROJECT_URL";
export const SUPABASE_ANON_KEY = "YOUR_SUPABASE_PUBLISHABLE_KEY";
```

with your real values.

## Supabase Auth dashboard

1. Go to **Authentication > Providers > Email**.
2. Enable **Email**.
3. Enable **Confirm email**.
4. Keep password signups enabled.
5. Go to **Authentication > Providers > Google** if you want Google login.
6. Enable Google and paste the Client ID and Client Secret from Google Cloud.
7. In Google Cloud, add this Supabase callback URL as an **Authorized redirect URI**:

```txt
https://vzpltgcafcmjsroxwmuy.supabase.co/auth/v1/callback
```

If Google shows `redirect_uri_mismatch`, this is the value it is asking for.
8. Go to **Authentication > URL Configuration**.
9. Set **Site URL** to `https://highlightly.xyz`.
10. Add redirect URLs:

```txt
https://highlightly.xyz
https://highlightly.xyz/
http://localhost:5173
http://localhost:5173/
http://127.0.0.1:5173
http://127.0.0.1:5173/
```

## Stripe checkout

This static website uses Stripe Payment Links for real payments. That is the cleanest Netlify-only setup.

1. Create or open your Stripe account.
2. Add your bank payout details in Stripe.
3. Create a recurring product called `Highlightly Pro`.
4. Set the price to `$10/month`.
5. Create one Payment Link for normal Pro checkout.
6. Create another Payment Link with a 3-day free trial if you want the trial button to work.
7. Open `app.js`.
8. Replace these two values:

```js
const STRIPE_PRO_CHECKOUT_URL = "https://buy.stripe.com/REPLACE_WITH_PRO_PAYMENT_LINK";
const STRIPE_TRIAL_CHECKOUT_URL = "https://buy.stripe.com/REPLACE_WITH_TRIAL_PAYMENT_LINK";
```

with your real Stripe Payment Link URLs.

Important: this folder can send people to real Stripe Checkout, but fully automatic paid-only access after a successful payment needs a Stripe webhook later. That webhook should update the user's Supabase plan only after Stripe confirms payment.

## Stripe payment methods

The checkout UI shows **Card**, **Cash App Pay**, and **Bank**. The real payment fields appear on Stripe Checkout after you enable those methods in Stripe.

### Card payments

1. Open the Stripe Dashboard.
2. Go to **Settings > Payment methods**.
3. Make sure **Cards** is enabled.
4. Cards should work with Stripe Checkout and Payment Links by default.

### Cash App Pay

1. Open **Settings > Payment methods** in Stripe.
2. Find **Cash App Pay**.
3. Click **Turn on**.
4. Cash App Pay is mainly for US Stripe accounts, US customers, and USD payments.
5. Make sure your `Highlightly Pro` price is in USD.

### Bank payment / US bank account

1. Open **Settings > Payment methods** in Stripe.
2. Find **ACH Direct Debit** or **US bank account**.
3. Click **Turn on**.
4. Use Stripe Checkout or Payment Links so Stripe handles bank verification.
5. ACH bank payments can take longer to fully confirm than card payments.

### Payouts to your bank

1. Open Stripe.
2. Go to **Settings > Business settings > Bank accounts and scheduling**.
3. Add your bank account.
4. Finish any identity/business verification Stripe asks for.
5. After real payments start, Stripe sends payouts to your bank based on your payout schedule.

### If a method does not show in checkout

1. Confirm the method is enabled in **Stripe > Settings > Payment methods**.
2. Confirm your business country, customer country, and currency support that method.
3. Confirm your Payment Link uses a recurring `$10/month` USD price.
4. Check that your Stripe account is fully activated for live payments.

## Deploy

Deploy this folder with Netlify. The website now uses Supabase for accounts, email verification, sign in, sign out, and password reset. Netlify only hosts the static site.

## Desktop app

Replace `downloads/Highlightly-Desktop-Access.txt` with your real installer later. If the filename changes, update `downloadHref` in `app.js`.
