import csv
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

from content_engine.market_demand import (
    IdeaCandidate, KNOWN_SOURCES, ManualMarketDemandProvider, MarketDemand, MarketDemandError,
    MarketDemandProvider, MockMarketDemandProvider, append_demands, append_ideas, build_idea_candidates,
    get_market_demand_provider, load_demands, load_ideas, normalize_row, score_demand, set_idea_status,
)
from content_engine.providers.base import ProviderError, ProviderNotConfiguredError
from scripts import market_demand as cli


def demand(**kw):
    base = {"source": "flippa", "title": "AI newsletter", "category": "newsletter", "price": 5000,
            "demand_signal": 0.6, "competition_signal": 0.3, "url": "https://x/1", "verified_transaction": "true"}
    base.update(kw)
    return normalize_row(base)


class MarketDemandTests(unittest.TestCase):
    def test_provider_contract(self):
        for provider in (MockMarketDemandProvider(), ManualMarketDemandProvider(rows=[{"title": "a", "source": "fiverr"}])):
            self.assertIsInstance(provider, MarketDemandProvider)
            items = provider.collect_demand("", 5)
            self.assertTrue(items)
            for item in items:
                self.assertIsInstance(item, MarketDemand)
                self.assertTrue(item.collected_at)
                self.assertIsNotNone(provider.score_opportunity(item).total)

    def test_no_network_in_mock_and_manual(self):
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network")):
            MockMarketDemandProvider().collect_demand("x")
            ManualMarketDemandProvider(rows=[{"title": "t"}]).collect_demand("")

    def test_normalize_validation(self):
        with self.assertRaises(MarketDemandError):
            normalize_row({"title": ""})
        with self.assertRaises(MarketDemandError):
            normalize_row({"title": "a", "price": "abc"})
        with self.assertRaises(MarketDemandError):
            normalize_row({"title": "a", "demand_signal": 1.5})
        with self.assertRaises(MarketDemandError):
            normalize_row({"title": "a", "price": -1})
        item = normalize_row({"title": "a", "price": "$1,200"})
        self.assertEqual(item.price, 1200.0)
        self.assertEqual(item.source, "manual")
        self.assertEqual(item.demand_id, normalize_row({"title": "a"}).demand_id)

    def test_scoring_deterministic_and_explained(self):
        item = demand()
        first, second = score_demand(item), score_demand(item)
        self.assertEqual(first, second)
        self.assertEqual(first.factors["transaction"], 100.0)
        self.assertEqual(first.factors["competition"], 70.0)
        self.assertIn("transaction", first.evidence)
        self.assertGreater(first.confidence, 0.8)

    def test_unknown_is_none_not_zero(self):
        item = normalize_row({"title": "x"})
        score = score_demand(item)
        self.assertIsNone(score.factors["transaction"])
        self.assertIsNone(score.factors["price"])
        self.assertLess(score.confidence, 0.5)

    def test_scoring_ordering(self):
        strong = score_demand(demand())
        weak = score_demand(demand(title="logo", category="design", price=20, competition_signal=0.95,
                                   verified_transaction="false"))
        self.assertGreater(strong.total, weak.total)
        self.assertLess(score_demand(demand(price=10)).factors["price"], score_demand(demand(price=5000)).factors["price"])

    def test_krw_price_and_unknown_currency(self):
        self.assertIsNotNone(score_demand(demand(price=140000, currency="KRW")).factors["price"])
        self.assertIsNone(score_demand(demand(currency="EUR")).factors["price"])

    def test_manual_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = Path(tmp) / "d.json"
            j.write_text(json.dumps([{"title": "ai blog", "source": "Empire Flippers", "price": 900}]), encoding="utf-8")
            c = Path(tmp) / "d.csv"
            with c.open("w", encoding="utf-8", newline="") as h:
                w = csv.DictWriter(h, fieldnames=["title", "source", "price", "recurring"])
                w.writeheader()
                w.writerow({"title": "sub box", "source": "acquire", "price": "100", "recurring": "yes"})
            self.assertEqual(ManualMarketDemandProvider(path=j).collect_demand("")[0].source, "empire_flippers")
            self.assertTrue(ManualMarketDemandProvider(path=c).collect_demand("")[0].metadata["recurring"])
            self.assertEqual(len(ManualMarketDemandProvider(path=c).collect_demand("zzz")), 0)
            with self.assertRaises(MarketDemandError):
                ManualMarketDemandProvider(path=Path(tmp) / "missing.json")
            bad = Path(tmp) / "bad.json"
            bad.write_text("{}", encoding="utf-8")
            with self.assertRaises(MarketDemandError):
                ManualMarketDemandProvider(path=bad)
        with self.assertRaises(ProviderNotConfiguredError):
            ManualMarketDemandProvider()

    def test_registry(self):
        for name in KNOWN_SOURCES:
            with self.assertRaises(ProviderNotConfiguredError):
                get_market_demand_provider(name)
        with self.assertRaises(ProviderError):
            get_market_demand_provider("nope")
        self.assertIsInstance(get_market_demand_provider("mock"), MockMarketDemandProvider)

    def test_ideas_and_stores_idempotent(self):
        demands = [demand(), demand(title="Another", url="https://x/2"), demand(title="logo", category="design",
                   price=20, competition_signal=0.95, verified_transaction="false", url="https://x/3")]
        ideas = build_idea_candidates(demands, min_score=50)
        self.assertEqual([i.category for i in ideas], ["newsletter"])
        self.assertEqual(ideas[0].status, "candidate")
        self.assertEqual(ideas, build_idea_candidates(demands, min_score=50, now=ideas[0].created_at))
        with tempfile.TemporaryDirectory() as tmp:
            dp, ip = Path(tmp) / "d.json", Path(tmp) / "i.json"
            self.assertEqual(append_demands(dp, demands), 3)
            self.assertEqual(append_demands(dp, demands), 0)
            self.assertEqual(len(load_demands(dp)), 3)
            self.assertEqual(append_ideas(ip, ideas), 1)
            self.assertEqual(append_ideas(ip, ideas), 0)
            self.assertEqual(set_idea_status(ip, ideas[0].idea_id, "accepted").status, "accepted")
            self.assertEqual(load_ideas(ip)[0].status, "accepted")
            with self.assertRaises(MarketDemandError):
                set_idea_status(ip, ideas[0].idea_id, "bogus")
            with self.assertRaises(MarketDemandError):
                set_idea_status(ip, "none", "accepted")
        with self.assertRaises(MarketDemandError):
            IdeaCandidate.from_dict({"idea_id": "x", "title": "t", "score": 1, "status": "bad"})

    def test_cli_preview_and_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.json"
            src.write_text(json.dumps([{"title": "AI newsletter", "category": "newsletter", "price": 5000,
                                        "verified_transaction": "true", "competition_signal": 0.2}]), encoding="utf-8")
            args = ["--input", str(src), "--data-dir", tmp, "--min-score", "30"]
            self.assertEqual(cli.main(args), 0)
            self.assertFalse((Path(tmp) / "tak_idea_candidates.json").exists())
            self.assertEqual(cli.main(args + ["--write"]), 0)
            ideas = load_ideas(Path(tmp) / "tak_idea_candidates.json")
            self.assertEqual(len(ideas), 1)
            self.assertEqual(cli.main(["--data-dir", tmp, "--set-status", ideas[0].idea_id, "rejected"]), 0)
            self.assertEqual(cli.main(["--provider", "flippa"]), 2)
            self.assertEqual(cli.main(["--input", str(Path(tmp) / "none.json")]), 2)


if __name__ == "__main__":
    unittest.main()
