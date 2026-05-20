import io
import logging
import re
from datetime import datetime, timedelta, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import config
import database as db
import hoodpay_client as hoodpay
import scraper
import coupon_generator

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation states
AWAITING_LINK = 1
AWAITING_DISCOUNT = 2

# ─── /start ───
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        db.get_or_create_user(user.id, user.username, user.first_name)
    except Exception as e:
        logger.exception(f"DB error in /start for user {user.id}: {e}")
        await update.message.reply_text(
            "Sorry, the bot is having trouble connecting to its database. "
            "Please try again in a moment, or contact support if the issue persists."
        )
        return ConversationHandler.END

    # Check active subscription
    try:
        sub = db.get_active_subscription(user.id)
    except Exception as e:
        logger.exception(f"DB error fetching subscription for {user.id}: {e}")
        sub = None
    if sub:
        slots = db.get_product_slots(sub["id"])
        remaining = sub["item_count"] - len(slots)
        end_str = sub["end_date"].strftime("%m/%d/%Y %I:%M %p EST") if sub["end_date"] else "N/A"
        text = (
            f"Welcome back, {user.first_name}!\n\n"
            f"Active Plan: {sub['plan_duration']} - {sub['item_count']} item(s)\n"
            f"Expires: {end_str}\n"
            f"Product slots used: {len(slots)}/{sub['item_count']}\n\n"
        )
        keyboard = []
        if remaining > 0:
            keyboard.append([InlineKeyboardButton("Add New Product Link", callback_data="add_product")])
        if slots:
            keyboard.append([InlineKeyboardButton("Generate Coupon for Existing Product", callback_data="gen_existing")])
        keyboard.append([InlineKeyboardButton("View My Products", callback_data="view_products")])
        keyboard.append([InlineKeyboardButton("Buy New Plan", callback_data="main_menu")])

        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END

    await _show_welcome(update.message)
    return ConversationHandler.END


WELCOME_TEXT = """\
Welcome

This bot generates manufacturer coupons for Walmart products.

How it works:

1. Find an item on walmart.com that's available at a store near you. Item must be around $50, as those work best.
Discount can not be over $50. Items over 50$ can not be returned for money back.
Discount can not be more than item value.

2. Copy the product link and send it here. The bot will look up the product and ask how much $ you want off.

3. You'll receive a printable coupon with a valid barcode to use that will automatically deduct the amount you select upon generating the coupon. Print out the coupon on paper (one coupon per transaction, so if you are buying 10 items you need to print 10 coupons), bring them to the store with you, and scan them at self-checkout after scanning your item and the discount will apply automatically.
If an employee is watching you, insert the coupon into the self checkout feeder on the bottom (it will pop up instruction on the screen to do so, if nobody is watching you, skip this step).

4. The coupon discount will be applied automatically to your transaction. Only sales tax is not covered and must be paid by you. You must use ONE coupon per transaction. DO NOT fill up a cart with 100 items all at once, this will draw attention, you want to remain and seem like a legit shopper. It's advised maximum 2-3 items per checkout, but of course you can do more if you feel like its very crowded and nobody is paying attention to you.
Scan one coupon per item, do not scan more than one item per purchase! if you have a cart with 5 items, you have to pay 5 separate times, NOT ring up 5 items all at once. You go one by one. After you purchase the 2-3 advised limit per cart, go to your car put the items there, come back in the store, and buy the rest, and keep repeating till you clear the entire stock.

These coupons are unlimited until the expiry date. They may be used unlimited times for the specific item chosen until expiration.

(WHEN LEAVING THE STORE IF SECURITY ASKS FOR RECEIPT SHOW THEM RECEIPT FROM MOBILE APP NOT PHYSICAL RECEIPT, see below how to add)
━━━━━━━━━━━━━━━━━━━━━━

HOW TO PROFIT FROM THIS:

1. After purchasing the items, keep the physical receipts with you, go to your Walmart app and scan the barcode on the receipt to add the purchase to your account, do this for all items.
2. After adding items to your app, start a return directly from the app for all of the items, and after doing so it will show you a barcode.
3. Go to Guest Services to return the items back, tell them you got the wrong ones or your boss cancelled construction project or something.. and show the barcodes from your mobile app so they just scan them and process the return. DO NOT SHOW YOUR PHYSICAL PAPER RECEIPT TO THEM.
4. After they scan barcode you will receive the original product price back. It is advised you pay with cash, so that you get back cash. Since you only paid for sales tax, which is only a few dollars, you receive back the original full price of the item, and earn around 48$ PER ITEM.

__________

Terms of Service

• All sales are final. No refunds.
• Keys are non-transferable.
• We are not responsible for how you use the generated coupons.
• Misuse of this service is at your own risk.
• We reserve the right to revoke access at any time.

By pressing Accept below, you agree to these terms.\
"""


