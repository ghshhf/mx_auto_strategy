"""
market_adapter.py - 行情/交易通道抽象层 (v6.5 架构预留)

设计目的:
  当前模拟盘只用腾讯行情 + mx-moni API. 但策略未来要迁移到:
    - 同花顺比赛 (若举办)
    - 加密货币交易所 (7x24, T+0, 用户提到"未来天天有")
    - 真实券商 API (用户本人炒股, 直接上现金)
  通过抽象层, 策略逻辑(auto_trader/selector/grid/rebalance)不需要改,
  只需替换底层 adapter 实现.

抽象接口:
  class MarketAdapter:
    get_realtime(codes) -> {code: {price, pe, ...}}
    get_kline(code, ktype, count) -> [{date,open,close,high,low,vol}]
    buy(code, price, qty) -> resp
    sell(code, price, qty) -> resp
    get_positions() -> {code: {qty, cost}}
    get_cash() -> float

当前实现:
  TencentMarketAdapter - 复用 market_data.py 行情 + auto_trader.call_mx_moni 下单

未来实现(占位, 暂不写):
  EastmoneyAdapter / HyprofitAdapter / BinanceAdapter / RealBrokerAdapter
"""
from abc import ABC, abstractmethod
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market_data as md


class MarketAdapter(ABC):
    """市场通道抽象基类. 所有具体市场实现此接口."""

    @abstractmethod
    def get_realtime(self, codes):
        """返回 {code: {price, pe_ttm, pb, turnover_pct, limit_up, limit_down, ...}}"""
        ...

    @abstractmethod
    def get_kline(self, code, ktype="day", count=260):
        """返回 [{date,open,close,high,low,vol}, ...] 升序"""
        ...

    @abstractmethod
    def buy(self, code, price, qty):
        """买入, 返回平台响应字符串"""
        ...

    @abstractmethod
    def sell(self, code, price, qty):
        """卖出, 返回平台响应字符串"""
        ...

    @abstractmethod
    def get_positions(self):
        """返回当前持仓 {code: {qty, cost_price}}"""
        ...

    @abstractmethod
    def get_cash(self):
        """返回可用现金(元)"""
        ...

    # ---------- 公共工具(子类可继承) ----------
    def price_percentile(self, code, window=250):
        """价格历史分位, 默认委托行情实现"""
        return md.price_percentile(code, window)

    def is_trade_time(self, now=None):
        """交易时段判断, 默认A股时段; 币圈override为7x24"""
        return md.is_trade_time(now)

    @property
    def market_name(self):
        return self.__class__.__name__


class TencentMarketAdapter(MarketAdapter):
    """A股模拟盘适配器: 腾讯行情 + mx-moni 下单."""

    def get_realtime(self, codes):
        return md.get_realtime(codes)

    def get_kline(self, code, ktype="day", count=260):
        return md.get_kline(code, ktype, count)

    def buy(self, code, price, qty):
        # 延迟导入避免循环依赖
        from auto_trader import call_mx_moni
        return call_mx_moni(f"买入 {code} {price:.2f} {qty}")

    def sell(self, code, price, qty):
        from auto_trader import call_mx_moni
        return call_mx_moni(f"卖出 {code} {price:.2f} {qty}")

    def get_positions(self):
        # mx-moni 模拟盘: 持仓由本地 _cost_basis 缓存代表(见 auto_trader)
        # 真实实现应调API拉取
        from auto_trader import _cost_basis
        return {c: {"qty": b["qty"], "cost_price": b["price"]} for c, b in _cost_basis.items()}

    def get_cash(self):
        # 模拟盘: 由外部传入本金-持仓市值近似; 真实应调API
        # 这里返回None表示"未知", 由调用方处理
        return None

    @property
    def market_name(self):
        return "A股模拟盘(腾讯+m x-moni)"


# ---------- 工厂函数 ----------
_ADAPTERS = {
    "tencent": TencentMarketAdapter,
    "a_share_sim": TencentMarketAdapter,  # 别名
    # 未来:
    # "hyprofit": HyprofitAdapter,
    # "binance": BinanceAdapter,
    # "real_broker": RealBrokerAdapter,
}


def get_adapter(market_key="tencent"):
    """
    根据 config.market.provider 返回对应 adapter 实例.
    未来新增市场只需在 _ADAPTERS 注册并实现对应类.
    """
    cls = _ADAPTERS.get(market_key, TencentMarketAdapter)
    return cls()


if __name__ == "__main__":
    # 自测
    a = get_adapter("tencent")
    print(f"当前适配器: {a.market_name}")
    print(f"交易时段(现在)? {a.is_trade_time()}")
    rt = a.get_realtime(["600016"])
    print(f"民生银行实时: {rt.get('600016', {}).get('price')}")
