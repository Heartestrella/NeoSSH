# ssh_webterm.py
"""
Web-based terminal widget using xterm.js embedded in a QWebEngineView,
communicating via QWebChannel.

Features:
- Transparent/web-background-supporting terminal (best-effort; some Qt/Chromium builds
  may not support page transparency; a bg_color fallback is available).
- text_color parameter (foreground color).
- bg_color parameter (fallback background color when transparency isn't desirable).
- text_shadow parameter (boolean) to add subtle text shadow for readability.
- Dynamic theme update via set_colors().
- Bridge (TerminalBridge) relays bytes <-> base64 across the QWebChannel.

Usage:
    widget = WebTerminal(parent, cols=120, rows=30,
                         text_color="white", bg_color="#00000080", text_shadow=True)
    widget.set_worker(ssh_worker)
    # To update colors later:
    widget.set_colors(text_color="#00ffcc",
                      bg_color="rgba(0,0,0,0.6)", text_shadow=False)
"""
import base64
import json
import html
from collections import deque
from PyQt5.QtCore import Qt, QObject, pyqtSignal, pyqtSlot, QUrl
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QSizePolicy, QHBoxLayout, QApplication
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel
import PyQt5.QtCore as qc
from tools.setting_config import SCM
import re
import os
from PyQt5.QtWidgets import QShortcut
from PyQt5.QtGui import QKeySequence
from tools.atool import resource_path
print("QT_VERSION:", qc.QT_VERSION_STR, "PYQT:", qc.PYQT_VERSION_STR)

configer = SCM()
config = configer.read_config()
_ansi_csi_re = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')
_ansi_esc_re = re.compile(r'\x1b.[@-~]?')


def _strip_ansi_sequences(s: str) -> str:
    """移除常见的 ESC/CSI 控制序列（方向键、功能键等）"""
    s = _ansi_csi_re.sub('', s)
    s = _ansi_esc_re.sub('', s)
    return s


