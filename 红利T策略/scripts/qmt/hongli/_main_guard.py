# === hongli/_main_guard.py ===
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
# 国金模型交易须按 PythonFormula 加载（init/handlebar）。
# 若经 doRun `python -u HLCL.py ...`（simpleRun=1）启动会立刻退出，
# 策略日志只见开始/结束 — 并非常驻监控。
if __name__ == "__main__":
    import sys

    print(
        "HongliT ERROR: standalone doRun (simpleRun=1). "
        "EXIT QMT fully -> python scripts/qmt/_fix_hlcl_simplerun.py -> "
        "reopen QMT -> compile HLCL -> model trade Start. "
        "Expect HongliT init, not this line."
    )
    sys.exit(2)
