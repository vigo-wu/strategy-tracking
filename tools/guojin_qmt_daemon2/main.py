import os
import time
import subprocess
import psutil
import pyautogui
import tkinter as tk
from tkinter import simpledialog

# ==================== 国金证券 QMT 配置区域 ====================
QMT_PATH = r"D:\service\GJQMT\bin.x64\XtItClient.exe"  # 修改为你的实际安装路径
QMT_DIR = os.path.dirname(QMT_PATH)
PROCESS_NAME = "XtItClient.exe"
CHECK_INTERVAL = 30                                     # 守护进程检查间隔（秒）

# 🔒 密码配置区
SAVED_PASSWORD = ""
# =============================================================

def is_process_running(process_name):
    """检测 QMT 进程是否存在（适配高版本 Python 的安全遍历）"""
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == process_name.lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

def is_back_to_login_page():
    """
    根据国金QMT特定窗口标题检测是否回退到了登录页面
    Python 3.14 适配版：移除不稳定的 pywinauto，改用 pyautogui 的窗口查找
    """
    try:
        # 获取当前所有打开的窗口标题
        windows = pyautogui.getAllTitles()
        for title in windows:
            # 登录前标题含有特定字样且不含账号与“-”号
            if "国金证券QMT交易端" in title and "-" not in title:
                return True
    except Exception:
        return False
    return False

def kill_process(process_name):
    """强行杀死指定的进程"""
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == process_name.lower():
                proc.kill()
        except Exception:
            pass
    time.sleep(2)

def start_and_login_qmt():
    """启动国金大 QMT 并自动填入内存中的密码"""
    try:
        proc = subprocess.Popen(QMT_PATH, cwd=QMT_DIR)
    except Exception:
        return

    time.sleep(8)  # 等待登录界面加载

    try:
        # Python 3.14 适配：利用 pyautogui 寻找并强行聚焦 QMT 窗口
        qmt_windows = pyautogui.getWindowsWithTitle("国金证券QMT交易端")
        if qmt_windows:
            qmt_win = qmt_windows[0]
            if qmt_win.isMinimized:
                qmt_win.restore()
            qmt_win.activate()  # 强行置顶并聚焦
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
    """当密码为空时，弹出一个独立的 GUI 输入框让用户输入密码（适配 Python 3.14 的 tkinter）"""
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口
    root.attributes("-topmost", True)  # 确保输入框弹在最前面

    # 弹出密码输入对话框
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
