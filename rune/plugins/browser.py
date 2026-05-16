"""
Rune Plugin: Web Browser Automation via Playwright.

This plugin uses Playwright to open a real browser window.
Instead of sending screenshots to the AI, it parses the DOM and generates
a concise "ID-to-Element" map. The AI can then read the page and call
click/type tools using these IDs.
"""

from typing import Any, Dict, List, Optional
import time

from rune.tools.base import PermissionLevel, ToolDefinition

try:
    from playwright.sync_api import sync_playwright, Browser, Page, Playwright
except ImportError:
    sync_playwright = None
    Browser = Any
    Page = Any
    Playwright = Any

PLUGIN_META = {
    "name": "browser",
    "display_name": "Web浏览器 (Playwright)",
    "version": "0.1.0",
    "description": "允许 AI 像人一样访问网页、点击内容并阅读信息。纯文本提取模式，又快又准。",
    "source": "bundled",
    "tool_count": 5,
}

PLUGIN_CONFIG_SECTION = "browser"

_playwright: Optional[Playwright] = None
_browser: Optional[Browser] = None
_page: Optional[Page] = None
_element_map: Dict[int, Any] = {}


def _ensure_browser() -> None:
    """初始化并启动 Playwright 浏览器实例。"""
    global _playwright, _browser, _page
    if not sync_playwright:
        raise Exception("未安装 Playwright。请运行 `pip install playwright`")

    # 检查当前页面是否被用户意外关闭，如果关闭则尝试恢复
    if _page and _page.is_closed():
        try:
            _page = _page.context.new_page()
        except Exception:
            try:
                _playwright.stop()
            except:
                pass
            _playwright = None # 连带 context 也挂了，强制完全重启

    if not _playwright:
        _playwright = sync_playwright().start()
        
        import os
        import subprocess

        def _get_system_browsers() -> List[tuple]:
            """返回所有已安装的系统浏览器 [(user_data_dir, channel, process_name), ...]。"""
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            program_files = os.environ.get("PROGRAMFILES", "")
            program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
            if not local_app_data:
                return []
            candidates = [
                (
                    os.path.join(local_app_data, "Google", "Chrome", "User Data"),
                    os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe"),
                    "chrome", "chrome",
                ),
                (
                    os.path.join(local_app_data, "Microsoft", "Edge", "User Data"),
                    os.path.join(program_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"),
                    "msedge", "msedge",
                ),
                (
                    os.path.join(local_app_data, "Microsoft", "Edge", "User Data"),
                    os.path.join(program_files, "Microsoft", "Edge", "Application", "msedge.exe"),
                    "msedge", "msedge",
                ),
            ]
            results = []
            seen_channels = set()
            for user_data_dir, exe_path, channel, proc_name in candidates:
                if channel in seen_channels:
                    continue
                if os.path.isdir(user_data_dir) and os.path.isfile(exe_path):
                    results.append((user_data_dir, channel, proc_name))
                    seen_channels.add(channel)
            return results

        def _kill_browser(process_name: str) -> bool:
            """尝试关闭指定浏览器进程，返回是否成功（或本来就没在运行）。"""
            try:
                result = subprocess.run(
                    ["taskkill", "/F", "/IM", f"{process_name}.exe"],
                    capture_output=True, timeout=10
                )
                # 进程不存在也算成功
                return True
            except Exception:
                return False

        def _is_browser_running(process_name: str) -> bool:
            """检查浏览器进程是否仍在运行。"""
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {process_name}.exe"],
                    capture_output=True, text=True, timeout=5
                )
                return process_name.lower() in result.stdout.lower()
            except Exception:
                return False

        browsers = _get_system_browsers()

        if not browsers:
            _playwright.stop()
            _playwright = None
            raise Exception("❌ 未找到系统浏览器（Chrome 或 Edge）。请安装 Chrome 或 Edge。")

        launch_kwargs = dict(
            headless=False,
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            args=["--disable-blink-features=AutomationControlled"]
        )

        context = None
        last_error = None

        for user_data_dir, channel, proc_name in browsers:
            # 如果浏览器在运行，先尝试关闭它
            if _is_browser_running(proc_name):
                _kill_browser(proc_name)
                import time as _time
                for _ in range(10):
                    if not _is_browser_running(proc_name):
                        break
                    _time.sleep(0.5)

                if _is_browser_running(proc_name):
                    last_error = f"❌ 浏览器被占用：无法关闭 {proc_name}.exe，请手动关闭浏览器后重试。"
                    continue

            try:
                context = _playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    channel=channel,
                    **launch_kwargs
                )
                break
            except Exception as e:
                last_error = str(e)
                continue

        if context is None:
            _playwright.stop()
            _playwright = None
            raise Exception(f"❌ 浏览器被占用：{last_error}")

        if len(context.pages) > 0:
            _page = context.pages[0]
        else:
            _page = context.new_page()


