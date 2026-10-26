"""Public-site ingestion and explicit publication; crawls never publish evidence."""

from collections import deque
import hashlib
import ipaddress
import json
import math
import re
import socket
import time
from urllib.parse import quote, urldefrag, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup, Comment, Doctype
import httpx
from sqlalchemy import delete, select

from .config import settings
from .models import Chunk, Document, Product, utcnow


USER_AGENT = "CoolDataSimKnowledgeBot/1.0"
MAX_BYTES = 2_000_000
MAX_CRAWL_SECONDS = 900
DOH_ENDPOINTS = ("https://dns.google/resolve", "https://cloudflare-dns.com/dns-query")
DESTINATION_ALIASES = {
    "日本": ("日本", "japan"), "韓國": ("韓國", "韩国", "korea"),
    "台灣": ("台灣", "臺灣", "台湾", "taiwan"), "中國": ("中國", "中国", "大陸", "大陆", "china"),
    "香港": ("香港", "hong kong"), "澳門": ("澳門", "澳门", "macau", "macao"),
    "泰國": ("泰國", "泰国", "thailand"), "新加坡": ("新加坡", "singapore"),
    "馬來西亞": ("馬來西亞", "马来西亚", "malaysia"), "印尼": ("印尼", "印度尼西亞", "印度尼西亚", "indonesia"),
    "越南": ("越南", "vietnam"), "菲律賓": ("菲律賓", "菲律宾", "philippines"),
    "歐洲": ("歐洲", "欧洲", "europe"), "東南亞": ("東南亞", "东南亚", "southeast asia"),
    "美國": ("美國", "美国", "united states", "usa"), "加拿大": ("加拿大", "canada"),
    "英國": ("英國", "英国", "united kingdom", "uk"), "法國": ("法國", "法国", "france"),
    "德國": ("德國", "德国", "germany"), "澳大利亞": ("澳大利亞", "澳大利亚", "澳洲", "australia"),
    "新西蘭": ("紐西蘭", "新西蘭", "新西兰", "new zealand"),
    "尼泊爾": ("尼泊爾", "尼泊尔", "nepal"), "巴基斯坦": ("巴基斯坦", "pakistan"),
    "老撾": ("老撾", "老挝", "laos"), "斯里蘭卡": ("斯里蘭卡", "斯里兰卡", "sri lanka"),
    "土耳其": ("土耳其", "turkey", "turkiye"), "墨西哥": ("墨西哥", "mexico"),
    "埃及": ("埃及", "egypt"), "南非": ("南非", "south africa"),
    "阿聯酋": ("阿聯酋", "阿联酋", "uae"), "沙特阿拉伯": ("沙特阿拉伯", "saudi arabia"),
}


def extract_destinations(text):
    """Only explicit supported destination names; never infer a region's members."""
    result = set()
    for canonical, aliases in DESTINATION_ALIASES.items():
        for alias in aliases:
            expression = re.escape(alias)
            if alias.isascii():
                expression = r"(?<![a-z])" + expression + r"(?![a-z])"
            if re.search(expression, text, re.I):
                result.add(canonical)
                break
    if "中港澳" in text:
        result.update(("中國", "香港", "澳門"))
    return result


def extract_days(text):
    days = {int(value) for value in re.findall(r"(?<!\d)(\d{1,3})\s*(?:日|天|days?\b)", text, re.I)}
    digits = {char: value for value, chars in enumerate(("零〇", "一", "二兩两", "三", "四", "五", "六", "七", "八", "九")) for char in chars}
    for value in re.findall(r"([一二兩两三四五六七八九十]{1,3})\s*(?:日|天)", text):
        if "十" in value:
            first, last = value.split("十", 1)
            days.add((digits.get(first, 1) * 10) + digits.get(last, 0))
        elif value in digits:
            days.add(digits[value])
    return days


def extract_card_type(text):
    esim = bool(re.search(r"(?<![a-z])esim(?![a-z])|電子\s*sim|电子\s*sim", text, re.I))
    physical = bool(re.search(r"實體|实体|physical|(?<![a-z])sim\s+card(?![a-z])", text, re.I))
    if esim and physical:
        return "ambiguous"
    return "eSIM" if esim else ("SIM" if physical or text.strip().lower() == "sim" else None)


