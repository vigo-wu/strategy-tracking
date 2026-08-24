# === kldump/runtime.py ===
def init(C):
    try:
        _dump_init(C)
    except Exception as e:
        print("%s init error" % STRATEGY_NAME, e)
        try:
            traceback.print_exc()
        except Exception:
            pass


def handlebar(C):
    return