async def _show_welcome(message):
    """Show the welcome/terms screen with an Accept button."""
    keyboard = [[InlineKeyboardButton("✅ Accept & Continue", callback_data="accept_terms")]]
    await message.reply_text(WELCOME_TEXT, reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_main_menu(message_or_query, first_name=None):
    """Show the main plan selection menu."""
    keyboard = [
        [InlineKeyboardButton("1 Day Plans", callback_data="dur_1day")],
        [InlineKeyboardButton("3 Days Plans", callback_data="dur_3day")],
        [InlineKeyboardButton("1 Week Plans", callback_data="dur_1week")],
    ]
    markup = InlineKeyboardMarkup(keyboard)

    if hasattr(message_or_query, "edit_message_text"):
        await message_or_query.edit_message_text(text, reply_markup=markup)
    else:
        await message_or_query.reply_text(text, reply_markup=markup)


# ─── Callback handler ───
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    # Accept terms -> show plan menu
    if data == "accept_terms":
        keyboard = [
            [InlineKeyboardButton("1 Day Plans", callback_data="dur_1day")],
            [InlineKeyboardButton("3 Days Plans", callback_data="dur_3day")],
            [InlineKeyboardButton("1 Week Plans", callback_data="dur_1week")],
        ]
        greeting = f"Welcome{(', ' + user.first_name) if user.first_name else ''}!"
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"{greeting}\n\nSelect a plan duration to get started:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Duration selection
    if data.startswith("dur_"):
        dur = data[4:]
        duration_map = {
            "1day": ("1 Day Plans", [
                ("1day_1item", "Coupon for 1 Item (Unlimited Use) - $25"),
                ("1day_3items", "Coupon for 3 Items (Unlimited Use) - $55"),
            ]),
            "3day": ("3 Days Plans", [
                ("3day_1item", "Coupon for 1 Item (Unlimited Use) - $65"),
                ("3day_3items", "Coupon for 3 Items (Unlimited Use) - $85"),
            ]),
            "1week": ("1 Week Plans", [
                ("1week_1item", "Coupon for 1 Item (Unlimited Use) - $150"),
                ("1week_3items", "Coupon for 3 Items (Unlimited Use) - $200"),
            ]),
        }
        title, options = duration_map[dur]
        keyboard = []
        for plan_key, btn_text in options:
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"plan_{plan_key}")])
        keyboard.append([InlineKeyboardButton("<< Back to Plans", callback_data="main_menu")])
        await query.edit_message_text(f"{title}\n\nSelect your plan:", reply_markup=InlineKeyboardMarkup(keyboard))

    # Plan selection -> initiate payment
    elif data.startswith("plan_"):
        plan_key = data[5:]
        plan = config.PLANS.get(plan_key)
        if not plan:
            await query.edit_message_text("Invalid plan. Please try again.")
            return

        # Acknowledge immediately so the button feels instant
        await query.edit_message_text(
            f"⏳ Creating your payment link for {plan['label']}...\nPlease wait a moment."
        )

        # Create payment in DB
        payment = db.create_payment(
            telegram_id=user.id,
            amount=plan["price"],
            plan_key=plan_key,
            plan_label=plan["label"],
        )

        # Create HoodPay payment
        hp_response = hoodpay.create_payment(
            amount=plan["price"],
            currency="USD",
            name=f"WallyBot - {plan['label']}",
            description=f"Telegram user {user.id} - {plan['label']}",
        )

        checkout_url = hoodpay.extract_checkout_url(hp_response)
        hp_id = hoodpay.extract_payment_id(hp_response)

        if hp_id:
            db.update_payment_hoodpay(payment["id"], hp_id, checkout_url)

        if checkout_url:
            keyboard = [
                [InlineKeyboardButton("Pay Now (Crypto)", url=checkout_url)],
                [InlineKeyboardButton("I've Paid - Check Status", callback_data=f"check_{payment['id']}")],
                [InlineKeyboardButton("<< Back to Plans", callback_data="main_menu")],
            ]
            await query.edit_message_text(
                f"Plan: {plan['label']}\n"
                f"Amount: ${plan['price']}\n\n"
                f"Click the button below to pay with crypto.\n"
                f"After payment, click 'I've Paid' to activate your subscription.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        else:
            # If HoodPay fails, show manual payment instructions
            keyboard = [
                [InlineKeyboardButton("I've Paid - Check Status", callback_data=f"check_{payment['id']}")],
                [InlineKeyboardButton("Simulate Payment (Test)", callback_data=f"sim_{payment['id']}")],
                [InlineKeyboardButton("<< Back to Plans", callback_data="main_menu")],
            ]
            await query.edit_message_text(
                f"Plan: {plan['label']}\n"
                f"Amount: ${plan['price']}\n\n"
                f"Payment gateway is being set up. Please contact support or use the test button below.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

    # Check payment status
    elif data.startswith("check_"):
        payment_id = int(data[6:])
        payment = db.get_payment_by_id(payment_id)
        if not payment:
            await query.edit_message_text("Payment not found.")
            return

        if payment["status"] == "completed":
            await query.edit_message_text("Payment already completed! Use /start to access your subscription.")
            return

        # Check with HoodPay
        if payment.get("hoodpay_id"):
            hp_status_resp = hoodpay.get_payment(payment["hoodpay_id"])
            hp_status = hoodpay.extract_payment_status(hp_status_resp)

            if hoodpay.is_payment_completed(hp_status):
                await _activate_subscription(query, user, payment)
                return
            elif hoodpay.is_payment_failed(hp_status):
                db.update_payment_status(payment_id, hp_status)
                await query.edit_message_text(
                    f"Payment {hp_status}. Please select a new plan.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Plans", callback_data="main_menu")]]),
                )
                return

        keyboard = [
            [InlineKeyboardButton("Check Again", callback_data=f"check_{payment_id}")],
            [InlineKeyboardButton("<< Back to Plans", callback_data="main_menu")],
        ]
        await query.edit_message_text(
            "Payment not yet confirmed. Please complete the payment and check again.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # Simulate payment (for testing)
    elif data.startswith("sim_"):
        payment_id = int(data[4:])
        payment = db.get_payment_by_id(payment_id)
        if not payment:
            await query.edit_message_text("Payment not found.")
            return
        await _activate_subscription(query, user, payment)

    # Main menu
    elif data == "main_menu":
        keyboard = [
            [InlineKeyboardButton("1 Day Plans", callback_data="dur_1day")],
            [InlineKeyboardButton("3 Days Plans", callback_data="dur_3day")],
            [InlineKeyboardButton("1 Week Plans", callback_data="dur_1week")],
        ]
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Select a plan duration to get started:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # Add product
    elif data == "add_product":
        sub = db.get_active_subscription(user.id)
        if not sub:
            await query.edit_message_text("No active subscription. Please buy a plan first.",
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Buy Plan", callback_data="main_menu")]]))
            return

        slots = db.get_product_slots(sub["id"])
        remaining = sub["item_count"] - len(slots)
        if remaining <= 0:
            await query.edit_message_text(
                "All product slots are filled! You can generate coupons for your existing products.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Generate Coupon", callback_data="gen_existing")],
                    [InlineKeyboardButton("Back", callback_data="back_to_start")],
                ]),
            )
            return

        context.user_data["state"] = "awaiting_link"
        context.user_data["subscription_id"] = sub["id"]
        await query.edit_message_text(
            f"You have {remaining} product slot(s) remaining.\n\n"
            "Please send me a Walmart.com product link.\n"
            "Example: https://www.walmart.com/ip/Product-Name/12345678"
        )

    # Generate coupon for existing product
    elif data == "gen_existing":
        sub = db.get_active_subscription(user.id)
        if not sub:
            await query.edit_message_text("No active subscription.",
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Buy Plan", callback_data="main_menu")]]))
            return

        slots = db.get_product_slots(sub["id"])
        if not slots:
            await query.edit_message_text(
                "No products added yet. Add a product first!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Add Product", callback_data="add_product")]]),
            )
            return

        keyboard = []
        for slot in slots:
            name = slot["product_name"] or f"Product (UPC: {slot['upc_first6']})"
            if len(name) > 45:
                name = name[:42] + "..."
            keyboard.append([InlineKeyboardButton(name, callback_data=f"genslot_{slot['id']}")])
        keyboard.append([InlineKeyboardButton("<< Back", callback_data="back_to_start")])

        await query.edit_message_text("Select a product to generate a coupon:", reply_markup=InlineKeyboardMarkup(keyboard))

    # Generate coupon for specific slot
    elif data.startswith("genslot_"):
        slot_id = int(data[8:])
        context.user_data["state"] = "awaiting_discount"
        context.user_data["slot_id"] = slot_id
        await query.edit_message_text(
            "What discount amount would you like?\n\n"
            "Discount must be $10-$49.\n"
            "Discount cannot be greater than item cost shown on shelf.\n\n"
            "Please type a number between 10 and 49:"
        )

    # View products
    elif data == "view_products":
        sub = db.get_active_subscription(user.id)
        if not sub:
            await query.edit_message_text("No active subscription.")
            return

        slots = db.get_product_slots(sub["id"])
        if not slots:
            text = "No products added yet."
        else:
            text = "Your Products:\n\n"
            for i, slot in enumerate(slots, 1):
                name = slot["product_name"] or "Unknown"
                text += f"{i}. {name}\n   UPC: {slot['upc_code']}\n\n"

        keyboard = [
            [InlineKeyboardButton("Generate Coupon", callback_data="gen_existing")],
            [InlineKeyboardButton("<< Back", callback_data="back_to_start")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "back_to_start":
        sub = db.get_active_subscription(user.id)
        if sub:
            slots = db.get_product_slots(sub["id"])
            remaining = sub["item_count"] - len(slots)
            end_str = sub["end_date"].strftime("%m/%d/%Y %I:%M %p") if sub["end_date"] else "N/A"
            text = (
                f"Active Plan: {sub['plan_duration']} - {sub['item_count']} item(s)\n"
                f"Expires: {end_str}\n"
                f"Product slots used: {len(slots)}/{sub['item_count']}\n"
            )
            keyboard = []
            if remaining > 0:
                keyboard.append([InlineKeyboardButton("Add New Product Link", callback_data="add_product")])
            if slots:
                keyboard.append([InlineKeyboardButton("Generate Coupon", callback_data="gen_existing")])
            keyboard.append([InlineKeyboardButton("View My Products", callback_data="view_products")])
            keyboard.append([InlineKeyboardButton("Buy New Plan", callback_data="main_menu")])
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        else:
            keyboard = [
                [InlineKeyboardButton("1 Day Plans", callback_data="dur_1day")],
                [InlineKeyboardButton("3 Days Plans", callback_data="dur_3day")],
                [InlineKeyboardButton("1 Week Plans", callback_data="dur_1week")],
            ]
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Select a plan duration to get started:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )


async def _activate_subscription(query, user, payment):
    """Activate subscription after payment confirmation."""
    plan_key = payment["plan_key"]
    plan = config.PLANS.get(plan_key)
    if not plan:
        await query.edit_message_text("Invalid plan configuration.")
        return

    db.update_payment_status(payment["id"], "completed")
    sub = db.create_subscription(
        telegram_id=user.id,
        plan_key=plan_key,
        duration_days=plan["duration_days"],
        item_count=plan["items"],
        payment_id=payment["id"],
        plan_duration_label=plan["duration_label"],
    )

    end_str = sub["end_date"].strftime("%m/%d/%Y %I:%M %p EST") if sub["end_date"] else "N/A"

    # Notify sales group
    await _notify_sale(query, user, plan, payment)

    keyboard = [
        [InlineKeyboardButton("Add Product Link", callback_data="add_product")],
    ]
    await query.edit_message_text(
        f"Payment confirmed! Your subscription is now active.\n\n"
        f"Plan: {plan['label']}\n"
        f"Expires: {end_str}\n"
        f"Product slots: {plan['items']}\n\n"
        f"Send me a Walmart product link to get started!",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _notify_sale(query, user, plan, payment):
    """Forward sale notification to the sales group."""
    sales_chat_id = config.SALES_GROUP_CHAT_ID
    if not sales_chat_id:
        logger.warning("SALES_GROUP_CHAT_ID not set, skipping sale notification")
        return

    try:
        text = (
            f"NEW SALE!\n\n"
            f"Plan: {plan['label']}\n"
            f"Amount: ${plan['price']}\n"
            f"Buyer: {user.first_name or 'Unknown'} (@{user.username or 'N/A'})\n"
            f"Telegram ID: {user.id}\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        await query.get_bot().send_message(chat_id=sales_chat_id, text=text)
    except Exception as e:
        logger.error(f"Failed to notify sales group: {e}")


# ─── Message handler (for links and discount input) ───
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    state = context.user_data.get("state")

    if state == "awaiting_link":
        await _handle_product_link(update, context, text)
    elif state == "awaiting_discount":
        await _handle_discount_input(update, context, text)
    elif re.match(r"https?://.*walmart\.com/ip/", text):
        # Auto-detect Walmart links
        sub = db.get_active_subscription(user.id)
        if not sub:
            await update.message.reply_text(
                "You need an active subscription to generate coupons.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Buy Plan", callback_data="main_menu")]]),
            )
            return

        context.user_data["subscription_id"] = sub["id"]
        context.user_data["state"] = "awaiting_link"
        await _handle_product_link(update, context, text)
    else:
        await update.message.reply_text("Use /start to see the menu, or send a Walmart product link.")


