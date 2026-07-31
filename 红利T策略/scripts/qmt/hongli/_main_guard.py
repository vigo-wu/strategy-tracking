# === hongli/_main_guard.py ===
# 作用: 拦截 simpleRun/doRun 独立启动（应走模型交易）
# 主要符号: __main__
# 拼接序: 16/16 | 上一部: strategy.py | 下一部: -
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
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
