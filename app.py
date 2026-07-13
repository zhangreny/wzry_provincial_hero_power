from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote as url_quote, urlparse
from urllib.request import Request, urlopen
import json
import socket
import threading
import time


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"
PORT = 8765
CACHE_ROOT = ROOT / ".cache"

HERO_LIST_URL = "https://www.sapi.run/hero/herolist.json"
HERO_RANK_URL = "https://www.sapi.run/hero/select.php"
DEFAULT_PLATFORM = "ios_wx"
MAX_WORKERS = 8
CACHE_TTL_SECONDS = 10 * 60
REFRESHING = {}
REFRESH_LOCK = threading.Lock()

PLATFORM_LABELS = {
    "qq": "安卓QQ",
    "wx": "安卓微信",
    "ios_qq": "苹果QQ",
    "ios_wx": "苹果微信",
}


def request(url, encoding="utf-8", referer="https://www.sapi.run/"):
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": referer,
        },
    )
    last_error = None
    for attempt in range(3):
        try:
            with urlopen(req, timeout=8) as response:
                return response.read().decode(encoding, errors="replace")
        except (HTTPError, URLError, TimeoutError, socket.timeout) as exc:
            last_error = exc
            time.sleep(0.4 * (attempt + 1))
    raise last_error


def read_int(value):
    if value in (None, "", "-"):
        return None
    return int(value)


def first_value(data, keys, default=""):
    if not isinstance(data, dict):
        return default
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def fetch_hero_list():
    payload = json.loads(request(HERO_LIST_URL))
    if payload.get("code") != 200 or not isinstance(payload.get("data"), list):
        raise ValueError("英雄列表接口返回异常")

    heroes = []
    for item in payload["data"]:
        hero_id = str(item.get("ename") or "").strip()
        name = str(item.get("cname") or "").strip()
        if hero_id and name:
            heroes.append(
                {
                    "ename": hero_id,
                    "cname": name,
                    "title": item.get("title") or "",
                    "iconUrl": item.get("iconUrl") or "",
                }
            )

    return sorted(heroes, key=lambda hero: int(hero["ename"]) if hero["ename"].isdigit() else hero["ename"])


def fetch_hero_rank(hero, platform=DEFAULT_PLATFORM):
    platform = platform if platform in PLATFORM_LABELS else DEFAULT_PLATFORM
    url = f"{HERO_RANK_URL}?hero={url_quote(hero['cname'])}&type={url_quote(platform)}"
    payload = json.loads(request(url))
    if payload.get("code") != 200 or not isinstance(payload.get("data"), dict):
        raise ValueError(payload.get("msg") or f"接口返回 code={payload.get('code')}")

    data = payload["data"]
    return {
        "heroId": str(first_value(data, ("uid", "id", "heroId", "ename"), hero.get("ename") or "")),
        "name": first_value(data, ("name", "cname"), hero.get("cname") or "--"),
        "alias": first_value(data, ("alias", "title"), hero.get("title") or ""),
        "platform": first_value(data, ("platform", "type"), PLATFORM_LABELS[platform]),
        "photo": first_value(data, ("photo", "iconUrl", "icon"), hero.get("iconUrl") or ""),
        "province": first_value(data, ("province",), ""),
        "provincePower": read_int(first_value(data, ("provincePower",), None)),
        "city": first_value(data, ("city",), ""),
        "cityPower": read_int(first_value(data, ("cityPower",), None)),
        "area": first_value(data, ("area",), ""),
        "areaPower": read_int(first_value(data, ("areaPower",), None)),
        "nationalPower": read_int(first_value(data, ("guobiao", "nationalPower"), None)),
        "updatedAt": first_value(data, ("updatetime", "updatedAt", "time"), ""),
        "source": "sapi.run",
        "ok": True,
    }


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
        "updatedAt": "",
        "source": "sapi.run",
        "ok": False,
        "error": str(error),
    }


def pending_rank(hero, platform):
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
        "updatedAt": "",
        "source": "sapi.run",
        "ok": False,
        "pending": True,
    }


def fetch_all_hero_ranks(platform=DEFAULT_PLATFORM):
    platform = platform if platform in PLATFORM_LABELS else DEFAULT_PLATFORM
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


def rank_cache_path(platform):
    return CACHE_ROOT / f"ranks-{normalize_platform(platform)}.json"


def read_rank_cache(platform):
    path = rank_cache_path(platform)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload.get("ranks"), list):
        return None
    return payload


def write_rank_cache(platform, ranks):
    platform = normalize_platform(platform)
    CACHE_ROOT.mkdir(exist_ok=True)
    payload = {
        "platform": platform,
        "platformLabel": PLATFORM_LABELS[platform],
        "cachedAt": time.time(),
        "ranks": ranks,
    }
    path = rank_cache_path(platform)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return payload


def refresh_rank_cache(platform):
    platform = normalize_platform(platform)
    try:
        write_rank_cache(platform, fetch_all_hero_ranks(platform))
    finally:
        with REFRESH_LOCK:
            REFRESHING[platform] = False


def start_background_refresh(platform):
    platform = normalize_platform(platform)
    with REFRESH_LOCK:
        if REFRESHING.get(platform):
            return True
        REFRESHING[platform] = True

    thread = threading.Thread(target=refresh_rank_cache, args=(platform,), daemon=True)
    thread.start()
    return True


def is_cache_stale(cache):
    cached_at = cache.get("cachedAt") if isinstance(cache, dict) else None
    return not isinstance(cached_at, (int, float)) or time.time() - cached_at >= CACHE_TTL_SECONDS


def ranks_payload(platform=DEFAULT_PLATFORM, force_refresh=False):
    platform = normalize_platform(platform)
    cache = read_rank_cache(platform)
    refreshing = False

    if force_refresh or cache is None or is_cache_stale(cache):
        refreshing = start_background_refresh(platform)

    if cache:
        return {
            "platform": platform,
            "platformLabel": PLATFORM_LABELS[platform],
            "cached": True,
            "cachedAt": cache.get("cachedAt"),
            "refreshing": refreshing or REFRESHING.get(platform, False),
            "ranks": cache["ranks"],
        }

    heroes = fetch_hero_list()
    return {
        "platform": platform,
        "platformLabel": PLATFORM_LABELS[platform],
        "cached": False,
        "cachedAt": None,
        "refreshing": refreshing or REFRESHING.get(platform, False),
        "ranks": [pending_rank(hero, platform) for hero in heroes],
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
    print(f"http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