def plugin_setup_wizard(console: Any) -> None:
    """交互式配置与依赖检查。"""
    if not sync_playwright:
        console.print("[bold red]❌ 未安装 Playwright！[/bold red]")
        console.print("请在终端执行: [cyan]pip install playwright[/cyan]")
        return
        
    console.print("[yellow]正在尝试启动系统原生的 Chrome 或 Edge 浏览器...[/yellow]")
    try:
        _ensure_browser()
        if _page:
            # 尝试访问一个空白页测试
            _page.goto("data:text/html,<h1>Rune Browser Ready</h1>")
        console.print("[bold green]✅ 浏览器启动成功！[/bold green]")
    except Exception as e:
        console.print(f"[bold red]❌ 浏览器启动失败: {e}[/bold red]")


def plugin_config_display() -> str:
    """设置菜单状态显示。"""
    if not sync_playwright:
        status = "[red]未安装依赖[/red]"
    elif _page:
        try:
            url = _page.url
            status = f"[green]已打开 ({url[:30]}...)[/green]"
        except:
            status = "[green]内核已启动[/green]"
    else:
        status = "[yellow]未初始化 (将在首次调用时自动启动)[/yellow]"
        
    return f"[bold]🌐 Web 浏览器 (Playwright)[/bold]\n  状态: {status}"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def browser_go_to(url: str) -> str:
    """导航到指定的 URL。"""
    try:
        _ensure_browser()
        
        if not url.startswith("http"):
            url = "https://" + url

        _page.goto(url, wait_until="domcontentloaded", timeout=15000)
        _page.wait_for_timeout(2000) # 给动态框架一点渲染时间
        return f"✅ 已成功导航至 {url}。现在你可以调用 browser_get_elements 来查看页面结构并操作此页面。"
    except Exception as e:
        return f"❌ 导航失败: {e}"


def browser_get_elements() -> str:
    """扫描当前页面，提取出所有可点击/输入的骨架，并分配唯一的 ID。"""
    try:
        _ensure_browser()
        
        # 使用 JS 脚本去抓取所有有意义的互动元素，这比直接在 python 循环判断快几十倍
        js_code = """
        () => {
            const elements = document.querySelectorAll('a, button, input, textarea, select, [role="button"], [tabindex]');
            const results = [];
            for (let i = 0; i < elements.length; i++) {
                const el = elements[i];
                
                // 检查是否可见
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
                
                // 提取文本内容
                let text = el.innerText ? el.innerText.trim() : '';
                if (!text && (el.tagName.toLowerCase() === 'input' || el.tagName.toLowerCase() === 'textarea')) {
                    text = el.placeholder || el.value || el.name || '';
                }
                if (!text) text = el.getAttribute('aria-label') || el.getAttribute('alt') || '';
                
                // 压缩长文本
                if (text.length > 40) text = text.substring(0, 40) + '...';
                text = text.replace(/\\n/g, ' ');

                // 只有包含文本或者是输入框才值得被AI看到并点击
                if (text || el.tagName.toLowerCase() === 'input') {
                    results.push({
                        index: i,  // DOM Node Index
                        tag: el.tagName.toLowerCase(),
                        text: text
                    });
                }
            }
            return results;
        }
        """
        
        raw_elements = _page.evaluate(js_code)
        
        global _element_map
        _element_map.clear()
        
        if not raw_elements:
            return "当前页面没有找到任何可交互的元素。它可能是纯文本或者加载未完成。"
            
        # 重新映射给 AI，避免给 AI 的 ID 过大
        lines = []
        for new_id, item in enumerate(raw_elements):
            # 将新 ID 映射到原始 DOM 树的 nthth-child() 或者 Locator 上很麻烦
            # 我们通过缓存 JS 里的实际对象来做绑定，这里我们先用 xpath 或者再次注入来绑定
            
            # 为了严谨，我们在前端页面直接给这些元素打个秘密的属性 rune-id
            _page.evaluate(f"(obj) => document.querySelectorAll('a, button, input, textarea, select, [role=\"button\"], [tabindex]')[obj.index].setAttribute('rune-id', '{new_id}')", item)
            
            tag = item['tag']
            text = item['text']
            _element_map[new_id] = True # 标记该 ID 合法
            
            lines.append(f"[ID: {new_id}] <{tag}> {text}")

        page_title = _page.title()
        
        summary = f"=== 当前网页标题: {page_title} ===\n"
        summary += "请根据下方的列表，使用 ID 作为参数调用 browser_click 或 browser_type_text。\n"
        summary += "\n".join(lines)
        
        # 保护 Prompt Token，如果特别多，只截取前 200 个元素
        return summary[:8000]
        
    except Exception as e:
        return f"❌ 获取页面元素失败: {e}"


