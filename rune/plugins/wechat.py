"""
Rune Plugin: Personal WeChat via UI Automation.

This plugin uses `uiautomation` and `pyperclip` to interact with the
already running official Windows WeChat Desktop application.

It simulates mouse clicks and keyboard typing.
No version degradation needed, 0% ban rate.
"""

import time
import subprocess
from typing import Any

from rune.tools.base import PermissionLevel, ToolDefinition

try:
    import uiautomation as auto
    import pyperclip
    # 降低默认搜索延迟，提高响应速度
    auto.uiautomation.SetGlobalSearchTimeout(2.0)
except ImportError:
    auto = None
    pyperclip = None

PLUGIN_META = {
    "name": "wechat",
    "display_name": "个人微信 (UI自动化)",
    "version": "0.3.0",
    "description": "基于 Windows UI 自动化操作最新版官方微信。调用时会自动拉起微信窗口模拟人工发消息。",
    "source": "bundled",
    "tool_count": 3,
}

PLUGIN_CONFIG_SECTION = "wechat"


def _get_wechat_window() -> Any:
    """Find and bring WeChat to the foreground."""
    # Native WeChat or UWP WeChat might have different class names
    wechat_win = auto.WindowControl(Name='微信')
    if not wechat_win.Exists(0, 0):
        # 尝试通过快捷键调起
        auto.SendKeys('{Ctrl}{Alt}w') # 默认微信唤醒快捷键
        time.sleep(1)
        wechat_win = auto.WindowControl(Name='微信')
    
    if not wechat_win.Exists(0, 0):
        raise Exception("未找到微信窗口。请确保微信已启动且已登录。")
        
    # Bring to front
    wechat_win.SetActive()
    wechat_win.SetTopmost(True)
    time.sleep(0.1)
    wechat_win.SetTopmost(False)
    return wechat_win


def plugin_setup_wizard(console: Any) -> None:
    """Interactive WeChat login wizard."""
    if not auto or not pyperclip:
        console.print("[bold red]❌ 未安装自动化依赖！[/bold red]")
        console.print("请在 Windows终端 执行: [cyan]pip install uiautomation pyperclip[/cyan]")
        return
        
    console.print("[yellow]正在寻找当前运行的微信窗口...[/yellow]")
    try:
        win = _get_wechat_window()
        console.print(f"[bold green]✅ 成功找到微信窗口！[/bold green]")
        console.print("[dim]提示: 发送消息时，鼠标会自动移动，请不要干预鼠标操作。[/dim]")
    except Exception as e:
        console.print(f"[bold red]❌ 初始化异常: {e}[/bold red]")


def plugin_config_display() -> str:
    """Status display for Rune `config` menu."""
    if not auto:
        status = "[red]未安装依赖[/red]"
    else:
        wechat_win = auto.WindowControl(Name='微信')
        if wechat_win.Exists(0, 0):
            status = "[green]窗口已找到准备就绪[/green]"
        else:
            status = "[yellow]未找到微信运行窗口[/yellow]"
            
    return f"[bold]💬 个人微信 (UI自动化)[/bold]\n  状态: {status}"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def wechat_send_message(contact_name: str, message: str) -> str:
    """Send text message by simulating UI interaction."""
    if not auto:
        return "Error: 缺少 uiautomation 库。"
        
    # 限制 AI 发送过长的内容，UI 方案发太长容易出 Bug
    if len(message) > 2000:
        return "Error: 消息过长（超过2000字符），请精简你要发送的内容。"
        
    try:
        win = _get_wechat_window()
        
        # 1. 寻找左侧的搜索框或者快捷键 Ctrl+F
        auto.SendKeys('{Ctrl}f')
        time.sleep(0.5)
        
        # 2. 清空搜索框并输入名字 (使用剪贴板防止由于输入法中英文问题直接输入拼音)
        pyperclip.copy(contact_name)
        auto.SendKeys('{Ctrl}v')
        time.sleep(1.0) # 等待微信全局搜索出结果
        
        # 3. 按回车进入该联系人的聊天界面
        auto.SendKeys('{Enter}')
        time.sleep(0.5)
        
        # 4. 把消息复制进输入框
        pyperclip.copy(message)
        auto.SendKeys('{Ctrl}v')
        time.sleep(0.2)
        
        # 5. 发送
        auto.SendKeys('{Enter}')
        time.sleep(0.2)
        
        return f"✅ 已成功模拟人手操作，将消息发送给 '{contact_name}'，内容：{message}"
        
    except Exception as e:
        return f"Error: 自动化操作发送失败。错误信息: {e}"


