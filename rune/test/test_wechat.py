import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.append(project_root)

from rune.plugins import wechat

def test_wechat_read_messages():
    print("正在尝试读取微信消息...")
    result = wechat.wechat_read_messages("Anson", count=5)
    print("读取微信消息结果：")
    print(result)
    
    print("正在尝试读取好友列表...")
    result = wechat.wechat_get_friend_list()
    print("好友列表结果：")
    print(result)

if __name__ == "__main__":
    test_wechat_read_messages()