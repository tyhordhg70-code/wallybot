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

# Lightweight JSON API headers (no browser noise)
API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.walmart.com/",
    "Origin": "https://www.walmart.com",
    "Connection": "keep-alive",
}


def _extract_item_id(url):
    """Extract Walmart numeric item ID from URL."""
    # Standard format: /ip/Product-Name/12345678 or /ip/12345678
    match = re.search(r"/ip/(?:[^/?]+/)?(\d{5,12})", url)
    if match:
        return match.group(1)
    # Query param fallback
    match = re.search(r"[?&]itemId=(\d+)", url)
    if match:
        return match.group(1)
    return None


def _extract_name_from_url(url):
    """Extract product name from Walmart URL slug."""
    match = re.search(r"/ip/([^/]+)/", url)
    if not match:
        match = re.search(r"/ip/([^/?]+)", url)
    if match:
        slug = match.group(1)
        # If it's all digits it's the item ID, not the name
        if slug.isdigit():
            return None
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


def _recursive_find_upc(obj, depth=0):
    """
    Recursively search a parsed JSON object for UPC/GTIN values.
    Returns the first plausible UPC string found (6-13 digits).
    """
    if depth > 15:
        return None
    if isinstance(obj, dict):
        for key in ("upc", "UPC", "upcA", "gtin", "GTIN", "ean", "EAN"):
            val = obj.get(key)
            if val and isinstance(val, str) and re.match(r"^\d{6,13}$", val.strip()):
                return val.strip()
        for val in obj.values():
            found = _recursive_find_upc(val, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _recursive_find_upc(item, depth + 1)
            if found:
                return found
    return None


def scrape_walmart_product(url):
    """
    Scrape a Walmart product page for UPC code, product name, and image.
    Tries six methods in order, logging the outcome of each.
    """
    result = {
        "upc": None,
        "upc_first6": None,
        "product_name": None,
        "product_image": None,
        "error": None,
    }

    item_id = _extract_item_id(url)
    logger.info(f"Scraping URL={url!r}  item_id={item_id!r}")

    try:
        # ── Method 1: Walmart terra-firma JSON API (lightest, most reliable) ──
        if item_id:
            data = _fetch_terra_firma(item_id)
            if data:
                _extract_from_json_blob(data, result)
                logger.info(f"terra-firma → upc={result['upc']!r}")

        # ── Method 2: Walmart internal product-page API ──
        if not result["upc"] and item_id:
            data = _fetch_product_api(item_id)
            if data:
                _extract_from_json_blob(data, result)
                logger.info(f"product-api → upc={result['upc']!r}")

        # ── Method 3: curl_cffi Chrome TLS impersonation ──
        if not result["upc"]:
            page_source = _fetch_with_curl_cffi(url)
            if page_source and not _is_captcha_page(page_source):
                _extract_from_source(page_source, result)
                logger.info(f"curl_cffi → upc={result['upc']!r}")
            elif page_source:
                logger.warning("curl_cffi returned a CAPTCHA page")
            else:
                logger.warning("curl_cffi returned no content")

        # ── Method 4: curl_cffi with homepage cookie warm-up ──
        if not result["upc"]:
            page_source = _fetch_with_curl_cffi_warmed(url)
            if page_source and not _is_captcha_page(page_source):
                _extract_from_source(page_source, result)
                logger.info(f"curl_cffi_warmed → upc={result['upc']!r}")
            elif page_source:
                logger.warning("curl_cffi_warmed returned a CAPTCHA page")

        # ── Method 5: Standard requests ──
        if not result["upc"]:
            page_source = _fetch_page_source(url)
            if page_source and not _is_captcha_page(page_source):
                _extract_from_source(page_source, result)
                logger.info(f"requests → upc={result['upc']!r}")
            else:
                logger.warning("requests: blocked or no content")

        # ── Method 6: Archive.org Wayback Machine ──
        if not result["upc"]:
            page_source = _fetch_via_archive(url)
            if page_source and not _is_captcha_page(page_source):
                _extract_from_source(page_source, result)
                logger.info(f"archive.org → upc={result['upc']!r}")
            else:
                logger.warning("archive.org: blocked or no content")

        # ── Method 7: allorigins / corsproxy ──
        if not result["upc"]:
            page_source = _fetch_via_proxy(url)
            if page_source and not _is_captcha_page(page_source):
                _extract_from_source(page_source, result)
                logger.info(f"proxy → upc={result['upc']!r}")
            else:
                logger.warning("proxy: blocked or no content")

        # Fallback product name from URL slug when UPC found but name missing
        if result["upc"] and not result["product_name"]:
            result["product_name"] = _extract_name_from_url(url)

        # Sanitise product name
        if result["product_name"]:
            bad_names = ["robot or human", "access denied", "captcha", "blocked", "verify"]
            if any(b in result["product_name"].lower() for b in bad_names):
                result["product_name"] = _extract_name_from_url(url)

        if not result["upc"]:
            logger.error(f"All scraping methods failed for URL={url!r}")
            result["error"] = "Cannot generate coupon for this product, please try a different link."

    except Exception as e:
        logger.exception(f"Unexpected scraper error for URL={url!r}: {e}")
        result["error"] = "Cannot generate coupon for this product, please try a different link."

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Fetch helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_terra_firma(item_id):
    """
    Walmart's internal terra-firma product endpoint — returns JSON with full
    product details including UPC.  Less aggressively bot-gated than the HTML page.
    """
    urls = [
        f"https://www.walmart.com/terra-firma/item/{item_id}",
        f"https://www.walmart.com/api/2/page/store/pagetype/1/item/{item_id}",
    ]
    for endpoint in urls:
        try:
            resp = requests.get(endpoint, headers=API_HEADERS, timeout=15)
            logger.info(f"terra-firma {endpoint} → HTTP {resp.status_code}")
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    continue
        except Exception as e:
            logger.warning(f"terra-firma fetch error ({endpoint}): {e}")
    return None


def _fetch_product_api(item_id):
    """
    Walmart's product-page JSON used by the SPA frontend.
    """
    endpoints = [
        f"https://www.walmart.com/api/2/page/store/pagetype/1/product/{item_id}",
        f"https://www.walmart.com/api/2/page/store/pagetype/1/product/{item_id}?appId=cafe24",
        f"https://www.walmart.com/api/2/page/store/pagetype/1/item/{item_id}?appId=cafe24",
    ]
    for endpoint in endpoints:
        try:
            resp = requests.get(endpoint, headers=API_HEADERS, timeout=15)
            logger.info(f"product-api {endpoint} → HTTP {resp.status_code}")
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    continue
        except Exception as e:
            logger.warning(f"product-api fetch error ({endpoint}): {e}")
    return None


def _fetch_with_curl_cffi(url):
    """Fetch using curl_cffi with Chrome TLS fingerprint impersonation."""
    try:
        from curl_cffi import requests as curl_requests

        session = curl_requests.Session(impersonate="chrome124")
        resp = session.get(url, headers=HEADERS, timeout=20)
        logger.info(f"curl_cffi → HTTP {resp.status_code}")
        if resp.status_code == 200:
            return resp.text
        return None
    except ImportError:
        logger.warning("curl_cffi not installed, skipping TLS impersonation")
        return None
    except Exception as e:
        logger.warning(f"curl_cffi fetch failed: {e}")
        return None


def _fetch_with_curl_cffi_warmed(url):
    """
    Fetch using curl_cffi after visiting walmart.com homepage first
    to collect cookies and appear more like a real browser session.
    """
    try:
        from curl_cffi import requests as curl_requests

        session = curl_requests.Session(impersonate="chrome124")
        # Warm-up: visit homepage to get cookies
        try:
            session.get("https://www.walmart.com/", headers=HEADERS, timeout=10)
        except Exception:
            pass  # Homepage warm-up is best-effort
        resp = session.get(url, headers={**HEADERS, "Sec-Fetch-Site": "same-origin"}, timeout=20)
        logger.info(f"curl_cffi_warmed → HTTP {resp.status_code}")
        if resp.status_code == 200:
            return resp.text
        return None
    except ImportError:
        return None
    except Exception as e:
        logger.warning(f"curl_cffi_warmed fetch failed: {e}")
        return None


def _fetch_page_source(url):
    """Directly fetch Walmart page source using standard requests."""
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        resp = session.get(url, timeout=15, allow_redirects=True)
        logger.info(f"requests → HTTP {resp.status_code}")
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception as e:
        logger.warning(f"Direct fetch failed: {e}")
        return None


def _fetch_via_archive(url):
    """Fetch from Internet Archive's Wayback Machine (latest available snapshot)."""
    try:
        archive_url = f"https://web.archive.org/web/{url}"
        resp = requests.get(
            archive_url,
            timeout=20,
            headers={"User-Agent": HEADERS["User-Agent"]},
            allow_redirects=True,
        )
        logger.info(f"archive.org → HTTP {resp.status_code}, len={len(resp.text)}")
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
            logger.info(f"proxy ({proxy_template[:30]}) → HTTP {resp.status_code}, len={len(resp.text)}")
            if resp.status_code == 200 and len(resp.text) > 5000:
                return resp.text
        except Exception as e:
            logger.warning(f"Proxy fetch failed: {e}")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Extraction helpers
# ──────────────────────────────────────────────────────────────────────────────

def _extract_from_json_blob(data, result):
    """
    Extract UPC / name / image from a Walmart JSON response
    (terra-firma or product-api).  Uses recursive UPC search as fallback.
    """
    if not isinstance(data, dict):
        return

    # Try well-known paths first
    try:
        # terra-firma path
        item = data.get("item") or {}
        upc = (
            item.get("upc")
            or item.get("upcA")
            or item.get("gtin")
        )
        if upc and re.match(r"^\d{6,13}$", str(upc).strip()):
            result["upc"] = str(upc).strip()
            result["upc_first6"] = str(upc).strip()[:6]

        if not result["product_name"]:
            result["product_name"] = item.get("name") or item.get("productName")

        if not result["product_image"]:
            images = item.get("imageInfo", {}).get("allImages", [])
            if images:
                result["product_image"] = images[0].get("url")
            elif item.get("image"):
                result["product_image"] = item["image"]
    except Exception:
        pass

    # Try __NEXT_DATA__ style nested path
    if not result["upc"]:
        try:
            props = data.get("props", {}).get("pageProps", {})
            initial = props.get("initialData", {}).get("data", {})
            product = initial.get("product", {})
            for key in ("upc", "upcA", "gtin"):
                val = product.get(key)
                if val and re.match(r"^\d{6,13}$", str(val).strip()):
                    result["upc"] = str(val).strip()
                    result["upc_first6"] = str(val).strip()[:6]
                    break
            if not result["product_name"]:
                result["product_name"] = product.get("name") or product.get("productName")
        except Exception:
            pass

    # Last resort: recursive scan of entire JSON blob
    if not result["upc"]:
        upc = _recursive_find_upc(data)
        if upc:
            result["upc"] = upc
            result["upc_first6"] = upc[:6]


def _extract_from_source(source, result):
    """Extract UPC, product name, and image from HTML page source."""

    # ── UPC regex patterns against raw HTML ──
    upc_patterns = [
        r'"UPC"\s*:\s*"(\d{6,13})"',
        r'"upc"\s*:\s*"(\d{6,13})"',
        r'"upcA"\s*:\s*"(\d{6,13})"',
        r'"gtin"\s*:\s*"(\d{6,13})"',
        r'"GTIN"\s*:\s*"(\d{6,13})"',
        r'"ean"\s*:\s*"(\d{6,13})"',
        r'"EAN"\s*:\s*"(\d{6,13})"',
        r'"barcode"\s*:\s*"(\d{6,13})"',
        # Sometimes embedded without quotes around value
        r'"UPC"\s*:\s*(\d{6,13})[,}\s]',
        r'"upc"\s*:\s*(\d{6,13})[,}\s]',
        # Data attribute style
        r'data-upc="(\d{6,13})"',
        r'data-barcode="(\d{6,13})"',
    ]

    for pattern in upc_patterns:
        match = re.search(pattern, source)
        if match:
            upc = match.group(1).strip()
            result["upc"] = upc
            result["upc_first6"] = upc[:6]
            break

    # ── __NEXT_DATA__ JSON (Walmart's Next.js payload) ──
    if not result["upc"]:
        try:
            next_data_match = re.search(
                r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>', source, re.DOTALL
            )
            if next_data_match:
                data = json.loads(next_data_match.group(1))
                _extract_from_next_data(data, result)
        except (json.JSONDecodeError, KeyError):
            pass

    # ── Product name ──
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

    if not result["product_name"]:
        title_match = re.search(r"<title>([^<]+)</title>", source)
        if title_match:
            title = title_match.group(1).strip()
            title = re.sub(r"\s*[-|]\s*Walmart\.com.*$", "", title)
            skip_words = ["robot", "human", "captcha", "blocked"]
            if len(title) > 5 and not any(w in title.lower() for w in skip_words):
                result["product_name"] = title

    # ── Product image ──
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
            if "walmartimages" in img_url or "scene7" in img_url:
                result["product_image"] = img_url
                break
            elif not result["product_image"]:
                result["product_image"] = img_url


def _extract_from_next_data(data, result):
    """Extract product info from __NEXT_DATA__ JSON (Next.js page payload)."""
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

    # If UPC still not found, do a full recursive search of __NEXT_DATA__
    if not result["upc"]:
        upc = _recursive_find_upc(data)
        if upc:
            result["upc"] = upc
            result["upc_first6"] = upc[:6]
