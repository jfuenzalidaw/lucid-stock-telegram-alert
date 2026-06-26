import os
import unittest
from decimal import Decimal
from unittest import mock

from scripts import stock_alert


class StockAlertTests(unittest.TestCase):
    def test_build_alert_message_contains_key_details(self):
        quote = stock_alert.Quote(
            symbol="LCID",
            price=Decimal("4.99"),
            currency="USD",
            market_state="REGULAR",
            source="test source",
        )

        message = stock_alert.build_alert_message(quote, Decimal("5"))

        self.assertIn("LCID", message)
        self.assertIn("4.99 USD", message)
        self.assertIn("below 5 USD", message)
        self.assertIn("REGULAR", message)

    def test_main_does_not_require_telegram_secrets_when_price_is_above_threshold(self):
        quote = stock_alert.Quote(
            symbol="LCID",
            price=Decimal("5.01"),
            currency="USD",
            market_state="REGULAR",
            source="test source",
        )

        with mock.patch.dict(os.environ, {"PRICE_THRESHOLD": "5"}, clear=True):
            with mock.patch.object(stock_alert, "fetch_quote", return_value=quote):
                with mock.patch.object(stock_alert, "send_telegram_message") as send:
                    self.assertEqual(stock_alert.main(), 0)

        send.assert_not_called()

    def test_main_sends_telegram_when_price_is_below_threshold(self):
        quote = stock_alert.Quote(
            symbol="LCID",
            price=Decimal("4.99"),
            currency="USD",
            market_state="REGULAR",
            source="test source",
        )

        with mock.patch.dict(
            os.environ,
            {
                "PRICE_THRESHOLD": "5",
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_CHAT_ID": "chat",
            },
            clear=True,
        ):
            with mock.patch.object(stock_alert, "fetch_quote", return_value=quote):
                with mock.patch.object(stock_alert, "send_telegram_message") as send:
                    self.assertEqual(stock_alert.main(), 0)

        send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
