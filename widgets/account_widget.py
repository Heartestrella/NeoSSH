import os
import random
from PyQt5.QtCore import Qt, QTimer, QUrl, pyqtSignal, QByteArray
from PyQt5.QtGui import QFont, QPixmap, QPainter, QColor, QPixmap, QImage
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel
from qfluentwidgets import (
    CardWidget, SimpleCardWidget, TitleLabel, CaptionLabel,
    StrongBodyLabel, BodyLabel, PillPushButton, MessageBoxBase,  LineEdit, PasswordLineEdit,
    ProgressRing, InfoBar, InfoBarPosition, PushButton
)
from pathlib import Path
from tools.font_config import font_config
from widgets.AvatarPicker import AvatarPickerWidget
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from tools.setting_config import SCM
import base64
import json
font_ = font_config()
configer = SCM()

LOGIN_URL = "http://localhost:5678/login"
REGISTER_URL = "http://localhost:5678/register"
config_dir = Path.home() / ".config" / "pyqt-ssh"


def set_font_recursive(widget: QWidget, font):
    if font is None:
        return
    widget.setFont(font)
    for child in widget.findChildren(QWidget):
        child.setFont(font)


class login_register_Dialog(MessageBoxBase):
    yesButtonClicked = pyqtSignal()
    cancelButtonClicked = pyqtSignal()

    def __init__(self, parent=None, login=True, username="", avatar_url="", qid="", email=""):
        super().__init__(parent)

        self.is_login_mode = login
        type_str = self.tr("Login") if login else self.tr("Register")

        self.yesButton.setText(type_str)
        self.cancelButton.setText(self.tr("Cancel"))

        # 移除原有的按钮连接，我们将完全重写事件处理
        try:
            self.yesButton.clicked.disconnect()
            self.cancelButton.clicked.disconnect()
        except:
            pass  # 如果之前没有连接，忽略错误

        # 重新连接按钮
        self.yesButton.clicked.connect(self._on_yes_clicked)
        self.cancelButton.clicked.connect(self._on_cancel_clicked)

        # 错误提示标签
        self.error_label = CaptionLabel("")
        self.error_label.setVisible(False)
        self.error_label.setStyleSheet("color: red; padding: 5px;")

        username_layout = QVBoxLayout()
        username_label_text = self.tr(
            "Username or Email") if login else self.tr("Username")
        self.username_label = QLabel(username_label_text)
        username_layout.addWidget(self.username_label)
        self.username_edit = LineEdit()
        self.username_edit.setText(username.replace(" (Local)", ""))
        self.username_edit.textChanged.connect(self._clear_error)
        username_layout.addWidget(self.username_edit)

        # 用户名错误提示
        self.username_error = CaptionLabel("")
        self.username_error.setVisible(False)
        self.username_error.setStyleSheet(
            "color: red; font-size: 11px; padding-left: 5px;")
        username_layout.addWidget(self.username_error)

        password_layout = QVBoxLayout()
        password_layout.addWidget(QLabel(self.tr("Password:")))
        self.password_edit = PasswordLineEdit()
        self.password_edit.textChanged.connect(self._clear_error)
        password_layout.addWidget(self.password_edit)

        # 密码错误提示
        self.password_error = CaptionLabel("")
        self.password_error.setVisible(False)
        self.password_error.setStyleSheet(
            "color: red; font-size: 11px; padding-left: 5px;")
        password_layout.addWidget(self.password_error)

        qid_layout = QVBoxLayout()
        self.qid_label = QLabel(self.tr("QID (Optional):"))
        qid_layout.addWidget(self.qid_label)
        self.qid_edit = LineEdit()
        self.qid_edit.setText(qid)
        qid_layout.addWidget(self.qid_edit)

        email_layout = QVBoxLayout()
        self.email_label = QLabel(self.tr("Email:"))
        email_layout.addWidget(self.email_label)
        self.email_edit = LineEdit()
        self.email_edit.setText(email)
        self.email_edit.textChanged.connect(self._clear_error)
        email_layout.addWidget(self.email_edit)

        # 邮箱错误提示
        self.email_error = CaptionLabel("")
        self.email_error.setVisible(False)
        self.email_error.setStyleSheet(
            "color: red; font-size: 11px; padding-left: 5px;")
        email_layout.addWidget(self.email_error)

        self.avatar = AvatarPickerWidget(size=90)

        self.modeButton = PushButton(self.get_mode_button_text())
        self.modeButton.clicked.connect(self.toggle_mode)

        avatar_button_layout = QHBoxLayout()
        avatar_button_layout.addWidget(self.avatar)
        avatar_button_layout.addStretch()
        avatar_button_layout.addWidget(self.modeButton)

        # 主布局
        self.viewLayout.addWidget(self.error_label)
        self.viewLayout.addSpacing(10)
        self.viewLayout.addLayout(username_layout)
        self.viewLayout.addLayout(password_layout)
        if not login:
            self.viewLayout.addLayout(qid_layout)
            self.viewLayout.addLayout(email_layout)
            self.viewLayout.addLayout(avatar_button_layout)

        self.viewLayout.addStretch()

        set_font_recursive(self, font_.get_font())

        self.network_manager = QNetworkAccessManager()
        self.network_manager.finished.connect(self.on_avatar_downloaded)

        self.set_avatar(avatar_url)

    def save_avatar(self):
        """保存头像到指定目录"""
        username = self.username_edit.text().strip()
        if not username:
            print("Username is required to save the avatar.")
            return

        # 获取保存路径（~/.config/pyqt-ssh/avatar_<username>.png）

        config_dir.mkdir(parents=True, exist_ok=True)  # 创建目录（如果不存在的话）
        avatar_path = config_dir / f"avatar_{username}.png"

        # 获取当前头像图像
        pixmap = self.avatar.pixmap()
        if pixmap.isNull():
            print("No avatar to save.")
            return

        # 将 QPixmap 转换为 QImage
        image = pixmap.toImage()

        # 保存 QImage 为 PNG 文件
        if not image.save(str(avatar_path), "PNG"):
            print(f"Failed to save avatar to {avatar_path}")
        else:
            print(f"Avatar saved to {avatar_path}")
        self.avatar_path = avatar_path

    def _on_yes_clicked(self):
        """处理确认按钮点击"""
        if self._validate_required_fields():
            # 验证通过，发射信号并关闭对话框
            self.yesButtonClicked.emit()
            self.save_avatar()
            self.accept()
        else:
            # 验证失败，不关闭对话框，只显示错误
            pass

    def _on_cancel_clicked(self):
        """处理取消按钮点击"""
        self.cancelButtonClicked.emit()
        self.reject()

    def get_mode_button_text(self):
        if self.is_login_mode:
            return self.tr("Switch to Register")
        else:
            return self.tr("Switch to Login")

    def toggle_mode(self):
        self.is_login_mode = not self.is_login_mode

        type_str = self.tr(
            "Login") if self.is_login_mode else self.tr("Register")
        self.yesButton.setText(type_str)
        self.modeButton.setText(self.get_mode_button_text())

        if self.is_login_mode:
            self.username_label.setText(self.tr("Username or Email"))
            self.qid_label.setVisible(False)
            self.qid_edit.setVisible(False)
            self.email_label.setVisible(False)
            self.email_edit.setVisible(False)
            self.avatar.setVisible(False)
            # 隐藏邮箱错误提示
            self.email_error.setVisible(False)
        else:
            self.username_label.setText(self.tr("Username"))
            self.qid_label.setVisible(True)
            self.qid_edit.setVisible(True)
            self.email_label.setVisible(True)
            self.email_edit.setVisible(True)
            self.avatar.setVisible(True)

        # 切换模式时清空所有错误
        self._clear_all_errors()

    def _validate_required_fields(self):
        """验证必填字段"""
        username = self.username_edit.text().strip()
        password = self.password_edit.text().strip()

        has_error = False

        # 清空之前的错误
        self._clear_all_errors()

        # 登录模式验证
        if self.is_login_mode:
            if not username:
                self._show_field_error(self.username_error, self.tr(
                    "Username or email is required"))
                has_error = True
            if not password:
                self._show_field_error(
                    self.password_error, self.tr("Password is required"))
                has_error = True

        # 注册模式验证
        else:
            if not username:
                self._show_field_error(
                    self.username_error, self.tr("Username is required"))
                has_error = True
            elif len(username) < 3:
                self._show_field_error(self.username_error, self.tr(
                    "Username must be at least 3 characters"))
                has_error = True

            if not password:
                self._show_field_error(
                    self.password_error, self.tr("Password is required"))
                has_error = True
            elif len(password) < 6:
                self._show_field_error(self.password_error, self.tr(
                    "Password must be at least 6 characters"))
                has_error = True

            email = self.email_edit.text().strip()
            if not email:
                self._show_field_error(
                    self.email_error, self.tr("Email is required"))
                has_error = True
            elif not self._is_valid_email(email):
                self._show_field_error(self.email_error, self.tr(
                    "Please enter a valid email address"))
                has_error = True

        if has_error:
            self.error_label.setText(self.tr("Please fix the errors below"))
            self.error_label.setVisible(True)

            # 如果有错误，将焦点设置到第一个错误的字段
            if self.is_login_mode:
                if not username:
                    self.username_edit.setFocus()
                elif not password:
                    self.password_edit.setFocus()
            else:
                if not username:
                    self.username_edit.setFocus()
                elif not password:
                    self.password_edit.setFocus()
                elif not email or not self._is_valid_email(email):
                    self.email_edit.setFocus()

            return False

        return True

    def _is_valid_email(self, email):
        """简单的邮箱格式验证"""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None

    def _show_field_error(self, error_label, message):
        """显示字段错误提示"""
        error_label.setText(f"• {message}")
        error_label.setVisible(True)

    def _clear_error(self):
        """输入内容时清除错误状态"""
        sender = self.sender()
        if sender == self.username_edit:
            self.username_error.setVisible(False)
        elif sender == self.password_edit:
            self.password_error.setVisible(False)
        elif sender == self.email_edit:
            self.email_error.setVisible(False)

        # 如果没有可见的错误，隐藏总错误标签
        if not any([
            self.username_error.isVisible(),
            self.password_error.isVisible(),
            self.email_error.isVisible()
        ]):
            self.error_label.setVisible(False)

    def _clear_all_errors(self):
        """清除所有错误状态"""
        self.error_label.setVisible(False)
        self.username_error.setVisible(False)
        self.password_error.setVisible(False)
        self.email_error.setVisible(False)

    def get_form_data(self):
        """获取表单数据"""
        return {
            'username': self.username_edit.text().strip(),
            'password': self.password_edit.text().strip(),
            'qid': self.qid_edit.text().strip() if not self.is_login_mode else "",
            'email': self.email_edit.text().strip() if not self.is_login_mode else "",
            'is_login': self.is_login_mode,
            "avatar": self.avatar_path
        }

    def set_avatar(self, avatar_url):
        if not avatar_url:
            return

        if avatar_url.startswith(('http://', 'https://')):
            self.download_avatar(avatar_url)
        else:
            self.avatar.setImage(avatar_url)

    def download_avatar(self, url):
        try:
            request = QNetworkRequest(QUrl(url))
            self.network_manager.get(request)
        except Exception as e:
            print(f"Error downloading avatar: {e}")

    def on_avatar_downloaded(self, reply):
        try:
            if reply.error():
                print(f"Failed to download avatar: {reply.errorString()}")
                return

            data = reply.readAll()
            image = QImage()
            image.loadFromData(data)

            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                self.avatar.setImage(pixmap)
            else:
                self.avatar.setDefaultAvatar()

        except Exception as e:
            print(f"Error processing downloaded avatar: {e}")
            self.avatar.setDefaultAvatar()
        finally:
            reply.deleteLater()

    @property
    def is_login(self):
        return self.is_login_mode

    @property
    def is_register(self):
        return not self.is_login_mode


