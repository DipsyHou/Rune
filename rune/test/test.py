import uiautomation as auto
import time

def inspect_wechat_ui():
    print("正在寻找微信窗口...")
    wechat_win = auto.WindowControl(Name='微信')
    
    if not wechat_win.Exists(2, 0):
        print("未找到微信窗口！")
        return
        
    wechat_win.SetActive()
    time.sleep(1)
    
    print("--- 正在抓取微信前 5 层 UI 结构 ---")
    # 遍历打印出你微信内部到底有哪些控件
    for control, depth in auto.WalkTree(wechat_win, getDepth=True, maxDepth=5):
        print(f"{'  ' * depth}[{control.ControlTypeName}] Name: '{control.Name}', ClassName: '{control.ClassName}'")

if __name__ == "__main__":
    inspect_wechat_ui()