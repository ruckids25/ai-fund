"""Strategy A: 4h EMA trend following on OKX perps. Fixed rules: backtests/crypto_trend4h_20261030/criteria.md

Stop = 2 ATR from entry, trailed at 3 ATR from the best price, tightening only.
Size and leverage come from core/risk_gate.py, so the numbers stay in config/risk.yaml.
"""
from datetime import datetime, timedelta

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.exchange import timeframe_to_minutes
from freqtrade.strategy import IStrategy, stoploss_from_absolute
from pandas import DataFrame

from core.config import risk_config
from core.risk_gate import check_liquidation, size_position

STOP_ATR, TRAIL_ATR = 2.0, 3.0


class TrendEma4h(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = True
    startup_candle_count = 400
    process_only_new_candles = True
    minimal_roi = {"0": 100}          # exits are the stop or the opposite cross
    stoploss = -0.99                  # replaced by custom_stoploss straight after the fill
    use_custom_stoploss = True
    use_exit_signal = True
    order_types = {"entry": "market", "exit": "market", "stoploss": "market",
                   "stoploss_on_exchange": True}

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["ema21"] = ta.EMA(df, timeperiod=21)
        df["ema55"] = ta.EMA(df, timeperiod=55)
        df["ema200"] = ta.EMA(df, timeperiod=200)
        df["atr"] = ta.ATR(df, timeperiod=14)
        above = df["ema21"] > df["ema55"]
        df["cross_up"] = above & ~above.shift(1, fill_value=False)
        df["cross_down"] = ~above & above.shift(1, fill_value=True)
        return df

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[df["cross_up"] & (df["close"] > df["ema200"]) & (df["volume"] > 0), "enter_long"] = 1
        df.loc[df["cross_down"] & (df["close"] < df["ema200"]) & (df["volume"] > 0), "enter_short"] = 1
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[df["cross_down"], "exit_long"] = 1
        df.loc[df["cross_up"], "exit_short"] = 1
        return df

    def _atr(self, pair: str, at: datetime) -> float:
        """ATR of the last candle fully closed at `at`, so size and stop use the same value."""
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        closed = df[df["date"] + timedelta(minutes=timeframe_to_minutes(self.timeframe)) <= at]
        return float(closed["atr"].iloc[-1])

    def leverage(self, pair: str, current_time: datetime, current_rate: float, proposed_leverage: float,
                 max_leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        cfg = risk_config()
        dist = STOP_ATR * self._atr(pair, current_time)
        stop = current_rate - dist if side == "long" else current_rate + dist
        for lev in range(int(min(cfg["desks"]["crypto"]["max_leverage"], max_leverage)), 0, -1):
            if check_liquidation(current_rate, stop, lev, cfg):
                return float(lev)
        return 1.0

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float | None, max_stake: float,
                            leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        cfg = risk_config()
        fx = cfg["fx"]["usdthb"]
        desk = cfg["desks"]["crypto"]
        qty = size_position(current_rate, current_rate - STOP_ATR * self._atr(pair, current_time), fx, cfg)
        max_margin = desk["capital_thb"] * desk["max_margin_pct"] / fx
        return min(qty * current_rate / leverage, max_margin, max_stake)

    def order_filled(self, pair: str, trade: Trade, order, current_time: datetime, **kwargs) -> None:
        if order.ft_order_side == trade.entry_side and trade.get_custom_data("init_stop") is None:
            dist = STOP_ATR * self._atr(pair, trade.open_date_utc)
            trade.set_custom_data("init_stop", trade.open_rate + dist if trade.is_short else trade.open_rate - dist)

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime, current_rate: float,
                        current_profit: float, after_fill: bool, **kwargs) -> float | None:
        init_stop = trade.get_custom_data("init_stop")
        if init_stop is None:
            return None
        trail = TRAIL_ATR * self._atr(pair, current_time)
        if trade.is_short:
            stop = min(init_stop, (trade.min_rate or trade.open_rate) + trail)   # no min/max yet right after fill
        else:
            stop = max(init_stop, (trade.max_rate or trade.open_rate) - trail)
        return stoploss_from_absolute(stop, current_rate, is_short=trade.is_short, leverage=trade.leverage)