class ApiUsageCard(CardWidget):
    def __init__(self, title, used, total, unit, parent=None):
        super().__init__(parent)
        self.used = used
        self.total = total
        self.unit = unit
        self.setFixedHeight(120)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)

        text_layout = QVBoxLayout()
        text_layout.setAlignment(Qt.AlignLeft)

        self.title_label = TitleLabel(self.tr(title))
        self.title_label.setStyleSheet("TitleLabel { font-size: 16px; }")

        self.usage_label = BodyLabel(
            self.tr(f"{self.used} / {self.total} {self.unit}"))
        self.usage_label.setStyleSheet(
            "BodyLabel { color: #666; font-size: 14px; }")

        self.percent_label = StrongBodyLabel(
            self.tr(f"{self.get_percentage():.1f}%"))
        self.percent_label.setStyleSheet(
            "StrongBodyLabel { font-size: 18px; color: #0078d4; }")

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.usage_label)
        text_layout.addStretch(1)
        text_layout.addWidget(self.percent_label)

        self.progress_ring = ProgressRing(self)
        self.progress_ring.setTextVisible(True)
        self.progress_ring.setFixedSize(80, 80)
        self.progress_ring.setValue(int(self.get_percentage()))

        layout.addLayout(text_layout)
        layout.addStretch(1)
        layout.addWidget(self.progress_ring)

        self.update_display()

    def get_percentage(self):
        return (self.used / self.total) * 100 if self.total else 0

    def update_display(self):
        self.usage_label.setText(
            self.tr(f"{self.used:,} / {self.total:,} {self.unit}"))
        self.percent_label.setText(self.tr(f"{self.get_percentage():.1f}%"))
        self.progress_ring.setValue(int(self.get_percentage()))
        p = self.get_percentage()
        color = "#d13438" if p > 90 else "#ffaa44" if p > 70 else "#0078d4"
        self.percent_label.setStyleSheet(
            f"StrongBodyLabel {{ font-size: 18px; color: {color}; }}")


