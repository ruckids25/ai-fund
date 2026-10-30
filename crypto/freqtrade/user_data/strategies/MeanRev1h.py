"""Strategy B: 1h mean reversion on OKX perps. Fixed rules: backtests/crypto_meanrev1h_20261030/criteria.md

Sizing, leverage and the entry stop are inherited from TrendEma4h; here the stop never trails.
"""
from datetime import datetime

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import stoploss_from_absolute
from pandas import DataFrame
from TrendEma4h import TrendEma4h


class MeanRev1h(TrendEma4h):
    timeframe = "1h"

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["rsi"] = ta.RSI(df, timeperiod=14)
        df["adx"] = ta.ADX(df, timeperiod=14)
        df["atr"] = ta.ATR(df, timeperiod=14)
        bands = ta.BBANDS(df, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        df["bb_upper"], df["bb_mid"], df["bb_lower"] = bands["upperband"], bands["middleband"], bands["lowerband"]
        return df

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        calm = (df["adx"] < 25) & (df["volume"] > 0)
        df.loc[calm & (df["rsi"] < 30) & (df["close"] < df["bb_lower"]), "enter_long"] = 1
        df.loc[calm & (df["rsi"] > 70) & (df["close"] > df["bb_upper"]), "enter_short"] = 1
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[df["close"] >= df["bb_mid"], "exit_long"] = 1
        df.loc[df["close"] <= df["bb_mid"], "exit_short"] = 1
        return df

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime, current_rate: float,
                        current_profit: float, after_fill: bool, **kwargs) -> float | None:
        init_stop = trade.get_custom_data("init_stop")
        if init_stop is None:
            return None
        return stoploss_from_absolute(init_stop, current_rate, is_short=trade.is_short, leverage=trade.leverage)