async def _handle_product_link(update: Update, context: ContextTypes.DEFAULT_TYPE, url):
    user = update.effective_user

    if not re.match(r"https?://.*walmart\.com/ip/", url):
        await update.message.reply_text(
            "That doesn't look like a valid Walmart product link.\n"
            "Please send a link like: https://www.walmart.com/ip/Product-Name/12345678"
        )
        return

    sub_id = context.user_data.get("subscription_id")
    sub = db.get_active_subscription(user.id)
    if not sub:
        context.user_data["state"] = None
        await update.message.reply_text("No active subscription found.",
                                       reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Buy Plan", callback_data="main_menu")]]))
        return

    sub_id = sub["id"]
    slots = db.get_product_slots(sub_id)
    remaining = sub["item_count"] - len(slots)

    await update.message.reply_text("Fetching product info... Please wait.")

    # Scrape the product
    product = scraper.scrape_walmart_product(url)

    if product["error"]:
        await update.message.reply_text(product["error"])
        return

    # Check if this product already has a slot
    existing_slot = db.find_product_slot_by_upc(sub_id, product["upc_first6"])
    if existing_slot:
        context.user_data["state"] = "awaiting_discount"
        context.user_data["slot_id"] = existing_slot["id"]
        await update.message.reply_text(
            f"Product found: {product['product_name'] or 'Unknown'}\n"
            f"UPC: {product['upc']}\n\n"
            "This product is already in your slots.\n"
            "What discount amount would you like? ($10-$49)\n"
            "Discount cannot be greater than item cost shown on shelf."
        )
        return

    if remaining <= 0:
        context.user_data["state"] = None
        await update.message.reply_text(
            "All product slots are filled! You can only generate coupons for existing products.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Generate Coupon", callback_data="gen_existing")],
            ]),
        )
        return

    # Add product slot
    slot = db.add_product_slot(
        subscription_id=sub_id,
        telegram_id=user.id,
        walmart_url=url,
        product_name=product.get("product_name"),
        product_image_url=product.get("product_image"),
        upc_code=product.get("upc"),
        upc_first6=product.get("upc_first6"),
    )

    context.user_data["state"] = "awaiting_discount"
    context.user_data["slot_id"] = slot["id"]

    await update.message.reply_text(
        f"Product found: {product.get('product_name', 'Unknown')}\n"
        f"UPC: {product.get('upc')}\n\n"
        "What discount amount would you like?\n"
        "Discount must be $10-$49.\n"
        "Discount cannot be greater than item cost shown on shelf.\n\n"
        "Please type a number between 10 and 49:"
    )


