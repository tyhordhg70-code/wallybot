import re
import json
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Referer": "https://www.google.com/",
    "Cache-Control": "max-age=0",
}


def _extract_name_from_url(url):
    """Extract product name from Walmart URL slug."""
    match = re.search(r"/ip/([^/]+)/", url)
    if not match:
        match = re.search(r"/ip/([^/?]+)", url)
    if match:
        slug = match.group(1)
        name = slug.replace("-", " ")
        name = " ".join(w.capitalize() for w in name.split())
        return name
    return None


def _is_captcha_page(source):
    """Check if the page is a CAPTCHA/bot-detection page."""
    captcha_indicators = [
        "robot or human",
        "captcha",
        "px/pxu6b0qd2s",
        "redirecturl.*blocked",
        "access denied",
        "verify you are human",
    ]
    lower = source[:5000].lower()
    return any(ind in lower for ind in captcha_indicators)


def scrape_walmart_product(url):
    """
    Scrape a Walmart product page for UPC code, product name, and image.
    Uses multiple fallback methods to bypass blocking.
    """
    result = {"upc": None, "upc_first6": None, "product_name": None, "product_image": None, "error": None}

    try:
        # Method 1: Direct scrape with curl_cffi (TLS fingerprint impersonation)
        page_source = _fetch_with_curl_cffi(url)
        if page_source and not _is_captcha_page(page_source):
            _extract_from_source(page_source, result)

        # Method 2: Standard requests with different headers
        if not result["upc"]:
            page_source = _fetch_page_source(url)
            if page_source and not _is_captcha_page(page_source):
                _extract_from_source(page_source, result)

        # Method 3: Archive.org Wayback Machine
        if not result["upc"]:
            page_source = _fetch_via_archive(url)
            if page_source and not _is_captcha_page(page_source):
                _extract_from_source(page_source, result)

        # Method 4: Allorigins proxy
        if not result["upc"]:
            page_source = _fetch_via_proxy(url)
            if page_source and not _is_captcha_page(page_source):
                _extract_from_source(page_source, result)

        # Fallback product name from URL slug
        if result["upc"] and not result["product_name"]:
            result["product_name"] = _extract_name_from_url(url)

        # Clean product name - remove captcha artifacts
        if result["product_name"]:
            bad_names = ["robot or human", "access denied", "captcha", "blocked", "verify"]
            if any(b in result["product_name"].lower() for b in bad_names):
                result["product_name"] = _extract_name_from_url(url)

        if not result["upc"]:
            result["error"] = "Cannot generate coupon for this product, please try a different link."

    except Exception as e:
        logger.error(f"Scraper error: {e}")
        result["error"] = "Cannot generate coupon for this product, please try a different link."

    return result


def _fetch_with_curl_cffi(url):
    """Fetch using curl_cffi with Chrome TLS fingerprint impersonation."""
    try:
        from curl_cffi import requests as curl_requests

        session = curl_requests.Session(impersonate="chrome124")
        resp = session.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            return resp.text
        return None
    except ImportError:
        logger.warning("curl_cffi not installed, skipping TLS impersonation")
        return None
    except Exception as e:
        logger.warning(f"curl_cffi fetch failed: {e}")
        return None


def _fetch_page_source(url):
    """Directly fetch Walmart page source."""
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        resp = session.get(url, timeout=15, allow_redirects=True)
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception as e:
        logger.warning(f"Direct fetch failed: {e}")
        return None


def _fetch_via_archive(url):
    """Fetch from Internet Archive's Wayback Machine."""
    try:
        archive_url = f"https://web.archive.org/web/2024/{url}"
        resp = requests.get(
            archive_url,
            timeout=20,
            headers={"User-Agent": HEADERS["User-Agent"]},
            allow_redirects=True,
        )
        if resp.status_code == 200 and len(resp.text) > 10000:
            return resp.text
        return None
    except Exception as e:
        logger.warning(f"Archive.org fetch failed: {e}")
        return None


def _fetch_via_proxy(url):
    """Fetch page source via allorigins or corsproxy."""
    for proxy_template in [
        "https://api.allorigins.win/raw?url={}",
        "https://corsproxy.io/?{}",
    ]:
        try:
            proxy_url = proxy_template.format(requests.utils.quote(url))
            resp = requests.get(
                proxy_url,
                timeout=20,
                headers={"User-Agent": HEADERS["User-Agent"]},
            )
            if resp.status_code == 200 and len(resp.text) > 5000:
                return resp.text
        except Exception as e:
            logger.warning(f"Proxy fetch failed: {e}")
    return None


