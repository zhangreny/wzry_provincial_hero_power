import unittest
from unittest.mock import patch

import app


class HonorDataTests(unittest.TestCase):
    def test_signs_yxsaoma_score_request_like_the_frontend(self):
        params = app.yxsaoma_signed_params({"heroId": "151", "gameAreaId": 3}, timestamp=1700000000000)

        self.assertEqual(params["heroId"], "151")
        self.assertEqual(params["gameAreaId"], 3)
        self.assertEqual(params["timestamp"], 1700000000000)
        self.assertEqual(params["sign"], "001972ce8c5d2c6f383933be3644c7f9")

    def test_fetches_heroes_from_yxsaoma_without_hero_page_urls(self):
        payload = {
            "code": "0000",
            "data": [
                {"ename": "151", "cname": "\u5b59\u6743", "title": "\u6c5f\u4e1c\u4e4b\u8c0b", "heroType": 5},
            ],
        }

        with patch.object(app, "request_json", return_value=payload) as request_json:
            heroes = app.fetch_hero_list()

        request_json.assert_called_once_with(app.YXSAOMA_HEROES_URL)
        self.assertEqual(heroes[0]["ename"], "151")
        self.assertEqual(heroes[0]["cname"], "\u5b59\u6743")
        self.assertEqual(heroes[0]["url"], "")

    def test_parses_lowest_province_and_macau_score(self):
        hero = {"ename": "151", "cname": "\u5b59\u6743", "title": "\u6c5f\u4e1c\u4e4b\u8c0b"}
        payload = {
            "code": "0000",
            "data": {
                "heroList": [
                    {"address": "\u6d59\u6c5f", "level": "province", "rank": 8200},
                    {"address": "\u6fb3\u95e8", "level": "province", "rank": 7700},
                    {"address": "\u5317\u4eac", "level": "province", "rank": 7600},
                    {"address": "\u5317\u4eac/\u4e1c\u57ce\u533a", "level": "city", "rank": 5000},
                ],
                "synDate": "2026-07-14",
            },
        }

        rank = app.parse_yxsaoma_apple_wechat_rank(payload, hero)

        self.assertEqual(rank["heroId"], "151")
        self.assertEqual(rank["name"], "\u5b59\u6743")
        self.assertEqual(rank["province"], "\u5317\u4eac")
        self.assertEqual(rank["provincePower"], 7600)
        self.assertEqual(rank["macauPower"], 7700)
        self.assertEqual(rank["source"], "yxsaoma.com")
        self.assertTrue(rank["ok"])
        self.assertEqual(len(rank["provinceRanks"]), 3)

    def test_fetch_hero_rank_uses_apple_wechat_score_endpoint(self):
        hero = {"ename": "151", "cname": "\u5b59\u6743", "title": ""}
        payload = {
            "code": "0000",
            "data": {"heroList": [{"address": "\u6fb3\u95e8", "level": "province", "rank": 7700}]},
        }

        with patch.object(app, "fetch_yxsaoma_score", return_value=payload) as fetch_score:
            rank = app.fetch_hero_rank(hero, "ios_wx")

        fetch_score.assert_called_once_with("151", app.APPLE_WECHAT_GAME_AREA_ID)
        self.assertEqual(rank["province"], "\u6fb3\u95e8")
        self.assertEqual(rank["macauPower"], 7700)

    def test_ranks_payload_fetches_without_cache(self):
        ranks = [{"heroId": "151", "name": "\u5b59\u6743", "provincePower": 7600, "macauPower": 7700, "ok": True}]

        with patch.object(app, "fetch_all_hero_ranks", return_value=ranks) as fetch:
            payload = app.ranks_payload("ios_wx")

        fetch.assert_called_once_with("ios_wx")
        self.assertEqual(payload["ranks"], ranks)
        self.assertFalse(payload["cached"])
        self.assertFalse(payload["refreshing"])

    def test_iter_rank_events_yields_each_rank_without_waiting_for_all(self):
        heroes = [
            {"ename": "151", "cname": "\u5b59\u6743"},
            {"ename": "167", "cname": "\u5b59\u609f\u7a7a"},
        ]

        def fake_fetch(hero, platform):
            return {"heroId": hero["ename"], "name": hero["cname"], "provincePower": 7600, "macauPower": 7700, "ok": True}

        with patch.object(app, "fetch_hero_list", return_value=heroes):
            with patch.object(app, "fetch_hero_rank", side_effect=fake_fetch):
                events = list(app.iter_rank_events("ios_wx"))

        self.assertEqual(events[0]["type"], "meta")
        self.assertEqual(events[0]["total"], 2)
        self.assertEqual([event["type"] for event in events[1:]], ["rank", "rank"])
        self.assertEqual({event["rank"]["heroId"] for event in events[1:]}, {"151", "167"})
        self.assertEqual(events[-1]["done"], 2)


if __name__ == "__main__":
    unittest.main()