class CrawlError(ValueError):
    """A source is unsafe, unavailable, or not suitable for this crawler."""


def _public_ip(value):
    try:
        address = ipaddress.ip_address(value)
        return address.is_global and not address.is_multicast
    except ValueError:
        return False


def _public_dns(hostname):
    """Recover from local fake-IP DNS using fixed, TLS-verified DNS providers.

    A website or API caller cannot supply the resolver endpoint. Redirects and
    environment proxies are disabled. Answers still must be public IPs, and the
    page request uses only the validated IP with its original TLS hostname.
    """
    for endpoint in DOH_ENDPOINTS:
        try:
            with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
                response = client.get(endpoint, params={"name": hostname, "type": "A"},
                                      headers={"Accept": "application/dns-json"})
                if response.status_code != 200 or len(response.content) > 64_000:
                    continue
                answer = response.json()
            if answer.get("Status") != 0:
                continue
            # Confirm the provider answered the requested hostname, not a
            # different question. CNAME chains may end in different A names.
            questions = answer.get("Question", [])
            if not any(item.get("name", "").rstrip(".").lower() == hostname and item.get("type") == 1 for item in questions):
                continue
            ips = {item.get("data") for item in answer.get("Answer", []) if item.get("type") == 1}
            if ips and all(isinstance(ip, str) and _public_ip(ip) for ip in ips):
                return ips
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            continue
    raise CrawlError("系統 DNS 未回傳公開 IP，可信 DNS-over-HTTPS 解析也未取得安全結果；禁止存取內網或假 IP")


def _validated_target(url):
    try:
        parsed = urlsplit(url.strip())
        hostname = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        port = parsed.port
    except (ValueError, UnicodeError) as exc:
        raise CrawlError("網址格式無效") from exc
    allowed = {host.strip().lower() for host in settings.crawl_allowed_hosts.split(",")}
    if parsed.scheme not in ("http", "https") or not hostname:
        raise CrawlError("只允許公開網站的 HTTP/HTTPS 網址")
    if parsed.username or parsed.password or hostname not in allowed:
        raise CrawlError("網址主機不在允許擷取清單，或包含登入憑證")
    if port not in (None, 80 if parsed.scheme == "http" else 443):
        raise CrawlError("擷取僅允許標準 HTTP/HTTPS 連接埠")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None and not _public_ip(hostname):
        raise CrawlError("禁止擷取內網、迴路、保留或非公開 IP 位址")
    try:
        addresses = socket.getaddrinfo(hostname, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        ips = {entry[4][0] for entry in addresses}
    except OSError:
        ips = set()
    if not ips or not all(_public_ip(ip) for ip in ips):
        ips = _public_dns(hostname)
    # Quote Unicode paths without changing already escaped Shopline product URLs.
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="=&/%:@!$'()*+,;?-._~")
    normalized = urlunsplit((parsed.scheme.lower(), hostname, path, query, ""))
    return normalized, sorted(ips)[0]


def validate_source_url(url: str) -> str:
    """Validate the allowlist and all DNS answers; perform no HTTP request."""
    return _validated_target(url)[0]


def _site_key(url):
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _fetch_once(url):
    normalized, address = _validated_target(url)
    parsed = urlsplit(normalized)
    host = parsed.hostname
    netloc = f"[{address}]" if ":" in address else address
    pinned = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))
    # Connect to the validated address, while TLS verifies the original hostname.
    # This closes the DNS validation/request rebinding window. Ignore env proxies.
    try:
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", pinned, headers={"Host": host, "User-Agent": USER_AGENT},
                               extensions={"sni_hostname": host}) as response:
                if int(response.headers.get("content-length", "0")) > MAX_BYTES:
                    raise CrawlError("頁面超過 2 MB 限制")
                payload = bytearray()
                started = time.monotonic()
                for block in response.iter_bytes():
                    payload.extend(block)
                    if len(payload) > MAX_BYTES or time.monotonic() - started > 25:
                        raise CrawlError("頁面過大或讀取逾時")
                return response.status_code, dict(response.headers), bytes(payload), normalized
    except (httpx.HTTPError, ValueError) as exc:
        if isinstance(exc, CrawlError):
            raise
        raise CrawlError("網站請求失敗（網路、TLS 或回應格式錯誤）") from exc


