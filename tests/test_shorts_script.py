import unittest

from content_engine.shorts_script import (
    DEFAULT_BRAND,
    MAX_CARDS,
    ShortsScript,
    ShortsScriptError,
    build_screen_plan,
    total_duration_seconds,
)


def _base_dict(**overrides):
    data = {
        "title": "좋은 사람이 만만한 사람이 되지 않으려면",
        "subtitle": "사람에게 잘하되 내 중심까지 내주지는 마세요.",
        "cards": [
            "무조건 잘해주는 것과 좋은 사람이 되는 것은 다릅니다.",
            "모든 부탁을 들어주다 보면 상대가 그것을 당연하게 생각할 수 있습니다.",
            "선을 넘는 순간에는 분명하게 선을 그어야 합니다.",
            "거절해야 할 때 거절하는 것도 나를 지키는 방법입니다.",
        ],
        "takeaway": "좋은 사람이 되는 것과 만만한 사람이 되는 것은 다릅니다.",
        "brand": "티몽의 지혜",
    }
    data.update(overrides)
    return data


class ShortsScriptFromDictTests(unittest.TestCase):
    def test_builds_from_well_formed_dict(self):
        script = ShortsScript.from_dict(_base_dict())
        self.assertEqual(script.title, "좋은 사람이 만만한 사람이 되지 않으려면")
        self.assertEqual(len(script.cards), 4)
        self.assertEqual(script.brand, "티몽의 지혜")

    def test_defaults_brand_when_missing(self):
        data = _base_dict()
        del data["brand"]
        script = ShortsScript.from_dict(data)
        self.assertEqual(script.brand, DEFAULT_BRAND)

    def test_rejects_non_mapping_input(self):
        with self.assertRaises(ShortsScriptError):
            ShortsScript.from_dict(["not", "a", "dict"])

    def test_rejects_cards_as_string(self):
        with self.assertRaises(ShortsScriptError):
            ShortsScript.from_dict(_base_dict(cards="한 문자열"))


class ShortsScriptValidationTests(unittest.TestCase):
    def test_rejects_empty_title(self):
        with self.assertRaises(ShortsScriptError):
            ShortsScript.from_dict(_base_dict(title="  "))

    def test_rejects_empty_takeaway(self):
        with self.assertRaises(ShortsScriptError):
            ShortsScript.from_dict(_base_dict(takeaway=""))

    def test_rejects_no_cards(self):
        with self.assertRaises(ShortsScriptError):
            ShortsScript.from_dict(_base_dict(cards=[]))

    def test_rejects_too_many_cards(self):
        with self.assertRaises(ShortsScriptError):
            ShortsScript.from_dict(_base_dict(cards=["문장"] * (MAX_CARDS + 1)))

    def test_rejects_blank_card_item(self):
        with self.assertRaises(ShortsScriptError):
            ShortsScript.from_dict(_base_dict(cards=["정상 문장입니다.", "   "]))

    def test_direct_construction_coerces_list_cards_to_tuple(self):
        script = ShortsScript(
            title="제목",
            subtitle="부제",
            cards=["카드1", "카드2"],
            takeaway="마무리",
        )
        self.assertIsInstance(script.cards, tuple)


class ScreenPlanTests(unittest.TestCase):
    def test_screen_count_matches_cover_plus_cards_plus_takeaway(self):
        script = ShortsScript.from_dict(_base_dict())
        plans = build_screen_plan(script)
        self.assertEqual(len(plans), 1 + len(script.cards) + 1)
        self.assertEqual(plans[0].kind, "cover")
        self.assertEqual(plans[-1].kind, "takeaway")
        for position, plan in enumerate(plans[1:-1], start=1):
            self.assertEqual(plan.kind, "card")
            self.assertEqual(plan.card_index, position)
            self.assertEqual(plan.card_total, len(script.cards))

    def test_more_cards_increase_total_duration(self):
        short_script = ShortsScript.from_dict(_base_dict(cards=["짧은 카드 하나입니다."]))
        long_script = ShortsScript.from_dict(_base_dict())

        short_total = total_duration_seconds(build_screen_plan(short_script), fade_seconds=0.4)
        long_total = total_duration_seconds(build_screen_plan(long_script), fade_seconds=0.4)

        self.assertGreater(long_total, short_total)

    def test_longer_card_text_gets_longer_duration_up_to_cap(self):
        short_script = ShortsScript.from_dict(_base_dict(cards=["짧다."]))
        long_script = ShortsScript.from_dict(
            _base_dict(
                cards=[
                    "이 카드는 훨씬 더 길게 작성된 문장으로, 읽는 데 시간이 더 오래 걸리는 본문 카드입니다."
                ]
            )
        )
        short_plan = build_screen_plan(short_script)[1]
        long_plan = build_screen_plan(long_script)[1]
        self.assertGreater(long_plan.duration_seconds, short_plan.duration_seconds)

    def test_all_card_text_preserved_in_plan(self):
        script = ShortsScript.from_dict(_base_dict())
        plans = build_screen_plan(script)
        card_texts = [plan.text for plan in plans if plan.kind == "card"]
        self.assertEqual(tuple(card_texts), script.cards)


if __name__ == "__main__":
    unittest.main()
