# === hongli/state_io.py ===
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
def _load_state():
    A.float_a = None
    A.float_b = None
    A.acted_day = ""
    A.acted = set()
    A.cooldown_until = ""
    A.pending = None
    if not os.path.isfile(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r") as f:
            raw = json.load(f)
        A.float_a = raw.get("float_a")
        A.float_b = raw.get("float_b")
        A.acted_day = raw.get("acted_day", "") or ""
        acted = raw.get("acted") or []
        if isinstance(acted, list):
            A.acted = set([str(x) for x in acted])
        A.cooldown_until = str(raw.get("cooldown_until", "") or "")
        pend = raw.get("pending")
        A.pending = pend if isinstance(pend, dict) else None
        # 丢弃旧版按 barpos 的冷却（重启不安全）
        print(
            "HongliT load state",
            STATE_FILE,
            A.float_a,
            A.float_b,
            "cd_until=",
            A.cooldown_until or "-",
            "pending=",
            bool(A.pending),
        )
    except Exception as e:
        print("HongliT load state fail", e)


def _save_state():
    # 回测: 仅内存；避免覆盖实盘 JSON / 再 init 不同步
    if getattr(A, "is_backtest", False):
        return
    payload = {
        "float_a": A.float_a,
        "float_b": A.float_b,
        "acted_day": A.acted_day,
        "acted": sorted(list(getattr(A, "acted", set()) or [])),
        "cooldown_until": getattr(A, "cooldown_until", "") or "",
        "pending": getattr(A, "pending", None),
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2)
    except Exception as e:
        print("HongliT save state fail", e)