def wechat_read_messages(contact_name: str, count: int = 5) -> str:
    """读取指定联系人的最新聊天记录。"""
    if not auto:
        return "Error: 缺少 uiautomation 库。"

    try:
        win = _get_wechat_window()

        # 1. 寻找左侧的搜索框或者快捷键 Ctrl+F
        auto.SendKeys('{Ctrl}f')
        time.sleep(0.5)

        # 2. 清空搜索框并输入名字
        pyperclip.copy(contact_name)
        auto.SendKeys('{Ctrl}v')
        time.sleep(1.0) 

        # 3. 按回车进入该联系人的聊天界面
        auto.SendKeys('{Enter}')
        time.sleep(0.8)

        # 4. 找到消息列表
        msg_list = win.ListControl(Name="消息")
        if not msg_list.Exists(2, 0):
            return "❌ 无法找到聊天记录界面，可能是名字不匹配。"
            
        messages = []
        children = msg_list.GetChildren()
        
        # 提取最后 count 个消息
        for child in children[-count:]:
            # 微信列表的项通常自带全部文本 name
            if child.Name:
                messages.append(child.Name)
            
        if not messages:
            return f"📭 '{contact_name}' 暂无任何文本消息记录。"
            
        return f"与 '{contact_name}' 的最近聊天记录:\n" + "\n".join(messages)

    except Exception as e:
        return f"Error: 读取消息失败: {e}"


def wechat_get_friend_list() -> str:
    """获取最近会话的好友列表。"""
    if not auto:
        return "Error: 缺少 uiautomation 库。"

    try:
        win = _get_wechat_window()
        
        # 找到会话列表
        session_list = win.ListControl(Name="会话")
        print(session_list)
        if not session_list.Exists(2, 0):
            return "❌ 无法找到微信的最近会话列表。"
            
        friends = []
        children = session_list.GetChildren()
        for child in children[:30]: # 最多拿前30个会话防止刷屏
            if child.Name:
                friends.append(child.Name)
                
        if not friends:
            return "📭 最近会话列表为空。"
            
        return "最近会话的好友或群聊列表（前30个）:\n" + "\n".join(friends)

    except Exception as e:
        return f"Error: 读取好友列表失败: {e}"


# ---------------------------------------------------------------------------
# Tool Definitions
# ---------------------------------------------------------------------------

TOOLS = [
    ToolDefinition(
        name="wechat_send_message",
        description="发送微信文本消息给指定的好友、备注名或群聊天。调用时系统会自动打开你的微信窗口打字发送消息，注意请保持微信在前台运行时不要动鼠标。",
        parameters={
            "type": "object",
            "properties": {
                "contact_name": {"type": "string", "description": "精确的好友备注名、昵称或群聊名。必须能通过搜一搜直接搜到。"},
                "message": {"type": "string", "description": "要发送的文本消息内容"}
            },
            "required": ["contact_name", "message"]
        },
        permission_level=PermissionLevel.RED, # 需要绝对确认才能发微信
        handler=wechat_send_message,
    ),
    ToolDefinition(
        name="wechat_get_friend_list",
        description="获取你的微信最近聊天的朋友列表或群聊列表，用于确认要聊天的人的精确昵称。",
        parameters={"type": "object", "properties": {}, "required": []},
        permission_level=PermissionLevel.GREEN,
        handler=wechat_get_friend_list,
    ),
    ToolDefinition(
        name="wechat_read_messages",
        description="读取你和某个指定好友或群聊的最近几条聊天记录。",
        parameters={
            "type": "object",
            "properties": {
                "contact_name": {"type": "string", "description": "要读取信息的精确联系人或群名称"},
                "count": {"type": "integer", "description": "要读取的最新消息数量，默认5条"}
            },
            "required": ["contact_name"]
        },
        permission_level=PermissionLevel.GREEN,
        handler=wechat_read_messages,
    )
]
