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
    try:
        _dump_track_bars(C)
    except Exception as e:
        print("%s handlebar error" % STRATEGY_NAME, e)
        try:
            traceback.print_exc()
        except Exception:
            pass


def stop(C):
    try:
        _dump_on_stop(C)
    except Exception as e:
        print("%s stop error" % STRATEGY_NAME, e)
