import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from scripts import stock_alert


class StockAlertTests(unittest.TestCase):
    def test_build_alert_message_contains_lower_trigger_details(self):
        quote = stock_alert.Quote(
            symbol="LCID",
            price=Decimal("4.99"),
            currency="USD",
            market_state="REGULAR",
            source="test source",
        )

        message = stock_alert.build_alert_message(quote, "below", Decimal("5"))

        self.assertIn("LCID", message)
        self.assertIn("4.99 USD", message)
        self.assertIn("below 5 USD", message)
        self.assertIn("REGULAR", message)

    def test_build_alert_message_contains_upper_trigger_details(self):
        quote = stock_alert.Quote(
            symbol="LCID",
            price=Decimal("8.01"),
            currency="USD",
            market_state="REGULAR",
            source="test source",
        )

        message = stock_alert.build_alert_message(quote, "above", Decimal("8"))

        self.assertIn("above 8 USD", message)
        self.assertIn("8.01 USD", message)

    def test_command_sets_lower_threshold(self):
        config = stock_alert.AlertConfig(
            stock_symbol="LCID",
            lower_threshold=Decimal("5"),
            upper_threshold=Decimal("8"),
        )

        reply = stock_alert.update_config_from_command(config, "/setlower 4.50")

        self.assertEqual(config.lower_threshold, Decimal("4.50"))
        self.assertEqual(reply, "Lower trigger set to 4.50.")

    def test_command_sets_upper_threshold(self):
        config = stock_alert.AlertConfig(stock_symbol="LCID", lower_threshold=Decimal("5"))

        reply = stock_alert.update_config_from_command(config, "/setupper 8.00")

        self.assertEqual(config.upper_threshold, Decimal("8.00"))
        self.assertEqual(reply, "Upper trigger set to 8.00.")

    def test_command_rejects_crossed_thresholds(self):
        config = stock_alert.AlertConfig(
            stock_symbol="LCID",
            lower_threshold=Decimal("5"),
            upper_threshold=Decimal("8"),
        )

        reply = stock_alert.update_config_from_command(config, "/setlower 9")

        self.assertEqual(config.lower_threshold, Decimal("5"))
        self.assertEqual(reply, "Lower trigger must be below the upper trigger.")

    def test_find_alert_uses_lower_and_upper_thresholds(self):
        config = stock_alert.AlertConfig(
            stock_symbol="LCID",
            lower_threshold=Decimal("5"),
            upper_threshold=Decimal("8"),
        )
        low_quote = stock_alert.Quote("LCID", Decimal("4.99"), "USD", "REGULAR", "test")
        high_quote = stock_alert.Quote("LCID", Decimal("8.01"), "USD", "REGULAR", "test")
        normal_quote = stock_alert.Quote("LCID", Decimal("6"), "USD", "REGULAR", "test")

        self.assertEqual(stock_alert.find_alert(low_quote, config), ("below", Decimal("5")))
        self.assertEqual(stock_alert.find_alert(high_quote, config), ("above", Decimal("8")))
        self.assertIsNone(stock_alert.find_alert(normal_quote, config))

    def test_main_does_not_require_telegram_secrets_when_price_is_in_range(self):
        quote = stock_alert.Quote(
            symbol="LCID",
            price=Decimal("5.01"),
            currency="USD",
            market_state="REGULAR",
            source="test source",
        )

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "stock_alert.json"
            with mock.patch.dict(
                os.environ,
                {"CONFIG_PATH": str(config_path), "LOWER_PRICE_THRESHOLD": "5"},
                clear=True,
            ):
                with mock.patch.object(stock_alert, "fetch_quote", return_value=quote):
                    with mock.patch.object(stock_alert, "send_telegram_message") as send:
                        self.assertEqual(stock_alert.main(), 0)

        send.assert_not_called()

    def test_main_sends_telegram_when_price_is_below_lower_threshold(self):
        quote = stock_alert.Quote(
            symbol="LCID",
            price=Decimal("4.99"),
            currency="USD",
            market_state="REGULAR",
            source="test source",
        )

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "stock_alert.json"
            with mock.patch.dict(
                os.environ,
                {
                    "CONFIG_PATH": str(config_path),
                    "LOWER_PRICE_THRESHOLD": "5",
                    "TELEGRAM_BOT_TOKEN": "token",
                    "TELEGRAM_CHAT_ID": "chat",
                },
                clear=True,
            ):
                with mock.patch.object(stock_alert, "process_telegram_commands", return_value=False):
                    with mock.patch.object(stock_alert, "fetch_quote", return_value=quote):
                        with mock.patch.object(stock_alert, "send_telegram_message") as send:
                            self.assertEqual(stock_alert.main(), 0)

        send.assert_called_once()

    def test_main_sends_telegram_when_price_is_above_upper_threshold(self):
        quote = stock_alert.Quote(
            symbol="LCID",
            price=Decimal("8.01"),
            currency="USD",
            market_state="REGULAR",
            source="test source",
        )

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "stock_alert.json"
            with mock.patch.dict(
                os.environ,
                {
                    "CONFIG_PATH": str(config_path),
                    "UPPER_PRICE_THRESHOLD": "8",
                    "TELEGRAM_BOT_TOKEN": "token",
                    "TELEGRAM_CHAT_ID": "chat",
                },
                clear=True,
            ):
                with mock.patch.object(stock_alert, "process_telegram_commands", return_value=False):
                    with mock.patch.object(stock_alert, "fetch_quote", return_value=quote):
                        with mock.patch.object(stock_alert, "send_telegram_message") as send:
                            self.assertEqual(stock_alert.main(), 0)

        send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
