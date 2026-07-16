from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
import hashlib
import json
import socket
import time


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"
PORT = 8765
SIGN_TIMESTAMP_LOCK = Lock()
LAST_SIGN_TIMESTAMP = 0

YXSAOMA_ROOT = "https://yxsaoma.com"
YXSAOMA_PAGE_URL = f"{YXSAOMA_ROOT}/czl"
YXSAOMA_HEROES_URL = f"{YXSAOMA_ROOT}/api/app/pvp/heroes"
YXSAOMA_SCORE_URL = f"{YXSAOMA_ROOT}/api/app/pvp/v2/area/score"
YXSAOMA_SIGN_KEY = "warzoneSignKey20240515"
APPLE_WECHAT_GAME_AREA_ID = 3
DEFAULT_PLATFORM = "ios_wx"
MAX_WORKERS = 4

PLATFORM_LABELS = {
    "qq": "\u5b89\u5353QQ",
    "wx": "\u5b89\u5353\u5fae\u4fe1",
    "ios_qq": "\u82f9\u679cQQ",
    "ios_wx": "\u82f9\u679c\u5fae\u4fe1",
}


def request(url, params=None, referer=YXSAOMA_PAGE_URL):
    if params:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urlencode(params)}"

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
            with urlopen(req, timeout=12) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            if 400 <= exc.code < 500:
                raise exc
            last_error = exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            last_error = exc
        time.sleep(0.4 * (attempt + 1))
    raise last_error


def request_json(url, params=None):
    try:
        return json.loads(request(url, params=params))
    except json.JSONDecodeError as exc:
        raise ValueError("yxsaoma returned invalid JSON") from exc


def read_int(value):
    if value in (None, "", "-"):
        return None
    return int(str(value).replace(",", "").strip())


def yxsaoma_signed_params(params, timestamp=None):
    signed = dict(params)
    if timestamp is None:
        global LAST_SIGN_TIMESTAMP
        with SIGN_TIMESTAMP_LOCK:
            timestamp = max(int(time.time() * 1000), LAST_SIGN_TIMESTAMP + 1)
            LAST_SIGN_TIMESTAMP = timestamp
    signed["timestamp"] = timestamp
    canonical = "&".join(f"{key}={signed[key]}" for key in sorted(signed)) + YXSAOMA_SIGN_KEY
    signed["sign"] = hashlib.md5(canonical.encode("utf-8")).hexdigest()
    return signed


def yxsaoma_data(payload):
    if payload.get("code") != "0000":
        raise ValueError(payload.get("desc") or "yxsaoma request failed")
    return payload.get("data")


def fetch_hero_list():
    data = yxsaoma_data(request_json(YXSAOMA_HEROES_URL))
    if not isinstance(data, list):
        raise ValueError("yxsaoma hero list is invalid")

    heroes = []
    for item in data:
        hero_id = str(item.get("ename") or "")
        if not hero_id:
            continue
        heroes.append(
            {
                "ename": hero_id,
                "cname": item.get("cname") or hero_id,
                "title": item.get("title") or "",
                "iconUrl": f"https://game.gtimg.cn/images/yxzj/img201606/heroimg/{hero_id}/{hero_id}.jpg",
                "url": "",
            }
        )
    return heroes


def fetch_yxsaoma_score(hero_id, game_area_id):
    params = yxsaoma_signed_params({"heroId": str(hero_id), "gameAreaId": game_area_id})
    return request_json(YXSAOMA_SCORE_URL, params=params)


def is_macau(area):
    normalized = (area or "").replace("\u7279\u522b\u884c\u653f\u533a", "")
    return normalized in {"\u6fb3\u95e8", "\u4e2d\u56fd\u6fb3\u95e8"}


