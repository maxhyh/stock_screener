#!/usr/bin/env python3
"""
生成沪深300基准文件（hs300_daily.csv）

输出默认路径：
  data/benchmarks/hs300_daily.csv

字段：
  date, open, close
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)


def _pick_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    low = {str(c).strip().lower(): c for c in df.columns}
    for x in candidates:
        c = low.get(x.lower())
        if c is not None:
            return c
    for raw in df.columns:
        s = str(raw).strip()
        if s in candidates:
            return raw
    return None


def fetch_hs300(symbol: str = "000300", start_date: str = "20100101", end_date: str | None = None) -> pd.DataFrame:
    import akshare as ak  # noqa: WPS433

    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    # AKShare 接口：指数日线
    raw = ak.index_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
    )
    if raw is None or raw.empty:
        raise RuntimeError("AKShare 返回空数据，无法生成基准文件。")

    date_col = _pick_col(raw, ["日期", "date", "trade_date"])
    open_col = _pick_col(raw, ["开盘", "open"])
    close_col = _pick_col(raw, ["收盘", "close"])
    if not date_col or not open_col or not close_col:
        raise RuntimeError(f"无法识别必要列，当前列为: {list(raw.columns)}")

    df = raw[[date_col, open_col, close_col]].copy()
    df.columns = ["date", "open", "close"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["open"] = pd.to_numeric(df["open"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "open", "close"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")
    if df.empty:
        raise RuntimeError("清洗后基准数据为空。")
    return df


def main() -> int:
    p = argparse.ArgumentParser(description="生成沪深300基准文件")
    p.add_argument("--symbol", type=str, default="000300", help="指数代码（默认 000300）")
    p.add_argument("--start-date", type=str, default="20100101", help="起始日期 YYYYMMDD")
    p.add_argument("--end-date", type=str, default=None, help="结束日期 YYYYMMDD，默认今天")
    p.add_argument(
        "--output",
        type=str,
        default=os.path.join(BASE_DIR, "data", "benchmarks", "hs300_daily.csv"),
        help="输出文件路径",
    )
    args = p.parse_args()

    out = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    print("=" * 72)
    print("生成沪深300基准文件")
    print("=" * 72)
    print(f"symbol: {args.symbol}")
    print(f"date range: {args.start_date} ~ {args.end_date or 'today'}")
    print(f"output: {out}")

    try:
        df = fetch_hs300(symbol=args.symbol, start_date=args.start_date, end_date=args.end_date)
        df.to_csv(out, index=False, encoding="utf-8-sig")
    except Exception as e:
        print(f"\n❌ 生成失败: {e}")
        print("可先使用 synthetic 基准继续回测：")
        print("python scripts/quant_portfolio_backtest.py --benchmark-mode synthetic ...")
        return 1

    print(f"\n✅ 生成完成: {out}")
    print(f"数据条数: {len(df)}")
    print(f"起止: {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

