from pyte.screens import HistoryScreen, Char
import pyte
from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPainter, QFont, QColor, QFontMetrics, QKeyEvent, QMouseEvent, QWheelEvent
import paramiko
import socket
import select
from tools.session_manager import SessionManager
import re
session_manager = SessionManager()


BASE_COLORS = {
    'black':   QColor("#000000"), 'red':     QColor("#C0392B"), 'green':   QColor("#27AE60"),
    'brown':   QColor("#D35400"), 'blue':    QColor("#2980B9"), 'magenta': QColor("#8E44AD"),
    'cyan':    QColor("#16A085"), 'white':   QColor("#BDC3C7"), 'default': QColor("#BDC3C7"),
}
BRIGHT_COLORS = {
    'black':   QColor("#7F8C8D"), 'red':     QColor("#E74C3C"), 'green':   QColor("#2ECC71"),
    'brown':   QColor("#F1C40F"), 'blue':    QColor("#3498DB"), 'magenta': QColor("#9B59B6"),
    'cyan':    QColor("#1ABC9C"), 'white':   QColor("#ECF0F1"), 'default': QColor("#ECF0F1"),
}

_ansi_csi_re = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')
_ansi_esc_re = re.compile(r'\x1b.[@-~]?')


def _strip_ansi_sequences(s: str) -> str:
    """移除常见的 ESC/CSI 控制序列"""
    s = _ansi_csi_re.sub('', s)
    s = _ansi_esc_re.sub('', s)
    return s


class SshClient(QThread):
    """
    SSH 连接和数据接收的后台线程。支持多种初始化方式：
    1. 账密连接: SshClient(host='...', port=22, user='...', password='...')
    2. 密钥连接: SshClient(host='...', port=22, user='...', key_path='...')
    3. 已有通道: SshClient(channel=<paramiko.Channel>)
    """
    data_received = pyqtSignal(bytes)

    def __init__(self, host=None, port=22, user=None, password=None, key_path=None, channel=None):
        super().__init__()

        # 模式1: 传入已打开的 channel
        if channel is not None:
            self.channel = channel
            self.client = None
            self.mode = 'channel'
        # 模式2&3: 需要连接
        elif host and user:
            self.host = host
            self.port = port
            self.user = user
            self.password = password
            self.key_path = key_path
            self.channel = None
            self.client = None
            if password:
                self.mode = 'password'
            elif key_path:
                self.mode = 'key'
            else:
                raise ValueError("必须提供 password 或 key_path")
        else:
            raise ValueError(
                "必须提供 channel 或 (host, user) 和 (password 或 key_path)")

        self.running = True

    def run(self):
        try:
            # 如果是 channel 模式，直接使用
            if self.mode == 'channel':
                self.channel.setblocking(0)
            else:
                # 建立 SSH 连接
                self.client = paramiko.SSHClient()
                self.client.set_missing_host_key_policy(
                    paramiko.AutoAddPolicy())

                if self.mode == 'password':
                    self.client.connect(
                        self.host, self.port, self.user,
                        password=self.password, timeout=10
                    )
                elif self.mode == 'key':
                    self.client.connect(
                        self.host, self.port, self.user,
                        key_filename=self.key_path, timeout=10
                    )

                self.channel = self.client.invoke_shell(
                    term='xterm-256color', width=80, height=24
                )
                self.channel.setblocking(0)

            # 数据接收循环
            while self.running:
                r, w, x = select.select([self.channel], [], [], 0.05)

                if self.channel in r:
                    try:
                        data = self.channel.recv(4096)
                        if len(data) == 0:
                            break
                        self.data_received.emit(data)
                    except socket.timeout:
                        pass
                    except Exception as e:
                        print(f"Read Error: {e}")
                        break
        except Exception as e:
            print(f"Connection Error: {e}")
        finally:
            if self.client:
                try:
                    self.client.close()
                except Exception:
                    pass

    def send(self, data):
        """发送数据到 SSH 通道"""
        if self.channel:
            try:
                self.channel.send(data)
            except Exception as e:
                print(f"Send Error: {e}")

    def stop(self):
        """停止接收线程"""
        self.running = False
        self.wait()


