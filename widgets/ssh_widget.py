from PyQt5.QtWidgets import (
    QWidget, QStackedWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QSizePolicy, QSplitter
)
from widgets.diff_viewer_widget import DiffViewerWidget
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QTimer, QSize, QPropertyAnimation, QEasingCurve,  pyqtProperty
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QPainterPath
import time
from tools.atool import resource_path
import os

from qfluentwidgets import SegmentedWidget, RoundMenu, Action, FluentIcon as FIF, ToolButton, Dialog
from widgets.system_info_dialog import SystemInfoDialog

from tools.setting_config import SCM
from widgets.ssh_webterm import WebTerminal
from widgets.network_detaile import NetProcessMonitor
from widgets.task_widget import Tasks
from widgets.file_tree_widget import File_Navigation_Bar, FileTreeWidget
from widgets.files_widgets import FileExplorer
from widgets.transfer_progress_widget import TransferProgressWidget
from widgets.command_input import CommandInput
from tools.session_manager import SessionManager
from widgets.task_detaile import ProcessMonitor
from widgets.disk_usage_item import DiskMonitor
from widgets.scripts_widget import CommandScriptWidget
from widgets.monitorbar import MonitorBar
from widgets.terminal import TerminalScreen, SshClient
import random
CONFIGER = SCM()
session_manager = SessionManager()


def generate_beautiful_color():
    """生成鲜艳的颜色"""
    h = random.randint(0, 360)      # 全色调范围
    s = random.randint(80, 100)     # 高饱和度（80-100%）

    color = QColor()
    color.setHsl(h, s, 100)
    return color


class SSHPage(QWidget):
    # 定义信号：action 名称, session 名称
    menuActionTriggered = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(10, 10, 10, 10)
        self.vbox.setSpacing(5)

        # 上半部分：SSH 导航栏
        self.pivot = SegmentedWidget(self)
        self.vbox.addWidget(self.pivot, 0)

        # 下半部分：SSH 主窗口
        self.sshStack = QStackedWidget(self)
        self.vbox.addWidget(self.sshStack, 1)

        # 切换逻辑
        self.pivot.currentItemChanged.connect(
            lambda k: self.sshStack.setCurrentWidget(
                self.findChild(QWidget, k))
        )

        # 设置右键菜单策略
        self.pivot.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pivot.customContextMenuRequested.connect(self.show_context_menu)

    def add_session(self, object_name: str, text: str, widget: QWidget):
        widget.setObjectName(object_name)
        if isinstance(widget, QLabel):
            widget.setAlignment(Qt.AlignCenter)

        self.sshStack.addWidget(widget)
        self.pivot.addItem(routeKey=object_name, text=text)
        QTimer.singleShot(0, lambda: self.pivot.setCurrentItem(object_name))
        self.sshStack.setCurrentWidget(widget)

    def get_current_route_key(self):
        """返回当前选中 tab 的 routeKey"""
        current_item = self.pivot.currentItem()
        if not current_item:
            return None
        for key, item in self.pivot.items.items():
            if item == current_item:
                return key
        return None

    def remove_session(self, routeKey: str):
        """删除指定的 session"""
        if routeKey not in self.pivot.items:
            return

        if self.pivot.currentItem() == self.pivot.items[routeKey]:
            remaining_keys = [k for k in self.pivot.items if k != routeKey]
            if remaining_keys:
                self.pivot.setCurrentItem(remaining_keys[0])
                self.sshStack.setCurrentWidget(
                    self.findChild(QWidget, remaining_keys[0])
                )
            else:
                self.pivot._currentRouteKey = None

        item = self.pivot.items.pop(routeKey)
        item.setParent(None)
        item.deleteLater()

        widget_to_remove = self.findChild(QWidget, routeKey)
        if widget_to_remove:
            self.sshStack.removeWidget(widget_to_remove)
            widget_to_remove.setParent(None)
            widget_to_remove.deleteLater()

    def show_context_menu(self, pos: QPoint):
        """在 pivot 上显示右键菜单，同时切换到鼠标所在的 tab"""
        child = self.pivot.childAt(pos)
        if not child:
            return

        route_key = None
        for key, item in self.pivot.items.items():  # items 是字典
            if item == child or item.isAncestorOf(child):
                route_key = key
                break

        # Switch to the tab where the right-click is located
        self.pivot.setCurrentItem(route_key)
        session_name = self.pivot.currentItem().text()
        # print(session_name)

        menu = RoundMenu(title="", parent=self)
        close_action = Action(self.tr("Close Session"))
        duplicate_action = Action(self.tr("Duplicate Session"))

        close_action.triggered.connect(
            lambda: self.menuActionTriggered.emit(
                "close", session_name)
        )
        duplicate_action.triggered.connect(
            lambda: self.menuActionTriggered.emit(
                "copy", session_name)
        )

        menu.addAction(close_action)
        menu.addAction(duplicate_action)

        global_pos = self.pivot.mapToGlobal(pos)
        menu.exec(global_pos)


