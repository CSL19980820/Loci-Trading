"""策略测试共用夹具。

用合成数据而不是接真实行情：前视偏差是结构性质，与数据内容无关，而单测必须
离线可复现、不受接口可用性影响。这份夹具原先内联在 `test_strategies.py` 里，
该文件拆分后由多个测试模块共用。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

QIANLONG_TDX_FORMULA = """
YTSL:=(3*CLOSE+LOW+OPEN+HIGH)/6;
白色线:=(20*YTSL+19*REF(YTSL,1)+18*REF(YTSL,2)+17*REF(YTSL,3)+16*REF(YTSL,4)+15*REF(YTSL,5)+14*REF(YTSL,6)+13*REF(YTSL,7)+12*REF(YTSL,8)+11*REF(YTSL,9)+10*REF(YTSL,10)+9*REF(YTSL,11)+8*REF(YTSL,12)+7*REF(YTSL,13)+6*REF(YTSL,14)+5*REF(YTSL,15)+4*REF(YTSL,16)+3*REF(YTSL,17)+2*REF(YTSL,18)+REF(YTSL,20))/211;
黄色线:=MA(CLOSE,26);
死叉:=CROSS(黄色线,白色线);
曾死叉:=EXIST(死叉,20);
白线下运行:=COUNT(CLOSE<白色线,10)>=3;
昨阳:=CLOSE>OPEN AND CLOSE>=6;
昨突破白线:=CLOSE>白色线 AND REF(CLOSE,1)<=REF(白色线,1);
昨放量:=VOL>MA(VOL,5)*1.3;
昨站稳:=CLOSE>白色线*1.002;
突破日:=昨阳 AND 昨突破白线 AND 昨放量 AND 昨站稳;
白线向上:=白色线>REF(白色线,1);
非涨停价:=CLOSE<ZTPRICE(REF(CLOSE,1),0.1);
XG:曾死叉 AND 白线下运行 AND 突破日 AND 白线向上 AND 非涨停价;
"""


def synthetic_panels(seed: int = 2026, rows: int = 160, cols: int = 40) -> dict[str, pd.DataFrame]:
    """造一批带随机涨跌与放量的合成行情，形状与真实面板一致。"""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2025-01-01", periods=rows, freq="B").strftime("%Y-%m-%d")
    codes = [f"{600000 + i:06d}" for i in range(cols)]

    close = pd.DataFrame(
        np.cumprod(1 + rng.normal(0.001, 0.03, (rows, cols)), axis=0) * 20.0,
        index=index,
        columns=codes,
    )
    prev = close.shift(1).fillna(close.iloc[0])
    open_ = prev * (1 + rng.normal(0, 0.01, (rows, cols)))
    high = pd.concat([close, open_]).groupby(level=0).max() * (1 + abs(rng.normal(0, 0.012, (rows, cols))))
    low = pd.concat([close, open_]).groupby(level=0).min() * (1 - abs(rng.normal(0, 0.012, (rows, cols))))
    volume = pd.DataFrame(rng.lognormal(15, 0.6, (rows, cols)), index=index, columns=codes)
    turnover = pd.DataFrame(rng.uniform(0.005, 0.15, (rows, cols)), index=index, columns=codes)
    # 股本按票恒定（真实世界里不会逐日变），跨度覆盖 2 亿股闸门两侧。
    shares = pd.DataFrame(
        np.tile(rng.uniform(0.5e8, 8e8, cols), (rows, 1)), index=index, columns=codes
    )
    # 与库内一致：多数源不返回成交额，用 close*volume 合成。
    amount = close * volume

    return {
        "open": open_.reindex(index),
        "high": high.reindex(index),
        "low": low.reindex(index),
        "close": close,
        "volume": volume,
        "amount": amount,
        "turnover": turnover,
        "outstanding_share": shares,
    }
