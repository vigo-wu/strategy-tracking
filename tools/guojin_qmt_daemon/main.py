import os
import time
import subprocess
import psutil
from pywinauto import Application
import pyautogui
import tkinter as tk
from tkinter import simpledialog

# ==================== 国金证券 QMT 配置区域 ====================
QMT_PATH = r"D:\service\GJQMT\bin.x64\XtItClient.exe"  # 修改为你的实际安装路径
QMT_DIR = os.path.dirname(QMT_PATH)
PROCESS_NAME = "XtItClient.exe"
CHECK_INTERVAL = 30                                     # 守护进程检查间隔（秒）

# 🔒 密码配置区
# 1. 如果写了密码（如 "123456"），开机完全无感自启动，不需要任何人工干预
# 2. 如果留空（如下面这样），开机时屏幕中央会自动弹出一个独立的密码输入框
SAVED_PASSWORD = ""
# =============================================================

def is_process_running(process_name):
    """检测 QMT 进程是否存在"""
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'].lower() == process_name.lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

def is_back_to_login_page():
    """根据国金QMT特定标题检测是否回退到了登录页面"""
    try:
        app = Application(backend="win32").connect(path=QMT_PATH, timeout=2)
        top_win = app.top_window()
        title = top_win.window_text()

        # 登录前标题不含账号与“-”号
        if "国金证券QMT交易端" in title and "-" not in title:
            return True
    except Exception:
        return False
    return False

def kill_process(process_name):
    """强行杀死指定的进程"""
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'].lower() == process_name.lower():
                proc.kill()
        except Exception:
            pass
    time.sleep(2)

def start_and_login_qmt():
    """启动国金大 QMT 并自动填入内存中的密码"""
    try:
        proc = subprocess.Popen(QMT_PATH, cwd=QMT_DIR)
        pid = proc.pid
    except Exception:
        return

    time.sleep(8)  # 等待登录界面加载

    try:
        app = Application(backend="uia").connect(process=pid, timeout=10)
        dlg = app.top_window()
        dlg.set_focus()
        time.sleep(1)

        # 键盘流切换并清空密码框
        pyautogui.press('tab')
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.press('delete')
        time.sleep(0.3)

        # 模拟输入密码并回车
        pyautogui.write(SAVED_PASSWORD, interval=0.05)
        time.sleep(0.5)
        pyautogui.press('enter')

    except Exception:
        pass

def get_password_via_gui():
    """当密码为空时，弹出一个独立的 GUI 输入框让用户输入密码（不依赖命令行窗口）"""
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口
    root.attributes("-topmost", True)  # 确保输入框弹在最前面

    # 弹出密码输入对话框，show="*" 表示隐藏输入的密码字符
    password = simpledialog.askstring("国金 QMT 守护程序", "检测到未配置密码，请输入您的国金交易密码：", show="*")
    root.destroy()
    return password

def daemon_loop():
    """守护进程主循环"""
    global SAVED_PASSWORD

    # 如果配置区域密码为空，则强行弹窗要求手动输入
    if not SAVED_PASSWORD:
        SAVED_PASSWORD = get_password_via_gui()

    # 如果用户直接关闭了弹窗或输入为空，则脚本安全退出
    if not SAVED_PASSWORD:
        return

    while True:
        try:
            # 情况 1：进程没有运行
            if not is_process_running(PROCESS_NAME):
                start_and_login_qmt()

            # 情况 2：进程在运行，但回退到了登录页面
            elif is_back_to_login_page():
                kill_process(PROCESS_NAME)
                start_and_login_qmt()

        except Exception:
            pass

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    daemon_loop()