class SSHWidget(QWidget):

    def __init__(self, name: str,  parent=None, font_name=None, user_name=None, ssh_client: SshClient = None):
        super().__init__(parent=parent)
        self.button_animations = {}
        self.file_manager = None
        self.loading_animations = {}
        self.animation_start_times = {}
        config = CONFIGER.read_config()
        use_ai = config.get("aigc_open", False)
        self.setObjectName(name)
        self.router = name
        self.parentkey = name.split('-')[0].strip()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.sys_info_msg = ""

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.mainLayout.setSpacing(0)

        # --- Left Widget ---
        leftContainer = QFrame(self)
        leftContainer.setObjectName("leftContainer")
        leftContainer.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Expanding)

        leftLayout = QVBoxLayout(leftContainer)
        leftLayout.setContentsMargins(0, 0, 0, 0)
        leftLayout.setSpacing(0)

        self.leftSplitter = QSplitter(Qt.Vertical, leftContainer)
        self.leftSplitter.setObjectName("splitter_left_components")
        self.leftSplitter.setChildrenCollapsible(False)
        self.leftSplitter.setHandleWidth(2)
        # The stylesheet will be set dynamically later

        # sys_resources
        # self.sys_resources = ProcessTable(self.leftSplitter)
        # self.sys_resources.set_font_family(font_name)
        # self.sys_resources.setObjectName("sys_resources")
        # self.sys_resources.setMinimumHeight(80)
        # self.sys_resources.setSizePolicy(
        #     QSizePolicy.Expanding, QSizePolicy.Preferred)
        # self.sys_resources.setStyleSheet("""
        #     QFrame#sys_resources {
        #         background-color: rgba(200, 200, 200, 0.12);
        #         border: 1px solid rgba(0,0,0,0.12);
        #         border-radius: 6px;
        #     }
        # """)

        # Task
        self.task = Tasks(font_name, self.leftSplitter)
        self.task.sysinfo_button.clicked.connect(self._sys_info_dialog)
        self.task.set_text_color(config["ssh_widget_text_color"])
        self.task.setObjectName("task")
        self.task.setMinimumHeight(80)
        self.task.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.task.setStyleSheet("""
            QFrame#task {
                background-color: rgba(220, 220, 220, 0.06);
                border: 1px solid rgba(0,0,0,0.06);
                border-radius: 6px;
            }
        """)

        self.disk_usage = DiskMonitor(self.leftSplitter)
        self.disk_usage.into_driver_path.connect(self._set_file_bar)
        self.disk_usage.setObjectName("disk_usage")
        self.disk_usage.setMinimumHeight(80)
        self.disk_usage.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.disk_usage.setStyleSheet("""
            QWidget#disk_usage {
                background-color: rgba(240,240,240,0.08);
                border: 1px solid rgba(0,0,0,0.04);
                border-radius: 6px;
            }
""")
        self.disk_usage.setAttribute(Qt.WA_StyledBackground, True)

        # self.leftSplitter.addWidget(self.sys_resources)
        self.leftSplitter.addWidget(self.task)
        self.leftSplitter.addWidget(self.disk_usage)

        # self.leftSplitter.setStretchFactor(0, 15)  # sys_resources
        self.leftSplitter.setStretchFactor(1, 6)  # task
        self.leftSplitter.setStretchFactor(2, 4)  # disk_usage

        self.leftSplitter.splitterMoved.connect(self.on_splitter_moved)

        leftLayout.addWidget(self.leftSplitter, 1)

        self.transfer_progress = TransferProgressWidget(leftContainer)
        self.transfer_progress.setObjectName("transfer_progress")
        self.transfer_progress.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred)
        leftLayout.addWidget(self.transfer_progress, 0)

        self.transfer_progress.expansionChanged.connect(
            lambda expanded: self._on_transfer_expansion_changed(
                expanded, leftLayout, self.leftSplitter)
        )

        splitter_left_ratio = config.get(
            "splitter_left_components", [0.18, 0.47, 0.35])
        if len(splitter_left_ratio) == 3:
            sizes = [int(r * 1000) for r in splitter_left_ratio]
            self.leftSplitter.setSizes(sizes)

        # --- Right Widgets
        rightContainer = QFrame(self)
        rightContainer.setObjectName("rightContainer")
        rightContainer.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)

        rightLayout = QVBoxLayout(rightContainer)
        rightLayout.setContentsMargins(0, 0, 0, 0)
        rightLayout.setSpacing(0)
        self.rsplitter = QSplitter(Qt.Vertical, rightContainer)
        self.rsplitter.setObjectName("splitter_tb_ratio")
        self.rsplitter.setChildrenCollapsible(False)
        self.rsplitter.setHandleWidth(1)

        # Top container for ssh_widget and command_bar
        top_container = QFrame(self.rsplitter)
        top_container_layout = QVBoxLayout(top_container)
        top_container_layout.setContentsMargins(0, 0, 0, 0)
        top_container_layout.setSpacing(0)

        # ssh_widget
        global mode
        mode = config.get("terminal_mode", 0)
        if mode == 1:
            # , font_family=font_name)
            self.ssh_widget = TerminalScreen(
                text_color=config["ssh_widget_text_color"],
                font_family=font_name)
        else:
            self.ssh_widget = WebTerminal(
                top_container,
                font_name=font_name,
                user_name=user_name,
                text_color=config["ssh_widget_text_color"]
            )
            self.ssh_widget.directoryChanged.connect(self._set_file_bar)
        self.ssh_widget.setObjectName("ssh_widget")
        self.ssh_widget.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ssh_widget.setStyleSheet("""
            QFrame#ssh_widget {
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px solid rgba(0,0,0,0.04);
                border-radius: 6px;
            }
        """)

        # MonitorBar
        self.monitorbar = MonitorBar()
        self.monitorbar.set_font_family(font_name)
        self.monitorbar.setObjectName("monitorbar")

        # command input bar
        self.command_bar = QFrame(top_container)
        self.command_bar.setObjectName("command_bar")
        # self.command_bar.setFixedHeight(42) # Remove fixed height

        self.command_bar.setStyleSheet("""
            QFrame#command_bar {
                background-color: rgba(30, 30, 30, 0.5);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
            QFrame#command_bar:focus-within {
                border: 1px solid rgba(0, 122, 255, 0.7);
            }
            ToolButton {
                background-color: transparent;
                border-radius: 4px;
            }
            ToolButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
            ToolButton:pressed {
                background-color: rgba(255, 255, 255, 0.05);
            }
        """)
        command_bar_layout = QHBoxLayout(self.command_bar)
        command_bar_layout.setContentsMargins(8, 5, 8, 5)
        command_bar_layout.setSpacing(8)

        self.status_icon = ToolButton(
            QIcon(resource_path(os.path.join("resource", "icons", "gray.png"))), self)
        # self.status_icon.setEnabled(False)
        self.status_icon.setFixedSize(30, 30)
        self.status_icon.setFocusPolicy(Qt.NoFocus)
        self.status_icon.setToolTip(self.tr("Clean History"))
        self.status_icon.setStyleSheet("""
            PushButton {
                border: none;
                color: rgb(180, 180, 180);
                font-weight: bold;
                background: transparent;
                font-size: 14px;
            }
            PushButton:hover {
                color: white;
                background-color: rgb(60, 60, 60);
                border-radius: 11px;
            }
        """)
        self.command_icon = ToolButton(FIF.BROOM, self.command_bar)
        self.history = ToolButton(FIF.HISTORY, self.command_bar)
        # Add bash wrap toggle button
        # Add bash wrap toggle button
        self.bash_wrap_button = ToolButton(
            self.command_bar)  # Icon will be set manually
        self.bash_wrap_button.setCheckable(True)
        self.bash_wrap_button.setToolTip(
            self.tr("Toggle `bash -c` wrapper for commands"))
        self.bash_wrap_enabled = False

        # Create and cache icons
        self.icon_bash_disabled = self._create_bash_wrap_icon(
            enabled=False)
        self.icon_bash_enabled = self._create_bash_wrap_icon(enabled=True)
        self.bash_wrap_button.setIcon(self.icon_bash_disabled)

        self.bash_wrap_button.toggled.connect(self._on_bash_wrap_toggled)

        self.command_input = CommandInput(font_name, use_ai, self.command_bar)

        self.command_input.setObjectName("command_input")
        self.command_input.setPlaceholderText(
            self.tr("Shift+Enter for new line. Enter Alt to show history command."))
        # self.command_input.setFixedHeight(32) # Remove fixed height
        self.command_input.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff)
        self.command_input.textChanged.connect(self.adjust_input_height)
        self.command_input.executeCommand.connect(self.send_command_to_ssh)
        self.command_input.clear_history_.connect(self._clear_history)
        self.command_input.setStyleSheet("""
            CommandInput#command_input {
                background-color: transparent;
                border: none;
                color: %s;
                font-size: 14px;
                padding-left: 5px;
            }
        """ % config["ssh_widget_text_color"])
        self.command_input.add_history(
            session_manager.get_session_by_name(self.parentkey).history)
        self.command_icon.clicked.connect(self.ssh_widget.clear_screen)
        self.history.clicked.connect(self.command_input.toggle_history)
        command_bar_layout.addWidget(self.status_icon)
        command_bar_layout.addWidget(self.command_icon)
        command_bar_layout.addWidget(self.bash_wrap_button)
        command_bar_layout.addWidget(self.history)
        command_bar_layout.addWidget(self.command_input)

        top_container_layout.addWidget(self.ssh_widget)
        top_container_layout.addWidget(self.monitorbar)
        top_container_layout.addWidget(self.command_bar)
        self.adjust_input_height()

        # file_manage
        self.file_manage = QWidget(self.rsplitter)
        self.file_manage.setObjectName("file_manage")
        self.file_manage.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )

        file_manage_layout = QVBoxLayout(self.file_manage)
        file_manage_layout.setContentsMargins(0, 0, 0, 0)
        file_manage_layout.setSpacing(0)

        # file_bar
        self.file_bar = File_Navigation_Bar(self.file_manage)
        self.file_bar.bar_path_changed.connect(self._set_file_bar)
        self.file_bar.setObjectName("file_bar")
        self.file_bar.setFixedHeight(45)
        self.file_bar.setStyleSheet("""
            QFrame#file_bar {
                background-color: rgba(240, 240, 240, 0.8);
                border-bottom: 1px solid rgba(0,0,0,0.1);
                border-radius: 6px 6px 0 0;
            }
        """)
        self.file_splitter = QSplitter(Qt.Horizontal, self.file_manage)
        # disk_storage
        self.disk_storage = FileTreeWidget(self.file_splitter)
        self.disk_storage.directory_selected.connect(self._set_file_bar)
        self.disk_storage.setObjectName("disk_storage")
        self.disk_storage.setMinimumHeight(80)
        self.disk_storage.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred)
        # self.disk_storage.directory_selected.connect(self._set_file_bar)
        self.disk_storage.setStyleSheet("""
            QFrame#disk_storage {
                background-color: rgba(220, 220, 220, 0.06);
                border: 1px solid rgba(0,0,0,0.06);
                border-radius: 6px;
            }
        """)

        # self.disk_storage.setSizePolicy(
        #     QSizePolicy.Expanding, QSizePolicy.Preferred)
        # file_explorer
        self.file_explorer = FileExplorer(
            self.file_splitter)
        self.file_splitter.setSizes([200, 800])

        def connect_file_explorer():
            # self.file_explorer.upload_file.connect(
            #     lambda source_path, _: self.show_file_action("upload", source_path))
            default_view = config.get("default_view", "icon")
            self.file_explorer.switch_view(default_view)
            self.file_explorer.selected.connect(self._process_selected_path)
            self.file_explorer.refresh_action.connect(
                self._update_file_explorer)
            self.file_bar.refresh_clicked.connect(self._update_file_explorer)
            self.file_bar.new_folder_clicked.connect(
                self.file_explorer._handle_mkdir)
            self.file_bar.view_switch_clicked.connect(self._switch_view_mode)
            self.file_bar.internal_editor_toggled.connect(
                self._on_internal_editor_toggled)

            self.file_bar.upload_mode_toggled.connect(
                self._on_upload_mode_toggled)
            self.file_explorer.upload_mode_switch.toggled.connect(
                self.file_bar.update_upload_mode_button)
            # init button state
            is_compress_upload = CONFIGER.read_config()["compress_upload"]
            self.file_bar.update_upload_mode_button(is_compress_upload)
            self.file_explorer.upload_mode_switch.setChecked(
                is_compress_upload)

            self.file_bar.update_view_switch_button(
                self.file_explorer.view_mode)
            self.file_bar.pivot.currentItemChanged.connect(
                self._change_file_or_net)

        connect_file_explorer()
        self.task_detaile = ProcessMonitor()
        self.net_monitor = NetProcessMonitor()
        # scripts book
        self.command_script_widget = CommandScriptWidget(self.file_splitter)
        self.command_script_widget.scriptExecuteRequested.connect(
            lambda s: self.send_command_to_ssh(s))
        self.command_script_widget.setObjectName("command_script")

        self.diff_widget = DiffViewerWidget(self.file_manage)
        self.diff_widget.setObjectName("diff_widget")

        self.file_explorer.dataRefreshed.connect(
            lambda: self.stop_loading_animation("file_explorer"))
        self.net_monitor.dataRefreshed.connect(
            lambda: self.stop_loading_animation("net"))
        self.task_detaile.dataRefreshed.connect(
            lambda: self.stop_loading_animation("task"))

        self.task_detaile.kill_process.connect(self._kill_process)
        self.net_monitor.kill_process.connect(self._kill_process)
        file_manage_layout.addWidget(self.file_bar)
        self.net_monitor.hide()
        file_manage_layout.addWidget(self.net_monitor)
        self.task_detaile.hide()
        file_manage_layout.addWidget(self.task_detaile)
        self.command_script_widget.hide()
        file_manage_layout.addWidget(self.command_script_widget)
        self.diff_widget.hide()
        file_manage_layout.addWidget(self.diff_widget)
        self.now_ui = "file_explorer"
        file_manage_layout.addWidget(self.file_splitter, 1)

        rightLayout.addWidget(self.rsplitter)

        # Left Right splitter
        self.splitter_lr = QSplitter(Qt.Horizontal, self)
        self.splitter_lr.setObjectName("splitter_lr_ratio")
        self.splitter_lr.addWidget(leftContainer)
        self.splitter_lr.addWidget(rightContainer)
        self.mainLayout.addWidget(self.splitter_lr)

        self.rsplitter.setStretchFactor(0, 3)   # top_container
        self.rsplitter.setStretchFactor(1, 2)   # file_manage

        self.splitter_lr.setStretchFactor(0, 25)  # 左侧面板
        self.splitter_lr.setStretchFactor(1, 75)  # 右侧主区
        self.splitter_lr.splitterMoved.connect(self.on_splitter_moved)
        # ---- Debounce terminal resize on splitter move ----
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(50)  # 150ms delay
        self.resize_timer.timeout.connect(self.ssh_widget.fit_terminal)
        self.rsplitter.splitterMoved.connect(self.on_splitter_moved)
        self.rsplitter.splitterMoved.connect(self.resize_timer.start)

        QTimer.singleShot(150, self.force_set_left_panel_width)

        splitter_tb_ratio = config.get("splitter_tb_ratio", [0.7, 0.3])
        if len(splitter_tb_ratio) == 2:
            QTimer.singleShot(100, lambda: self._restore_splitter_sizes(
                self.rsplitter, splitter_tb_ratio))

        # Apply theme color to splitter on initialization
        theme_color_info = config.get("bg_theme_color")
        if theme_color_info:
            initial_color = theme_color_info
        else:
            initial_color = '#cccccc'
        self.update_splitter_color('#cccccc')

    def start_loading_animation(self, key: str):
        if key not in self.file_bar.pivot.items:
            return
        button = self.file_bar.pivot.items[key]
        if key in self.loading_animations:
            self.stop_loading_animation(key, force_immediate=True)
        original_style = button.styleSheet()
        gradient_color1 = generate_beautiful_color()
        gradient_color1.setAlpha(180)
        gradient_color2 = generate_beautiful_color()
        gradient_color2.setAlpha(180)

        class GradientHelper(QWidget):
            def __init__(self, widget, original_style, color1, color2):
                super().__init__()
                self.widget = widget
                self.original_style = original_style
                self.color1 = color1
                self.color2 = color2
                self._offset = -0.6

            @pyqtProperty(float)
            def offset(self):
                return self._offset

            @offset.setter
            def offset(self, value):
                self._offset = value
                total_width = 0.6
                solid_width = 0.2
                fade_width = (total_width - solid_width) / 1.5
                p1, p2, p3, p4 = (self._offset, self._offset + fade_width,
                                  self._offset + fade_width + solid_width,
                                  self._offset + fade_width * 2 + solid_width)
                stops = [max(0, min(1, p)) for p in [p1, p2, p3, p4]]
                if stops[0] >= 1 or stops[3] <= 0:
                    return
                gradient_str = (
                    f"qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                    f"stop: {stops[0]} transparent, "
                    f"stop: {stops[1]} {self.color1.name(QColor.HexArgb)}, "
                    f"stop: {stops[2]} {self.color2.name(QColor.HexArgb)}, "
                    f"stop: {stops[3]} transparent)"
                )
                self.widget.setStyleSheet(
                    f"background: {gradient_str}; {self.original_style}"
                )
        helper = GradientHelper(
            button, original_style, gradient_color1, gradient_color2)
        animation = QPropertyAnimation(helper, b'offset', self)
        animation.setDuration(1200)
        animation.setStartValue(-0.6)
        animation.setEndValue(1.6)
        animation.setEasingCurve(QEasingCurve.Linear)
        animation.setLoopCount(-1)
        self.loading_animations[key] = (animation, original_style, helper)
        self.animation_start_times[key] = time.time()
        animation.start()

    def stop_loading_animation(self, key: str, force_immediate=False):
        if key not in self.loading_animations:
            return
        animation_to_stop, original_style, helper = self.loading_animations[key]
        button = helper.widget
        start_time = self.animation_start_times.get(key, 0)
        elapsed = time.time() - start_time
        min_duration = 1.8

        def cleanup():
            current_animation_tuple = self.loading_animations.get(key)
            if current_animation_tuple and current_animation_tuple[0] == animation_to_stop:
                animation_to_stop.stop()
                button.setStyleSheet(original_style)
                del self.loading_animations[key]
                if key in self.animation_start_times:
                    del self.animation_start_times[key]
        if force_immediate or elapsed >= min_duration:
            cleanup()
        else:
            remaining_time = (min_duration - elapsed) * 1000
            QTimer.singleShot(int(remaining_time), cleanup)

    def _kill_process(self, pid: int):
        if self.file_manager:
            self.file_manager.kill_process(pid)

    def update_splitter_color(self, color_hex: str):
        """Updates the color of all splitter handles."""
        try:
            # Create a slightly darker color for hover effect
            base_color = QColor(color_hex)
            hover_color = base_color.darker(120).name()

            vertical_stylesheet = f"""
                QSplitter::handle:vertical {{
                    background-color: {color_hex};
                    height: 1px;
                    margin: 0px;
                }}
                QSplitter::handle:vertical:hover {{
                    background-color: {hover_color};
                }}
            """

            horizontal_stylesheet = f"""
                QSplitter::handle:horizontal {{
                    background-color: {color_hex};
                    width: 1px;
                    margin: 0px;
                }}
                QSplitter::handle:horizontal:hover {{
                    background-color: {hover_color};
                }}
            """
            # self.leftSplitter.setStyleSheet(vertical_stylesheet)
            self.rsplitter.setStyleSheet(vertical_stylesheet)
            self.file_splitter.setStyleSheet(horizontal_stylesheet)
        except Exception as e:
            print(f"Failed to update splitter color: {e}")
            # Fallback to default if color is invalid
            default_v_style = '''
                QSplitter::handle:vertical { background-color: #cccccc; height: 1px; margin: 0px; }
                QSplitter::handle:vertical:hover { background-color: #999999; }
            '''
            default_h_style = '''
                QSplitter::handle:horizontal { background-color: #cccccc; width: 1px; margin: 0px; }
                QSplitter::handle:horizontal:hover { background-color: #999999; }
            '''
            self.leftSplitter.setStyleSheet(default_v_style)
            self.rsplitter.setStyleSheet(default_v_style)
            self.file_splitter.setStyleSheet(default_h_style)

    def _on_transfer_expansion_changed(self, expanded, left_layout, left_splitter):
        if expanded:
            left_layout.setStretch(0, 2)
            left_layout.setStretch(1, 1)
        else:
            left_layout.setStretch(0, 1)
            left_layout.setStretch(1, 0)

    def on_splitter_moved(self, pos, index):
        splitter = self.sender()
        obj_name = splitter.objectName()
        sizes = splitter.sizes()

        # For the left-right splitter, save fixed width of the left panel
        if obj_name == "splitter_lr_ratio":
            # Ensure width is valid
            if sizes and len(sizes) > 1 and sizes[0] > 10:
                CONFIGER.revise_config("splitter_lr_left_width", sizes[0])
        # For other splitters, save ratios as before
        else:
            total = sum(sizes)
            if total > 0:
                ratios = [s/total for s in sizes]
                # print(f"移动: {obj_name}, 比例: {ratios}")
                CONFIGER.revise_config(f"{obj_name}", ratios)

    def _change_file_or_net(self, router):
        self.net_monitor.hide()
        self.task_detaile.hide()
        self.file_splitter.hide()
        self.command_script_widget.hide()
        self.diff_widget.hide()
        self.file_bar.pivot.items["diff"].hide()

        if router == "file_explorer" and self.now_ui != "file_explorer":
            self.file_splitter.show()
            self.now_ui = "file_explorer"
        elif router == "net" and self.now_ui != "net":
            self.net_monitor.show()
            self.now_ui = "net"
        elif router == "task" and self.now_ui != "task":
            self.task_detaile.show()
            self.now_ui = "task"
        elif router == "command" and self.now_ui != "command":
            self.command_script_widget.show()
            self.now_ui = "command"
        elif router == "diff" and self.now_ui != "diff":
            self.diff_widget.show()
            self.now_ui = "diff"

    def _clear_history(self):
        session_manager.clear_history(self.parentkey)

    def _on_upload_mode_toggled(self, checked):
        CONFIGER.revise_config("compress_upload", checked)
        self.file_explorer.upload_mode_switch.setChecked(checked)

    def adjust_input_height(self):
        doc = self.command_input.document()
        # Get the required height from the document's layout
        content_height = int(doc.size().height())

        # The document margin is the internal padding of the TextEdit
        margin = int(self.command_input.document().documentMargin()) * 2

        # Calculate the total required height
        required_height = content_height + margin

        # Define min/max heights
        font_metrics = self.command_input.fontMetrics()
        line_height = font_metrics.lineSpacing()
        # Min height for at least one line
        min_height = line_height + margin
        # Max height for 5 lines
        max_height = (line_height * 5) + margin + \
            5  # A bit of extra padding for max

        # Clamp the final height
        final_height = min(max(required_height, min_height), max_height)

        # Update the heights of the input and its container
        self.command_input.setFixedHeight(final_height)
        self.command_bar.setFixedHeight(
            final_height + 10)  # 10 for container's padding

    def send_command_to_ssh(self, command):
        if self.ssh_widget and command:
            if self.bash_wrap_enabled:
                # Escape double quotes in the command
                escaped_command = command.replace('"', '\\"')
                final_command = f'bash -c "{escaped_command}"\n'
            else:
                final_command = command + '\n'
            self.ssh_widget.send_command(final_command)
            session_manager.add_command_to_session(
                self.parentkey, final_command)

    def _on_bash_wrap_toggled(self, checked):
        self.bash_wrap_enabled = checked
        if checked:
            self.bash_wrap_button.setIcon(self.icon_bash_enabled)
        else:
            self.bash_wrap_button.setIcon(self.icon_bash_disabled)

    def _create_bash_wrap_icon(self, enabled: bool) -> QIcon:
        """Draws a custom icon with a checkmark overlay if enabled."""
        # Use a fixed size for consistency
        size = QSize(20, 20)

        # Create base icon from FluentIcon
        base_icon = Action(FIF.COMMAND_PROMPT, '', self.command_bar).icon()
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw base icon centered
        base_pixmap = base_icon.pixmap(size)
        painter.drawPixmap(0, 0, base_pixmap)

        if enabled:
            # Draw checkmark in the bottom-right corner
            pen = QPen(QColor("#00E676"), 2.5)  # A vibrant green, thicker
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)

            w, h = size.width(), size.height()
            path = QPainterPath()
            path.moveTo(w * 0.50, h * 0.65)
            path.lineTo(w * 0.70, h * 0.85)
            path.lineTo(w * 1.0, h * 0.55)
            painter.drawPath(path)

        painter.end()
        return QIcon(pixmap)

    def _switch_view_mode(self):
        if self.file_explorer.view_mode == "icon":
            new_mode = "details"
        else:
            new_mode = "icon"
        self.file_explorer.switch_view(new_mode)
        self.file_bar.update_view_switch_button(new_mode)

    def _on_internal_editor_toggled(self, checked: bool):
        # This is where the logic to enable/disable the internal editor will go.
        # For now, we can just print a message.
        print(f"Internal editor mode toggled: {'On' if checked else 'Off'}")

    def _process_selected_path(self, path_dict: dict):
        # print(f"选中了: {path_dict}")
        name = next(iter(path_dict.keys()))
        is_dir = next(iter(path_dict.values()))
        if name == '..':
            #
            current_path = self.file_explorer.path
            if current_path and current_path != '/':
                new_path = '/'.join(current_path.split('/')[:-1])
                if not new_path:
                    new_path = '/'
                self._set_file_bar(new_path)
            return

        new_path = self.file_explorer.path + "/" + name
        if is_dir:
            self._set_file_bar(new_path)
        else:
            if self.file_manager:
                print(f"get file type for: {new_path}")
                self.file_manager.get_file_type(new_path)

    def _update_file_explorer(self, path: str = None):
        if path:
            self.file_explorer.path = path
        else:
            path = self.file_explorer.path  # Refresh the original directory

        if not self.file_manager:
            parent = self.parent()
            while parent:
                if hasattr(parent, 'file_tree_object'):
                    # Pass the correct parameter: route_key, not parent
                    self.file_manager = parent.file_tree_object[self.router]
                    break
                parent = parent.parent()
            self.file_manager.list_dir_finished.connect(
                self._on_list_dir_finished, type=Qt.QueuedConnection)
        if self.file_manager:
            # print(f"添加：{path} 到任务")
            self.start_loading_animation("file_explorer")
            self.file_manager.list_dir_async(path)

    def _on_list_dir_finished(self, path: str, file_dict: dict):
        # if path != self.file_explorer.path:
        #     return

        try:
            self.file_explorer.add_files(file_dict)
            if hasattr(self, '_perf_counter_start') and self._perf_counter_start:
                end_time = time.perf_counter()
                total_duration = end_time - self._perf_counter_start
                print(f"从点击到渲染完成总耗时: {total_duration:.4f} 秒")
                self._perf_counter_start = None  # Reset timer
            # self.file_manager._add_path_to_tree(path, False)
            # file_tree = self.file_manager.get_file_tree()
            # self.disk_storage.refresh_tree(file_tree)
        except Exception as e:
            print(f"_on_list_dir_finished error: {e}")

    def _set_file_bar(self, path: str):
        self._perf_counter_start = time.perf_counter()

        def parse_linux_path(path: str) -> list:
            if not path:
                return []
            path_list = []
            if path.startswith('/'):
                path_list.append('/')
            parts = [p for p in path.strip('/').split('/') if p]
            path_list.extend(parts)
            return path_list

        path_list = parse_linux_path(path)

        # BLOCK signals while rebuilding breadcrumb to avoid multiple refreshes
        try:
            self.file_bar.breadcrumbBar.blockSignals(True)
        except Exception:
            pass

        self.file_bar.set_path(path)
        self.file_bar.breadcrumbBar.clear()
        for p in path_list:
            self.file_bar.breadcrumbBar.addItem(p, p)

        try:
            self.file_bar.breadcrumbBar.blockSignals(False)
        except Exception:
            pass

        self.file_bar._hide_path_edit()

        # ensure explorer.path updated and only refresh once
        self.file_explorer.path = path
        if mode == 0:
            self.ssh_widget.bridge.current_directory = path
        # explicitly request one refresh
        self._update_file_explorer(path)

    def on_main_window_resized(self):
        # A simple way to trigger the debounced resize
        self.resize_timer.start()

    def _sys_info_dialog(self):
        if self.sys_info_msg:
            dialog = SystemInfoDialog(
                self.tr("System Information"), self.sys_info_msg, self)
            dialog.exec()
        else:
            dialog = SystemInfoDialog(self.tr("System Information"), "", self)
            dialog.exec()

    def cleanup(self):
        for key in list(self.loading_animations.keys()):
            self.stop_loading_animation(key, force_immediate=True)

        self.ssh_widget.cleanup()
        try:
            self.ssh_widget.directoryChanged.disconnect()
            self.disk_storage.directory_selected.disconnect()
        except Exception:
            pass
        try:
            self.command_input.textChanged.disconnect()
            self.command_input.executeCommand.disconnect()
        except Exception:
            pass

        for container in [getattr(self, 'ssh_widget', None),
                          getattr(self, 'command_bar', None),
                          getattr(self, 'sys_resources', None),
                          getattr(self, 'task', None),
                          getattr(self, 'disk_storage', None),
                          getattr(self, 'transfer_progress', None),
                          getattr(self, 'file_manage', None),
                          getattr(self, 'file_bar', None),
                          getattr(self, 'file_explorer', None)]:
            if container:
                container.setParent(None)
                container.deleteLater()

        if hasattr(self, 'mainLayout'):
            while self.mainLayout.count():
                item = self.mainLayout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.setParent(None)
                    widget.deleteLater()

        parent_layout = self.parentWidget().layout() if self.parentWidget() else None
        if parent_layout:
            parent_layout.removeWidget(self)
        self.setParent(None)
        self.deleteLater()

    def _restore_splitter_sizes(self, splitter, ratios):
        if splitter.orientation() == Qt.Horizontal:
            total_size = splitter.width()
        else:
            total_size = splitter.height()

        if total_size > 0:
            sizes = [int(r * total_size) for r in ratios]
            splitter.setSizes(sizes)

    def force_set_left_panel_width(self):
        """
        Reads the absolute width for the left panel from config and applies it.
        This ensures the left panel width is maintained during parent resizes.
        """
        config = CONFIGER.read_config()
        left_width = config.get("splitter_lr_left_width", 300)
        total_width = self.splitter_lr.width()
        if total_width > left_width:
            right_width = total_width - left_width
            self.splitter_lr.blockSignals(True)
            self.splitter_lr.setSizes([left_width, right_width])
            self.splitter_lr.blockSignals(False)

    def execute_command_and_capture(self, command: str):
        if self.ssh_widget:
            self.ssh_widget.execute_command_and_capture(command)

    def keyPressEvent(self, event):
        # Alt 切换历史
        if event.key() == Qt.Key_Alt:
            self.command_input.toggle_history()
            return
        super().keyPressEvent(event)
