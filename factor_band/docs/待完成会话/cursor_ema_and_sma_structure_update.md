# EMA and SMA structure update
_Exported on 2026/9/14 at GMT+8 18:28:05 from Cursor (3.20.17)_

---

**User**

d_ma、w_ma改成 
ema: {
  周期: {
    mid: xx,
slow: xx,
trend: xx,
  }
}

sma: {
  周期: {
    mid: xx,
slow: xx,
trend: xx,
  }
}

---

**Cursor**

这是 FactorBand 指标周期窗契约改动。我先读技能和现行 `RECIPE.structure`，确认 `d_ma`/`w_ma` 现在怎么读、怎么覆盖。

当前是 Ask 模式，我只梳理契约和改动面，不会改代码。接着查 `d_ma`/`w_ma` 的唯一可信数据源、读取路径和覆盖形态。

结构看起来是把按日/周拆的 `d_ma`/`w_ma` 改成按算法拆的 `ema`/`sma`。我继续核对现行默认值、读取 API，以及调用点实际用的是 `_ema` 还是 `_sma`。

这是 **`RECIPE.structure` 指标周期窗的不兼容改动**：把按日/周拆的 `d_ma` / `w_ma`，改成按算法拆的 `ema` / `sma`。当前是 Ask 模式，下面只给契约和改法；要落地请切 Agent 模式。

现行默认是：

```101:106:factor_band/scripts/qmt/fband/config.py
    "structure": {
        # 日线中/慢/趋势均线；<=0 关该条
        "d_ma": {"mid": 20, "slow": 60, "trend": 120},
        # 周线快/中/生命线；mid 仅日志 weekly_bull
        "w_ma": {"fast": 5, "mid": 13, "life": 34},
```

日/周价格均线都由调用点直调 `_ema`，量均才走 `_sma`。窗一律经 `_structure_windows()` 读出再传入。

---

## 「周期」不要做成中文键

草图里的 `周期` 应对齐现有英文键，做成 **日/周两段**。不要写成字面量 `"周期"`，也不要把日线和周线压进同一组 `mid/slow/trend`——数字本来就不是一套（20/60/120 vs 5/13/34）。

建议形态：

```python
"structure": {
    "ema": {
        "d": {"mid": 20, "slow": 60, "trend": 120},
        "w": {"mid": 5, "slow": 13, "trend": 34},  # 原 w_ma.fast/mid/life
    },
    "sma": {
        "d": {"mid": 20, "slow": 60, "trend": 120},
        "w": {"mid": 5, "slow": 13, "trend": 34},
    },
    "macd": {"fast": 12, "slow": 26, "signal": 9},
    "atr": {"n": 14},
    "keltner": {"ema_n": 20, "atr_n": 20},
}
```

读法变成 `_structure_windows()["ema"]["d"]["mid"]`。周线键统一成 `mid/slow/trend`（5/13/34），废弃 `fast/life`。

格子 overrides：

```text
{"structure": {"ema": {"d": {"mid": 15}}}}
{"structure": {"ema": {"d": {"trend": 120}}}}
{"structure": {"sma": {"w": {"trend": 34}}}}
```

轴 id：`ema.d.mid`、`ema.d.slow`、`ema.d.trend`、`ema.w.mid`、`ema.w.slow`、`ema.w.trend`（`sma.*` 同形）。旧 `d_ma.*` / `w_ma.*` 与顶层 `D_MA_MID` 一样，写入即报错。

算法仍由调用点选定，不上 `MA_TYPE`：用 `_ema` 就读 `ema.*`，用 `_sma` 就读 `sma.*`。`keltner.ema_n` 不动。

---

## 落地前要拍板的两处

**1）`sma` 默认数字**

| 做法 | 效果 |
| :--- | :--- |
| 与 `ema` 同字面量（上表） | 某调用点改 `_sma` 时窗不用另填 |
| 全 `0` | `<=0` 关条；现行盘若只算 EMA，SMA 不占暖机 |

现行默认盘全部走 `_ema`，SMA 段暂时没有调用点。更干净的是 **SMA 先写 `0` 关条**，要用再开。

**2）三层嵌套必须改合并/展平**

现在的合并是「段 → 键」两层：`{"d_ma": {"mid": 15}}` 只改 `mid`。`nest_factor_path("ema.d.mid")` 今天会变成 `{ema: {"d.mid": 15}}`，是错的。

必须改成递归：`_structure_apply_global`、`deep_merge_factor_params`（或单独的 structure 深合并）、`flatten_structure` / `nest_*`。否则覆盖 `ema.d.mid` 会整段换掉 `ema.d`，`slow`/`trend` 丢失。

---

## 调用点怎么改（现行默认仍用 EMA）

| 位置 | 现在 | 改后 |
| :--- | :--- | :--- |
| `ctx._factor_daily_features` | `_ema(closes, d_ma.mid/slow/trend)` | `_ema(closes, ema.d.*)` |
| `ctx._weekly_market_features` | `_ema(..., w_ma.fast/mid/life)` | `_ema(..., ema.w.mid/slow/trend)` |
| `above_ema` | `d_ma.trend` | `ema.d.trend` |
| `time_force` | `d_ma.slow` + `_ema` | `ema.d.slow` + `_ema` |
| `market._ohlcv_need_1d/1w` | `d_ma.*` / `w_ma.life` | 取 `ema` 与 `sma` 对应窗的 max（`>0` 才计入） |
| `runtime` init `dMA=` / `wMA=` | `d_ma` / `w_ma` | 改打 `ema.d` / `ema.w`（若 SMA 启用再并列） |
| `local_bt/run.py` 暖机 | 读裸表 `d_ma`/`w_ma` | 同步新键；缺键当 0 |

`ctx.market` 的 `ma20`/`ma60`/`ma_trend`/`w_detail.ma5` 可以先不动；只换窗从哪读、用哪个函数。叶子继续读已算好的序列。

---

## 必改面（契约同步）

**代码：** `config.py` → `ctx.py`（读窗 + 深合并）→ 上述调用点 → `grid_spec.py`（`STRUCTURE_KEYS` / `STRUCTURE_ROOTS` / 短 id / 标签）→ `run.py` 拒绝旧 `d_ma`/`w_ma` → 相关单测。

**主分支现行文档（同一次变更）：** `Recipe分类.md` §8、`架构.md` + `策略架构.drawio`、`model.md`、三个 `NAV.md`、`qmt-local-bt-grid` 的 `SKILL.md` 与 `reference-contract.md`。

**不要：** 手改 `qmt_terminal_*.py`；改完走 `_deploy_qmt_gbk.py`。`recipe=` 指纹会变，参数指纹预检按新默认重算，不对历史 `report/grid/` 旧哈希。

验证：

```bash
python factor_band/scripts/local_bt/test_catalog.py
python factor_band/scripts/qmt/_deploy_qmt_gbk.py
```

外加 `test_grid_spec` / `test_above_ema` / `test_time_force` / `test_factor_expr`。

---

请先确认两件事，再切 Agent 落地：

1. **周期键用 `d` / `w`**，周线 `fast/mid/life` → `mid/slow/trend`（5/13/34）？
2. **`sma` 默认：与 EMA 同数字，还是全 `0` 关条？**

