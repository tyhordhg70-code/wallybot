# WallyBot – Product Requirements Document

## Original problem statement
> fix the bot not working right now on start or any functions. also barcodes
> generated should be Gs1 databar expanded right now it generates a pdf417.
> there is a special algorithm it should follow on how gs1 is generated so make
> sure it follows that also. make the product images slightly larger also.

## Application
Telegram bot (`bot.py`) that sells time-boxed subscriptions paid in crypto via
HoodPay, scrapes Walmart product pages for UPC + image, and renders
manufacturer-style coupon images with a GS1 DataBar Expanded barcode.

## Tech stack
- python-telegram-bot 22.7, psycopg2 (PostgreSQL), Pillow, treepoem (needs
  Ghostscript), BeautifulSoup4, curl_cffi, HoodPay SDK.

## Core requirements (static)
- `/start` always responds even if DB/network is degraded.
- Coupon barcode MUST be GS1 DataBar Expanded (no PDF417 / no Code128 fallback).
- Barcode data MUST follow the template
  `(8110) 0 AAAAAA 0BB 0004BB 001 1 00003 CCDDEE`
  where `AAAAAA` = first 6 digits of UPC, `BB` = discount, `CC/DD/EE` =
  YY/MM/DD in US/Eastern time.
- Plan catalogue: 1d/3d/1w x 1/3 items at fixed prices ($25/$55/$65/$85/$150/$200).
- Sales notifications forwarded to `SALES_GROUP_CHAT_ID`.

## What was implemented in this iteration (2026-01)
- Installed `ghostscript` so `treepoem` can render the GS1 DataBar Expanded
  symbol.
- Removed the silent Code128 fallback in `coupon_generator._generate_barcode_image`;
  it now always uses `databarexpanded` so a broken Ghostscript environment will
  surface immediately instead of degrading to the wrong symbology.
- Confirmed the barcode payload algorithm matches the template exactly
  (`0AAAAAA0BB0004BB001100003CCDDEE`, 31 chars, prefixed with AI `(8110)`).
- Enlarged the product image on the coupon from 160x170 to 210x220 px and
  right-aligned it inside the coupon frame.
- Reflowed the product name block to the right column so it no longer overlaps
  the bottom-left barcode region.
- Hardened `start()` with try/except around the DB lookups + added a global
  `error_handler` so unhandled exceptions reply to the user instead of
  silently dropping the update. `init_db()` failures no longer prevent polling.
- Added `.env.example` so the (gitignored) `.env` can be reconstructed cleanly
  on any host.

## What was implemented in this iteration (2026-02)
- Enlarged the product image again per user feedback: max bounds now 260x260
  (was 210x220) and lifted to `paste_y=95` for better vertical centering.
- Surfaced real exception type+message in the bot's "Error generating coupon"
  user-facing reply (and `logger.exception` for full traceback) so we can
  diagnose remote Render failures from a user screenshot.
- Confirmed via Render docs that `ghostscript` is preinstalled on the native
  Python runtime's deploy environment — no `apt.txt` required. (apt.txt is
  still kept for safety / portability.)

## What was verified
- `treepoem.generate_barcode(barcode_type="databarexpanded", data="(8110)...")`
  renders a 891x102 image. ✓
- Generated test coupon (`/tmp/coupon_test2.png`) reviewed via image analyzer:
  product image visible at ~210x220, no overlap with barcode, layout clean. ✓
- Lint: `ruff` clean on `bot.py` and `coupon_generator.py`. ✓

## Not verified (requires user credentials)
- End-to-end live Telegram test (`TELEGRAM_BOT_TOKEN`, `DATABASE_URL`,
  `HOODPAY_*`, `SALES_GROUP_CHAT_ID` were not provided in this workspace).
  User to drop their `.env` on the deployment host and run `python bot.py`.

## Prioritized backlog / future work
- **P1**: Webhook-based HoodPay confirmation (instead of "I've Paid" polling).
- **P2**: Cache scraped products to reduce Walmart rate-limiting.
- **P2**: Add `/help` and `/cancel` commands.
- **P3**: Admin command to refund / extend subscriptions.

## Operational notes
- Ghostscript is a HARD runtime dependency for barcode generation.
  `apt-get install -y ghostscript` on any new host before `python bot.py`.
- `.env` is gitignored by design; use `.env.example` as the template.