def _fetch(url, site, robots_check=None):
    current = url
    for _ in range(6):
        if _site_key(current) != site:
            raise CrawlError("禁止重新導向其他網站")
        if robots_check:
            robots_check(current)
        status, headers, payload, current = _fetch_once(current)
        if status in (301, 302, 303, 307, 308):
            location = headers.get("location")
            if not location:
                raise CrawlError("重新導向缺少目標網址")
            current = urljoin(current, location)
            continue
        return status, headers, payload, current
    raise CrawlError("網頁重新導向次數過多")


class _Robots:
    def __init__(self, site):
        self.site = site
        self.cache = {}

    def check(self, url):
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.cache:
            status, _, body, _ = _fetch(origin + "/robots.txt", self.site)
            if status not in (200, 404):
                raise CrawlError("無法確認 robots.txt 許可，暫不擷取")
            parser = RobotFileParser()
            lines = body.decode("utf-8", errors="replace").splitlines() if status == 200 else []
            parser.parse(lines)
            if status == 404:
                parser.allow_all = True
            self.cache[origin] = (parser, lines)
        parser, lines = self.cache[origin]
        if not _robots_allowed(lines, url):
            raise CrawlError("robots.txt 禁止擷取此網址")
        delay = parser.crawl_delay(USER_AGENT) or 0
        if delay > 20:
            raise CrawlError("網站要求較長擷取間隔，請降低擷取頻率後使用專門同步任務")
        if delay:
            time.sleep(delay)


def _robots_allowed(lines, url):
    """Respect most-specific agent/rule, wildcard paths, and Allow ties.

    urllib.robotparser treats '*' in paths literally; Shopline actually uses
    wildcard query rules, so relying on its can_fetch would miss those rules.
    """
    groups, agents, rules = [], [], []
    for line in [*lines, ""]:
        line = line.split("#", 1)[0].strip()
        if not line:
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key in ("allow", "disallow") and agents and value:
            rules.append((value, key == "allow"))
    relevant = []
    for names, entries in groups:
        matching = [0 if name == "*" else len(name) for name in names if name == "*" or name in USER_AGENT.lower()]
        if matching:
            relevant.append((max(matching), entries))
    if not relevant:
        return True
    specificity = max(score for score, _ in relevant)
    parsed = urlsplit(url)
    path = parsed.path + ("?" + parsed.query if parsed.query else "")
    matches = []
    for score, entries in relevant:
        if score != specificity:
            continue
        for pattern, allowed in entries:
            end = pattern.endswith("$")
            expression = re.escape(pattern[:-1] if end else pattern).replace(r"\*", ".*")
            if re.match("^" + expression + ("$" if end else ""), path):
                matches.append((len(pattern.replace("*", "").rstrip("$")), allowed))
    return max(matches)[1] if matches else True


def _json_objects(value):
    if isinstance(value, list):
        for item in value:
            yield from _json_objects(item)
    elif isinstance(value, dict):
        yield value
        if "@graph" in value:
            yield from _json_objects(value["@graph"])


def _price(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError):
        return None


def _prose_text(root):
    # Keep inline emphasis/numbers in their sentences. get_text("\n") splits
    # <strong>21</strong> onto its own line and can lose the meaning when pages
    # repeat the same number. Only actual block boundaries introduce new lines.
    for text in list(root.find_all(string=True)):
        if isinstance(text, (Comment, Doctype)):
            text.extract()
        else:
            text.replace_with(re.sub(r"\s+", " ", str(text)))
    for line_break in list(root.find_all("br")):
        line_break.replace_with("\n")
    for block in list(root.find_all(("p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote"))):
        block.insert_before("\n")
        block.insert_after("\n")
    return root.get_text("", strip=False)