def browser_click(element_id: int) -> str:
    """点击指定的网页元素。"""
    try:
        _ensure_browser()
        if element_id not in _element_map:
            return f"❌ ID {element_id} 不存在。如果你刚刚转跳了新网页，请务必先调用 browser_get_elements 重新获取 ID。"
            
        locator = _page.locator(f"[rune-id='{element_id}']")
        locator.click(timeout=5000)
        _page.wait_for_timeout(1000) # 给网页留出反应时间
        return f"✅ 已成功点击 ID: {element_id}。请根据常识判断是否需要重新调用 browser_get_elements。"
    except Exception as e:
        return f"❌ 点击失败 (这通常是被其他弹窗挡住了): {e}"


def browser_type_text(element_id: int, text: str, press_enter: bool = False) -> str:
    """在输入框中输入文本。"""
    try:
        _ensure_browser()
        if element_id not in _element_map:
            return f"❌ ID {element_id} 不存在。"
            
        locator = _page.locator(f"[rune-id='{element_id}']")
        locator.fill(text, timeout=3000)
        if press_enter:
            locator.press("Enter")
        _page.wait_for_timeout(1000)
        
        res = f"✅ 已在 ID {element_id} 中输入 '{text}'。"
        if press_enter:
            res += "并按下了回车触发搜索/提交。"
        return res
    except Exception as e:
        return f"❌ 输入框交互失败: {e}"


def browser_read_page() -> str:
    """如果你只想阅读当前网页里的整篇纯文本内容（如阅读文章、新闻），调用此工具。"""
    try:
        _ensure_browser()
        text = _page.evaluate("document.body.innerText")
        if not text:
            return "页面是空的。"
            
        return text[:4000] + "\n...(由于长度限制已截断)"
    except Exception as e:
        return f"❌ 读取页面失败: {e}"


# ---------------------------------------------------------------------------
# Tool Definitions
# ---------------------------------------------------------------------------

TOOLS = [
    ToolDefinition(
        name="browser_go_to",
        description="打开或导航至指定的网址。例如 'www.baidu.com' 或 'https://github.com'。导航后应紧接着调用 browser_get_elements。",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "目标链接"}
            },
            "required": ["url"]
        },
        permission_level=PermissionLevel.GREEN,
        handler=browser_go_to,
    ),
    ToolDefinition(
        name="browser_get_elements",
        description="极其重要：每次来到新网页，或网页发生变化后，必须调用这个工具！它会返回当前屏幕上所有可点击/可输入元素的专属【ID列表】。你必须有了 ID 才能点击或输入。",
        parameters={"type": "object", "properties": {}, "required": []},
        permission_level=PermissionLevel.GREEN,
        handler=browser_get_elements,
    ),
    ToolDefinition(
        name="browser_click",
        description="通过由 browser_get_elements 获取的 ID，模拟鼠标左键点击一个元素（如链接或按钮）。",
        parameters={
            "type": "object",
            "properties": {
                "element_id": {"type": "integer", "description": "元素的 ID"}
            },
            "required": ["element_id"]
        },
        permission_level=PermissionLevel.GREEN,
        handler=browser_click,
    ),
    ToolDefinition(
        name="browser_type_text",
        description="通过 ID 选中一个输入框，向里面输入文字，并可选择是否按下回车键（用于直接搜索或提交）。",
        parameters={
            "type": "object",
            "properties": {
                "element_id": {"type": "integer", "description": "输入框的 ID"},
                "text": {"type": "string", "description": "要输入的文字"},
                "press_enter": {"type": "boolean", "description": "输入完后是否立即敲回车，默认 false"}
            },
            "required": ["element_id", "text"]
        },
        permission_level=PermissionLevel.GREEN,
        handler=browser_type_text,
    ),
    ToolDefinition(
        name="browser_read_page",
        description="不考虑交互，直接把当前网页的所有看得见的文字提取出来，一般用于在博客或新闻网站看完文章总结。不要提取乱码的页面。",
        parameters={"type": "object", "properties": {}, "required": []},
        permission_level=PermissionLevel.GREEN,
        handler=browser_read_page,
    )
]
