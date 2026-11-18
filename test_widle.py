import json
import struct
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

import widle


class ParseAmountTests(unittest.TestCase):
    def test_parses_plain_and_formatted_numbers(self):
        self.assertEqual(widle.parse_amount("1234.5"), Decimal("1234.50"))
        self.assertEqual(widle.parse_amount("RM 1,234.567"), Decimal("1234.57"))
        self.assertEqual(widle.parse_amount("$10"), Decimal("10.00"))
        self.assertEqual(widle.parse_amount("-50"), Decimal("-50.00"))

    def test_rejects_invalid_input(self):
        for bad in ("", "abc", "NaN", "Infinity", "1e20"):
            with self.assertRaises(ValueError):
                widle.parse_amount(bad)


class ConversionTests(unittest.TestCase):
    def test_convert_both_directions(self):
        rate = Decimal("0.25")
        self.assertEqual(widle.convert(Decimal("100"), rate, to_usd=True), Decimal("25.00"))
        self.assertEqual(widle.convert(Decimal("25"), rate, to_usd=False), Decimal("100.00"))

    def test_amount_color(self):
        self.assertEqual(widle.amount_color(Decimal("0.01")), widle.POSITIVE)
        self.assertEqual(widle.amount_color(Decimal("0.00")), widle.FG)
        self.assertEqual(widle.amount_color(Decimal("-1")), widle.NEGATIVE)

    def test_format_money(self):
        self.assertEqual(widle.format_money(Decimal("1234.5"), "MYR"), "RM 1,234.50")
        self.assertEqual(widle.format_money(Decimal("-3"), "USD"), "-USD 3.00")


class MonthTests(unittest.TestCase):
    def test_shift_month_wraps_years(self):
        self.assertEqual(widle.shift_month("2026-01", -1), "2025-12")
        self.assertEqual(widle.shift_month("2026-12", 1), "2027-01")
        self.assertEqual(widle.month_label("2026-11"), "November 2026")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sub" / "data.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults(self):
        store = widle.Store(self.path)
        self.assertEqual(store.businesses, ["Trading", "Investment", "Car Business"])
        self.assertEqual(store.currency, "MYR")
        self.assertIsNone(store.month_total("2026-11"))

    def test_round_trip_and_total(self):
        store = widle.Store(self.path)
        store.set_profit("2026-11", "Trading", Decimal("5699.00"))
        store.set_profit("2026-11", "Investment", Decimal("5999.00"))
        store.set_profit("2026-11", "Car Business", Decimal("10000.00"))
        store.set_rate(Decimal("0.24528"), "2026-11-03")
        store.set_currency("USD")
        reloaded = widle.Store(self.path)
        self.assertEqual(reloaded.profits["2026-11"]["Trading"], Decimal("5699.00"))
        self.assertEqual(reloaded.month_total("2026-11"), Decimal("21698.00"))
        self.assertEqual(reloaded.rate, Decimal("0.24528"))
        self.assertEqual(reloaded.rate_date, "2026-11-03")
        self.assertEqual(reloaded.currency, "USD")

    def test_clear_profit_removes_empty_month(self):
        store = widle.Store(self.path)
        store.set_profit("2026-11", "Trading", Decimal("1"))
        store.set_profit("2026-11", "Trading", None)
        self.assertEqual(widle.Store(self.path).profits, {})

    def test_add_rename_remove_business(self):
        store = widle.Store(self.path)
        store.add_business("  Food   Stall ")
        store.set_profit("2026-11", "Food Stall", Decimal("300"))
        store.set_profit("2026-10", "Food Stall", Decimal("200"))
        store.rename_business("Food Stall", "Cafe")
        self.assertEqual(store.profits["2026-11"], {"Cafe": Decimal("300")})
        store.rename_business("Cafe", "CAFE")
        store.remove_business("CAFE")
        reloaded = widle.Store(self.path)
        self.assertEqual(reloaded.businesses, ["Trading", "Investment", "Car Business"])
        self.assertEqual(reloaded.profits, {})

    def test_invalid_business_names(self):
        store = widle.Store(self.path)
        for bad in ("", "   ", "trading", "x" * 31):
            with self.assertRaises(ValueError):
                store.add_business(bad)
        with self.assertRaises(ValueError):
            store.rename_business("Trading", "investment")

    def test_corrupt_or_invalid_file_is_ignored(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("not json", encoding="utf-8")
        self.assertEqual(widle.Store(self.path).profits, {})
        self.path.write_text(json.dumps({
            "businesses": ["Trading", "", "Trading"],
            "profits": {"bad": {"Trading": "1"}, "2026-10": "12", "2026-08": {"Trading": "x"},
                        "2026-09": {"Trading": "12", "Unknown": "5"}},
            "rate": "oops", "position": ["a", 1], "currency": "EUR",
        }), encoding="utf-8")
        store = widle.Store(self.path)
        self.assertEqual(store.businesses, ["Trading"])
        self.assertEqual(store.profits, {"2026-09": {"Trading": Decimal("12.00")}})
        self.assertIsNone(store.rate)
        self.assertIsNone(store.position)
        self.assertEqual(store.currency, "MYR")


class FetchRateTests(unittest.TestCase):
    def _mock_response(self, body):
        resp = mock.MagicMock()
        resp.read.return_value = json.dumps(body).encode()
        resp.__enter__.return_value = resp
        return resp

    def test_fetch_rate_parses_response(self):
        body = {"amount": 1.0, "base": "MYR", "date": "2026-11-03", "rates": {"USD": 0.24528}}
        with mock.patch("urllib.request.urlopen", return_value=self._mock_response(body)):
            self.assertEqual(widle.fetch_rate(), (Decimal("0.24528"), "2026-11-03"))

    def test_fetch_rate_rejects_implausible_rate(self):
        body = {"date": "2026-11-03", "rates": {"USD": 500}}
        with mock.patch("urllib.request.urlopen", return_value=self._mock_response(body)):
            with self.assertRaises(ValueError):
                widle.fetch_rate()


class VersionTests(unittest.TestCase):
    def test_version_is_semver(self):
        self.assertRegex(widle.__version__, r"^\d+\.\d+\.\d+$")


class IconTests(unittest.TestCase):
    def test_icon_dib_layout(self):
        import tray
        for size in (16, 20, 32):
            dib = tray.icon_dib(size)
            self.assertEqual(len(dib), 40 + size * size * 4 + (size + 31) // 32 * 4 * size)
            self.assertEqual(struct.unpack_from("<Iii", dib), (40, size, size * 2))

    def test_icon_has_transparent_corner_and_green_bar(self):
        import tray
        pixels = tray.icon_pixels(32)
        self.assertEqual(pixels[0][0][3], 0)
        self.assertEqual(pixels[24][22][:3], tray.BAR_RGB)

    def test_ico_file_directory(self):
        import tray
        data = tray.ico_file((16, 32))
        self.assertEqual(struct.unpack_from("<HHH", data), (0, 1, 2))
        _, _, _, _, _, bpp, size, offset = struct.unpack_from("<BBBBHHII", data, 22)
        self.assertEqual((bpp, offset + size), (32, len(data)))


if __name__ == "__main__":
    unittest.main()