def parse_page(html, url):
    """Extract static HTML and Schema.org Products; never infer unknown prices."""
    soup = BeautifulSoup(html, "html.parser")
    products = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            values = _json_objects(json.loads(script.string or script.get_text()))
            for item in values:
                item_type = item.get("@type", [])
                if "Product" not in (item_type if isinstance(item_type, list) else [item_type]):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                offers = item.get("offers", {})
                offers = offers if isinstance(offers, dict) else (offers[0] if isinstance(offers, list) and len(offers) == 1 else {})
                # AggregateOffer/variant ranges are not a single purchasable price.
                price = _price(offers.get("price")) if offers.get("@type") != "AggregateOffer" else None
                currency = str(offers.get("priceCurrency") or "").strip() or None
                days = extract_days(name)
                allowance = re.search(r"\d+(?:\.\d+)?\s*(?:GB|MB)", name, re.I)
                products.append({"name": name[:300], "sku": str(item["sku"])[:160] if item.get("sku") else None,
                                 "price": price, "currency": currency[:12] if currency else None,
                                 "country": "、".join(sorted(extract_destinations(name))) or None,
                                 "days": next(iter(days)) if len(days) == 1 else None,
                                 "data_allowance": allowance.group(0) if allowance else None,
                                 "card_type": extract_card_type(name) if extract_card_type(name) != "ambiguous" else None,
                                 "url": url})
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue
    title_node = soup.find("h1") or soup.find("title")
    title = title_node.get_text(" ", strip=True)[:300] if title_node else url
    links = [urldefrag(urljoin(url, str(a.get("href"))))[0] for a in soup.find_all("a", href=True)]
    # Shopline's actual page has no <main>/<article>. Its menus/cart/account
    # drawers are sibling <div>s, so a body fallback previously polluted every
    # product with the complete country directory and hidden cart templates.
    for node in soup.select("script,style,noscript,nav,header,footer,form,svg,iframe,template,"
                            "#MenuPanel,#LanguagePanel,#CurrencyPanel,#cart-panel,#cookie-consent-popup,"
                            "#shopline-section-header,#shopline-section-footer,#shopline-section-announcement,"
                            ".MenuPanel,.CartPanel,.ProductDetail-loading-data,.product-review-summary-container,"
                            ".variation-detail,.txt-notify,.out-of-stock,.product-detail-button-container,"
                            "[role='navigation']"):
        node.decompose()
    product_info = soup.select_one(".js-product-info, .ProductDetail-product-info")
    if product_info:
        # These nodes were verified against the live Cool Data Sim Shopline
        # theme. Exclude selectors/prices/stock UI, retain useful prose and the
        # full description + shipping/payment/after-sales accordion body.
        roots = product_info.select(".Product-title, .Product-summary, .ProductDetail-additionalInfo")
        if not roots:
            roots = [product_info]
    else:
        body = (soup.select_one(".CustomPage-text-page, .CustomPage-content")
                or soup.find("main") or soup.find("article") or soup.select_one("[role='main']")
                or soup.select_one("#Content, .js-content") or soup.body or soup)
        roots = [body]
    lines = []
    raw_text = "\n".join(_prose_text(root) for root in roots)
    for line in raw_text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        line = line.replace("\u200b", "").replace("\u2060", "").strip()
        if (line and "{{" not in line and "}}" not in line and line not in lines[-1:]
                and not re.match(r"^(?:product|products|cart|checkout|general)\.[\w.]+$", line)):
            lines.append(line)
    return title, "\n".join(lines)[:100_000], products, links