class TerminalBridge(QObject):
    """
    Bridge object exposed to JavaScript via QWebChannel.

    Signals:
        output(str) : emits base64-encoded bytes from SSHWorker to JS.
        ready() : emits when frontend is ready.
        scrollPositionChanged(int) : emits scroll position from JS to Python.
        directoryChanged(str) : emits directory change events.
    """
    output = pyqtSignal(str)
    ready = pyqtSignal()
    directoryChanged = pyqtSignal(str)

    def __init__(self, parent=None, user_name=None, home_path=None):
        super().__init__(parent)
        self.worker = None
        self.current_directory = "/"
        self._input_buffer = ""  # 用户输入缓冲
        self.username = user_name
        # self.home_path = home_path
        # print(home_path)

    def set_worker(self, worker):
        """Attach an SSHWorker. The worker must emit bytes via result_ready signal."""
        if self.worker is not None:
            try:
                self.worker.result_ready.disconnect(self._on_worker_output)
            except Exception:
                pass
        self.worker = worker
        if worker:
            worker.result_ready.connect(self._on_worker_output)

    def _process_user_input(self, data: bytes):
        """
        处理用户输入：
         - 识别退格、Ctrl+U、Ctrl+W
         - 忽略常见 ESC/CSI 序列
         - 遇到回车时提交命令
        """
        try:
            text = data.decode('utf-8', errors='ignore')
            text = _strip_ansi_sequences(text)

            buf_chars = list(self._input_buffer)
            i = 0
            L = len(text)
            while i < L:
                ch = text[i]

                # 退格
                if ch == '\x08' or ch == '\x7f':
                    if buf_chars:
                        buf_chars.pop()
                    i += 1
                    continue

                # Ctrl+U 清行
                if ch == '\x15':
                    buf_chars = []
                    i += 1
                    continue

                # Ctrl+W 删除上一个单词
                if ch == '\x17':
                    while buf_chars and buf_chars[-1].isspace():
                        buf_chars.pop()
                    while buf_chars and not buf_chars[-1].isspace():
                        buf_chars.pop()
                    i += 1
                    continue

                # 回车或换行
                if ch == '\r' or ch == '\n':
                    cmd = ''.join(buf_chars).strip()
                    if cmd:
                        self._process_command(cmd)
                    buf_chars = []
                    while i < L and (text[i] == '\r' or text[i] == '\n'):
                        i += 1
                    continue

                # 普通字符追加
                buf_chars.append(ch)
                i += 1

            self._input_buffer = ''.join(buf_chars)

        except Exception as e:
            print(f"处理用户输入时出错: {e}")
            self._input_buffer = ""

    def _process_command(self, command: str):
        """
        只在完整命令提交（按回车）时调用。
        支持 cd <dir>、cd、cd ~、cd ~/subdir 等。
        """
        try:
            parts = command.split()
            if not parts:
                return

            if parts[0] == 'cd':
                target_dir = '~' if len(parts) == 1 else parts[1]
                username = self.username
                # 波浪符展开
                if target_dir == '~':
                    if username == 'root':
                        target_dir = '/root'
                    else:
                        target_dir = f'/home/{username}' if username else '/home/user'
                elif target_dir.startswith('~/'):
                    if username == 'root':
                        target_dir = target_dir.replace('~', '/root', 1)
                    else:
                        target_dir = target_dir.replace(
                            '~', f'/home/{username}' if username else '/home/user', 1)
                # 相对路径处理
                if not target_dir.startswith('/'):
                    base = self.current_directory.rstrip('/')
                    base = '/' if base == '' else base
                    candidate = base + '/' + \
                        target_dir if not base.endswith(
                            '/') else base + target_dir
                else:
                    candidate = target_dir

                # 规范化路径
                candidate = os.path.normpath(candidate).replace('\\', '/')

                if candidate != self.current_directory:
                    self.current_directory = candidate
                    self.directoryChanged.emit(candidate)

        except Exception as e:
            print(f"_process_command error: {e}")

    def _on_worker_output(self, chunk: bytes):
        """Encode bytes -> base64 and emit to JS."""
        try:
            b64 = base64.b64encode(chunk).decode("ascii")
            self.output.emit(b64)
        except Exception as e:
            print(f"处理输出时出错: {e}")

    @pyqtSlot(str)
    def sendInput(self, b64: str):
        """JS -> Python: base64-encoded user input"""
        if not self.worker:
            return
        try:
            data = base64.b64decode(b64)
            # print("接收到:", data.decode("utf-8", errors="ignore"))
            self._process_user_input(data)
            self.worker.run_command(data, add_newline=False)
        except Exception as e:
            print("TerminalBridge.sendInput error:", e)

    @pyqtSlot(int, int)
    def resize(self, cols: int, rows: int):
        """JS -> Python: terminal size change"""
        if not self.worker:
            return
        try:
            self.worker.resize_pty(cols, rows)
        except Exception as e:
            print("TerminalBridge.resize error:", e)

    @pyqtSlot()
    def notifyReady(self):
        self.ready.emit()

    @pyqtSlot(str)
    def copyToClipboard(self, text):
        QApplication.clipboard().setText(text)

    @pyqtSlot()
    def pasteFromClipboard(self):
        """JS -> Python: paste from clipboard"""
        clipboard_text = QApplication.clipboard().text()
        if clipboard_text:
            self.sendInput(base64.b64encode(
                clipboard_text.encode('utf-8')).decode('ascii'))


