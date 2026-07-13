import json
import unittest
from unittest.mock import patch

import app


class HonorDataTests(unittest.TestCase):
    def test_normalizes_apple_wechat_province_rank(self):
        payload = {
            "code": 200,
            "data": {
                "uid": "131",
                "name": "李白",
                "alias": "青莲剑仙-李白",
                "platform": "苹果-微信区",
                "photo": "https://example.test/libai.jpg",
                "province": "北京市",
                "provincePower": "7192",
                "city": "北京市",
                "cityPower": "4750",
                "area": "朝阳区",
                "areaPower": "1652",
                "guobiao": "11053",
                "updatetime": "2026/07/12 22:35:18",
            },
        }

        with patch.object(app, "request", return_value=json.dumps(payload, ensure_ascii=False)):
            rank = app.fetch_hero_rank({"ename": "131", "cname": "李白"}, "ios_wx")

        self.assertEqual(
            rank,
            {
                "heroId": "131",
                "name": "李白",
                "alias": "青莲剑仙-李白",
                "platform": "苹果-微信区",
                "photo": "https://example.test/libai.jpg",
                "province": "北京市",
                "provincePower": 7192,
                "city": "北京市",
                "cityPower": 4750,
                "area": "朝阳区",
                "areaPower": 1652,
                "nationalPower": 11053,
                "updatedAt": "2026/07/12 22:35:18",
                "source": "sapi.run",
                "ok": True,
            },
        )

    def test_fetch_all_hero_ranks_keeps_failed_hero_rows(self):
        heroes = [
            {"ename": "131", "cname": "李白"},
            {"ename": "132", "cname": "马可波罗"},
        ]

        def fake_fetch(hero, platform):
            if hero["cname"] == "马可波罗":
                raise ValueError("接口返回 code=500")
            return {
                "heroId": "131",
                "name": "李白",
                "alias": "青莲剑仙-李白",
                "platform": "苹果-微信区",
                "photo": "",
                "province": "北京市",
                "provincePower": 7192,
                "city": "北京市",
                "cityPower": 4750,
                "area": "朝阳区",
                "areaPower": 1652,
                "nationalPower": 11053,
                "updatedAt": "2026/07/12 22:35:18",
                "source": "sapi.run",
                "ok": True,
            }

        with patch.object(app, "fetch_hero_list", return_value=heroes):
            with patch.object(app, "fetch_hero_rank", side_effect=fake_fetch):
                ranks = app.fetch_all_hero_ranks("ios_wx")

        self.assertEqual(len(ranks), 2)
        self.assertTrue(ranks[0]["ok"])
        self.assertEqual(ranks[0]["provincePower"], 7192)
        self.assertFalse(ranks[1]["ok"])
        self.assertEqual(ranks[1]["heroId"], "132")
        self.assertEqual(ranks[1]["name"], "马可波罗")
        self.assertEqual(ranks[1]["platform"], "苹果微信")
        self.assertIn("接口返回 code=500", ranks[1]["error"])

    def test_ranks_payload_returns_disk_cache_without_blocking_on_remote_refresh(self):
        cached_ranks = [
            {
                "heroId": "131",
                "name": "李白",
                "alias": "青莲剑仙-李白",
                "platform": "苹果-微信区",
                "photo": "",
                "province": "北京市",
                "provincePower": 7192,
                "city": "北京市",
                "cityPower": 4750,
                "area": "朝阳区",
                "areaPower": 1652,
                "nationalPower": 11053,
                "updatedAt": "2026/07/12 22:35:18",
                "source": "sapi.run",
                "ok": True,
            }
        ]

        with patch.object(app, "read_rank_cache", return_value={"ranks": cached_ranks, "cachedAt": 123}):
            with patch.object(app, "fetch_all_hero_ranks", side_effect=AssertionError("must not block")):
                with patch.object(app, "start_background_refresh", return_value=True) as refresh:
                    payload = app.ranks_payload("ios_wx", force_refresh=True)

        self.assertEqual(payload["ranks"], cached_ranks)
        self.assertTrue(payload["cached"])
        self.assertTrue(payload["refreshing"])
        refresh.assert_called_once_with("ios_wx")

    def test_ranks_payload_returns_pending_rows_when_cache_is_empty(self):
        heroes = [
            {"ename": "131", "cname": "李白", "title": "青莲剑仙", "iconUrl": "https://example.test/libai.jpg"}
        ]

        with patch.object(app, "read_rank_cache", return_value=None):
            with patch.object(app, "fetch_hero_list", return_value=heroes):
                with patch.object(app, "start_background_refresh", return_value=True) as refresh:
                    payload = app.ranks_payload("ios_wx")

        self.assertFalse(payload["cached"])
        self.assertTrue(payload["refreshing"])
        self.assertEqual(payload["ranks"][0]["heroId"], "131")
        self.assertEqual(payload["ranks"][0]["name"], "李白")
        self.assertTrue(payload["ranks"][0]["pending"])
        self.assertIsNone(payload["ranks"][0]["provincePower"])
        refresh.assert_called_once_with("ios_wx")


if __name__ == "__main__":
    unittest.main()
