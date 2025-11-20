# coding:utf-8
from pathlib import Path
import sys

import time
from PyQt5.QtCore import Qt, QTranslator, QTimer, QLocale, QUrl, QEvent, pyqtSignal
from PyQt5.QtGui import QPixmap, QPainter, QDesktopServices, QIcon
from PyQt5.QtWidgets import QApplication, QStackedWidget, QHBoxLayout, QWidget, QMessageBox, QSplitter, QLabel
from widgets.editor_widget import EditorWidget
from qfluentwidgets import (NavigationInterface,  NavigationItemPosition, InfoBar,
                            isDarkTheme, setTheme, Theme, InfoBarPosition, FluentIcon as FIF, FluentTranslator, IconWidget, NavigationAvatarWidget, MessageBoxBase, SubtitleLabel, CheckBox, Dialog)
from tools.animation_manager import PageTransitionAnimator
from qfluentwidgets.common.config import qconfig
from qframelesswindow import FramelessWindow, StandardTitleBar
from widgets.setting_page import SettingPage
from widgets.home_interface import MainInterface
from tools.font_config import font_config
from tools.session_manager import SessionManager
from tools.logger import setup_global_logging, main_logger
from tools.ssh import SSHWorker
from tools.remote_file_manage import RemoteFileManager, FileManagerHandler
from widgets.sync_widget import SycnWidget
import os
import shutil
import subprocess
from tools.atool import resource_path
from tools.setting_config import SCM
from widgets.ssh_widget import SSHPage, SSHWidget
from tools.icons import My_Icons
from functools import partial
from tools.watching_saved import FileWatchThread
from widgets.side_panel import SidePanelWidget, AutoFitImageLabel
from widgets.expander_bar import ExpanderBar
import magic
import traceback
from tools.check_update import CheckUpdate, get_version
import sys
import os
import pyperclip as cb
import psutil
from widgets.session_dialog import PasswordDialog
import re
from widgets.account_widget import AccountPage
try:
    import ctypes
except:
    ctypes = None

try:
    import pyi_splash
except ImportError:
    pyi_splash = None
font_ = font_config()
setting_ = SCM()
mime_types = [
    "text/plain",
    "text/html",
    "text/css",
    "text/javascript",
    "application/json",
    "application/xml",
    "application/x-empty"
]


def setup_webengine_environment():
    """设置WebEngine运行环境"""

    # 设置必要的环境变量
    env_vars = {
        "QT_PLUGIN_PATH": "/usr/lib/x86_64-linux-gnu/qt5/plugins",
        "QT_QPA_PLATFORM_PLUGIN_PATH": "/usr/lib/x86_64-linux-gnu/qt5/plugins/platforms",
        "QT_QPA_PLATFORM": "xcb",
        "QTWEBENGINE_CHROMIUM_FLAGS": "--no-sandbox --disable-gpu"
    }

    for key, value in env_vars.items():
        os.environ[key] = value

    # 检查并安装最小依赖
    try:
        # 检查是否已安装必要的系统包
        check_cmd = "dpkg -l | grep -E 'libqt5webengine5|python3-pyqt5.qtwebengine'"
        result = subprocess.run(check_cmd, shell=True,
                                capture_output=True, text=True)

        if not result.stdout.strip():
            print("安装必要的WebEngine依赖...")
            subprocess.run(
                "sudo apt-get install -y python3-pyqt5.qtwebengine libqt5webengine5",
                shell=True,
                check=True
            )

    except subprocess.CalledProcessError:
        print("WebEngine依赖安装失败，某些功能可能不可用")
    except Exception:
        pass

    print("WebEngine环境设置完成")


def isDebugMode():
    """Check if the application is running under a debugger."""
    # return True
    return sys.gettrace() is not None


