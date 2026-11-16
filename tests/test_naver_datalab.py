import json
import unittest
from unittest.mock import patch

from tak_scout.naver_datalab import NaverDataLabError, NaverDataLabProvider


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.payload


class NaverDataLabTests(unittest.TestCase):
    def test_missing_credentials_fail_before_network(self):
        provider = NaverDataLabProvider(client_id="", client_secret="")
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(NaverDataLabError):
                provider.search_trend([{"groupName": "AI", "keywords": ["인공지능"]}],
                                      start_date="2026-10-01", end_date="2026-10-31")

    def test_maps_relative_ratio_and_discloses_measurement(self):
        payload = {
            "startDate": "2026-10-01", "endDate": "2026-10-31", "timeUnit": "date",
            "results": [{"title": "AI", "keywords": ["인공지능", "AI"],
                         "data": [{"period": "2026-10-01", "ratio": 42.5}]}],
        }
        provider = NaverDataLabProvider("id", "secret")
        with patch("tak_scout.naver_datalab.urlopen", return_value=FakeResponse(payload)) as mocked:
            result = provider.search_trend(
                [{"groupName": "AI", "keywords": ["인공지능", "AI"]}],
                start_date="2026-10-01", end_date="2026-10-31")
        self.assertEqual(result.results[0].data[0]["ratio"], 42.5)
        self.assertEqual(result.to_dict()["measurement"], "naver_datalab_relative_ratio")
        request = mocked.call_args.args[0]
        self.assertEqual(request.get_header("X-naver-client-id"), "id")

    def test_rejects_unsupported_time_unit(self):
        provider = NaverDataLabProvider("id", "secret")
        with self.assertRaises(ValueError):
            provider.search_trend([{"groupName": "AI", "keywords": ["AI"]}],
                                  start_date="2026-10-01", end_date="2026-10-31",
                                  time_unit="hour")


if __name__ == "__main__":
    unittest.main()
