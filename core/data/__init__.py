# -*- coding: utf-8 -*-
"""Read-only market-data adapters and source-neutral access boundaries."""

from .ashare_ods_loader import AShareOdsLoader
from .market_data_gateway import AShareMarketDataGateway, load_execution_bars

__all__ = ["AShareMarketDataGateway", "AShareOdsLoader", "load_execution_bars"]