class WebTerminal(QWidget):
    """
    Web terminal widget embedding xterm.js in a QWebEngineView.

    Parameters:
      parent: parent widget
      cols, rows: initial terminal size (cols, rows)
      text_color: CSS color for foreground text (e.g., "white" or "#fff")
      bg_color: CSS color fallback for background (e.g., "#000000" or "rgba(0,0,0,0.6)")
      text_shadow: boolean, whether to add a subtle text shadow for improve readability
    """
    directoryChanged = pyqtSignal(str)

    def __init__(self, parent=None, cols=120, rows=30, text_color="white", bg_color="transparent", text_shadow=False, font_name=None, user_name=None, devmode=True):
        super().__init__(parent)
        self._rows = int(rows)
        self._cols = cols
        # Means not set color
        if text_color == "white":
            self._text_color = text_color
            # config = configer.read_config()
            # self._text_color = config["ssh_widget_text_color"]
            # print(self._text_color)
        else:
            self._text_color = text_color
        # self._text_color = text_color or "white"
        self._bg_color = bg_color or "transparent"
        self._text_shadow = bool(text_shadow)
        self._scroll_position = 0
        self._max_scroll = 1000
        print(font_name)
        self._font_family = font_name or "monospace"

        # 确保整个 widget 透明
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent; border: none;")

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # 创建水平布局用于放置终端和自定义滚动条
        self.terminal_layout = QHBoxLayout()
        self.terminal_layout.setContentsMargins(0, 0, 0, 0)
        self.terminal_layout.setSpacing(0)

        # QWebEngineView setup
        self.view = QWebEngineView(self)

        self.view.setAttribute(Qt.WA_TranslucentBackground, True)
        self.view.setStyleSheet("""
            QWebEngineView {
                background: transparent;
                border: none;
            }
            QWebEngineView::scroll-bar:vertical {
                width: 0px;
            }
            QWebEngineView::scroll-bar:horizontal {
                height: 0px;
            }
        """)

        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.terminal_layout.addWidget(self.view, 1)
        self.main_layout.addLayout(self.terminal_layout)

        try:
            self.view.page().setBackgroundColor(QColor(0, 0, 0, 0))
        except Exception as e:
            print("Warning: could not set page background transparent:", e)

        # WebChannel + Bridge
        self.channel = QWebChannel(self.view.page())
        print(f"User name {user_name}")
        self.bridge = TerminalBridge(self, user_name=user_name)
        self.bridge.directoryChanged.connect(self._on_directory_changed)
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)

        if devmode:
            self._open_dev_mode()

        self.hide_scrollbars_js = """
        const style = document.createElement('style');
        style.innerHTML = `
            ::-webkit-scrollbar {
                display: none !important;
                width: 0 !important;
                height: 0 !important;
            }
            * {
                scrollbar-width: none !important;
                -ms-overflow-style: none !important;
            }
        `;
        document.head.appendChild(style);
        """

        # Load HTML
        html = self._build_html()
        self.view.setHtml(html, QUrl("qrc:///"))

        self.view.page().loadFinished.connect(self._on_page_loaded)

        self.terminal_texts = ""
        self._terminal_texts_max = 1500
        if config["aigc_open"]:
            try:
                self.bridge.output.connect(self._on_bridge_output)
            except Exception:
                pass

    def _open_dev_mode(self):
        self.devtools = QWebEngineView()
        self.devtools.setWindowTitle("DevTools")
        self.devtools.resize(900, 700)
        self.view.page().setDevToolsPage(self.devtools.page())

        shortcut = QShortcut(QKeySequence("Ctrl+Shift+I"), self)
        shortcut.activated.connect(self._toggle_devtools)

    def _toggle_devtools(self):
        if self.devtools.isVisible():
            self.devtools.hide()
        else:
            self.devtools.show()
            self.devtools.raise_()
            self.devtools.activateWindow()

    def _on_directory_changed(self, new_dir):
        if config["follow_cd"]:
            self.directoryChanged.emit(new_dir)

    def _set_font(self, font_name):
        """
        设置终端内显示的字体

        Args:
            font_name: 系统已安装的字体名称
        """

        self._font_family = font_name or "monospace"
        self._update_font_in_html()
        self._force_rerender()

    def _force_rerender(self):
        """强制终端重新渲染"""
        rerender_js = """
        const term = window.term;
        if (term) {
            const text = term.getSelection() || term.getText();
            term.clear();
            term.write(text);
        }
        """
        self.view.page().runJavaScript(rerender_js)

    def _update_font_in_html(self):
        """更新 HTML 中的字体设置"""
        font_js = f"""
      // 更新终端字体
      const terminal = document.getElementById('terminal');
      if (terminal) {{
          terminal.style.fontFamily = '{self._font_family}, monospace !important';
          terminal.style.letterSpacing = 'normal !important';
      }}
      
      // 更新 xterm 字体
      const xtermElements = document.querySelectorAll('.xterm, .xterm *');
      xtermElements.forEach(element => {{
          element.style.fontFamily = '{self._font_family}, monospace !important';
          element.style.letterSpacing = 'normal !important';
      }});
      """
        self.view.page().runJavaScript(font_js)

    def _on_page_loaded(self):
        """页面加载完成后的回调函数，用于调试透明度和隐藏滚动条"""
        def check_bg_color(color):
            print(f"Page background color: {color}")

        def check_body_bg(color):
            print(f"Body background color: {color}")

        def check_terminal_bg(color):
            print(f"Terminal div background color: {color}")

        # 检查各种元素的背景色
        self.view.page().runJavaScript(
            "window.getComputedStyle(document.body).backgroundColor",
            check_body_bg
        )

        self.view.page().runJavaScript(
            "window.getComputedStyle(document.getElementById('terminal')).backgroundColor",
            check_terminal_bg
        )

        # 检查页面背景色
        bg_color = self.view.page().backgroundColor()
        print(
            f"QWebEnginePage background color: {bg_color.name(QColor.HexArgb)}")

        # 隐藏原生滚动条
        self.view.page().runJavaScript(self.hide_scrollbars_js)

    def _html_escape(self, s: str) -> str:
        return json.dumps(s)

    def _build_html(self) -> str:
        """
        Return the HTML string used as the web page for the terminal.
        """
        try:
            # # 获取当前脚本所在的目录
            # current_dir = os.path.dirname(os.path.abspath(__file__))
            # # 拼接正确的模板文件路径
            # tpl_path = os.path.join(
            #     current_dir, '..', 'resource', 'tpl', 'terminal.tpl')
            tpl_path = resource_path(os.path.join(
                "resource", "tpl", "terminal.tpl"))
            with open(tpl_path, 'r', encoding='utf-8') as f:
                tpl = f.read()
        except Exception as e:
            print(f"Error loading terminal.html: {e}")
            return f"<html><body><h1>Error loading template</h1><p>{e}</p></body></html>"

        # JSON-encoded strings for safe embedding in JS
        fg_js = self._html_escape(self._text_color)
        bg_js = self._html_escape(self._bg_color)
        shadow_bool = "true" if self._text_shadow else "false"

        # Replace placeholders in the template
        final = tpl.replace("{{rows}}", str(self._rows))
        final = final.replace("{{cols}}", str(self._cols))
        final = final.replace("{{fg}}", fg_js)
        final = final.replace("{{bg}}", bg_js)
        final = final.replace("{{shadow}}", shadow_bool)
        final = final.replace("{{bg_css}}", self._bg_color)
        final = final.replace("{{font_family}}", self._font_family)

        return final

    def set_worker(self, worker):
        """Attach SSHWorker to the bridge and notify it of current pty size."""
        self.bridge.set_worker(worker)
        try:
            worker.resize_pty(self._cols, self._rows)
        except Exception:
            pass

    def set_colors(self, text_color=None, bg_color=None, text_shadow=None):
        """
        Dynamically update terminal colors.
        Parameters accept CSS color strings:
          text_color: e.g. "white" or "#00ffcc"
          bg_color: fallback background (used as CSS variable), e.g. "rgba(0,0,0,0.6)"
          text_shadow: boolean
        """
        if text_color is not None:
            self._text_color = text_color
        if bg_color is not None:
            self._bg_color = bg_color
        if text_shadow is not None:
            self._text_shadow = bool(text_shadow)

        # Call JS function to update theme; serialize strings safely via json.dumps
        fg_js = json.dumps(self._text_color)
        bg_js = json.dumps(self._bg_color)
        shadow_js = "true" if self._text_shadow else "false"
        js = f"if (window.setTerminalTheme) window.setTerminalTheme({fg_js}, {bg_js}, {shadow_js});"
        try:
            self.view.page().runJavaScript(js)
        except Exception as e:
            print("set_colors runJavaScript error:", e)

    def resizeEvent(self, event):
        """
        Optionally, we rely on the front-end's window.resize event and fitAddon to call
        bridge.resize. Still, we keep this hook in case additional Python-side logic is desired.
        """
        super().resizeEvent(event)
        # No explicit action here; JS side handles sizing via fitAddon and window resize listener.

    # Prevent all drag operations

    def dragEnterEvent(self, event):
        event.ignore()

    def dropEvent(self, event):
        event.ignore()

    def clear_screen(self):
        """Clears the terminal screen."""
        js = "if (window.term) window.term.clear();"
        try:
            self.view.page().runJavaScript(js)
        except Exception as e:
            print("clear_screen runJavaScript error:", e)

    def send_command(self, command: str):
        """Sends a string command to the terminal."""
        try:
            # The bridge's sendInput expects base64
            b64 = base64.b64encode(command.encode('utf-8')).decode('ascii')
            self.bridge.sendInput(b64)
        except Exception as e:
            print("send_command error:", e)

    def fit_terminal(self):
        """Triggers the fit addon in the browser to resize the terminal."""
        js = "if (typeof notifySize === 'function') notifySize();"
        try:
            self.view.page().runJavaScript(js)
        except Exception as e:
            print("fit_terminal runJavaScript error:", e)

    def cleanup(self):
        """
        安全清理 WebTerminal：
        - 注销 TerminalBridge 的信号
        - 清理 QWebEngineView
        - 断开 worker
        - 删除子控件
        """
        # 1️⃣ 断开 bridge 的信号
        try:
            self.bridge.directoryChanged.disconnect()
        except Exception:
            pass
        try:
            self.terminal_texts = ""
        except Exception:
            pass
        # 2️⃣ 注销 worker
        if self.bridge.worker:
            try:
                self.bridge.worker.result_ready.disconnect(
                    self.bridge._on_worker_output)
            except Exception:
                pass
            self.bridge.worker = None

        # 3️⃣ 清空输入缓冲
        self.bridge._input_buffer = ""
        self.bridge.current_directory = "/"

        # 4️⃣ 清理 QWebEngineView
        if hasattr(self, 'view') and self.view:
            try:
                self.view.page().setWebChannel(None)
                self.view.setParent(None)
                self.view.deleteLater()
            except Exception:
                pass
            self.view = None

        # 5️⃣ 删除主布局里的所有 item
        if hasattr(self, 'main_layout') and self.main_layout:
            while self.main_layout.count():
                item = self.main_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.setParent(None)
                    w.deleteLater()
            self.main_layout = None

        # 6️⃣ 从父控件中移除自己
        parent_layout = self.parentWidget().layout() if self.parentWidget() else None
        if parent_layout:
            parent_layout.removeWidget(self)
        self.setParent(None)

    def _on_bridge_output(self, b64: str):
        """
        Slot connected to TerminalBridge.output (base64-encoded bytes).
        Decode -> strip ANSI -> append to self.terminal_texts, trimming from head if needed.
        """
        try:
            # decode base64 -> bytes -> text
            chunk_bytes = base64.b64decode(b64)
            text = chunk_bytes.decode('utf-8', errors='ignore')
            # strip ANSI sequences to keep plain terminal text (optional but usually desired)
            plain = _strip_ansi_sequences(text)

            # append and trim to max length (keep newest chars)
            self.terminal_texts += plain
            if len(self.terminal_texts) > self._terminal_texts_max:
                # keep the last _terminal_texts_max characters
                self.terminal_texts = self.terminal_texts[-self._terminal_texts_max:]

        except Exception as e:
            # Don't crash the app for logging reasons; print for debug
            print(f"_on_bridge_output error: {e}")

    def execute_command_and_capture(self, command: str):
        if self.bridge and self.bridge.worker:
            self.bridge.worker.execute_command_and_capture(command)

    def get_latest_output(self, count=1):
        if not self.terminal_texts:
            return "<results></results>"
        prompt_re = re.compile(r"[\w\d\._-]+@[\w\d\.-]+:.*[#\$]")
        lines = self.terminal_texts.splitlines()
        prompt_indices = [i for i, line in enumerate(
            lines) if prompt_re.search(line)]
        results_xml = "<results>"
        num_possible_outputs = len(prompt_indices) - 1
        if num_possible_outputs < 1:
            return "<results></results>"
        actual_count = min(count, num_possible_outputs)
        for i in range(actual_count):
            end_prompt_index = prompt_indices[-(i + 1)]
            start_prompt_index = prompt_indices[-(i + 2)]
            start_prompt_line = lines[start_prompt_index]
            cleaned_start_line = _strip_ansi_sequences(start_prompt_line)
            command = ""
            last_hash_pos = cleaned_start_line.rfind('#')
            last_dollar_pos = cleaned_start_line.rfind('$')
            split_pos = max(last_hash_pos, last_dollar_pos)
            if split_pos != -1:
                command = cleaned_start_line[split_pos + 1:].strip()
            output_lines = lines[start_prompt_index + 1: end_prompt_index]
            full_output = "\n".join(output_lines)
            plain_output = _strip_ansi_sequences(full_output)
            results_xml += f"""<command_{i + 1}><cmd>{command}</cmd><output>{plain_output}</output></command_{i + 1}>"""
        results_xml += "\n</results>"
        return results_xml
