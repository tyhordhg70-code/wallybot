import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, timezone
from config import DATABASE_URL


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            telegram_id BIGINT NOT NULL,
            amount NUMERIC(10,2) NOT NULL,
            currency TEXT DEFAULT 'USD',
            plan_key TEXT NOT NULL,
            plan_label TEXT,
            hoodpay_id TEXT,
            hoodpay_checkout_url TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            telegram_id BIGINT NOT NULL,
            plan_key TEXT NOT NULL,
            plan_duration TEXT,
            duration_days INTEGER,
            item_count INTEGER,
            start_date TIMESTAMPTZ,
            end_date TIMESTAMPTZ,
            status TEXT DEFAULT 'active',
            payment_id INTEGER REFERENCES payments(id),
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS product_slots (
            id SERIAL PRIMARY KEY,
            subscription_id INTEGER REFERENCES subscriptions(id),
            telegram_id BIGINT NOT NULL,
            walmart_url TEXT,
            product_name TEXT,
            product_image_url TEXT,
            upc_code TEXT,
            upc_first6 TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()


def get_or_create_user(telegram_id, username=None, first_name=None):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
    user = cur.fetchone()
    if not user:
        cur.execute(
            "INSERT INTO users (telegram_id, username, first_name) VALUES (%s, %s, %s) RETURNING *",
            (telegram_id, username, first_name),
        )
        user = cur.fetchone()
        conn.commit()
    cur.close()
    conn.close()
    return dict(user)


def create_payment(telegram_id, amount, plan_key, plan_label, hoodpay_id=None, hoodpay_checkout_url=None):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    user = get_or_create_user(telegram_id)
    cur.execute(
        """INSERT INTO payments (user_id, telegram_id, amount, plan_key, plan_label, hoodpay_id, hoodpay_checkout_url, status)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending') RETURNING *""",
        (user["id"], telegram_id, amount, plan_key, plan_label, hoodpay_id, hoodpay_checkout_url),
    )
    payment = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return dict(payment)


def update_payment_status(payment_id, status, hoodpay_id=None):
    conn = get_connection()
    cur = conn.cursor()
    if hoodpay_id:
        cur.execute(
            "UPDATE payments SET status = %s, hoodpay_id = %s, updated_at = NOW() WHERE id = %s",
            (status, hoodpay_id, payment_id),
        )
    else:
        cur.execute(
            "UPDATE payments SET status = %s, updated_at = NOW() WHERE id = %s",
            (status, payment_id),
        )
    conn.commit()
    cur.close()
    conn.close()


def update_payment_hoodpay(payment_id, hoodpay_id, checkout_url):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE payments SET hoodpay_id = %s, hoodpay_checkout_url = %s, updated_at = NOW() WHERE id = %s",
        (hoodpay_id, checkout_url, payment_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_payment_by_id(payment_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM payments WHERE id = %s", (payment_id,))
    payment = cur.fetchone()
    cur.close()
    conn.close()
    return dict(payment) if payment else None


def get_pending_payment_for_user(telegram_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT * FROM payments WHERE telegram_id = %s AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
        (telegram_id,),
    )
    payment = cur.fetchone()
    cur.close()
    conn.close()
    return dict(payment) if payment else None


def create_subscription(telegram_id, plan_key, duration_days, item_count, payment_id, plan_duration_label):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    user = get_or_create_user(telegram_id)
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=duration_days)
    cur.execute(
        """INSERT INTO subscriptions (user_id, telegram_id, plan_key, plan_duration, duration_days, item_count, start_date, end_date, status, payment_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', %s) RETURNING *""",
        (user["id"], telegram_id, plan_key, plan_duration_label, duration_days, item_count, now, end, payment_id),
    )
    sub = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return dict(sub)


def get_active_subscription(telegram_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    now = datetime.now(timezone.utc)
    cur.execute(
        """SELECT * FROM subscriptions
           WHERE telegram_id = %s AND status = 'active' AND end_date > %s
           ORDER BY end_date DESC LIMIT 1""",
        (telegram_id, now),
    )
    sub = cur.fetchone()
    cur.close()
    conn.close()
    return dict(sub) if sub else None


def get_product_slots(subscription_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM product_slots WHERE subscription_id = %s ORDER BY created_at", (subscription_id,))
    slots = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(s) for s in slots]


def add_product_slot(subscription_id, telegram_id, walmart_url, product_name, product_image_url, upc_code, upc_first6):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """INSERT INTO product_slots (subscription_id, telegram_id, walmart_url, product_name, product_image_url, upc_code, upc_first6)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (subscription_id, telegram_id, walmart_url, product_name, product_image_url, upc_code, upc_first6),
    )
    slot = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return dict(slot)


def ensure_free_subscription(telegram_id):
    """
    Find or create a permanent (36 500-day / ~100-year) subscription for a
    free/admin user.  Called once per bot interaction — idempotent.
    """
    sub = get_active_subscription(telegram_id)
    if sub:
        return sub
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    get_or_create_user(telegram_id)
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=36500)
    cur.execute(
        """INSERT INTO subscriptions
               (user_id, telegram_id, plan_key, plan_duration, duration_days,
                item_count, start_date, end_date, status, payment_id)
           VALUES (
               (SELECT id FROM users WHERE telegram_id = %s LIMIT 1),
               %s, 'free', 'Unlimited', 36500, 999, %s, %s, 'active', NULL
           ) RETURNING *""",
        (telegram_id, telegram_id, now, end),
    )
    sub = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return dict(sub)


def find_product_slot_by_upc(subscription_id, upc_first6):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT * FROM product_slots WHERE subscription_id = %s AND upc_first6 = %s LIMIT 1",
        (subscription_id, upc_first6),
    )
    slot = cur.fetchone()
    cur.close()
    conn.close()
    return dict(slot) if slot else None
