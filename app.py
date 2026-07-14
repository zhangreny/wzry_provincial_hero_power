from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen
import html as html_lib
import json
import re
import socket
import time


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"
PORT = 8765

YATEJIA_ROOT = "https://wenda.yatejia.cn"
YATEJIA_HERO_INDEX_URL = f"{YATEJIA_ROOT}/wangzherongyao/"
DEFAULT_PLATFORM = "ios_wx"
MAX_WORKERS = 24

PLATFORM_LABELS = {
    "qq": "安卓QQ",
    "wx": "安卓微信",
    "ios_qq": "苹果QQ",
    "ios_wx": "苹果微信",
}

APPLE_WECHAT_SECTION = "苹果微信大区"


def request(url, encoding="utf-8", referer=YATEJIA_ROOT):
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/json,text/plain,*/*",
            "Referer": referer,
        },
    )
    last_error = None
    for attempt in range(3):
        try:
            with urlopen(req, timeout=12) as response:
                return response.read().decode(encoding, errors="replace")
        except HTTPError as exc:
            if 400 <= exc.code < 500:
                raise exc
            last_error = exc
            time.sleep(0.4 * (attempt + 1))
        except (URLError, TimeoutError, socket.timeout) as exc:
            last_error = exc
            time.sleep(0.4 * (attempt + 1))
    raise last_error


def read_int(value):
    if value in (None, "", "-"):
        return None
    return int(str(value).replace(",", "").strip())


def strip_tags(value):
    text = re.sub(r"<[^>]+>", "", value or "")
    return html_lib.unescape(text).strip()


def first_match(pattern, text, default="", flags=re.S):
    match = re.search(pattern, text, flags)
    return html_lib.unescape(match.group(1)).strip() if match else default


def fetch_apple_wechat_hero_urls():
    html = request(YATEJIA_HERO_INDEX_URL)
    seen = set()
    heroes = []

    for href in re.findall(r"<a\b[^>]*href=[\"']([^\"']*?/wangzherongyao/[^\"']+/?)", html, re.I):
        url = urljoin(YATEJIA_HERO_INDEX_URL, html_lib.unescape(href))
        parsed = urlparse(url)
        if parsed.netloc != "wenda.yatejia.cn":
            continue
        slug = parsed.path.strip("/").split("/")[-1]
        if not slug or slug == "wangzherongyao" or url in seen:
            continue
        seen.add(url)
        heroes.append(
            {
                "ename": slug,
                "cname": slug,
                "title": "",
                "iconUrl": "",
                "url": url,
            }
        )

    return heroes


def fetch_hero_list():
    return fetch_apple_wechat_hero_urls()


def yatejia_platform_section(page_html):
    start = page_html.find(APPLE_WECHAT_SECTION)
    if start < 0:
        raise ValueError("页面缺少苹果微信大区")

    next_item = page_html.find('<div class="material-item"', start + len(APPLE_WECHAT_SECTION))
    return page_html[start : next_item if next_item >= 0 else len(page_html)]


def parse_province_rows(section_html):
    province_start = section_html.find("<h3>省标战区</h3>")
    if province_start < 0:
        raise ValueError("页面缺少苹果微信省标战区")

    province_html = section_html[province_start:]
    data_section_start = province_html.find('<div class="data-section"')
    if data_section_start >= 0:
        province_html = province_html[:data_section_start]

    rows = []
    row_pattern = re.compile(
        r"<span[^>]*class=['\"]fraction-prefix['\"][^>]*>\s*(\d+)\s*</span>\s*"
        r"<span[^>]*class=['\"]area['\"][^>]*>(.*?)</span>\s*"
        r"<span[^>]*class=['\"]fraction-value['\"][^>]*>\s*([0-9,]+)\s*分\s*</span>",
        re.S,
    )
    for rank, area, value in row_pattern.findall(province_html):
        rows.append(
            {
                "rank": read_int(rank),
                "area": strip_tags(area),
                "power": read_int(value),
            }
        )

    if not rows:
        raise ValueError("页面未解析到苹果微信省标分数")
    return rows


def parse_national_power(section_html):
    match = re.search(
        r"苹果微信区国标上榜分数：.*?([0-9,]+)\s*（大国标）.*?([0-9,]+)\s*（小国标）",
        strip_tags(section_html),
        re.S,
    )
    if not match:
        return None, None
    return read_int(match.group(1)), read_int(match.group(2))


def parse_yatejia_apple_wechat_rank(page_html, hero):
    section = yatejia_platform_section(page_html)
    province_rows = parse_province_rows(section)
    national_power, small_national_power = parse_national_power(section)
    top = province_rows[0]

    name = first_match(r'<div class="character-name">\s*(.*?)\s*</div>', page_html, hero.get("cname") or "--")
    photo = first_match(r'<img\s+src="([^"]+)"\s+alt="[^"]*的头像"', page_html, hero.get("iconUrl") or "")
    updated_at = first_match(r'<div id="update-time"[^>]*>\s*更新时间:\s*(.*?)\s*</div>', page_html, "")
    if not updated_at:
        updated_at = first_match(r'article:modified_time"\s+content="([^"]+)"', page_html, "")

    return {
        "heroId": str(hero.get("ename") or ""),
        "name": name,
        "alias": hero.get("title") or "",
        "platform": "苹果微信大区",
        "photo": photo,
        "province": top["area"],
        "provincePower": top["power"],
        "city": "",
        "cityPower": None,
        "area": "",
        "areaPower": None,
        "nationalPower": national_power,
        "smallNationalPower": small_national_power,
        "updatedAt": updated_at,
        "source": "wenda.yatejia.cn",
        "sourceUrl": hero.get("url") or "",
        "provinceRanks": province_rows,
        "ok": True,
    }


def fetch_hero_rank(hero, platform=DEFAULT_PLATFORM):
    if normalize_platform(platform) != DEFAULT_PLATFORM:
        raise ValueError("yatejia 当前只抓取苹果微信大区")
    url = hero.get("url")
    if not url:
        raise ValueError("英雄缺少 yatejia URL")
    return parse_yatejia_apple_wechat_rank(request(url, referer=YATEJIA_HERO_INDEX_URL), hero)


def failed_rank(hero, platform, error):
    return {
        "heroId": str(hero.get("ename") or ""),
        "name": hero.get("cname") or "--",
        "alias": hero.get("title") or "",
        "platform": PLATFORM_LABELS.get(platform, PLATFORM_LABELS[DEFAULT_PLATFORM]),
        "photo": hero.get("iconUrl") or "",
        "province": "",
        "provincePower": None,
        "city": "",
        "cityPower": None,
        "area": "",
        "areaPower": None,
        "nationalPower": None,
        "smallNationalPower": None,
        "updatedAt": "",
        "source": "wenda.yatejia.cn",
        "sourceUrl": hero.get("url") or "",
        "ok": False,
        "error": str(error),
    }


def fetch_all_hero_ranks(platform=DEFAULT_PLATFORM):
    platform = normalize_platform(platform)
    heroes = fetch_hero_list()
    results = [None] * len(heroes)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(fetch_hero_rank, hero, platform): (index, hero)
            for index, hero in enumerate(heroes)
        }
        for future in as_completed(future_map):
            index, hero = future_map[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                results[index] = failed_rank(hero, platform, exc)

    return results


def normalize_platform(platform):
    return platform if platform in PLATFORM_LABELS else DEFAULT_PLATFORM


def read_rank_cache(_platform):
    return None


def write_rank_cache(_platform, _ranks):
    return None


def ranks_payload(platform=DEFAULT_PLATFORM, force_refresh=False):
    platform = normalize_platform(platform)
    ranks = fetch_all_hero_ranks(platform)
    return {
        "platform": platform,
        "platformLabel": PLATFORM_LABELS[platform],
        "cached": False,
        "cachedAt": None,
        "refreshing": False,
        "ranks": ranks,
    }


def json_response(handler, payload, status=200):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_ROOT, **kwargs)

    def log_message(self, *_):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/api/heroes":
            try:
                json_response(self, {"heroes": fetch_hero_list()})
            except Exception as exc:
                json_response(self, {"heroes": [], "error": str(exc)}, 502)
            return

        if parsed.path == "/api/ranks":
            platform = query.get("platform", [DEFAULT_PLATFORM])[0]
            try:
                force_refresh = query.get("refresh", ["0"])[0] == "1"
                json_response(self, ranks_payload(platform, force_refresh))
            except Exception as exc:
                json_response(self, {"platform": platform, "ranks": [], "error": str(exc)}, 502)
            return

        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()


if __name__ == "__main__":
    print(f"http://0.0.0.0:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