class TerminalScreen(QWidget):
    """使用 pyte 维护屏幕状态，QPainter 绘制终端内容。"""

    def __init__(self, font_family="Consolas", font_size=11, text_color=None):
        super().__init__()
        self.ssh = None  # 延迟设置
        self.setFocusPolicy(Qt.StrongFocus)
        self.terminal_texts = ""
        self._terminal_texts_max = 15000  # 增加限制，确保不会无限增长
        # 支持通过参数传入默认文本颜色（可以传 QColor 或字符串 '#rrggbb'）
        if text_color is None:
            # 保持向后兼容的默认颜色（与原先 BRIGHT_COLORS['default'] 类似）
            self.default_fg = QColor("#ECF0F1")
        else:
            try:
                self.default_fg = QColor(text_color) if not isinstance(
                    text_color, QColor) else text_color
            except Exception:
                self.default_fg = QColor("#ECF0F1")

        # 透明背景设置：窗口透明，只绘制字符与高亮
        # 需要窗口/父窗口支持透明（在部分平台/样式下需顶级窗口启用）
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")

        self.font = QFont(font_family, font_size)
        self.font.setStyleHint(QFont.Monospace)
        self.metrics = QFontMetrics(self.font)
        self.char_w = self.metrics.horizontalAdvance('W')
        self.char_h = self.metrics.lineSpacing()

        self.cols, self.rows = 80, 24
        self.screen = HistoryScreen(self.cols, self.rows, history=5000)
        self.stream = pyte.Stream(self.screen)

        self.setStyleSheet("background-color: #1e1e1e;")

        self.selection_start = None
        self.selection_end = None
        self.is_selecting = False
        self.scroll_offset = 0
        self.press_pos = None

    def set_ssh_thread(self, ssh_thread: SshClient):
        """设置 SSH 线程对象"""
        self.ssh = ssh_thread
        # 连接数据接收信号到处理槽
        if self.ssh and hasattr(self.ssh, 'data_received'):
            self.ssh.data_received.connect(self.put_data)

    def _get_max_buffer_rows(self):
        """计算 HistoryScreen 中所有可访问的行"""
        history_len = len(self.screen.history.top)
        max_rows = history_len + self.rows
        # print(
        #     f"DEBUG: History Top Len: {history_len}, Calculated Total Rows: {max_rows}")
        return max_rows

    def get_color(self, name, bold=False, bg=False):
        """获取颜色值，默认颜色使用 self.default_fg（可通过 __init__ 设置）"""
        if name == 'default':
            if bg:
                return QColor(Qt.transparent)
            return self.default_fg

        if name in BASE_COLORS:
            if bold and not bg:
                return BRIGHT_COLORS.get(name, self.default_fg)
            return BASE_COLORS.get(name, self.default_fg)
        if name.startswith('#'):
            return QColor(name)
        return self.default_fg if not bg else QColor(Qt.black)

    # def put_data(self, data: bytes):
    #     """处理接收到的数据"""
    #     try:
    #         self.stream.feed(data.decode('utf-8', errors='replace'))

    #         max_rows = self._get_max_buffer_rows()
    #         self.scroll_offset = max(0, max_rows - self.rows)

    #         self.update()
    #     except Exception:
    #         pass
    def put_data(self, data: bytes):
        """处理接收到的数据"""
        try:
            text = data.decode('utf-8', errors='replace')
            self.stream.feed(text)

            plain = _strip_ansi_sequences(text)
            self.terminal_texts += plain
            if len(self.terminal_texts) > self._terminal_texts_max:
                self.terminal_texts = self.terminal_texts[-self._terminal_texts_max:]

            max_rows = self._get_max_buffer_rows()
            self.scroll_offset = max(0, max_rows - self.rows)

            self.update()
        except Exception:
            pass

    def wheelEvent(self, event: QWheelEvent):
        """鼠标滚动处理"""
        delta = event.angleDelta().y()

        max_rows = self._get_max_buffer_rows()
        max_scroll_offset = max(0, max_rows - self.rows)

        old_offset = self.scroll_offset
        scroll_step = 3

        if delta > 0:
            self.scroll_offset = max(0, self.scroll_offset - scroll_step)
        elif delta < 0:
            self.scroll_offset = min(
                max_scroll_offset, self.scroll_offset + scroll_step)

        if old_offset != self.scroll_offset:
            self.update()

        event.accept()

    def _to_buffer_coords(self, event_x, event_y):
        """将窗口像素坐标转换为 pyte 缓冲区坐标"""
        char_x = int(event_x / self.char_w)
        char_y = int(event_y / self.char_h) + self.scroll_offset
        return char_x, char_y

    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下处理"""
        if event.button() == Qt.LeftButton:
            self.is_selecting = True
            self.press_pos = event.pos()

            char_x, char_y = self._to_buffer_coords(event.x(), event.y())

            if not (event.modifiers() & Qt.ShiftModifier):
                self.selection_start = (char_x, char_y)

            self.selection_end = (char_x, char_y)
            self.setCursor(Qt.IBeamCursor)
            self.update()

        elif event.button() == Qt.MidButton:
            clipboard = QApplication.clipboard()
            self.ssh.send(clipboard.text().encode('utf-8'))

    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动处理"""
        if self.is_selecting:
            char_x, char_y = self._to_buffer_coords(event.x(), event.y())
            self.selection_end = (char_x, char_y)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放处理"""
        if event.button() == Qt.LeftButton:
            self.is_selecting = False
            self.setCursor(Qt.ArrowCursor)

            if self.press_pos and (event.pos() - self.press_pos).manhattanLength() < 5:
                self.selection_start = None
                self.selection_end = None
                self.press_pos = None
                self.update()
                return

            selected_text = self.get_selected_text()
            if selected_text:
                clipboard = QApplication.clipboard()
                clipboard.setText(selected_text)

            self.press_pos = None

    def get_selected_text(self):
        """获取选中的文本"""
        if not self.selection_start or not self.selection_end:
            return ""

        (sx, sy) = self.selection_start
        (ex, ey) = self.selection_end

        if (sy > ey) or (sy == ey and sx > ex):
            sx, sy, ex, ey = ex, ey, sx, sy

        text = []

        for y in range(sy, ey + 1):
            if y not in self.screen.buffer:
                continue

            line_dict = self.screen.buffer[y]

            line = "".join(line_dict.get(col).data if line_dict.get(
                col) else ' ' for col in range(self.cols))

            start_col = sx if y == sy else 0
            end_col = ex + 1 if y == ey else len(line)

            text.append(line[start_col:end_col])

        return "\n".join(text).strip()

    def paintEvent(self, event):
        """绘制终端内容"""
        painter = QPainter(self)
        painter.setFont(self.font)
        # 不填充背景，保持完全透明（仅绘制字符与高亮）
        painter.setRenderHint(QPainter.Antialiasing)

        history_len = len(self.screen.history.top)

        start_abs_index = self.scroll_offset
        end_abs_index = self.scroll_offset + self.rows

        class PlaceholderChar:
            data = ' '
            fg = 'default'
            bg = 'default'
            bold = False
            italics = False
            underscore = False
            strikethrough = False
            reverse = False
            blink = False

        for screen_y in range(self.rows):
            abs_y = start_abs_index + screen_y
            line_buffer_dict = {}

            if abs_y < history_len:
                try:
                    line_buffer_dict = self.screen.history.top[abs_y]
                except IndexError:
                    pass

            elif history_len <= abs_y < history_len + self.rows:
                buffer_y = abs_y - history_len
                line_buffer_dict = self.screen.buffer.get(buffer_y, {})

            else:
                continue

            if not line_buffer_dict:
                continue

            for x in range(self.cols):
                char = line_buffer_dict.get(x)

                is_selected = False
                if self.selection_start and self.selection_end:
                    (sx, sy) = self.selection_start
                    (ex, ey) = self.selection_end
                    min_y, max_y = min(sy, ey), max(sy, ey)

                    if min_y <= abs_y <= max_y:
                        if (abs_y == min_y and x >= (min(sx, ex) if min_y == max_y else sx)) or \
                           (abs_y == max_y and x <= (max(sx, ex) if min_y == max_y else ex)) or \
                           (min_y < abs_y < max_y):
                            is_selected = True

                if char is None:
                    if is_selected:
                        char = PlaceholderChar()
                    else:
                        continue

                fg_color = self.get_color(char.fg, char.bold, bg=False)
                bg_color = self.get_color(
                    char.bg, bg=True) if char.bg != 'default' else QColor(Qt.transparent)

                if char.reverse:
                    fg_color, bg_color = bg_color, fg_color

                pos_x = x * self.char_w
                pos_y = screen_y * self.char_h

                final_bg_color = QColor(
                    65, 131, 196) if is_selected else bg_color
                painter.fillRect(pos_x, pos_y, self.char_w,
                                 self.char_h, final_bg_color)

                final_fg_color = Qt.white if is_selected else fg_color
                painter.setPen(final_fg_color)

                if char.data:
                    painter.drawText(
                        pos_x, pos_y + self.metrics.ascent(), char.data)

        max_scroll_offset = max(0, self._get_max_buffer_rows() - self.rows)
        if self.scroll_offset == max_scroll_offset:
            cx, cy = self.screen.cursor.x, self.screen.cursor.y

            if 0 <= cx < self.cols and 0 <= cy < self.rows:
                painter.fillRect(cx * self.char_w, cy * self.char_h,
                                 self.char_w, self.char_h, QColor(255, 255, 255, 120))

    def resizeEvent(self, event):
        """自动适应窗口大小"""
        super().resizeEvent(event)

        new_width = self.width()
        new_height = self.height()

        new_cols = max(20, new_width // self.char_w) if self.char_w > 0 else 80
        new_rows = max(5, new_height // self.char_h) if self.char_h > 0 else 24

        if new_cols != self.cols or new_rows != self.rows:
            old_cols, old_rows = self.cols, self.rows

            print(f"DEBUG [RESIZE]: Widget Size: {new_width}x{new_height}px")
            print(f"DEBUG [RESIZE]: Old Terminal Size: {old_cols}x{old_rows}")
            print(
                f"DEBUG [RESIZE]: New Terminal Size: {new_cols}x{new_rows}")
            print(f"DEBUG [RESIZE]: Char Size: {self.char_w}x{self.char_h}px")

            self.cols = new_cols
            self.rows = new_rows

            self.screen.lines = self.rows
            self.screen.columns = self.cols

            if self.ssh and self.ssh.channel:
                try:
                    self.ssh.channel.resize_pty(
                        width=self.cols, height=self.rows)
                    print(
                        f"DEBUG [RESIZE]: SSH PTY resized to {self.cols}x{self.rows}")
                except Exception as e:
                    print(f"DEBUG [RESIZE]: Failed to resize SSH PTY: {e}")

            self.update()

    def keyPressEvent(self, event: QKeyEvent):
        """键盘事件处理"""
        key = event.key()
        text = event.text()

        mapping = {
            Qt.Key_Return: '\r', Qt.Key_Enter: '\r',
            Qt.Key_Backspace: '\x7f',
            Qt.Key_Tab: '\t',
            Qt.Key_Up: '\x1b[A', Qt.Key_Down: '\x1b[B',
            Qt.Key_Right: '\x1b[C', Qt.Key_Left: '\x1b[D',
            Qt.Key_Home: '\x1b[H', Qt.Key_End: '\x1b[F',
            Qt.Key_Delete: '\x1b[3~',
        }

        data_to_send = None

        if event.modifiers() & Qt.ControlModifier:
            if Qt.Key_A <= key <= Qt.Key_Z:
                code = key - Qt.Key_A + 1
                data_to_send = chr(code)

        elif key in mapping:
            data_to_send = mapping[key]

        elif text:
            data_to_send = text

        if data_to_send:
            self.ssh.send(data_to_send.encode('utf-8'))

            max_rows = self._get_max_buffer_rows()
            self.scroll_offset = max(0, max_rows - self.rows)
            self.update()

    def send_command(self, command: str):
        """Sends a string command to the terminal."""
        if command is None:
            return
        try:
            payload = command if isinstance(command, str) else str(command)
            data = payload.encode('utf-8', errors='ignore')
            self.ssh.send(data)

        except Exception:
            pass

    def clear_screen(self):
        """Clears the terminal screen."""
        try:
            # 清空屏幕缓冲区
            self.screen.buffer.clear()
            # 重置光标位置
            self.screen.cursor.x = 0
            self.screen.cursor.y = 0
            # 重置滚动偏移
            self.scroll_offset = 0
            # 刷新显示
            self.update()
        except Exception:
            pass

    def fit_terminal(self):
        pass

    def execute_command_and_capture(self, command: str):
        """Sends a command to the terminal for execution and capture."""
        # 确保 SSH 连接对象存在，即 self.ssh 不为 None
        if self.ssh is None:
            # 如果 self.ssh 为 None，则返回或抛出错误，
            # 否则后续的 self.send_command 会失败
            print("Error: SSH connection (self.ssh) is not set.")
            return

        if command is None:
            return

        # 直接调用 send_command
        self.send_command(command + '\r')

    def get_latest_output(self, count=1):
        """
        Parses the last 'count' command outputs from the terminal_texts buffer.
        Returns the result as an XML string.
        """
        if not self.terminal_texts:
            return "<results></results>"
        # 兼容 WebTerminal 的逻辑，使用正则表达式匹配常见的 Shell 提示符
        prompt_re = re.compile(r"[\w\d\._-]+@[\w\d\.-]+:.*[#\$]")
        lines = self.terminal_texts.splitlines()
        prompt_indices = [i for i, line in enumerate(
            lines) if prompt_re.search(line)]

        results_xml = "<results>"
        # 至少需要两个提示符才能界定一个命令及其输出
        num_possible_outputs = len(prompt_indices) - 1

        if num_possible_outputs < 1:
            return "<results></results>"

        actual_count = min(count, num_possible_outputs)

        for i in range(actual_count):
            # 从后向前解析
            end_prompt_index = prompt_indices[-(i + 1)]  # 当前命令执行结束后的提示符
            start_prompt_index = prompt_indices[-(i + 2)]  # 上一个命令执行前的提示符

            start_prompt_line = lines[start_prompt_index]
            cleaned_start_line = _strip_ansi_sequences(start_prompt_line)

            command = ""
            last_hash_pos = cleaned_start_line.rfind('#')
            last_dollar_pos = cleaned_start_line.rfind('$')
            split_pos = max(last_hash_pos, last_dollar_pos)

            # 提取命令文本 (提示符之后的内容)
            if split_pos != -1:
                command = cleaned_start_line[split_pos + 1:].strip()

            # 提取命令输出 (从命令提示符的下一行到下一个提示符的上一行)
            output_lines = lines[start_prompt_index + 1: end_prompt_index]
            full_output = "\n".join(output_lines)
            plain_output = _strip_ansi_sequences(full_output)

            # 构建 XML 结果
            results_xml += f"""<command_{i + 1}><cmd>{command}</cmd><output>{plain_output}</output></command_{i + 1}>"""

        results_xml += "\n</results>"
        return results_xml