def _extract_from_source(source, result):
    """Extract UPC, product name, and image from page source."""

    # Search for "UPC":" pattern
    upc_patterns = [
        r'"UPC":"(\d{6,13})"',
        r'"upc":"(\d{6,13})"',
        r'"upcA":"(\d{6,13})"',
        r'"gtin":"(\d{6,13})"',
        r'"UPC":\s*"(\d{6,13})"',
        r'"upc":\s*"(\d{6,13})"',
    ]

    for pattern in upc_patterns:
        match = re.search(pattern, source)
        if match:
            upc = match.group(1)
            result["upc"] = upc
            result["upc_first6"] = upc[:6]
            break

    # Extract product name - try og:title meta tag first
    if not result["product_name"]:
        og_title = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', source)
        if og_title:
            name = og_title.group(1).strip()
            if len(name) > 5 and "walmart" not in name.lower():
                result["product_name"] = name

    if not result["product_name"]:
        name_patterns = [
            r'"productName"\s*:\s*"([^"]{10,200})"',
            r'"name"\s*:\s*"([^"]{10,200})".*?"@type"\s*:\s*"Product"',
            r'"product"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]{10,200})"',
            r'<h1[^>]*itemprop="name"[^>]*>([^<]{5,200})</h1>',
            r'<h1[^>]*>([^<]{10,200})</h1>',
        ]
        for pattern in name_patterns:
            match = re.search(pattern, source)
            if match:
                name = match.group(1).strip()
                skip_words = ["walmart", "grid", "addtocart", "sticky", "button", "modal", "robot", "captcha"]
                if len(name) > 8 and not any(w in name.lower() for w in skip_words):
                    result["product_name"] = name
                    break

    # Fallback: title tag
    if not result["product_name"]:
        title_match = re.search(r"<title>([^<]+)</title>", source)
        if title_match:
            title = title_match.group(1).strip()
            title = re.sub(r"\s*[-|]\s*Walmart\.com.*$", "", title)
            skip_words = ["robot", "human", "captcha", "blocked"]
            if len(title) > 5 and not any(w in title.lower() for w in skip_words):
                result["product_name"] = title

    # Extract product image
    img_patterns = [
        r'"og:image"\s+content="(https?://[^"]+)"',
        r'"imageUrl"\s*:\s*"(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
        r'"image"\s*:\s*"(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
        r'"thumbnailUrl"\s*:\s*"(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
        r'"heroImage(?:Url)?"\s*:\s*\[?\s*"(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
        r'"contentUrl"\s*:\s*"(https?://i5\.walmartimages\.com[^"]+)"',
    ]

    for pattern in img_patterns:
        match = re.search(pattern, source)
        if match:
            img_url = match.group(1)
            # Filter out non-product images
            if "walmartimages" in img_url or "scene7" in img_url:
                result["product_image"] = img_url
                break
            elif not result["product_image"]:
                result["product_image"] = img_url

    # Also try __NEXT_DATA__ JSON for structured data
    try:
        next_data_match = re.search(
            r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>', source, re.DOTALL
        )
        if next_data_match:
            data = json.loads(next_data_match.group(1))
            _extract_from_next_data(data, result)
    except (json.JSONDecodeError, KeyError):
        pass


def _extract_from_next_data(data, result):
    """Extract product info from __NEXT_DATA__ JSON."""
    try:
        props = data.get("props", {}).get("pageProps", {})
        initial_data = props.get("initialData", {}).get("data", {})
        product = initial_data.get("product", {})

        if not result["upc"]:
            for key in ["upc", "upcA", "gtin"]:
                val = product.get(key)
                if val and re.match(r"^\d{6,13}$", str(val)):
                    result["upc"] = str(val)
                    result["upc_first6"] = str(val)[:6]
                    break

        if not result["product_name"]:
            name = product.get("name") or product.get("productName")
            if name:
                result["product_name"] = name

        if not result["product_image"]:
            images = product.get("imageInfo", {}).get("allImages", [])
            if images:
                result["product_image"] = images[0].get("url")
            elif product.get("image"):
                result["product_image"] = product["image"]
    except Exception:
        pass
