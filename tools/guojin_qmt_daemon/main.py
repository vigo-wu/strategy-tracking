import os
import time
import subprocess
import psutil
from pywinauto import Application
import pyautogui
import getpass  # 用于隐藏输入的密码（类似于Linux输入密码不显示）

# ==================== 国金证券 QMT 配置区域 ====================
QMT_PATH = r"D:\service\GJQMT\bin.x64\XtItClient.exe"  # 修改为你的实际安装路径
QMT_DIR = os.path.dirname(QMT_PATH)
PROCESS_NAME = "XtItClient.exe"
CHECK_INTERVAL = 30                                     # 守护进程检查间隔（秒）
# =============================================================

# 全局变量，用于在内存中临时存储密码
SAVED_PASSWORD = ""

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
    """
    根据国金QMT特定标题检测是否回退到了登录页面
    登录后标题：'39953913 - 国金证券QMT交易端 2.1.19.0'
    登录前标题：'国金证券QMT交易端 2.1.19.0'
    """
    try:
        # 使用 win32 后端快速连接当前运行的 QMT 进程
        app = Application(backend="win32").connect(path=QMT_PATH, timeout=2)

        # 获取 QMT 的主窗口/顶部窗口
        top_win = app.top_window()
        title = top_win.window_text()

        # 判断逻辑：如果标题包含"国金证券QMT交易端" 且 标题开头不是数字加空格减号（即没有登录账号）
        if "国金证券QMT交易端" in title and "-" not in title:
            print(f"[-] 检测到当前窗口标题为: '{title}'，处于未登录/回退状态。")
            return True

    except Exception:
        # 如果连不上进程或找不到窗口，说明可能压根没运行，让主循环的 is_process_running 去处理
        return False
    return False

def kill_process(process_name):
    """强行杀死指定的进程"""
    print(f"[-] 准备清理残余的 {process_name} 进程...")
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'].lower() == process_name.lower():
                proc.kill()
                print(f"[-] 已强制结束进程 PID: {proc.pid}")
        except Exception as e:
            print(f"[!] 结束进程时发生异常: {e}")
    time.sleep(2)  # 给系统稳妥释放资源的时间

def start_and_login_qmt():
    """启动国金大 QMT 并自动填入内存中的密码"""
    print("[-] 准备拉起国金 QMT 并自动登录...")

    # 1. 启动 QMT 进程并获取 PID
    try:
        proc = subprocess.Popen(QMT_PATH, cwd=QMT_DIR)
        pid = proc.pid
        print(f"[-] 进程已拉起，PID: {pid}，等待登录窗口初始化...")
    except Exception as e:
        print(f"[!] 无法拉起 QMT 进程: {e}")
        return

    # 2. 等待 8~10 秒让国金登录界面完全加载
    time.sleep(8)

    try:
        # 3. 通过 PID 绑定进程并强行前置窗口
        app = Application(backend="uia").connect(process=pid, timeout=10)
        dlg = app.top_window()
        dlg.set_focus()
        print("[-] 成功锁定国金 QMT 登录窗口")
        time.sleep(1)

        # 4. 键盘流切换到密码框
        pyautogui.press('tab')
        time.sleep(0.3)

        # 清空密码框
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.press('delete')
        time.sleep(0.3)

        # 5. 模拟键盘逐字输入保存在内存中的密码
        pyautogui.write(SAVED_PASSWORD, interval=0.05)
        print("[-] 密码自动填充完成")
        time.sleep(0.5)

        # 6. 回车登录
        pyautogui.press('enter')
        print("[+] 已发送回车登录指令，等待进入系统。")

    except Exception as e:
        print(f"[!] 自动登录期间发生异常: {e}")

def daemon_loop():
    """守护进程主循环"""
    global SAVED_PASSWORD
    print("="*50)
    print(" 国金大 QMT 进程守护精准匹配端")
    print("="*50)

    SAVED_PASSWORD = getpass.getpass("请输入您的国金交易密码 (输入时屏幕不显示，输完回车即可): ")

    if not SAVED_PASSWORD:
        print("[!] 密码不能为空，脚本退出。")
        return

    print("\n[*] 密码已成功加载至内存（不会保存到硬盘文件中）。")
    print("[*] 进程守护已开始运行...")

    while True:
        try:
            # 情况 1：进程彻底没有运行
            if not is_process_running(PROCESS_NAME):
                print("[!] 未检测到国金 QMT 进程，准备拉起...")
                start_and_login_qmt()

            # 情况 2：进程在运行，但通过标题判定回退到了登录页面
            elif is_back_to_login_page():
                print("[!] 检测到国金 QMT 窗口标题符合断线回退特征！正在执行安全重置策略...")
                kill_process(PROCESS_NAME)  # 先杀死残留进程
                start_and_login_qmt()       # 干净地重新拉起登录

            else:
                # 正常运行中（标题包含账号），无需操作
                pass

        except Exception as e:
            print(f"[!] 守护循环异常: {e}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    daemon_loop()
