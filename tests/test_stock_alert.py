import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from scripts import stock_alert


def quote(symbol, price):
    return stock_alert.Quote(
        symbol=symbol,
        price=Decimal(str(price)),
        currency="USD",
        market_state="REGULAR",
        source="test source",
    )


class StockAlertTests(unittest.TestCase):
    def test_build_alert_message_contains_lower_trigger_details(self):
        message = stock_alert.build_alert_message(quote("LCID", "4.99"), "below", Decimal("5"))

        self.assertIn("LCID", message)
        self.assertIn("4.99 USD", message)
        self.assertIn("below 5 USD", message)
        self.assertIn("REGULAR", message)

    def test_build_alert_message_contains_upper_trigger_details(self):
        message = stock_alert.build_alert_message(quote("LCID", "8.01"), "above", Decimal("8"))

        self.assertIn("above 8 USD", message)
        self.assertIn("8.01 USD", message)

    def test_add_command_validates_quote_and_adds_stock(self):
        config = stock_alert.AlertConfig(stocks={})

        reply = stock_alert.update_config_from_command(
            config,
            "/add AAPL 150 220",
            quote_fetcher=lambda symbol: quote(symbol, "175"),
        )

        self.assertIn("Added AAPL", reply)
        self.assertEqual(config.stocks["AAPL"].lower_threshold, Decimal("150"))
        self.assertEqual(config.stocks["AAPL"].upper_threshold, Decimal("220"))

    def test_remove_command_deletes_stock(self):
        config = stock_alert.AlertConfig(
            stocks={"AAPL": stock_alert.StockMonitor(symbol="AAPL")}
        )

        reply = stock_alert.update_config_from_command(config, "/remove AAPL")

        self.assertEqual(reply, "Removed AAPL from monitoring.")
        self.assertEqual(config.stocks, {})

    def test_status_command_includes_current_prices(self):
        config = stock_alert.AlertConfig(
            stocks={
                "AAPL": stock_alert.StockMonitor(
                    symbol="AAPL",
                    lower_threshold=Decimal("150"),
                    upper_threshold=Decimal("220"),
                )
            }
        )

        reply = stock_alert.update_config_from_command(
            config,
            "/status",
            quote_fetcher=lambda symbol: quote(symbol, "175"),
        )

        self.assertIn("AAPL: 175 USD", reply)
        self.assertIn("lower 150", reply)
        self.assertIn("/add AAPL", reply)

    def test_setlower_accepts_symbol_when_multiple_stocks_are_monitored(self):
        config = stock_alert.AlertConfig(
            stocks={
                "LCID": stock_alert.StockMonitor(symbol="LCID", lower_threshold=Decimal("5")),
                "AAPL": stock_alert.StockMonitor(symbol="AAPL"),
            }
        )

        reply = stock_alert.update_config_from_command(config, "/setlower AAPL 150")

        self.assertEqual(config.stocks["AAPL"].lower_threshold, Decimal("150"))
        self.assertEqual(reply, "AAPL lower trigger set to 150.")

    def test_setlower_keeps_legacy_single_stock_command_shape(self):
        config = stock_alert.AlertConfig(
            stocks={"LCID": stock_alert.StockMonitor(symbol="LCID", lower_threshold=Decimal("5"))}
        )

        reply = stock_alert.update_config_from_command(config, "/setlower 4.50")

        self.assertEqual(config.stocks["LCID"].lower_threshold, Decimal("4.50"))
        self.assertEqual(reply, "LCID lower trigger set to 4.50.")

    def test_setupper_rejects_crossed_thresholds(self):
        config = stock_alert.AlertConfig(
            stocks={
                "LCID": stock_alert.StockMonitor(
                    symbol="LCID",
                    lower_threshold=Decimal("5"),
                    upper_threshold=Decimal("8"),
                )
            }
        )

        reply = stock_alert.update_config_from_command(config, "/setupper LCID 4")

        self.assertEqual(config.stocks["LCID"].upper_threshold, Decimal("8"))
        self.assertEqual(reply, "Upper trigger must be above the lower trigger.")

    def test_find_alert_uses_lower_and_upper_thresholds(self):
        monitor = stock_alert.StockMonitor(
            symbol="LCID",
            lower_threshold=Decimal("5"),
            upper_threshold=Decimal("8"),
        )

        self.assertEqual(stock_alert.find_alert(quote("LCID", "4.99"), monitor), ("below", Decimal("5")))
        self.assertEqual(stock_alert.find_alert(quote("LCID", "8.01"), monitor), ("above", Decimal("8")))
        self.assertIsNone(stock_alert.find_alert(quote("LCID", "6"), monitor))

    def test_load_config_migrates_old_single_stock_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "stock_alert.json"
            config_path.write_text(
                """
                {
                  "stock_symbol": "LCID",
                  "lower_threshold": "5",
                  "upper_threshold": null,
                  "telegram_update_offset": 123
                }
                """,
                encoding="utf-8",
            )

            config = stock_alert.load_config(config_path)

        self.assertEqual(set(config.stocks), {"LCID"})
        self.assertEqual(config.stocks["LCID"].lower_threshold, Decimal("5"))
        self.assertEqual(config.telegram_update_offset, 123)

    def test_main_does_not_require_telegram_secrets_when_prices_are_in_range(self):
        config = stock_alert.AlertConfig(
            stocks={"LCID": stock_alert.StockMonitor(symbol="LCID", lower_threshold=Decimal("5"))}
        )

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "stock_alert.json"
            stock_alert.save_config(config_path, config)
            with mock.patch.dict(os.environ, {"CONFIG_PATH": str(config_path)}, clear=True):
                with mock.patch.object(stock_alert, "fetch_quote", return_value=quote("LCID", "5.01")):
                    with mock.patch.object(stock_alert, "send_telegram_message") as send:
                        self.assertEqual(stock_alert.main(), 0)

        send.assert_not_called()

    def test_main_sends_one_telegram_message_for_multiple_alerts(self):
        config = stock_alert.AlertConfig(
            stocks={
                "LCID": stock_alert.StockMonitor(symbol="LCID", lower_threshold=Decimal("5")),
                "AAPL": stock_alert.StockMonitor(symbol="AAPL", upper_threshold=Decimal("220")),
            }
        )

        def fake_fetch(symbol):
            return {"LCID": quote("LCID", "4.99"), "AAPL": quote("AAPL", "221")}[symbol]

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "stock_alert.json"
            stock_alert.save_config(config_path, config)
            with mock.patch.dict(
                os.environ,
                {
                    "CONFIG_PATH": str(config_path),
                    "TELEGRAM_BOT_TOKEN": "token",
                    "TELEGRAM_CHAT_ID": "chat",
                },
                clear=True,
            ):
                with mock.patch.object(stock_alert, "process_telegram_commands", return_value=False):
                    with mock.patch.object(stock_alert, "fetch_quote", side_effect=fake_fetch):
                        with mock.patch.object(stock_alert, "send_telegram_message") as send:
                            self.assertEqual(stock_alert.main(), 0)

        send.assert_called_once()
        message = send.call_args.args[2]
        self.assertIn("LCID is below", message)
        self.assertIn("AAPL is above", message)


if __name__ == "__main__":
    unittest.main()
