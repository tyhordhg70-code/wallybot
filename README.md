# WallyBot - Telegram Coupon Generator Bot

A Telegram bot that generates Walmart coupons with cryptocurrency payments via HoodPay.io.

## Features

- **Plan-based subscriptions** (1 Day, 3 Days, 1 Week)
- **Crypto payments** via HoodPay.io
- **Walmart product scraping** - extracts UPC codes from product links
- **Coupon generation** - creates professional coupon images with GS1 DataBar barcodes
- **Unlimited coupon generation** during subscription period
- **Sales notifications** forwarded to a Telegram group

## Plans

| Duration | Items | Price |
|----------|-------|-------|
| 1 Day    | 1     | $25   |
| 1 Day    | 3     | $55   |
| 3 Days   | 1     | $65   |
| 3 Days   | 3     | $85   |
| 1 Week   | 1     | $150  |
| 1 Week   | 3     | $200  |

## Setup

### Prerequisites
- Python 3.10+
- PostgreSQL database (Neon or local)
- Telegram Bot Token
- HoodPay.io API Key
- Ghostscript (for barcode generation)

### Installation

```bash
# Clone the repository
git clone https://github.com/tyhordhg70-code/wallybot.git
cd wallybot

# Install system dependency
sudo apt-get install ghostscript

# Install Python dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env with your credentials
```

### Environment Variables

Create a `.env` file with:

```
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
DATABASE_URL=postgresql://user:pass@host/dbname
HOODPAY_API_KEY=your_hoodpay_api_key
HOODPAY_BUSINESS_ID=your_business_id
SALES_GROUP_CHAT_ID=your_telegram_group_chat_id
```

### Running

```bash
python bot.py
```

## How It Works

1. User starts the bot with `/start`
2. Selects a plan duration and item count
3. Pays via cryptocurrency through HoodPay checkout
4. After payment confirmation, user sends a Walmart product link
5. Bot scrapes the product page for UPC code and product info
6. User inputs desired discount amount ($10-$49)
7. Bot generates a professional coupon image with GS1 barcode
8. User can regenerate coupons unlimited times during subscription

## Barcode Format

GS1 DataBar Expanded with template:
```
(8110)0AAAAAA0BB0004BB001100003CCDDEE
```
- `AAAAAA` = First 6 digits of UPC
- `BB` = Discount amount
- `CC` = Year (2-digit)
- `DD` = Month
- `EE` = Day (EST timezone)

## Tech Stack

- **python-telegram-bot** - Telegram Bot API
- **psycopg2** - PostgreSQL driver
- **Pillow** - Image generation
- **treepoem** - GS1 barcode generation
- **BeautifulSoup4** - Web scraping
- **HoodPay SDK** - Crypto payments