async def _handle_discount_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    # Remove $ if present
    text = text.replace("$", "").strip()

    try:
        discount = int(text)
    except ValueError:
        await update.message.reply_text("Please input a valid number between $10-$49.")
        return

    if discount < 10 or discount > 49:
        await update.message.reply_text("Please input a valid discount between $10-$49.")
        return

    slot_id = context.user_data.get("slot_id")
    if not slot_id:
        await update.message.reply_text("Session expired. Please use /start and try again.")
        context.user_data["state"] = None
        return

    # Get slot info
    from database import get_connection
    import psycopg2.extras
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM product_slots WHERE id = %s", (slot_id,))
    slot = cur.fetchone()
    cur.close()
    conn.close()

    if not slot:
        await update.message.reply_text("Product not found. Please use /start and try again.")
        context.user_data["state"] = None
        return

    slot = dict(slot)
    await update.message.reply_text("Generating your coupon... Please wait.")

    try:
        # NOTE: the visible "EXPIRES" date on the coupon must match the date
        # embedded inside the GS1 DataBar Expanded payload (today in EST). The
        # coupon generator defaults to today (EST) when expiry_date=None, so we
        # pass None here on purpose. Do NOT pass the subscription end_date — it
        # is unrelated to the coupon date and would make the barcode/visible
        # date mismatch, causing scanners to reject the coupon.
        coupon_bytes = coupon_generator.generate_coupon_image(
            upc_first6=slot["upc_first6"],
            discount=discount,
            product_name=slot.get("product_name"),
            product_image_url=slot.get("product_image_url"),
            expiry_date=None,
        )

        keyboard = [
            [InlineKeyboardButton("Generate Another Coupon", callback_data="gen_existing")],
            [InlineKeyboardButton("Add New Product", callback_data="add_product")],
            [InlineKeyboardButton("Back to Menu", callback_data="back_to_start")],
        ]

        coupon_file = io.BytesIO(coupon_bytes)
        coupon_file.name = "coupon.png"
        # Coupon expiry = today (EST) — same date embedded in the GS1 barcode.
        today_est = datetime.now(coupon_generator.EST).strftime("%m/%d/%Y")
        await update.message.reply_document(
            document=coupon_file,
            filename="coupon.png",
            caption=f"Coupon for: {slot.get('product_name', 'Product')}\nDiscount: ${discount}.00 OFF\nExpires: {today_est}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception as e:
        logger.exception(f"Coupon generation error: {e}")
        err_text = f"{type(e).__name__}: {e}"
        if len(err_text) > 300:
            err_text = err_text[:300] + "..."
        await update.message.reply_text(
            f"Error generating coupon.\n\nDetails: {err_text}\n\nPlease share this with support so we can fix it.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Try Again", callback_data="gen_existing")]]),
        )

    context.user_data["state"] = None


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler – logs the error and notifies the user."""
    logger.exception("Unhandled exception while handling update", exc_info=context.error)
    try:
        if isinstance(update, Update):
            if update.callback_query:
                await update.callback_query.answer("Something went wrong. Please try /start again.", show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(
                    "Something went wrong handling your request. Please try /start again."
                )
    except Exception:
        pass


def main():
    try:
        db.init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.exception(f"Database init failed (bot will still start): {e}")

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_error_handler(error_handler)

    # On Render, a new deploy starts before the old instance fully releases
    # its Telegram long-poll connection.  Retry with back-off until the slot
    # is free (usually 10-20 s after the old process receives SIGTERM).
    import time
    from telegram.error import Conflict

    max_retries = 10
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Bot starting (attempt {attempt}/{max_retries})...")
            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
            )
            break
        except Conflict:
            wait = attempt * 6
            logger.warning(
                f"Conflict: another instance is still polling. "
                f"Waiting {wait}s before retry {attempt}/{max_retries}..."
            )
            time.sleep(wait)
        except Exception:
            logger.exception("Unexpected error during polling startup")
            raise
    else:
        logger.error("Could not start polling after %d attempts — giving up", max_retries)


if __name__ == "__main__":
    main()