def parse_yxsaoma_apple_wechat_rank(payload, hero):
    data = yxsaoma_data(payload)
    rows = data.get("heroList") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("yxsaoma province list is invalid")

    province_rows = []
    for row in rows:
        if row.get("level") != "province":
            continue
        power = read_int(row.get("rank"))
        area = str(row.get("address") or "").strip()
        if power is None or not area:
            continue
        province_rows.append({"area": area, "power": power})

    if not province_rows:
        raise ValueError("yxsaoma returned no province scores")

    lowest = min(province_rows, key=lambda row: row["power"])
    macau_rows = [row for row in province_rows if is_macau(row["area"])]
    macau_power = min((row["power"] for row in macau_rows), default=None)

    return {
        "heroId": str(hero.get("ename") or ""),
        "name": hero.get("cname") or "--",
        "alias": hero.get("title") or "",
        "platform": PLATFORM_LABELS[DEFAULT_PLATFORM],
        "photo": hero.get("iconUrl") or "",
        "province": lowest["area"],
        "provincePower": lowest["power"],
        "macauPower": macau_power,
        "city": "",
        "cityPower": None,
        "area": "",
        "areaPower": None,
        "nationalPower": None,
        "smallNationalPower": None,
        "source": "yxsaoma.com",
        "sourceUrl": YXSAOMA_PAGE_URL,
        "provinceRanks": province_rows,
        "ok": True,
    }


def fetch_hero_rank(hero, platform=DEFAULT_PLATFORM):
    if normalize_platform(platform) != DEFAULT_PLATFORM:
        raise ValueError("only Apple WeChat is supported")
    payload = fetch_yxsaoma_score(hero.get("ename"), APPLE_WECHAT_GAME_AREA_ID)
    return parse_yxsaoma_apple_wechat_rank(payload, hero)


def failed_rank(hero, platform, error):
    return {
        "heroId": str(hero.get("ename") or ""),
        "name": hero.get("cname") or "--",
        "alias": hero.get("title") or "",
        "platform": PLATFORM_LABELS.get(platform, PLATFORM_LABELS[DEFAULT_PLATFORM]),
        "photo": hero.get("iconUrl") or "",
        "province": "",
        "provincePower": None,
        "macauPower": None,
        "city": "",
        "cityPower": None,
        "area": "",
        "areaPower": None,
        "nationalPower": None,
        "smallNationalPower": None,
        "source": "yxsaoma.com",
        "sourceUrl": YXSAOMA_PAGE_URL,
        "ok": False,
        "error": str(error),
    }


def fetch_all_hero_ranks(platform=DEFAULT_PLATFORM):
    return [event["rank"] for event in iter_rank_events(platform) if event["type"] == "rank"]


def iter_rank_events(platform=DEFAULT_PLATFORM):
    platform = normalize_platform(platform)
    heroes = fetch_hero_list()
    total = len(heroes)
    done = 0

    yield {
        "type": "meta",
        "platform": platform,
        "platformLabel": PLATFORM_LABELS[platform],
        "total": total,
    }

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(fetch_hero_rank, hero, platform): hero
            for hero in heroes
        }
        for future in as_completed(future_map):
            hero = future_map[future]
            done += 1
            try:
                rank = future.result()
            except Exception as exc:
                rank = failed_rank(hero, platform, exc)

            yield {
                "type": "rank",
                "platform": platform,
                "done": done,
                "total": total,
                "rank": rank,
            }


def normalize_platform(platform):
    return platform if platform in PLATFORM_LABELS else DEFAULT_PLATFORM


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


def stream_json_lines(handler, events):
    handler.send_response(200)
    handler.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Accel-Buffering", "no")
    handler.end_headers()

    for event in events:
        line = json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"
        handler.wfile.write(line)
        handler.wfile.flush()


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

        if parsed.path == "/api/ranks/stream":
            platform = query.get("platform", [DEFAULT_PLATFORM])[0]
            try:
                stream_json_lines(self, iter_rank_events(platform))
            except Exception as exc:
                try:
                    line = json.dumps({"type": "error", "error": str(exc)}, ensure_ascii=False).encode("utf-8") + b"\n"
                    self.wfile.write(line)
                    self.wfile.flush()
                except Exception:
                    pass
            return

        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()


if __name__ == "__main__":
    print(f"http://0.0.0.0:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
