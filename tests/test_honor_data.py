import unittest
from unittest.mock import patch

import app


class HonorDataTests(unittest.TestCase):
    def test_fetch_apple_wechat_hero_urls_from_yatejia_index(self):
        html = """
        <a href="https://wenda.yatejia.cn/wangzherongyao/libai/"></a>
        <a href="/wangzherongyao/zhaoyun/"></a>
        <a href="https://wenda.yatejia.cn/wangzherongyao/libai/"></a>
        <a href="https://wenda.yatejia.cn/other/"></a>
        """

        with patch.object(app, "request", return_value=html):
            heroes = app.fetch_apple_wechat_hero_urls()

        self.assertEqual(
            heroes,
            [
                {
                    "ename": "libai",
                    "cname": "libai",
                    "title": "",
                    "iconUrl": "",
                    "url": "https://wenda.yatejia.cn/wangzherongyao/libai/",
                },
                {
                    "ename": "zhaoyun",
                    "cname": "zhaoyun",
                    "title": "",
                    "iconUrl": "",
                    "url": "https://wenda.yatejia.cn/wangzherongyao/zhaoyun/",
                },
            ],
        )

    def test_parses_yatejia_apple_wechat_province_rank(self):
        html = """
        <meta property="article:modified_time" content="2025-01-20T17:26:00+08:00">
        <div class="character">
          <img src="https://game.gtimg.cn/images/yxzj/img201606/heroimg/131/131.jpg" alt="李白的头像">
          <div class="character-info">
            <div class="character-name">李白</div>
            <div id="update-time" class="update-date">更新时间: 2025/05/31 05:33:30</div>
          </div>
        </div>
        <div class="material-item">苹果微信大区
          <div class="material-options active">
            <div class="material-option"><h3>铜标战区</h3></div>
            <div class="material-option"><h3>市标战区</h3></div>
            <div class="material-option"><h3>省标战区</h3>
              <p>
                <li><span class='fraction-prefix'>1</span><span class='area'>山西省</span><span class='fraction-value'>6707分</span></li>
                <li><span class='fraction-prefix'>2</span><span class='area'>黑龙江省</span><span class='fraction-value'>6738分</span></li>
              </p>
            </div>
          </div>
          <div class="data-section">
            <p><strong>苹果微信区国标上榜分数：</strong>11291（大国标），9933（小国标）分</p>
          </div>
        </div>
        """

        rank = app.parse_yatejia_apple_wechat_rank(
            html,
            {
                "ename": "libai",
                "cname": "libai",
                "url": "https://wenda.yatejia.cn/wangzherongyao/libai/",
            },
        )

        self.assertEqual(rank["heroId"], "libai")
        self.assertEqual(rank["name"], "李白")
        self.assertEqual(rank["platform"], "苹果微信大区")
        self.assertEqual(rank["photo"], "https://game.gtimg.cn/images/yxzj/img201606/heroimg/131/131.jpg")
        self.assertEqual(rank["province"], "山西省")
        self.assertEqual(rank["provincePower"], 6707)
        self.assertEqual(rank["nationalPower"], 11291)
        self.assertEqual(rank["smallNationalPower"], 9933)
        self.assertEqual(rank["updatedAt"], "2025/05/31 05:33:30")
        self.assertEqual(rank["source"], "wenda.yatejia.cn")
        self.assertTrue(rank["ok"])
        self.assertEqual(len(rank["provinceRanks"]), 2)

    def test_ranks_payload_curls_all_urls_without_cache(self):
        ranks = [
            {
                "heroId": "libai",
                "name": "李白",
                "province": "山西省",
                "provincePower": 6707,
                "ok": True,
            }
        ]

        with patch.object(app, "read_rank_cache", side_effect=AssertionError("cache must not be read")):
            with patch.object(app, "write_rank_cache", side_effect=AssertionError("cache must not be written")):
                with patch.object(app, "fetch_all_hero_ranks", return_value=ranks) as fetch:
                    payload = app.ranks_payload("ios_wx")

        fetch.assert_called_once_with("ios_wx")
        self.assertEqual(payload["ranks"], ranks)
        self.assertFalse(payload["cached"])
        self.assertFalse(payload["refreshing"])


if __name__ == "__main__":
    unittest.main()