class AccountInfoCard(SimpleCardWidget):
    def __init__(self, username=None, qid=None, email=None, avatar_url=None, combo=None, parent=None):
        super().__init__(parent)
        self.setFixedHeight(140)
        self.setContentsMargins(15, 16, 15, 16)
        self.avatar_url = avatar_url
        self.login_to_cloud()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(15)

        self.avatar = AvatarPickerWidget()
        self.avatar.setFixedSize(64, 64)
        layout.addWidget(self.avatar, 0, Qt.AlignVCenter)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(8)
        info_layout.setContentsMargins(0, 5, 0, 5)

        name = username or self.tr("Guest")
        upgrade_text = self.tr(
            "Login or Register") if not self.apikey else self.tr("Upgrade")

        self.name_label = TitleLabel(name, self)
        self.name_label.setStyleSheet("font-size: 18px; font-weight: 600;")

        self.qid_label = CaptionLabel(
            self.tr(f"QID: {qid}") if qid else self.tr("QID: "), self)
        self.email_label = CaptionLabel(email or "", self)
        self.email_label.setStyleSheet("color: #666;")
        self.combo = CaptionLabel(self.tr(f"{combo}") if combo else "", self)

        info_layout.addWidget(self.name_label)
        info_layout.addWidget(self.qid_label)
        info_layout.addWidget(self.email_label)
        info_layout.addWidget(self.combo)
        info_layout.addStretch(1)

        layout.addLayout(info_layout, stretch=1)

        button_layout = QVBoxLayout()
        button_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.upgrade_btn = PillPushButton(upgrade_text)
        self.upgrade_btn.setFixedWidth(150)
        button_layout.addWidget(self.upgrade_btn)
        button_layout.addStretch(1)
        layout.addLayout(button_layout)

        self.qid_label.setVisible(bool(qid))
        self.email_label.setVisible(bool(email))
        self.combo.setVisible(bool(combo))

        self._network_manager = QNetworkAccessManager()
        self._tmp_avatar_file = None
        self._set_avatar(username, avatar_url)

    def login_to_cloud(self):
        self.apikey = configer.read_config().get("account", {}).get("apikey", "")

    def _set_avatar(self, username, avatar_url):
        print(avatar_url)
        if self._tmp_avatar_file and os.path.exists(self._tmp_avatar_file):
            try:
                os.remove(self._tmp_avatar_file)
            except:
                pass
            self._tmp_avatar_file = None

        if avatar_url and avatar_url.startswith("http"):
            request = QNetworkRequest(QUrl(avatar_url))
            reply = self._network_manager.get(request)
            self._current_reply = reply
            reply.finished.connect(
                lambda r=reply, u=username: self._on_avatar_downloaded(r, u))
        elif avatar_url and os.path.exists(avatar_url):
            self.avatar.setImage(avatar_url)
        else:
            self._set_default_avatar(username)

    def _on_avatar_downloaded(self, reply, username):
        if hasattr(self, '_current_reply') and self._current_reply == reply:
            self._current_reply = None
        if reply.error():
            self._set_default_avatar(username)
            reply.deleteLater()
            return
        data = reply.readAll()
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.avatar.setPixmap(pixmap)
        else:
            self._set_default_avatar(username)
        reply.deleteLater()

    def _set_default_avatar(self, username):
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#D0D0D0"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, 64, 64)
        painter.setPen(QColor("#555"))
        painter.setFont(QFont("Segoe UI", 20, QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter,
                         (username[:1] if username else "G").upper())
        painter.end()
        self.avatar.setPixmap(pixmap)

    def update_account_info(self, username=None, qid=None, email=None, combo=None, avatar_url=None):
        self.name_label.setText(username or self.tr("Guest"))

        if qid:
            self.qid_label.setText(self.tr(f"QID: {qid}"))
            self.qid_label.setVisible(True)
        else:
            self.qid_label.setVisible(False)

        if email:
            self.email_label.setText(email)
            self.email_label.setVisible(True)
        else:
            self.email_label.setVisible(False)

        if combo:
            self.combo.setText(self.tr(str(combo)))
            self.combo.setVisible(True)
        else:
            self.combo.setVisible(False)

        self.username = username
        self.avatar_url = avatar_url
        self.upgrade_btn.setText(
            self.tr("Login or Register") if self.apikey else self.tr("Upgrade"))
        self._set_avatar(username, avatar_url)


class BillingCard(CardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(120)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)

        title_label = TitleLabel(self.tr("Account Balance"))
        title_label.setStyleSheet("TitleLabel { font-size: 16px; }")

        balance_layout = QHBoxLayout()
        self.balance_label = StrongBodyLabel(self.tr("¥ 0.00"))
        self.balance_label.setStyleSheet(
            "StrongBodyLabel { font-size: 24px; color: #107c10; }")
        # self.recharge_btn = PrimaryPushButton(self.tr("Recharge Now"))
        # self.recharge_btn.setFixedWidth(100)

        balance_layout.addWidget(self.balance_label)
        balance_layout.addStretch(1)
        # balance_layout.addWidget(self.recharge_btn)

        self.billing_label = CaptionLabel(self.tr("Next billing date: None"))
        self.billing_label.setStyleSheet("CaptionLabel { color: #666; }")

        layout.addWidget(title_label)
        layout.addSpacing(10)
        layout.addLayout(balance_layout)
        layout.addSpacing(5)
        layout.addWidget(self.billing_label)


class AccountPage(QWidget):
    def __init__(self, username=None, qid=None, email=None,  avatar_url=None, combo=None, parent=None):
        super().__init__(parent)
        self.username = username
        self.qid = qid
        self.email = email
        self.avatar_url = avatar_url
        self.combo = combo
        self._network_manager = QNetworkAccessManager()
        self._network_manager.finished.connect(self.on_request_finished)
        self.setup_ui()
        # self.timer = QTimer(self)
        # self.timer.timeout.connect(self.update_data)
        # self.timer.start(5000)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(30, 20, 30, 20)

        title_label = TitleLabel(self.tr("Account Information"))
        title_label.setStyleSheet(
            "TitleLabel { font-size: 24px; padding: 10px 0; }")

        self.account_card = AccountInfoCard(
            username=self.username, qid=self.qid, email=self.email, avatar_url=self.avatar_url, combo=self.combo
        )

        usage_grid = QGridLayout()
        usage_grid.setSpacing(15)
        self.api_cards = [
            ApiUsageCard(self.tr("API Calls"), 0, 0, self.tr("times")),
            ApiUsageCard(self.tr("Tokens Usage"), 0, 0, self.tr("tokens")),
        ]
        for i, card in enumerate(self.api_cards):
            row, col = divmod(i, 2)
            usage_grid.addWidget(card, row, col)

        self.billing_card = BillingCard()
        layout.addWidget(title_label)
        layout.addWidget(self.account_card)
        layout.addSpacing(10)
        layout.addLayout(usage_grid)
        layout.addSpacing(10)
        layout.addWidget(self.billing_card)
        layout.addStretch(1)
        self.connect_signals()
        self.auto_login()

    def auto_login(self):
        if self.account_card.apikey:
            config = configer.read_config()
            username = config.get("account", {}).get("user", "")
            password = config.get("account", {}).get("password", "")
            if username and password:
                self.password = password
                form_data = {
                    "username": username,
                    "password": password
                }
                request = QNetworkRequest(QUrl(LOGIN_URL))
                request.setHeader(
                    QNetworkRequest.ContentTypeHeader, "application/json")
                byte_array = QByteArray(
                    json.dumps(form_data).encode('utf-8'))
                self._network_manager.post(request, byte_array)
        else:
            pass

    def login(self):
        if self.account_card.upgrade_btn.text() == self.tr("Upgrade"):
            pass
        elif self.account_card.upgrade_btn.text() == self.tr("Verify Email"):
            pass
        else:  # Login or Register
            dialog = login_register_Dialog(
                self, login=False, avatar_url=self.avatar_url, username=self.username, qid=self.qid, email=self.email)
            if dialog.exec_():
                form_data = dialog.get_form_data()
                url = LOGIN_URL
                if not form_data["is_login"]:
                    img = b""
                    if dialog.avatar_path:
                        img = base64.b64encode(
                            open(dialog.avatar_path, "rb").read()).decode('utf-8')
                    # print(len(img), img[20:])
                    form_data.update({"avatar": img})
                    url = REGISTER_URL
                else:
                    form_data.pop("avatar", None)
                    form_data.pop("email", None)
                    form_data.pop("qid", None)
                self.passwrod = form_data["password"]
                request = QNetworkRequest(QUrl(url))
                request.setHeader(
                    QNetworkRequest.ContentTypeHeader, "application/json")
                byte_array = QByteArray(json.dumps(form_data).encode('utf-8'))
                self._network_manager.post(request, byte_array)

            else:
                pass

    def on_request_finished(self, reply):
        """
        请求完成时的回调
        """

        def info_show(title, content, status=True):
            if status:
                InfoBar.info(
                    title=title,
                    content=content,
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=3000, parent=self
                )
            else:
                InfoBar.error(
                    title=title,
                    content=content,
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=-1, parent=self
                )

        status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        print(f"HTTP状态码: {status_code}")
        print(f"网络错误: {reply.error()} - {reply.errorString()}")

        if reply.error():
            response_data = reply.readAll().data()
            response_text = response_data.decode(
                'utf-8') if response_data else ""
            # print(f"错误响应内容: {response_text}")

            try:
                if response_text:
                    error_response = json.loads(response_text)
                    error_message = error_response.get(
                        'error') or error_response.get('message') or response_text
                else:
                    error_message = reply.errorString()
            except:
                error_message = reply.errorString()

            if status_code == 409:
                info_show(self.tr("Registration Conflict"),
                          self.tr("Username or email already registered, please use other information"), False)
            elif status_code == 400:
                info_show(self.tr("Request Error"),
                          self.tr("Request parameters are incorrect, please check the information"), False)
            elif status_code == 401:
                info_show(self.tr("Authentication Failed"),
                          self.tr("Username or password is incorrect"), False)
            else:
                info_show(self.tr("Request Failed"),
                          self.tr(f"Error: {error_message}"), False)

        else:
            response_data = reply.readAll().data()
            response_text = response_data.decode('utf-8')
            print(f"成功响应: {response_text}")

            try:
                json_response = json.loads(response_text)
                success = json_response.get("success")
                message = json_response.get("message")
                username = json_response.get("username")
                email = json_response.get("email")
                qid = json_response.get("qid")
                self.email_verified = json_response.get("email_verified")
                api_key = json_response.get("api_key")
                combo = json_response.get("combo")
                type_ = json_response.get("type")

                config = configer.read_config()["account"]
                config["user"] = username
                config["email"] = email
                config["qid"] = qid
                config["combo"] = combo
                config["apikey"] = api_key
                config["password"] = self.password

                if type_ == "login":
                    if not success:
                        info_show(self.tr("Login Failed"),
                                  self.tr(message), False)
                        reply.deleteLater()
                        return
                    avatar = json_response.get("avatar")
                    if avatar:
                        try:
                            b64_img = base64.b64decode(avatar)
                            avatar_path = config_dir / f"avatar_{username}.png"
                            with open(avatar_path, 'wb') as f:
                                f.write(b64_img)
                            config["avatar_url"] = str(avatar_path)
                        except Exception as e:
                            print(f"头像保存失败: {e}")
                            message += self.tr(
                                "\nAvatar save failed (you may not have uploaded an avatar)")
                    configer.revise_config("account", config)
                    info_show(self.tr("Login Successful"),
                              self.tr(message), True)

                    self.update_account_info(
                        username=username,
                        qid=qid,
                        email=email,
                        combo=combo,
                        avatar_url=config.get("avatar_url")
                    )
                    if not self.email_verified:
                        self.account_card.upgrade_btn.setText(
                            self.tr("Verify Email"))
                else:
                    if not success:
                        info_show(self.tr("Registration Failed"),
                                  self.tr(message), False)
                        reply.deleteLater()
                        return

                    configer.revise_config("account", config)
                    info_show(self.tr("Registration Successful"),
                              self.tr("Registration successful! Please log in with your new account"), True)
                    self.account_card.upgrade_btn.setText(
                        self.tr("Verify Email"))

            except json.JSONDecodeError as e:
                info_show(self.tr("Response Parse Failed"),
                          self.tr(f"Server returned invalid JSON data: {e}"), False)
            except Exception as e:
                info_show(self.tr("Processing Error"),
                          self.tr(f"An error occurred while processing the response: {e}"), False)

        reply.deleteLater()

    def connect_signals(self):

        # self.billing_card.recharge_btn.clicked.connect(
        #     self.show_recharge_dialog)
        self.account_card.upgrade_btn.clicked.connect(self.login)

    def show_recharge_dialog(self):
        InfoBar.info(
            title=self.tr("Recharge Function"),
            content=self.tr("Recharge function is under development..."),
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=2000, parent=self
        )

    def show_upgrade_dialog(self):
        InfoBar.info(
            title=self.tr("Upgrade Account"),
            content=self.tr(
                "Account upgrade function is under development..."),
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=2000, parent=self
        )

    def update_data(self):
        for card in self.api_cards:
            increment = random.randint(1, 10)
            card.used = min(card.used + increment, card.total)
            card.update_display()
        current_balance_text = self.billing_card.balance_label.text().replace(
            "¥ ", "").replace(self.tr("¥ "), "")
        try:
            current_balance = float(current_balance_text)
            new_balance = current_balance + random.uniform(0.01, 0.1)
            self.billing_card.balance_label.setText(
                self.tr(f"¥ {new_balance:.2f}"))
        except ValueError:
            self.billing_card.balance_label.setText(self.tr("¥ 0.00"))

    def update_account_info(self, username=None, qid=None, email=None, combo=None, avatar_url=None):
        self.username, self.qid, self.email, self.avatar_url = username, qid, email, avatar_url
        self.account_card.update_account_info(
            username=username, qid=qid, email=email, combo=combo, avatar_url=avatar_url
        )
