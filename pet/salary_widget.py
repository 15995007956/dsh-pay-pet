# -*- coding: utf-8 -*-
"""打工人小部件：今日已赚 / 今日净赚 的随机气泡播报（纯计算，零 Qt）。

口径与「打工人小部件」需求文档一致：

    mwh   = 每日工时 × 21.75          # 劳动法月计薪天数
    gRate = 月薪 / mwh                # 毛收入，未扣月耗
    cRate = 月耗 / mwh
    nRate = max(0, gRate - cRate)
    今日已赚 / 净赚 = 对应时速 × 当日在上班窗口内已过秒数 / 3600

上班窗口外冻结（上班前 0、下班后为当日满额），与文档的 FR-01 / FR-03 一致。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

#: 劳动法月计薪天数（固定，不可配置）
WORK_DAYS = 21.75

DEFAULTS = {
    "enabled": True,
    "monthlySalary": 10000.0,
    "monthlyConsumption": 5000.0,
    "workStart": "08:00",
    "workEnd": "18:00",
    "min_interval_minutes": 20,
    "max_interval_minutes": 45,
}


def _config(cfg) -> dict:
    data = dict(DEFAULTS)
    if isinstance(cfg, dict):
        for key in DEFAULTS:
            if key in cfg:
                data[key] = cfg[key]
    return data


def enabled(cfg) -> bool:
    return bool(_config(cfg).get("enabled", True))


def _number(value, fallback: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    if value != value:  # NaN
        return fallback
    return max(0.0, value)


def _parse_hhmm(value, fallback: int) -> int:
    try:
        hour_text, minute_text = str(value).split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
        if 0 <= hour < 24 and 0 <= minute < 60:
            return hour * 3600 + minute * 60
    except (TypeError, ValueError):
        pass
    return fallback


def _rates(cfg) -> tuple[float, float, int, int]:
    """返回 (毛时速, 月耗时速, 上班起点秒, 当日工时秒)。"""
    data = _config(cfg)
    start = _parse_hhmm(data.get("workStart"), 8 * 3600)
    end = _parse_hhmm(data.get("workEnd"), 18 * 3600)
    if end <= start:  # 跨天窗口（22:00-06:00）
        end += 24 * 3600
    seconds = end - start
    if seconds <= 0:  # 起止相等：按 10 小时兜底，避免除零
        seconds = 10 * 3600
    salary = _number(data.get("monthlySalary"), DEFAULTS["monthlySalary"])
    consume = _number(data.get("monthlyConsumption"), DEFAULTS["monthlyConsumption"])
    mwh = (seconds / 3600.0) * WORK_DAYS
    if mwh <= 0:
        mwh = 1.0
    return salary / mwh, consume / mwh, start, seconds


def compute(cfg, now: datetime | None = None) -> dict:
    """返回今日实时数值与相位（before / working / after）。"""
    now = now or datetime.now()
    gross, consume, start, seconds = _rates(cfg)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    begin = midnight + timedelta(seconds=start)
    finish = begin + timedelta(seconds=seconds)
    if now < begin:
        phase, elapsed = "before", 0.0
    elif now >= finish:
        phase, elapsed = "after", float(seconds)
    else:
        phase, elapsed = "working", (now - begin).total_seconds()
    earned = gross * elapsed / 3600.0
    net = max(0.0, gross - consume) * elapsed / 3600.0
    full_earned = gross * seconds / 3600.0
    full_net = max(0.0, gross - consume) * seconds / 3600.0
    return {
        "phase": phase,
        "elapsed": elapsed,
        "earned": earned,
        "net": net,
        "full_earned": full_earned,
        "full_net": full_net,
        "pct": min(100.0, elapsed / seconds * 100.0) if seconds > 0 else 0.0,
    }


def _money(value: float) -> str:
    if value >= 100000:
        return f"{value / 10000:.1f}万"
    return f"{value:,.2f}"


def bubble_text(cfg) -> str:
    """按相位组装一句播报；无可用数值时返回空串（调用方跳过本次）。"""
    data = _config(cfg)
    if not enabled(data):
        return ""
    values = compute(data)
    earned = _money(values["earned"])
    net = _money(values["net"])
    phase = values["phase"]
    if phase == "working":
        return f"今日已赚 ¥{earned} · 净赚 ¥{net}"
    if phase == "after":
        return f"今日收工：已赚 ¥{earned} · 净赚 ¥{net}"
    return f"还没开工～今天预计 ¥{_money(values['full_earned'])} · 净 ¥{_money(values['full_net'])}"


def next_delay_seconds(cfg, rng=None) -> float:
    """下一次播报的随机间隔（秒），夹在 [min, max] 内并给 60 秒下限。"""
    import random as _random

    data = _config(cfg)
    rng = rng or _random
    try:
        low = float(data.get("min_interval_minutes", DEFAULTS["min_interval_minutes"]))
        high = float(data.get("max_interval_minutes", DEFAULTS["max_interval_minutes"]))
    except (TypeError, ValueError):
        low, high = DEFAULTS["min_interval_minutes"], DEFAULTS["max_interval_minutes"]
    low = max(1.0, low)
    high = max(low, high)
    return rng.uniform(low, high) * 60.0


#: 独立配置文件：绕开 DSH 的全局/每宠配置归一化（那里会把自定义键清掉）。
CONFIG_FILENAME = "salary-widget.json"


def config_path() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    return base / "dsh-pet-standalone" / CONFIG_FILENAME


def load_runtime_config() -> dict:
    """读独立配置文件；缺失/损坏一律退回默认值（并补写一份默认文件）。"""
    path = config_path()
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2), encoding="utf-8")
            return dict(DEFAULTS)
        raw = json.loads(path.read_text(encoding="utf-8"))
        data = dict(DEFAULTS)
        if isinstance(raw, dict):
            for key in DEFAULTS:
                if key in raw:
                    data[key] = raw[key]
        return data
    except (OSError, ValueError):
        return dict(DEFAULTS)


# ---------------------------------------------------------------- 到期调度
# 进程级单例状态：不另起定时器，由自言自语那条定时器到点时顺带检查。
_due_at: float | None = None


def should_bubble_now(cfg, now: float | None = None) -> bool:
    """到点了吗？首次调用只登记下次到期时间（不立即播）。"""
    global _due_at
    if not enabled(cfg):
        _due_at = None
        return False
    now = time.monotonic() if now is None else now
    if _due_at is None:
        _due_at = now + next_delay_seconds(cfg)
        return False
    return now >= _due_at


def mark_bubbled(cfg, now: float | None = None) -> None:
    """播完一次后重新排下一次。"""
    global _due_at
    now = time.monotonic() if now is None else now
    _due_at = now + next_delay_seconds(cfg)