class PermissionDialog(MessageBoxBase):
    def __init__(self, file_name: str, permission_num: int = None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.titleLabel = SubtitleLabel(file_name)
        self.yesButton.setText(self.tr("Apply"))
        self.cancelButton.setText(self.tr("Cancel"))

        # Owner permissions
        owner_group = QHBoxLayout()
        owner_group.addWidget(QLabel(self.tr("Owner: ")))
        self.owner_read = CheckBox(self.tr("Read"))
        self.owner_write = CheckBox(self.tr("Write"))
        self.owner_exec = CheckBox(self.tr("Execute"))

        owner_group.addWidget(self.owner_read)
        owner_group.addWidget(self.owner_write)
        owner_group.addWidget(self.owner_exec)

        # Group permissions
        group = QHBoxLayout()
        group.addWidget(QLabel(self.tr("Group: ")))
        self.group_read = CheckBox(self.tr("Read"))
        self.group_write = CheckBox(self.tr("Write"))
        self.group_exec = CheckBox(self.tr("Execute"))

        group.addWidget(self.group_read)
        group.addWidget(self.group_write)
        group.addWidget(self.group_exec)

        # Other permissions
        other = QHBoxLayout()
        other.addWidget(QLabel(self.tr("Other: ")))
        self.other_read = CheckBox(self.tr("Read"))
        self.other_write = CheckBox(self.tr("Write"))
        self.other_exec = CheckBox(self.tr("Execute"))

        other.addWidget(self.other_read)
        other.addWidget(self.other_write)
        other.addWidget(self.other_exec)

        self.permission_label = QLabel("")
        self.permission_label.setAlignment(Qt.AlignCenter)

        # Add all to layout
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addLayout(owner_group)
        self.viewLayout.addLayout(group)
        self.viewLayout.addLayout(other)
        self.viewLayout.addWidget(self.permission_label)

        self._parent = parent

        if permission_num is not None:
            self.set_permission_state(permission_num)

        self._connect_checkbox_signals()

    def set_permission_state(self, permission_num: int):

        owner_perm = (permission_num >> 6) & 0o7
        group_perm = (permission_num >> 3) & 0o7
        other_perm = permission_num & 0o7

        self.owner_read.setChecked(bool(owner_perm & 4))
        self.owner_write.setChecked(bool(owner_perm & 2))
        self.owner_exec.setChecked(bool(owner_perm & 1))

        self.group_read.setChecked(bool(group_perm & 4))
        self.group_write.setChecked(bool(group_perm & 2))
        self.group_exec.setChecked(bool(group_perm & 1))

        self.other_read.setChecked(bool(other_perm & 4))
        self.other_write.setChecked(bool(other_perm & 2))
        self.other_exec.setChecked(bool(other_perm & 1))

        self._update_permission_display()

    def get_permission_num(self) -> int:
        permission_num = 0

        if self.owner_read.isChecked():
            permission_num |= 0o400
        if self.owner_write.isChecked():
            permission_num |= 0o200
        if self.owner_exec.isChecked():
            permission_num |= 0o100

        if self.group_read.isChecked():
            permission_num |= 0o040
        if self.group_write.isChecked():
            permission_num |= 0o020
        if self.group_exec.isChecked():
            permission_num |= 0o010

        if self.other_read.isChecked():
            permission_num |= 0o004
        if self.other_write.isChecked():
            permission_num |= 0o002
        if self.other_exec.isChecked():
            permission_num |= 0o001

        return permission_num

    def _connect_checkbox_signals(self):
        checkboxes = [
            self.owner_read, self.owner_write, self.owner_exec,
            self.group_read, self.group_write, self.group_exec,
            self.other_read, self.other_write, self.other_exec
        ]

        for checkbox in checkboxes:
            checkbox.stateChanged.connect(self._update_permission_display)

    def _update_permission_display(self):
        permission_num = self.get_permission_num()

        owner_perm = (permission_num >> 6) & 0o7
        group_perm = (permission_num >> 3) & 0o7
        other_perm = permission_num & 0o7

        def to_symbol(perm):
            return f"{'r' if perm & 4 else '-'}{'w' if perm & 2 else '-'}{'x' if perm & 1 else '-'}"

        owner_symbol = to_symbol(owner_perm)
        group_symbol = to_symbol(group_perm)
        other_symbol = to_symbol(other_perm)

        display_text = self.tr(
            f"Current permissions: {owner_symbol}{group_symbol}{other_symbol} ({permission_num:03o})")
        self.permission_label.setText(display_text)

    def showEvent(self, event):
        super().showEvent(event)

        if self._parent:
            parent_geometry = self._parent.geometry()
            self.setGeometry(parent_geometry)
            self.raise_()
            self.activateWindow()


class Window(FramelessWindow):
    windowResized = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        if isDebugMode():
            os.environ['QTWEBENGINE_REMOTE_DEBUGGING'] = '3354'
            print('Debug mode enabled: http://localhost:' +
                  os.environ['QTWEBENGINE_REMOTE_DEBUGGING'])
        self.icons = My_Icons()
        self.expander_bar_width = 8
        self.active_transfers = {}
        self.watching_dogs = {}
        self.last_session_click_time = {}
        self.file_id_to_path = {}
        self._download_debounce_timer = QTimer(self)
        self._download_debounce_timer.setSingleShot(True)
        self._download_debounce_timer.setInterval(500)
        self._download_debounce_timer.timeout.connect(
            self._process_pending_downloads)
        self._pending_download_paths = {}

        self.page_animator = PageTransitionAnimator(duration=500)
        self._animation_in_progress = False

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self.apply_locked_ratio)

        self.setMinimumSize(800, 600)
        self.setTitleBar(StandardTitleBar(self))
        self._bg_ratio = None
        self.setWindowTitle("NeoSSH Beta")
        icon = QIcon(resource_path("resource/icons/icon.ico"))
        self.setWindowIcon(icon)
        QApplication.setWindowIcon(icon)
        self.titleBar.raise_()
        self.connect_status_dict = {}
        self.ssh_session = {}
        self.sessionmanager = SessionManager()
        self.session_widgets = {}
        self.file_tree_object = {}
        self._bg_opacity = 1.0
        # self.unprocessed_tasks = ["systemd","kthreadd","pool_workqueue_release","kworker/R-rcu_g"]
        self._bg_pixmap = None
        self.hBoxLayout = QHBoxLayout(self)
        self.navigationInterface = NavigationInterface(
            self, showMenuButton=True)
        self.stackWidget = QStackedWidget(self)
        try:
            self.sidePanel = SidePanelWidget(self, main_window=self)
            self.sidePanel.aichat_widget.bridge.userinfo_got.connect(
                partial(self.update_user_info, local=True))
            # self.sidePanel.aichat_widget.bridge.userinfo_got.connect(
            #     lambda name, qid: self.account_widget.update_account_info(name, qid, email=f"{qid}@qq.com", avatar_url=f'http://q.qlogo.cn/headimg_dl?dst_uin={qid}&spec=640&img_type=png'))
            self.sidePanel.tabActivity.connect(self._ensure_side_panel_visible)
        except:  # 关闭后会有报错
            pass
        # create sub interface
        self.MainInterface = MainInterface(self)
        self.MainInterface.sessionClicked.connect(self._on_session_selected)

        self.sync_widget = SycnWidget(self)
        self.sync_widget.setWindowModality(Qt.ApplicationModal)
        self.sync_widget.setWindowFlags(
            self.sync_widget.windowFlags() |
            Qt.Dialog
        )
        self.sync_widget.center_on_parent()
        self.sync_widget.sync_finished.connect(
            lambda status, msg: InfoBar.success(
                title=msg if status == "updated" or status == "created" else self.tr(
                    "Error"),
                content="",
                orient=Qt.Vertical,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=5000 if status == "updated" or status == "created" else -1,
                parent=self
            ) if status == "updated" or status == "created" else InfoBar.error(
                title=self.tr("Error"),
                content=msg,
                orient=Qt.Vertical,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=-1,
                parent=self
            )
        )
        self.sync_widget.hide()
        # self.sessions = Widget(
        #     self.tr('No conversation selected yet'), True, self)
        self.ssh_page = SSHPage()
        self.ssh_page.menuActionTriggered.connect(self._handle_action)

        self.navigationInterface.setStyleSheet("background: transparent;")
        self.navigationInterface.setCollapsible(True)
        self.stackWidget.setStyleSheet("background: transparent;")

        self.settingInterface = SettingPage(self,)
        self.settingInterface.themeChanged.connect(self._on_theme_changed)
        self.settingInterface.lock_ratio_card.checkedChanged.connect(
            self.apply_locked_ratio)
        self.settingInterface.opacityEdit.valueChanged.connect(
            self.set_background_opacity)
        self.settingInterface.themeColorChanged.connect(
            self.on_theme_color_changed)
        # Connect transparency setting signal
        # self.settingInterface.bgOpacityChanged.connect(
        #     self.set_background_opacity)
        self._on_theme_changed(
            self.settingInterface.cfg.background_color.value)
        self.init_account()
        self.initLayout()
        self.initNavigation()

        self.expanderBar = ExpanderBar(self, width=self.expander_bar_width)
        self.expanderBar.hide()
        self.expanderBar.clicked.connect(self._expand_side_panel)

        self.initWindow()
        if setting_.read_config()["maximized"]:
            self.showMaximized()
        # self.switchTo(self.MainInterface)
        self.checker = CheckUpdate()
        self.checker.start()
        if isDebugMode():
            print("\\\\ Debuger Done \\\\")

    def set_background_opacity(self, opacity: float):
        if not self._bg_pixmap:
            return

        # In the case of int, only setting is passed in
        if isinstance(opacity, int):
            opacity = opacity / 100

        self._bg_opacity = max(0.0, min(1.0, opacity))
        self.update()

    def _on_ssh_connected(self, success: bool, msg: str):
        if success:
            InfoBar.success(
                title=msg,
                content="",
                orient=Qt.Vertical,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=2000,
                parent=self
            )

    def _on_ssh_error(self, msg: str):
        InfoBar.error(
            title=self.tr("Connection failed"),
            content=self.tr(f"Error:\n{msg}\nPlease close this session"),
            orient=Qt.Vertical,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=-1,
            parent=self
        )

    def _set_usage(self, widget_key, usage):
        try:
            result = dict(usage)
            parent_key = widget_key.split("-", 1)[0].strip()
            # print(self.session_widgets)
            # print(parent_key)
            widget = self.session_widgets[widget_key]
            if widget:
                if result["type"] == "info":
                    widget.start_loading_animation("task")
                    widget.start_loading_animation("net")
                    connections = result["connections"]
                    cpu_percent = result["cpu_percent"]
                    mem_percent = result["mem_percent"]
                    mem_used = result["mem_used"]
                    # print(f'memused : {mem_used}')
                    net_usage = result["net_usage"]
                    top_processes = result["top_processes"]
                    all_processes = result["all_processes"]
                    disk_usage = result["disk_usage"]
                    uptime_seconds = result["uptime_seconds"]
                    load = result["load"]
                    upload, download = 0, 0
                    try:
                        if not widget.task.netmonitor.init_interface and net_usage:
                            interfaces = []
                            for i in net_usage:
                                name = i.get("iface")
                                if name and name not in interfaces:  # 去重
                                    interfaces.append(name)

                            if interfaces:
                                success = widget.task.netmonitor.initialize_interfaces(
                                    interfaces)
                                if success:
                                    widget.task.netmonitor.init_interface = True
                                    print(f"初始化网卡成功: {interfaces}")

                        if net_usage:
                            current_interface = widget.task.netmonitor.interface_combo.currentText()

                            target_dict = next((item for item in net_usage if item.get(
                                'iface') == current_interface), None)

                            if target_dict:
                                upload = target_dict.get("tx_kbps", 0)
                                download = target_dict.get("rx_kbps", 0)
                                widget.task.netmonitor.update_speed(
                                    upload, download, current_interface)
                            else:
                                # 如果找不到当前网卡数据，使用第一个网卡的数据
                                if net_usage:
                                    first_interface = net_usage[0].get('iface')
                                    if first_interface:
                                        widget.task.netmonitor.interface_combo.setCurrentText(
                                            first_interface)
                                        upload = net_usage[0].get("tx_kbps", 0)
                                        download = net_usage[0].get(
                                            "rx_kbps", 0)
                                        widget.task.netmonitor.update_speed(
                                            upload, download, first_interface)
                    except:
                        pass

                    # widget.sys_resources.set_progress("cpu", cpu_percent)
                    # widget.sys_resources.set_progress("ram", mem_percent)
                    # print(mem_percent)
                    for processes in top_processes:
                        processes_cpu_percent = processes["cpu"]
                        processes_name = processes["name"]
                        processes_mem = processes["mem_mb"]
                        widget.task.add_row(
                            f"{processes_mem:.1f}",
                            f"{processes_cpu_percent:.1f}",
                            processes_name
                        )
                    if connections:
                        widget.net_monitor.updateProcessData(connections)
                        # print(processes_cpu_percent, processes_name, processes_mem)
                    if all_processes:
                        widget.task_detaile.updateProcessData(all_processes)
                    if disk_usage:
                        for disk in disk_usage:
                            # print(disk)
                            device = disk.get("device", "")
                            mount = disk.get("mount", "")
                            # 唯一ID
                            disk_id = f"{device}:{mount}"

                            widget.disk_usage.update_disk_item(disk_id, {
                                "device": device,
                                "mount": mount,
                                "used_percent": disk.get("used_percent"),
                                "size_kb": disk.get("size_kb"),
                                "used_kb": disk.get("used_kb"),
                                "avail_kb": disk.get("avail_kb"),
                                "read_kbps": disk.get("read_kbps"),
                                "write_kbps": disk.get("write_kbps"),
                            })

                    widget.stop_loading_animation("task")
                    widget.stop_loading_animation("net")
                    disk_usage = 0
                    if disk_usage:
                        disk_usage[0].get("used_percent", None)
                    metrics = {
                        "uptime_seconds": uptime_seconds,
                        "load": load,
                        "cpu_percent": cpu_percent,
                        "ram_percent": mem_percent,
                        "ram_used_mb": mem_used,
                        "disk_percent": disk_usage,
                        "net_up_kbps": upload,
                        "net_down_kbps": download,
                    }
                    widget.monitorbar.update_metrics(metrics)

                elif result["type"] == "sysinfo":
                    print("Got SysInfo:", result)
                    sys_info = f'''
                    System : {result["system"]} kernel {result["kernel"]}
                    Arch : {result["arch"]}
                    Host name : {result["hostname"]}
                    CPU : {result["cpu_model"]} with {result["cpu_cores"]} cores
                    Freq : {result["cpu_freq"]} Cache : {result["cpu_cache"]}
                    Memory : {result["mem_total"]}
                    Host IP : {result["ip"]}
                    '''
                    widget.sys_info_msg = sys_info
            else:
                print("Failed to obtain the SSH Widget")
        except Exception as e:
            print(e)

    def _show_info(self, path: str = None, status: bool = None, msg: str = None, type_: str = None, widget_key: str = None, local_path: str = None, open_it: bool = False):
        no_refresh_types = ["download",
                            "start_upload", "start_download", "info"]
       #  print(f"showinfo : {type_} {widget_key}")
        duration = 3000
        session_widget = self.session_widgets[widget_key]
        if not session_widget:
            return
        title = ""
        if type_ == "upload":
            paths = path if isinstance(path, list) else [path]
            for p in paths:
                # The 'path' from the finished signal is the unique identifier
                file_id = self.active_transfers.get(p, {}).get("id")
                if not file_id:
                    # Fallback for safety, though it should exist
                    file_id = f"{widget_key}_{p}_{time.time()}"

                if status:
                    if p not in self.active_transfers:
                        # This can happen if the file is very small and finishes
                        # before any progress signal is emitted.
                        self._add_transfer_item_if_not_exists(
                            widget_key, p, "upload")
                        file_id = self.active_transfers[p]["id"]

                    if p in self.active_transfers:
                        self.active_transfers[p]['type'] = 'completed'
                        self.active_transfers[p]['progress'] = 100

                    data = {"type": "completed", "progress": 100}
                    session_widget.transfer_progress.update_transfer_item(
                        file_id, data)
                    title = self.tr(f"Upload {p} completed")
                    duration = 2000
                else:
                    title = f"Uoload {p} failure"
                    duration = -1
                    if p in self.active_transfers:
                        session_widget.transfer_progress.remove_transfer_item(
                            self.active_transfers[p]["id"])
                        del self.active_transfers[p]

        elif type_ == "start_upload":
            # This is now handled by _add_transfer_item_if_not_exists
            # It will be called from _handle_files for single files/compressed,
            # or dynamically from progress/finished signals for expanded dirs.
            pass

        elif type_ == "start_download":
            paths = path if isinstance(path, list) else [path]
            for p in paths:
                file_id = f"{widget_key}_{os.path.basename(p)}_{time.time()}"
                data = {
                    "type": "download",
                    "filename": os.path.basename(p),
                    "progress": 0
                }
                self.active_transfers[file_id] = data
                session_widget.transfer_progress.add_transfer_item(
                    file_id, data)

        elif type_ == "download":
            # 'path' is the unique remote path identifier
            if path in self.active_transfers:
                file_id = self.active_transfers[path]["id"]
                if status:
                    self.active_transfers[path]['type'] = 'completed'
                    self.active_transfers[path]['progress'] = 100
                    data = {"type": "completed", "progress": 100}
                    session_widget.transfer_progress.update_transfer_item(
                        file_id, data)

                    if open_it and local_path:
                        try:
                            print(f"From Remote Path : {path}")
                            self._open_downloaded_file(
                                local_path, widget_key, path)
                        except Exception as e:
                            print(f"Error opening file/folder: {e}")
                else:
                    session_widget.transfer_progress.remove_transfer_item(
                        file_id)
                    del self.active_transfers[path]
            elif status:  # Finished signal for a small file that sent no progress
                self._add_transfer_item_if_not_exists(
                    widget_key, path, "download", open_it=open_it)
                if path in self.active_transfers:
                    file_id = self.active_transfers[path]["id"]
                    self.active_transfers[path]['type'] = 'completed'
                    self.active_transfers[path]['progress'] = 100
                    data = {"type": "completed", "progress": 100}
                    session_widget.transfer_progress.update_transfer_item(
                        file_id, data)

        else:
            duration = 5000
            title = ""
            if type_ in ("compression", "uncompression"):
                title = self.tr(f"Start to {type_} : {path}")
                msg = ""
            elif type_ == "delete":
                print("delete showinfo")
                if status:
                    title = self.tr(f"Deleted {path} successfully")
                else:
                    title = self.tr(f"Failed to delete {path}\n{msg}")
                    duration = -1
            elif type_ == "paste":
                if status:
                    title = self.tr("Paste Successful")
                    msg = self.tr(f"Pasted {path} to {local_path}")
                else:
                    title = self.tr("Paste Failed")
                    duration = -1
            elif type_ == "rename":
                if status:
                    title = self.tr("Rename Successful")
                    msg = self.tr(f"Renamed {path} to {local_path}")
                else:
                    title = self.tr("Rename Failed")
                    duration = -1
            elif type_ == "mkdir":
                if status:
                    title = self.tr(f"Created directory {path} successfully")
                else:
                    title = self.tr(
                        f"Failed to create directory {path}\n{msg}")
                    duration = -1
            elif type_ == "mkfile":
                if status:
                    title = self.tr(f"Created file {path} successfully")
                else:
                    title = self.tr(
                        f"Failed to create file {path}\n{msg}")
                    duration = -1
            elif type_ == "kill":
                if status:
                    title = self.tr(f"Kill process of pid {path}")
                    duration = 2000
                else:
                    title = self.tr(f"Kill process of pid {path} failed")
                    duration = -1
        if title:
            InfoBar.info(
                title=title,
                content=msg,
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT,
                duration=duration,
                parent=self.window()
            )

        if type_ not in no_refresh_types and widget_key:
            self._refresh_paths(widget_key)
            print(f"刷新路径: {widget_key}")

    def _show_progresses(self, path, percentage, bytes_so_far, total_bytes, widget_key, transfer_type):
        """Handles progress updates for both uploads and downloads."""
        session_widget = self.session_widgets[widget_key]
        if not session_widget:
            return

        # 'path' is the unique identifier (local for upload, remote for download)
        if path not in self.active_transfers:
            self._add_transfer_item_if_not_exists(
                widget_key, path, transfer_type)

        if path in self.active_transfers:
            file_id = self.active_transfers[path]["id"]
            data = self.active_transfers[path]
            data["progress"] = percentage
            data["bytes_so_far"] = bytes_so_far
            data["total_bytes"] = total_bytes
            if percentage >= 100:
                data["type"] = "completed"
            session_widget.transfer_progress.update_transfer_item(
                file_id, data)

    def update_user_info(self, name, qid, local=True):
        config = configer.read_config()
        if config["account"]["apikey"]:
            return  # apikey exists, do not modify account info
        noneed_change = False

        if local:
            name = self.tr(f"{name} (Local)")

            if "account" not in config:
                config["account"] = {}

            account_config = config["account"]

            expected_values = {
                "user": name,
                "qid": qid,
                "email": f"{qid}@qq.com",
                "avatar_url": f'http://q.qlogo.cn/headimg_dl?dst_uin={qid}&spec=640&img_type=png'
            }

            updates = {
                key: value for key, value in expected_values.items()
                if account_config.get(key) != value
            }

            if not updates:
                noneed_change = True
            else:
                account_config.update(updates)
                config["account"] = account_config
                configer.write_config(config)

        if not noneed_change:
            self.account_widget.update_account_info(
                username=name,
                qid=qid,
                email=f"{qid}@qq.com",
                avatar_url=f'http://q.qlogo.cn/headimg_dl?dst_uin={qid}&spec=640&img_type=png'
            )

    def _open_downloaded_file(self, local_path: str, widget_key: str, remote_path: str):
        """打开下载的文件"""
        config = setting_.read_config()
        external_editor = config.get("external_editor", "")
        open_mode = config.get("open_mode", False)
        is_text = False
        mime = None
        try:
            with open(local_path, "rb") as f:
                content = f.read(2048)
                mime = magic.from_buffer(content, mime=True)
            if mime in mime_types or mime.startswith("text/"):
                is_text = True
            elif mime == "application/octet-stream":
                try:
                    content.decode('utf-8')
                    is_text = True
                except UnicodeDecodeError:
                    try:
                        content.decode('gbk')
                        is_text = True
                    except UnicodeDecodeError:
                        is_text = False
        except Exception as e:
            print(f"Error checking file type: {e}")

        if mime.startswith("image/"):
            self.open_media_in_panel(local_path, widget_key)
            return

        if (external_editor and os.path.isfile(external_editor)) and open_mode:
            try:
                subprocess.Popen([external_editor, local_path])
            except Exception as editor_error:
                print(
                    f"Error opening with external editor: {editor_error}, fallback to internal editor")
                if is_text:
                    self._open_in_internal_editor(
                        local_path, widget_key, remote_path)
        else:
            if is_text:
                self._open_in_internal_editor(
                    local_path, widget_key, remote_path)

            else:
                print(
                    f"File {local_path} is not a text file (MIME: {mime}), cannot open in editor")

        self._start_file_watching_if_text(
            local_path, widget_key, remote_path)

    def open_media_in_panel(self, local_path: str, widget_key: str):
        if os.path.exists(local_path):
            try:
                img = AutoFitImageLabel(local_path)
                img.set_tab_id = lambda tid: setattr(img, "tab_id", tid)

                base_name = os.path.basename(local_path)
                self.sidePanel.add_new_tab(img, f"{widget_key} - {base_name}")

            except Exception as e:
                img = QLabel(str(e))
                img.setAlignment(Qt.AlignCenter)
                base_name = os.path.basename(local_path)
                self.sidePanel.add_new_tab(img, f"{widget_key} - {base_name}")

    def _open_in_internal_editor(self, local_path: str, widget_key: str, remote_path: str):
        """在内置编辑器中打开文件"""
        try:
            existing_tab_id = self.sidePanel.find_tab_by_remote_path(
                remote_path)
            if existing_tab_id:
                self.sidePanel.switch_to_tab(existing_tab_id)
                tab_info = self.sidePanel.tabs[existing_tab_id]
                editor_widget = tab_info['page']
                if isinstance(editor_widget, EditorWidget):
                    editor_widget.load_file(local_path)
            else:
                tab_title = os.path.basename(remote_path)
                tab_id = self.sidePanel.add_new_tab(EditorWidget(), f'{widget_key} - {tab_title}', {
                                                    "path": local_path, "remote_path": remote_path, "widget_key": widget_key})
        except Exception as e:
            print(f"Error opening in internal editor: {e}")
            import traceback
            traceback.print_exc()

    def _start_file_watching_if_text(self, local_path: str, widget_key: str, remote_path: str):
        """如果是文本文件，启动文件监视以便自动重新上传"""
        try:
            with open(local_path, "rb") as f:
                content = f.read(2048)
                mime = magic.from_buffer(content, mime=True)
            is_text = False
            if mime in mime_types or mime.startswith("text/"):
                is_text = True
            elif mime == "application/octet-stream":
                try:
                    content.decode('utf-8')
                    is_text = True
                    print(
                        f"File detected as text by content analysis (MIME: {mime})")
                except UnicodeDecodeError:
                    try:
                        content.decode('gbk')
                        is_text = True
                        print(
                            f"File detected as text (GBK encoding) by content analysis (MIME: {mime})")
                    except UnicodeDecodeError:
                        is_text = False

            if is_text:
                if widget_key in self.watching_dogs:
                    for watcher in self.watching_dogs[widget_key]:
                        if os.path.abspath(watcher.file_path) == os.path.abspath(local_path):
                            print(
                                f"Watcher for {local_path} already exists. Skipping.")
                            return
                print(
                    f"Text file detected (MIME: {mime}), starting file watching: {local_path}")
                file_thread = FileWatchThread(local_path)
                file_thread.file_saved.connect(
                    lambda local: self.reupload_when_saved(widget_key, local, remote_path))
                file_thread.start()

                if widget_key not in self.watching_dogs:
                    self.watching_dogs[widget_key] = []
                self.watching_dogs[widget_key].append(file_thread)
            else:
                print(
                    f"File type {mime} is not text file, won't start watching")
        except Exception as e:
            print(f"Error checking file type: {e}")

    def reupload_when_saved(self, widget_name, local_path, remote_path,):
        remote_path = os.path.dirname(remote_path)
        # print(f"将上传 {local_path} 到 {widget_name}的 {remote_path}")
        file_manager: RemoteFileManager = self.file_tree_object[widget_name]

        if file_manager:
            self._handle_upload_request(widget_key=widget_name, local_path=local_path,
                                        remote_path=remote_path, compression=False, file_manager=file_manager)

    def _start_ssh_connect(self, widget_key):
        parent_key = widget_key.split("-")[0].strip()
        session = self.sessionmanager.get_session_by_name(parent_key)
        jumpbox = None
        worker = None
        session_widget = self.session_widgets[widget_key]
        if session.jump_server != "None" and session.jump_server:
            print(f"{session.name} use Jumpbox")
            jumpbox = self.sessionmanager.get_session_by_name(
                session.jump_server)

        def on_auth_error(e=None):
            update_password, reshow = self.verify_password(
                session, reinput=True)
            if update_password and (not reshow):
                start_processes()
            elif reshow:
                on_auth_error()
            else:
                self._on_ssh_error(
                    self.tr("The user did not enter a password. Connection canceled."))

        def key_verification(file_md5, host_key):
            msg = ''
            session_file_md5 = session.processes_md5
            session_host_key = session.host_key

            if session_file_md5 != file_md5:
                msg += self.tr(
                    f"The MD5 file fingerprint of the Processes file does not match the record.\nMD5:{file_md5}\n")
            if session_host_key != host_key:
                msg += self.tr(
                    f"The host key does not match the recorded one.\n{host_key}\n")

            if msg:
                msg += self.tr("Are you sure to continue?")
                w = Dialog(self.tr("Warning!!!!!"), msg, self)
                if w.exec():
                    self.sessionmanager.update_session_processes_md5(
                        parent_key, file_md5)
                    self.sessionmanager.update_session_host_key(
                        parent_key, host_key)
                    start_real_connection()
                else:
                    return
            else:
                start_real_connection()

        def start_real_connection():
            nonlocal worker

            # processes = SSHWorker(session, for_resources=True)
            # processes.key_verification.connect(key_verification)
            worker.sys_resource.connect(
                lambda usage, key=widget_key: self._set_usage(key, usage))

            file_manager = RemoteFileManager(session)
            handler = FileManagerHandler(
                file_manager, session_widget, widget_key, self)

            def on_sftp_ready():
                global home_path
                home_path = file_manager.get_default_path(
                    session.file_manager_default_path)
                path_list = self.parse_linux_path(home_path)

                session_widget.file_bar.send_signal = False
                for i, path in enumerate(path_list):
                    if i == len(path_list) - 1:
                        session_widget.file_bar.send_signal = True
                    session_widget.file_bar.breadcrumbBar.addItem(path, path)

                session_widget.file_explorer.path = home_path
                file_manager.add_path(home_path)

                def _on_path_check_result(widget_key, path, result):
                    self._update_file_tree_branch_when_cd(path, widget_key)

                file_manager.path_check_result.connect(
                    partial(_on_path_check_result,
                            widget_key), Qt.QueuedConnection
                )
            file_manager.sftp_ready.connect(on_sftp_ready)
            file_manager.start()

            self.file_tree_object[widget_key] = file_manager
            self.file_tree_object[f"{widget_key}-handler"] = handler

            # worker.connected.connect(
            #     lambda success, msg: self._on_ssh_connected(success, msg))
            # worker.connected.connect(
            #     lambda s, m: session_widget.status_icon.setIcon(
            #         resource_path(os.path.join("resource", "icons", "green.png")))
            # )
            # worker.error_occurred.connect(lambda e: self._on_ssh_error(e))
            # worker.error_occurred.connect(lambda s, : session_widget.status_icon.setIcon(
            #     resource_path(os.path.join("resource", "icons", "red.png"))))

            try:
                child_widget = self.session_widgets[widget_key]
                if hasattr(child_widget, 'ssh_widget'):
                    child_widget.ssh_widget.set_worker(worker)
                    child_widget._set_file_bar(session.ssh_default_path)
                else:
                    print("child_widget does not have an ssh_widget attribute")
            except Exception as e:
                print("Injecting worker failed:", e)

            session_widget.ssh_widget.directoryChanged.connect(
                lambda path: file_manager.check_path_async(path)
            )
            session_widget.disk_storage.refresh.triggered.connect(
                lambda checked, ck=widget_key: self._refresh_paths(ck)
            )

        def start_processes():
            nonlocal worker
            worker = SSHWorker(session, jumpbox=jumpbox)
            worker.auth_error.connect(lambda e: on_auth_error(e))
            worker.connected.connect(self._on_ssh_connected)
            worker.error_occurred.connect(self._on_ssh_error)
            worker.error_occurred.connect(lambda s, : session_widget.status_icon.setIcon(
                resource_path(os.path.join("resource", "icons", "red.png"))))
            worker.connected.connect(
                lambda s, m: session_widget.status_icon.setIcon(
                    resource_path(os.path.join("resource", "icons", "green.png")))
            )
            self.ssh_session[widget_key] = worker
            worker.key_verification.connect(key_verification)
            worker.start()

        start_processes()

    def _open_server_files(self, path: str, type_: str, widget_key: str):
        config = setting_.read_config()
        file_manager: RemoteFileManager = self.file_tree_object[widget_key]

        # 停止此文件的现有观察者，以防止在重新下载时触发
        session_id = file_manager.session_info.id
        # 构建预期的本地路径以查找观察者
        expected_local_path = os.path.abspath(os.path.join(
            "tmp", "edit", session_id, path.lstrip('/')))

        if widget_key in self.watching_dogs:
            # 遍历列表的副本以安全地删除项目
            for watcher in self.watching_dogs[widget_key][:]:
                if os.path.abspath(watcher.file_path) == expected_local_path:
                    print(
                        f"Stopping existing watcher for {expected_local_path}")
                    watcher.stop()
                    self.watching_dogs[widget_key].remove(watcher)

        duration = 2000

        # 检查是否配置了外置编辑器
        external_editor = config.get("external_editor", "")
        # True for external, False for internal
        open_mode = config.get("open_mode", False)

        if (external_editor and os.path.isfile(external_editor)) and open_mode:
            title = self.tr(f"File: {path} Type: {type_}\n")
            msg = self.tr(f"Start to download and open with external editor")
        else:
            title = self.tr(f"File: {path} Type: {type_}\n")
            msg = self.tr(f"Start to download and open with internal editor")

        if type_ == "executable":
            title = self.tr(f"{path} is an executable won't start downloading")
            msg = ""

        InfoBar.info(
            title=title,
            content=msg,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.BOTTOM_RIGHT,
            duration=duration,
            parent=self.window()
        )
        if type_ != "executable":
            # 获取稳定的会话ID
            session_id = file_manager.session_info.id
            file_manager.download_path_async(
                path, open_it=True, session_id=session_id)

    def is_messagebox_showing(self):
        """检查是否有模态对话框正在显示"""
        # 方法1: 检查活跃模态窗口
        active_modal = QApplication.activeModalWidget()
        if active_modal and isinstance(active_modal, MessageBoxBase):
            return True

        # 方法2: 遍历所有顶层窗口
        for widget in QApplication.topLevelWidgets():
            if widget.isModal() and isinstance(widget, MessageBoxBase) and widget.isVisible():
                return True

        return False

    def _on_permission_info_got(self, file_path: str, permission_num: int, success: bool, error_msg: str, file_manager=None):
        """
        处理获取权限信息的回调
        """
        file_name = os.path.basename(file_path)
        if self.is_messagebox_showing():
            print("其他模态对话框正在显示 跳过")
            self._on_ssh_connected(True, self.tr(
                f"Another modal dialog is showing. Skip the file {file_name}"))
            return
        if success:
            # owner_perm = (permission_num >> 6) & 0o7
            # group_perm = (permission_num >> 3) & 0o7
            # other_perm = permission_num & 0o7

            # print(f"\n📁 文件权限信息: {file_path}")
            # print(
            #     f"🟦 所有者权限: {owner_perm:03o} (r:{bool(owner_perm&4)}, w:{bool(owner_perm&2)}, x:{bool(owner_perm&1)})")
            # print(
            #     f"🟩 所属组权限: {group_perm:03o} (r:{bool(group_perm&4)}, w:{bool(group_perm&2)}, x:{bool(group_perm&1)})")
            # print(
            #     f"🟥 其他用户权限: {other_perm:03o} (r:{bool(other_perm&4)}, w:{bool(other_perm&2)}, x:{bool(other_perm&1)})")
            # print(f"🔢 完整权限码: {permission_num:03o}")

            per_box = PermissionDialog(file_name, permission_num, self)

            if per_box.exec_():
                new_permission_num = per_box.get_permission_num()
                print(
                    f"✅ 用户确认设置新权限: 十进制={new_permission_num}, 八进制=0{new_permission_num:03o}")

                file_manager.set_permissions(file_path, new_permission_num)

        else:
            print(f"❌ 获取权限失败 [{file_path}]: {error_msg}")

    def _handle_files(self, action_type, full_path, copy_to, cut, widget_key):
        file_manager: RemoteFileManager = self.file_tree_object[widget_key]
        if action_type == "delete":
            file_manager.delete_path(full_path)
        elif action_type == "copy_path":
            paths_to_copy = full_path if isinstance(
                full_path, list) else [full_path]
            text_to_copy = '\n'.join(path for path in paths_to_copy)
            cb.copy(text_to_copy)
        elif action_type == "download":
            # Debounce download requests
            if widget_key not in self._pending_download_paths:
                self._pending_download_paths[widget_key] = {
                    "paths": [], "compression": cut}

            # Since _handle_files is called for each item, full_path is a single path string
            self._pending_download_paths[widget_key]["paths"].append(full_path)
            self._pending_download_paths[widget_key]["compression"] = cut
            self._download_debounce_timer.start()

        elif action_type == "paste":
            source_paths = full_path if isinstance(
                full_path, list) else [full_path]
            for source_path in source_paths:
                if source_path and copy_to:
                    print(
                        f"Copy {source_path} to {copy_to} Cut status : {cut}")
                    file_manager.copy_to(source_path, copy_to, cut)
        elif action_type == "rename":
            if copy_to:
                print(f"Rename {full_path} to {copy_to}")
                file_manager.rename(path=full_path, new_name=copy_to)
        elif action_type == "info":

            paths_to_info = full_path if isinstance(
                full_path, list) else [full_path]

            # file_manager.get_file_info(path)
            file_manager.get_permissions(paths_to_info[-1])

        elif action_type == "mkdir":
            if full_path:
                file_manager.mkdir(full_path)
        elif action_type == "mkfile":
            print(f"mkfile", full_path)
            if full_path:
                file_manager.mkfile(full_path)

    def _process_pending_downloads(self):
        """Process the accumulated download paths after the debounce delay."""
        if not self._pending_download_paths:
            return

        # Atomically take ownership of the pending paths and reset the shared collection
        paths_to_process_now = self._pending_download_paths
        self._pending_download_paths = {}

        for widget_key, download_info in paths_to_process_now.items():
            paths_to_download = download_info["paths"]
            compression = download_info["compression"]

            if not paths_to_download:
                continue

            file_manager: RemoteFileManager = self.file_tree_object.get(
                widget_key)
            if not file_manager:
                continue

            if not compression:  # Non-compressed download
                path_types = file_manager.check_path_type_list(
                    paths_to_download)
                files_to_add_ui = [
                    p for p, t in path_types.items() if t == "file"]
                for path in files_to_add_ui:
                    self._add_transfer_item_if_not_exists(
                        widget_key, path, "download", open_it=False)
                file_manager.download_path_async(
                    paths_to_download, open_it=False, compression=compression)

            else:  # Compressed download
                print(f"{type(paths_to_download)} {paths_to_download}")
                self._add_transfer_item_if_not_exists(
                    widget_key, paths_to_download[0], "download", open_it=False)
                file_manager.download_path_async(
                    paths_to_download[0], open_it=False, compression=compression)

    def _refresh_paths(self, widget_key: str):
        print("Refresh the page")
        session_widget: SSHWidget = self.session_widgets[widget_key]
        session_widget._update_file_explorer()

    def parse_linux_path(self, path: str) -> list:
        """
        Parse a Linux path into a list of path elements, with each level as an element.

        Example:
            '/home/bee' -> ['/', 'home', 'bee']
            '/' -> ['/']

        Parameters:
            path: str, Linux-style path

        Returns:
            list[str], list from root to deepest directory
        """
        if not path:
            return []

        path_list = []
        if path.startswith('/'):
            path_list.append('/')
        parts = [p for p in path.strip('/').split('/') if p]

        path_list.extend(parts)

        return path_list

    def _update_file_tree_branch_when_cd(self, path: str, widget_key: str):
        file_manager: RemoteFileManager = self.file_tree_object[widget_key]
        file_manager.add_path(path, update_tree_sign=True)
        # path_status = file_manager.check_path_type(path)
        # # print(f"更新目录：{path}")
        # if path_status:
        #     file_manager._add_path_to_tree(path)
        # else:
        #     print(f"{path}不存在")

    def on_file_tree_updated(self, file_tree, sw, path=None):
        """Handling file tree updates"""
        sw.disk_storage.refresh_tree(file_tree)
        if path:
            sw.disk_storage.switch_to(path)

    def on_file_manager_error(self, error_msg):
        InfoBar.error(
            title=self.tr('File management errors'),
            content=self.tr(f'''Error details:\n{error_msg}'''),
            orient=Qt.Vertical,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=-1,
            parent=self
        )

    def _count_sessions_starting_with(self, session_id_prefix):
        """Count the number of sessions starting with the specified prefix"""
        count = 0
        for key in self.session_widgets.keys():
            if key.startswith(session_id_prefix):
                count += 1
        return count

    def verify_password(self, session, reinput: bool = False) -> bool:
        '''verify password is or not None and incorrect if reinput is true it means password incorrec
        the second returned parameter indicates whether to continue displaying. '''
        if (not session.password) or reinput:
            password_box = PasswordDialog(self)
            if password_box.exec_():
                password = password_box.password.text()
                if not password:
                    InfoBar.error(
                        title=self.tr('Password is None'),
                        content=self.tr(
                            f"The password entered is empty. The connection will not continue."),
                        orient=Qt.Horizontal,
                        isClosable=True,
                        position=InfoBarPosition.TOP_RIGHT,
                        duration=10000,
                        parent=self
                    )
                    return False, True
                session.password = password
                if password_box.save_password.isChecked():
                    session.save(self.sessionmanager)
                return True, False
            else:
                return False, False
        return True, False

    def _on_session_selected(self, session_id=None, session_name=None):
        """Handling session selection"""
        now = time.time()
        debounce_key = None
        session = None
        if session_id:
            debounce_key = session_id
            session = self.sessionmanager.get_session(session_id=session_id)
        elif session_name:
            name = session_name.rsplit(" - ", 1)[0]
            session = self.sessionmanager.get_session_by_name(name)
            if session:
                debounce_key = session.id
        if not session:
            print(
                "Warning: _on_session_selected called with no valid session identifier.")
            return

        update, reshow = self.verify_password(session=session)
        if not update:
            return
        if debounce_key:
            last_click_time = self.last_session_click_time.get(debounce_key, 0)
            if (now - last_click_time) < 1.0:  # 1 second debounce time
                print(f"Debouncing click for session: {debounce_key}")
                return
            self.last_session_click_time[debounce_key] = now

        def _connect_file_explorer_signals(self, widget, widget_key):
            # 文件操作
            widget.file_explorer.file_action.connect(
                partial(self._handle_files, widget_key=widget_key)
            )

            # 目录选择
            widget.disk_storage.directory_selected.connect(
                partial(self._update_file_tree_branch_when_cd,
                        widget_key=widget_key)
            )

            # 取消传输
            widget.transfer_progress.cancelRequested.connect(
                partial(self._handle_transfer_cancellation,
                        widget_key=widget_key)
            )

            widget.transfer_progress.open_file.connect(
                self.open_in_explorer
            )
            self.windowResized.connect(widget.on_main_window_resized)

        name = session.name

        child_number = 1
        for key in self.session_widgets.keys():
            if key.startswith(f"{name} - "):
                try:
                    existing_num = int(key.split(" - ")[-1])
                    child_number = max(child_number, existing_num + 1)
                except ValueError:
                    continue
        widget_key = f"{name} - {child_number}"
        print(widget_key)
        font_name, font_size = font_.read_font()
        widget = SSHWidget(widget_key, font_name=font_name)
        self.ssh_page.add_session(widget_key, widget_key, widget=widget)
        _connect_file_explorer_signals(self, widget, widget_key)

        self.session_widgets[widget_key] = widget

        self._start_ssh_connect(widget_key)
        self.switchTo(self.ssh_page, widget_key)

    def apply_locked_ratio(self, event=None):
        new_width, new_height = 0, 0
        if not self.isMaximized():
            """Apply background image proportionally to window size"""
            if self.settingInterface._lock_ratio and self._bg_pixmap and self._bg_ratio:
                if event is not None and not isinstance(event, bool):
                    new_width = event.size().width()
                    new_height = event.size().height()
                else:
                    new_width = self.width()
                    new_height = self.height()

                target_ratio = self._bg_ratio

                if abs(new_width / new_height - target_ratio) > 0.01:
                    new_height = int(new_width / target_ratio)
                    self.resize(new_width, new_height)
            if self.settingInterface.init_window_size and new_width and new_height:
                self.settingInterface.save_window_size((new_width, new_height))

    def resizeEvent(self, event):
        self.windowResized.emit()
        self._resize_timer.start(50)
        if not self.isActiveWindow() or not self.underMouse():
            self.apply_locked_ratio(event)
        if hasattr(self, 'expanderBar') and self.expanderBar.isVisible():
            self._position_expander_bar()
        super().resizeEvent(event)

    def eventFilter(self, obj, event):
        if hasattr(self, 'mainSplitter') and self.mainSplitter:
            handle = self.mainSplitter.handle(1)
            if handle and obj == handle:
                if event.type() == QEvent.MouseButtonRelease:
                    self._save_main_splitter_state()
        return super().eventFilter(obj, event)

    def initLayout(self):
        self.hBoxLayout.setSpacing(0)
        self.hBoxLayout.setContentsMargins(0, self.titleBar.height(), 0, 0)
        self.hBoxLayout.addWidget(self.navigationInterface)

        # Create a splitter to hold the main content and the side panel
        self.mainSplitter = QSplitter(Qt.Horizontal, self)
        self.mainSplitter.addWidget(self.stackWidget)
        self.mainSplitter.addWidget(self.sidePanel)

        # Restore splitter sizes
        splitter_sizes = setting_.read_config().get(
            "splitter_sizes", [self.width() * 0.7, self.width() * 0.3])
        self.mainSplitter.setSizes([int(s) for s in splitter_sizes])

        # Connect signal to save sizes
        self.mainSplitter.splitterMoved.connect(self._on_main_splitter_moved)

        # Install event filter to save state on mouse release
        handle = self.mainSplitter.handle(1)
        if handle:
            handle.installEventFilter(self)

        # Style the splitter handle to be thin and subtle
        self.mainSplitter.setStyleSheet("""
            QSplitter::handle {
                background-color: transparent;
                width: 1px;
                margin: 0px;
                padding: 0px;
            }
            QSplitter::handle:hover {
                background-color: #555555;
            }
        """)

        self.hBoxLayout.addWidget(self.mainSplitter)
        self.hBoxLayout.setStretchFactor(self.mainSplitter, 1)

        QTimer.singleShot(100, self._update_expander_visibility)

    def initNavigation(self):
        self.addSubInterface(self.MainInterface, FIF.HOME, self.tr("Home"))
        self.navigationInterface.addSeparator()

        self.addSubInterface(self.ssh_page, FIF.ALBUM, self.tr("SSH Session"))

        version = get_version()
        if version:
            version_widget = NavigationAvatarWidget(
                version, resource_path('resource/icons/update.svg'))
            self.navigationInterface.addWidget(
                routeKey='version_widget',
                widget=version_widget,
                onClick=lambda: None,
                position=NavigationItemPosition.BOTTOM
            )

        self.navigationInterface.addWidget(
            routeKey='sync',
            widget=NavigationAvatarWidget(
                'Sync', resource_path('resource/icons/sync.svg')),
            onClick=lambda: self.sync_widget.exec_(),
            position=NavigationItemPosition.BOTTOM,
        )

        self.navigationInterface.addWidget(
            routeKey='about',
            widget=NavigationAvatarWidget(
                'Github', resource_path('resource/icons/github.svg')),
            onClick=self._open_github,
            position=NavigationItemPosition.BOTTOM,
        )
        avatar_url = config.get("account", {}).get(
            "avatar_url") or resource_path('resource/icons/guest.png')
        self.navigationInterface.addWidget(
            routeKey='account',
            widget=NavigationAvatarWidget(
                'Account', avatar_url),
            onClick=lambda: (
                self.switchTo(self.account_widget),
                self.navigationInterface.setCurrentItem('account')
            ),
            position=NavigationItemPosition.BOTTOM,
        )

        # self.navigationInterface.addSeparator()
        # self.addSubInterface(self.account_widget, FIF.PEOPLE, self.tr(
        #     "Account"), position=NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.settingInterface, FIF.SETTING,
                             self.tr("Setting"), NavigationItemPosition.BOTTOM)

        self.stackWidget.currentChanged.connect(self.onCurrentInterfaceChanged)
        self.stackWidget.setCurrentIndex(1)
        self.onCurrentInterfaceChanged(1)

    def init_account(self):
        config = configer.read_config().get("account", {
            "user": "Guest",
            "avatar_url": r"resource\icons\guest.png",
            "combo": "",
            "qid": "",
            "email": ""
        })
        self.account_widget = AccountPage(
            username=config["user"],
            qid=config["qid"],
            email=config["email"],
            avatar_url=config["avatar_url"],
            combo=config["combo"]
        )
        self.account_widget.setObjectName("accountPage")
        self.stackWidget.addWidget(self.account_widget)
        # self.stackWidget.addWidget(self.account_widget)

    def _open_github(self):
        github_url = QUrl("https://github.com/Heartestrella/P-SSH")
        QDesktopServices.openUrl(github_url)

    def initWindow(self):
        self.titleBar.setAttribute(Qt.WA_StyledBackground)
        self.setWindowFlags(Qt.FramelessWindowHint)
        desktop = QApplication.desktop().availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w//2 - self.width()//2, h//2 - self.height()//2)

        self.setQss()

    def _handle_action(self, action, name):
        if action == "close":
            self.remove_interface(name)
        elif action == "copy":
            self._on_session_selected(session_name=name)

    def remove_interface(self, widget_name):
        try:
            self.ssh_page.remove_session(widget_name)
            widget = self.session_widgets[widget_name]
            widget.cleanup()
            self.session_widgets.pop(widget_name, None)
            widget.deleteLater()
            worker = self.ssh_session.pop(widget_name, None)
            worker_processes = self.ssh_session.pop(
                f'{widget_name}-processes', None)
            watching_dogs = self.watching_dogs.pop(widget_name, None)
            if worker:
                worker.close()
            if worker_processes:
                worker_processes.close()
            file_manager = self.file_tree_object.pop(widget_name, None)
            if file_manager:
                file_manager._cleanup()
            file_manager_handler = self.file_tree_object.pop(
                f"{widget_name}-handler", None)
            if file_manager_handler:
                file_manager_handler.cleanup()
            if watching_dogs:
                for dog in watching_dogs:
                    dog.stop()
            if len(self.session_widgets) <= 0:
                self.switchTo(self.MainInterface)
        except Exception as e:
            InfoBar.error(
                title=self.tr('Error closing session!'),
                content=self.tr(f'''Error details:\n{e}'''),
                orient=Qt.Vertical,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=-1,
                parent=self
            )

    def addSubInterface(self, interface, icon, text: str, position=NavigationItemPosition.TOP, parent=None):
        """ Add a page """
        self.stackWidget.addWidget(interface)
        self.navigationInterface.addItem(
            routeKey=interface.objectName(),
            icon=icon,
            text=text,
            onClick=lambda: self.switchTo(interface),
            position=position,
            tooltip=text,
            parentRouteKey=parent.objectName() if parent else None
        )

    def setQss(self):
        color = 'dark' if isDarkTheme() else 'light'
        with open(resource_path(f'resource/{color}/demo.qss'), encoding='utf-8') as f:
            self.setStyleSheet(f.read())

    def switchTo(self, widget, window_tittle=None):
        if self._animation_in_progress:
            return
        current_widget = self.stackWidget.currentWidget()
        if current_widget == widget:
            return
        direction = "left"
        if widget == self.MainInterface:
            direction = "right"
        self._animation_in_progress = True

        def on_animation_finished():
            self.stackWidget.setCurrentWidget(widget)
            self._animation_in_progress = False
            if window_tittle:
                self.setWindowTitle(window_tittle)
            elif widget.objectName():
                self.setWindowTitle(widget.objectName())
            if widget == self.ssh_page:
                current_ssh_widget = self.ssh_page.sshStack.currentWidget()
                if isinstance(current_ssh_widget, SSHWidget):

                    QTimer.singleShot(
                        150, current_ssh_widget.force_set_left_panel_width)

        config = setting_.read_config()
        animation_type = config.get("page_animation", "slide_fade")

        if animation_type == "slide_fade":
            self.page_animator.slide_fade_transition(
                from_widget=current_widget, to_widget=widget, direction=direction, on_finished=on_animation_finished)
        elif animation_type == "zoom_in":
            self.page_animator.zoom_in_transition(
                from_widget=current_widget, to_widget=widget, on_finished=on_animation_finished)
        elif animation_type == "zoom_out":
            self.page_animator.zoom_out_transition(
                from_widget=current_widget, to_widget=widget, on_finished=on_animation_finished)
        elif animation_type == "cross_fade":
            self.page_animator.cross_fade_transition(
                from_widget=current_widget, to_widget=widget, on_finished=on_animation_finished)
        elif animation_type == "bounce":
            self.page_animator.bounce_transition(
                from_widget=current_widget, to_widget=widget, direction=direction, on_finished=on_animation_finished)
        elif animation_type == "elastic":
            self.page_animator.elastic_transition(
                from_widget=current_widget, to_widget=widget, direction=direction, on_finished=on_animation_finished)
        elif animation_type == "fade_scale":
            self.page_animator.fade_scale_transition(
                from_widget=current_widget, to_widget=widget, on_finished=on_animation_finished)
        elif animation_type == "slide_scale":
            self.page_animator.slide_scale_transition(
                from_widget=current_widget, to_widget=widget, direction=direction, on_finished=on_animation_finished)
        elif animation_type == "stack":
            self.page_animator.stack_transition(
                from_widget=current_widget, to_widget=widget, direction=direction, on_finished=on_animation_finished)
        else:
            self.page_animator.slide_fade_transition(
                from_widget=current_widget, to_widget=widget, direction=direction, on_finished=on_animation_finished)

    def onCurrentInterfaceChanged(self, index):
        widget = self.stackWidget.widget(index)
        self.navigationInterface.setCurrentItem(widget.objectName())
        if widget == self.ssh_page:
            self.sidePanel.show()
            QTimer.singleShot(50, self._update_expander_visibility)
        else:
            self.sidePanel.hide()
            if hasattr(self, 'expanderBar'):
                self.expanderBar.hide()

    def _handle_upload_request(self, widget_key, local_path, remote_path, compression, file_manager):
        """Pre-handles upload requests to determine if UI items should be pre-created."""
        # If compression is on and we have a list, create a single UI item for the batch.
        if compression and isinstance(local_path, list):
            task_id = f"compress_upload_{time.time()}"
            self._add_transfer_item_if_not_exists(
                widget_key, local_path, 'upload', task_id=task_id)
            file_manager.upload_file(
                local_path, remote_path, compression, task_id=task_id)
            return

        # Original logic for other cases (single files, non-compressed lists/dirs)
        paths = local_path if isinstance(local_path, list) else [local_path]
        print(f"Paths Len : {len(paths)}")
        for p in paths:
            # For non-compressed dirs, we don't create items here.
            # They will be created dynamically on first progress/finished signal.
            if not (os.path.isdir(p) and not compression):
                self._add_transfer_item_if_not_exists(
                    widget_key, p, 'upload')
            file_manager.upload_file(p, remote_path, compression)

    def _add_transfer_item_if_not_exists(self, widget_key, path, transfer_type, task_id=None, open_it=False):
        """Helper to add a transfer item to the UI if it doesn't exist."""
        print(f"{type(path)} {path}")
        session_widget = self.session_widgets[widget_key]
        if not session_widget:
            return

        # The unique identifier for a task is now the full path for single files,
        # or the string representation of the list for compressed batches.
        task_identifier = task_id if task_id else (
            str(path) if isinstance(path, list) else path)

        if task_identifier in self.active_transfers:
            return  # Avoid creating duplicate entries

        # Create a truly unique ID for the UI widget
        file_id = f"{widget_key}_{task_identifier}_{time.time()}"

        # 根据 transfer_type 和 open_it 决定本地路径
        if transfer_type == 'download' and open_it:
            # 双击编辑模式：使用会话隔离的编辑目录，并镜像远程路径
            file_manager = self.file_tree_object.get(widget_key)
            if file_manager:
                session_id = file_manager.session_info.id
                if type(path) == list:
                    for i in path:
                        remote_path_normalized = i.lstrip('/')
                        self.file_id_to_path[file_id] = os.path.join(
                            "tmp", "edit", session_id, remote_path_normalized)
                else:
                    remote_path_normalized = path.lstrip('/')
                    self.file_id_to_path[file_id] = os.path.join(
                        "tmp", "edit", session_id, remote_path_normalized)
            else:
                # 降级到常规下载路径
                if type(path) == list:
                    for i in path:
                        self.file_id_to_path[file_id] = os.path.join(
                            "_ssh_download", os.path.basename(i))
                else:
                    self.file_id_to_path[file_id] = os.path.join(
                        "_ssh_download", os.path.basename(path))
        else:
            # 常规下载或上传：使用原有逻辑
            if type(path) == list:
                for i in path:
                    self.file_id_to_path[file_id] = os.path.join(
                        "_ssh_download", os.path.basename(i))
            else:
                self.file_id_to_path[file_id] = os.path.join(
                    "_ssh_download", os.path.basename(path))
        if isinstance(path, list) and transfer_type == 'upload':
            # Special handling for compressed list uploads
            file_name = "Compressing..."
        elif isinstance(path, list):
            count = len(path)
            if count == 0:
                return
            file_name = f"{os.path.basename(path[0][0])}"
            if count > 1:
                file_name += f" and {count - 1} others"
        else:
            file_name = os.path.basename(path)

        data = {
            "id": file_id,  # The unique ID for the widget
            "type": transfer_type,
            "filename": file_name,
            "progress": 0
        }

        # Use the task_identifier as the key in our tracking dictionary
        self.active_transfers[task_identifier] = data
        session_widget.transfer_progress.add_transfer_item(file_id, data)

    def open_in_explorer(self, file_id: str):
        filepath = self.file_id_to_path.get(file_id, None)

        if filepath and os.path.exists(filepath):  # maybe its remote path

            print("Open : ", filepath)
            if sys.platform == "win32":
                subprocess.Popen(
                    ["explorer", "/select,", os.path.normpath(filepath)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", filepath])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(filepath)])

    def _handle_transfer_cancellation(self, file_id, widget_key):
        # import inspect
        # caller_frame = inspect.stack()[1]
        # caller_filename = caller_frame.filename
        # caller_line_no = caller_frame.lineno
        # caller_func_name = caller_frame.function
        # print(
        #     f"Called from {caller_func_name} in {caller_filename}:{caller_line_no}")

        file_manager = self.file_tree_object.get(widget_key)
        if not file_manager:
            return

        # Find the original identifier for the task
        task_identifier = None
        for identifier, data in self.active_transfers.items():
            if data.get("id") == file_id:
                task_identifier = identifier
                break

        if task_identifier:
            # Tell the file manager to cancel the backend worker
            file_manager.cancel_transfer(task_identifier)

            # Remove from UI and tracking dictionary
            session_widget = self.session_widgets[widget_key]
            if session_widget:
                session_widget.transfer_progress.remove_transfer_item(file_id)

            self.active_transfers.pop(task_identifier, None)

    def remove_nav_edge(self):
        self.navigationInterface.setStyleSheet("""
            NavigationInterface {
                background-color: transparent;
                border: none;
            }
            NavigationInterface > QWidget {
                background-color: transparent;
            }
        """)

    def _update_transfer_item_name(self, identifier, new_name, widget_key):
        session_widget = self.session_widgets[widget_key]
        if not session_widget:
            return

        if identifier in self.active_transfers:
            file_id = self.active_transfers[identifier]["id"]
            self.active_transfers[identifier]["filename"] = new_name
            data = self.active_transfers[identifier]
            session_widget.transfer_progress.update_transfer_item(
                file_id, data)

    def set_ssh_session_text_color(self, color: str):
        try:
            for _, value_ in self.session_widgets.items():
                for key, value_1 in value_.items():
                    if key != "widget":
                        print(value_1)
                        if not value_1.parent_state:
                            value_1.ssh_widget.set_colors(text_color=color)
                            value_1.task.set_text_color(color)
        except Exception as e:
            print(f"Setting font color failed:{e}")

    def _on_theme_changed(self, value):
        if value == "Light":
            setTheme(Theme.LIGHT)
        elif value == "Dark":
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.AUTO)

        self.setQss()

        for i in range(self.stackWidget.count()):
            w = self.stackWidget.widget(i)
            if hasattr(w, 'widget') and isinstance(w.widget, QWidget):
                w.widget.update()
            else:
                w.update()

    def clear_global_background(self):
        self._bg_pixmap = None
        self._bg_opacity = 1.0
        self.update()

        self.navigationInterface.setStyleSheet("")

    def set_global_background(self, image_path: str):
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            print(f"Invalid image path: {image_path}")
            return
        self._bg_pixmap = pixmap
        self._bg_ratio = pixmap.width() / pixmap.height()
        self._bg_opacity = 1.0
        self.update()
        self.remove_nav_edge()

    def paintEvent(self, event):
        if self._bg_pixmap:
            painter = QPainter(self)
            painter.setOpacity(self._bg_opacity)
            painter.drawPixmap(self.rect(), self._bg_pixmap)
        super().paintEvent(event)

    def on_theme_color_changed(self, color_hex: str):
        """
        Applies the new theme color to all relevant widgets.
        """
        for widget_key, session_widget in self.session_widgets.items():
            try:
                if hasattr(session_widget, 'update_splitter_color'):
                    session_widget.update_splitter_color(color_hex)
            except Exception as e:
                print(f"Error updating splitter color for {widget_key}: {e}")

    def _save_main_splitter_state(self):
        new_sizes = self.mainSplitter.sizes()
        if len(new_sizes) == 2 and new_sizes[1] <= 10:
            old_sizes = setting_.read_config().get("splitter_sizes", [0, 0])
            if len(old_sizes) == 2 and old_sizes[1] > 10:
                setting_.revise_config("side_panel_last_width", old_sizes[1])

        setting_.revise_config("splitter_sizes", new_sizes)

    def _on_main_splitter_moved(self):
        current_widget = self.ssh_page.sshStack.currentWidget()
        if isinstance(current_widget, SSHWidget):
            QTimer.singleShot(10, current_widget.force_set_left_panel_width)
        self._update_expander_visibility()

    def _ensure_side_panel_visible(self):
        sizes = self.mainSplitter.sizes()
        if len(sizes) == 2 and sizes[1] == 0:
            self.mainSplitter.blockSignals(True)
            config = setting_.read_config()
            last_width = config.get("side_panel_last_width")
            if not last_width or last_width <= 10:
                last_width = int(self.width() * 0.3)
            total_width = sum(sizes)
            new_sizes = [total_width - last_width, last_width]
            self.mainSplitter.setSizes(new_sizes)
            setting_.revise_config("splitter_sizes", new_sizes)
            self.mainSplitter.blockSignals(False)
            current_widget = self.ssh_page.sshStack.currentWidget()
            if isinstance(current_widget, SSHWidget):
                QTimer.singleShot(
                    10, current_widget.force_set_left_panel_width)

    def _expand_side_panel(self):
        self.expanderBar.hide()
        self._ensure_side_panel_visible()

    def _update_expander_visibility(self):
        if self.stackWidget.currentWidget() != self.ssh_page:
            if hasattr(self, 'expanderBar'):
                self.expanderBar.hide()
            return

        sizes = self.mainSplitter.sizes()
        if len(sizes) == 2:
            if sizes[1] == 0:
                self.expanderBar.show()
                self._position_expander_bar()
            else:
                self.expanderBar.hide()

    def _position_expander_bar(self):
        expander_width = self.expander_bar_width
        window_width = self.width()
        window_height = self.height()
        titlebar_height = self.titleBar.height()
        self.expanderBar.setGeometry(
            window_width - expander_width,
            titlebar_height,
            expander_width,
            window_height - titlebar_height
        )
        self.expanderBar.raise_()

    def _set_language(self, lang_code: str):
        translator = QTranslator()
        if lang_code == "system":
            system_locale = QLocale.system().name()
            if translator.load(f"resource/i18n/pssh_{system_locale}.qm"):
                QApplication.instance().installTranslator(translator)
            else:
                print("Translation file loading failed")
        else:
            if translator.load(f"resource/i18n/pssh_{lang_code}.qm"):
                QApplication.instance().installTranslator(translator)
            else:
                print("Translation file loading failed")
        self.settingInterface.retranslateUi()
        self.MainInterface.retranslateUi()
        for _, value_ in self.session_widgets.items():
            for key, value_1 in value_.items():
                if key != "widget":
                    value_1.retranslateUi()

    def nativeEvent(self, eventType, message):
        if sys.platform == "win32" and eventType == "windows_generic_MSG":
            try:
                from ctypes import windll, cast, POINTER
                from ctypes.wintypes import MSG, LPRECT
                msg = cast(int(message), POINTER(MSG)).contents
                if msg.message == 0x0083:
                    if msg.wParam:
                        return True, 0
            except Exception as e:
                pass
        return super().nativeEvent(eventType, message)

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            if self.isMaximized():
                setting_.revise_config("maximized", True)
            else:
                setting_.revise_config("maximized", False)
        super().changeEvent(event)

    def get_active_ssh_widget(self):
        if self.stackWidget.currentWidget() == self.ssh_page:
            current_ssh_widget = self.ssh_page.sshStack.currentWidget()
            if isinstance(current_ssh_widget, SSHWidget):
                return current_ssh_widget
        return None


def language_code_to_locale(code: str) -> str:
    """
    EN -> en_US
    CN -> zh_CN
    JP -> ja_JP
    RU -> ru_RU
    system ->
    """
    mapping = {
        "EN": "en_US",
        "CN": "zh_CN",
        "JP": "zh_JP",
        "RU": "ru_RU",
    }

    code = code.upper().strip()

    if code == "SYSTEM":
        return QLocale.system().name()

    return mapping.get(code, "en_US")


def excepthook(exc_type, exc_value, exc_traceback):
    print("Uncaught exception:", exc_type, exc_value)
    traceback.print_tb(exc_traceback)
    error_msg = "".join(traceback.format_exception(
        exc_type, exc_value, exc_traceback))
    QMessageBox.critical(None, "程序出错", error_msg)


# sys.excepthook = excepthook


def update_splash_progress(step, total_steps=10, message=""):
    try:
        if not pyi_splash:
            return

        progress = int((step / total_steps) * 100)

        if message:
            clean_message = message.replace('\n', ' ').replace('\r', '')
            display_text = f"{clean_message} {progress}%"
        else:
            display_text = f"Loading {progress}%"

        try:
            pyi_splash.update_text(display_text)
        except Exception as e:
            pass

    except:
        pass


def is_pyinstaller_bundle():
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def check_for_update_lock_and_recover():
    try:
        if not is_pyinstaller_bundle():
            return False

        def is_internal_local():
            if getattr(sys, 'frozen', False):
                base_path = os.path.dirname(sys.executable)
                return os.path.exists(os.path.join(base_path, "_internal"))
            return os.path.exists("_internal")
        if is_internal_local():
            target_path = os.path.dirname(sys.executable)
        else:
            target_path = sys.executable
        app_dir = os.path.dirname(target_path)
        lock_file = os.path.join(app_dir, 'update.lock')
        if os.path.exists(lock_file):
            pid = None
            try:
                with open(lock_file, 'r') as f:
                    pid = int(f.read().strip())
            except (ValueError, IOError):
                pid = None
            if pid and psutil.pid_exists(pid):
                app_temp = QApplication(sys.argv)
                QMessageBox.information(
                    None, "Update in Progress", "An update is currently in progress. The application will start automatically when it's done.")
                return True
            else:
                if os.path.exists(lock_file):
                    os.remove(lock_file)
                return False
        return False
    except Exception as e:
        app_temp = QApplication(sys.argv)
        QMessageBox.critical(
            None, "Startup Error", f"A critical error occurred during startup integrity check: {e}\nPlease reinstall the application.")
        return True


def has_chinese(text):
    """判断文本是否包含中文"""
    pattern = re.compile(r'[\u4e00-\u9fff]+')  # 匹配中文字符
    return bool(pattern.search(text))


if __name__ == '__main__':
    try:
        import platform
        if platform.system().lower() == "linux":
            setup_webengine_environment()

        if isDebugMode():
            print("\\\\ Debuger Software Starting \\\\")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if has_chinese(script_dir):
            pyi_splash.update_text("请勿运行在中文路径下")
            app = QApplication(sys.argv)
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setText("路径错误")
            msg.setInformativeText("程序不能在包含中文的路径下运行，请将程序移动到英文目录。")
            msg.setWindowTitle("启动失败")
            if msg.exec_():
                sys.exit(1)
            # time.sleep(30000)
        else:
            if len(sys.argv) > 1 and sys.argv[1] == '--update':
                if pyi_splash:
                    pyi_splash.close()
                from tools.updater import main as updater_main
                updater_args = [sys.argv[0]] + sys.argv[2:]
                sys.argv = updater_args
                updater_main()
                sys.exit(0)

            if check_for_update_lock_and_recover():
                sys.exit()
            config_dir = Path.home() / ".config" / "pyqt-ssh"
            config_path = config_dir / "qfluentwidgets_config.json"
            qconfig.load(config_path)
            try:
                # 步骤1: 初始化日志
                update_splash_progress(1, 8, "初始化日志系统")
                configer = SCM()
                setup_global_logging()

                # 步骤2: 设置DPI
                update_splash_progress(2, 8, "设置高DPI支持")
                QApplication.setHighDpiScaleFactorRoundingPolicy(
                    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
                QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)

                app = QApplication(sys.argv)
                # 步骤3: 设置应用属性
                update_splash_progress(3, 8, "设置应用属性")
                try:
                    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                        "su8aru.remmotessh.1.0.0")
                except:
                    pass

                # 步骤4: 加载配置
                update_splash_progress(4, 8, "加载配置文件")
                config = configer.read_config()
                lang = language_code_to_locale(
                    config.get("language", "system"))

                # 步骤5: 设置语言
                update_splash_progress(5, 8, "设置语言环境")
                translator = QTranslator()
                translator_1 = FluentTranslator()
                if lang != "en_US":
                    translator.load(resource_path(
                        f"resource/i18n/app_{lang}.qm"))
                    app.installTranslator(translator)
                app.installTranslator(translator_1)

                # 步骤6: 初始化组件
                update_splash_progress(6, 8, "初始化组件")

                # 步骤7: 创建主窗口
                update_splash_progress(7, 8, "准备主界面")
                w = Window()

                # 步骤8: 完成，关闭启动画面
                update_splash_progress(8, 8, "启动完成")
                if pyi_splash:
                    pyi_splash.close()
                if isDebugMode():
                    print("\\\\ Debuger Software Starting Done \\\\")
                w.show()
                app.exec_()

                # Clean up the edit directory on exit
                main_logger.info(" cleaning up tmp/edit directory...")
                edit_tmp_dir = "tmp/edit"
                if os.path.exists(edit_tmp_dir):
                    try:
                        shutil.rmtree(edit_tmp_dir)
                        main_logger.info(
                            f"Successfully cleaned up {edit_tmp_dir}.")
                    except Exception as e:
                        main_logger.error(
                            f"Error cleaning up {edit_tmp_dir}: {e}")

            except Exception as e:
                main_logger.critical(
                    "Application startup failure", exc_info=True)
    except Exception as e:
        print(e)
        input()