def crawl_source(db, source, job) -> None:
    start = validate_source_url(source.url)
    site = _site_key(start)
    robots = _Robots(site)
    queue, seen = deque([start]), set()
    limit = min(max(source.max_pages, 1), 100)
    result = {"pages": 0, "documents_changed": 0, "products_changed": 0, "errors": [], "published": False,
              "scope": "bounded_same_site_html", "max_pages": limit, "attempted_pages": 0,
              "limit_reached": False, "time_limit_reached": False, "remaining_discovered": 0,
              "full_site_verified": False}
    started = time.monotonic()
    source.status = "syncing"
    db.commit()
    while queue and len(seen) < limit and time.monotonic() - started < MAX_CRAWL_SECONDS:
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        try:
            status, headers, payload, final_url = _fetch(url, site, robots.check)
            if status != 200:
                raise CrawlError(f"網頁回傳 HTTP {status}")
            if "html" not in headers.get("content-type", "").lower():
                raise CrawlError("首版僅擷取靜態 HTML；尚未支援此內容類型")
            title, content, products, links = parse_page(payload, final_url)
            if len(content.replace(title, "", 1).strip()) < 30:
                raise CrawlError("未擷取到足夠正文，頁面可能需要 JavaScript")
            digest = hashlib.sha256(content.encode()).hexdigest()
            doc = db.scalar(select(Document).where(Document.source_id == source.id, Document.url == final_url).with_for_update())
            if doc is None:
                doc = Document(source_id=source.id, url=final_url, title=title, content=content, content_hash=digest,
                               category="product" if products else "general")
                db.add(doc)
                result["documents_changed"] += 1
            elif doc.content_hash != digest or doc.title != title:
                doc.title, doc.content, doc.content_hash = title, content, digest
                doc.status, doc.revision, doc.updated_at = "draft", doc.revision + 1, utcnow()
                result["documents_changed"] += 1
            for fields in products[:1]:
                product = db.scalar(select(Product).where(Product.url == final_url).with_for_update())
                if product is None:
                    product = Product(source_id=source.id, **fields)
                    db.add(product)
                    result["products_changed"] += 1
                elif any(getattr(product, key) != value for key, value in fields.items()):
                    for key, value in fields.items():
                        setattr(product, key, value)
                    product.status, product.verified_at = "draft", None
                    result["products_changed"] += 1
            result["pages"] += 1
            # Query parameters produce duplicate locale/cart/filter pages; only
            # the explicitly provided source may carry them.
            useful = []
            for link in links:
                parsed = urlsplit(link)
                if parsed.scheme in ("https", "http") and _site_key(link) == site and not parsed.query:
                    if not re.search(r"/(users|cart|checkout|orders|api|preview)(/|$)", parsed.path):
                        useful.append(link)
            useful.sort(key=lambda value: ("/products/" not in value, "/pages/" not in value))
            queue.extend(link for link in useful if link not in seen and link not in queue)
            db.commit()
        except CrawlError as exc:
            result["errors"].append({"url": url, "error": str(exc)})
        job.progress = min(99, int(len(seen) / limit * 100))
        result["attempted_pages"] = len(seen)
        result["remaining_discovered"] = len(set(queue) - seen)
        job.updated_at, job.result = utcnow(), dict(result)
        db.commit()
    result["remaining_discovered"] = len(set(queue) - seen)
    result["limit_reached"] = len(seen) >= limit and result["remaining_discovered"] > 0
    result["time_limit_reached"] = bool(queue and time.monotonic() - started >= MAX_CRAWL_SECONDS)
    if result["time_limit_reached"]:
        result["errors"].append({"url": start, "error": "達到本次擷取 15 分鐘時間上限"})
    job.status = "succeeded" if result["pages"] and not result["errors"] else ("partial" if result["pages"] else "failed")
    job.progress, job.updated_at, job.result = 100, utcnow(), result
    job.error = None if not result["errors"] else f"{len(result['errors'])} 個頁面未成功擷取，詳見任務結果"
    source.status = ("limited" if result["remaining_discovered"] else "synced") if job.status == "succeeded" else job.status
    if result["pages"]:
        source.last_synced = utcnow()
    db.commit()


def split_content(content, size=900, overlap=120):
    text = content.strip()
    return [text[index:index + size] for index in range(0, len(text), size - overlap)]


def publish_document(db, doc) -> None:
    from .ai import embed_texts

    # Serialize publication/withdrawal with edits and other publishers. The API
    # owns commit/rollback, so this lock is retained through its final commit.
    db.flush()
    db.refresh(doc, with_for_update=True)
    pieces = split_content(doc.content)
    if not pieces:
        raise ValueError("空白文件不能發佈")
    vectors = embed_texts(pieces) if settings.embedding_base_url else [None] * len(pieces)
    # Build/validate every embedding before touching the old published snapshot.
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    for piece, vector in zip(pieces, vectors, strict=True):
        db.add(Chunk(document_id=doc.id, body=piece, embedding=vector,
                     model=settings.embedding_model if vector is not None else None))
    doc.published_content, doc.published_title, doc.published_url = doc.content, doc.title, doc.url
    doc.status, doc.vector_status, doc.updated_at = "published", "indexed" if settings.embedding_base_url else "text_only", utcnow()
    db.flush()


def withdraw_document(db, doc) -> None:
    db.flush()
    db.refresh(doc, with_for_update=True)
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    doc.status, doc.vector_status, doc.updated_at = "withdrawn", "not_indexed", utcnow()
    doc.published_content = doc.published_title = doc.published_url = None
    db.flush()
