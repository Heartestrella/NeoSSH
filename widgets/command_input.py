from PyQt5.QtCore import Qt, pyqtSignal, QRect, QPoint, QEvent, QStringListModel, QTimer
from PyQt5.QtGui import QFont, QFontMetrics
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QWidget, QFrame, QVBoxLayout, QLabel
from qfluentwidgets import TextEdit, ListView, VBoxLayout, ToolButton, FluentIcon
import re
import json


class OneSuggestionPopup(QFrame):
    def __init__(self, parent=None, max_width=440):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)
        self.suggestion_accepted = False
        self.max_width = max_width
        self.is_error_state = False  # 新增错误状态标记
        self.is_loading_state = False  # 新增加载状态标记

        self.setMinimumSize(150, 50)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowFlags(self.windowFlags() | Qt.Tool)
        self.setFocusPolicy(Qt.NoFocus)

        self.setObjectName("one_sugg_popup")
        self.setStyleSheet("""
            QFrame#one_sugg_popup {
                border-radius: 12px;
                background: rgb(29,29,29);
                border: 1px solid rgba(255,255,255,10);
            }
            QLabel { color: #FFFFFF; padding: 4px 8px; }
            QLabel#cmd_label { font-family: "Courier New", monospace; }
            QLabel#error_label { color: #FF6B6B; }  /* 错误样式 */
            QLabel#loading_label { color: #4ECDC4; }  /* 加载样式 */
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # 解释标签 - 支持不同状态
        self.expl_label = QLabel("", self)
        self.expl_label.setWordWrap(True)
        self.expl_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        font = QFont()
        font.setPointSize(10)
        font.setStyleStrategy(QFont.PreferAntialias)
        self.expl_label.setFont(font)

        # 命令标签
        self.cmd_label = QLabel("", self)
        self.cmd_label.setWordWrap(True)
        self.cmd_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.cmd_label.setFont(QFont("Courier New", 10))
        self.cmd_label.setObjectName("cmd_label")
        self.cmd_label.setStyleSheet("color: #00FF00; padding: 4px;")

        layout.addWidget(self.expl_label)
        layout.addWidget(self.cmd_label)

        self.hide()

    def show_suggestion(self, explanation: str = None, command: str = None,
                        input_widget=None, is_error=False, is_loading=False):
        """显示建议弹窗

        Args:
            explanation: 解释文本
            command: 命令文本
            input_widget: 关联的输入控件
            is_error: 是否为错误状态
            is_loading: 是否为加载状态
        """
        # 重置状态
        self.is_error_state = is_error
        self.is_loading_state = is_loading

        # 根据状态设置样式
        if is_error:
            self.expl_label.setObjectName("error_label")
            self.setStyleSheet(self.styleSheet() + """
                QFrame#one_sugg_popup { border: 1px solid #FF6B6B; }
            """)
        elif is_loading:
            self.expl_label.setObjectName("loading_label")
            self.setStyleSheet(self.styleSheet() + """
                QFrame#one_sugg_popup { border: 1px solid #4ECDC4; }
            """)
        else:
            self.expl_label.setObjectName("")
            self.setStyleSheet(self.styleSheet() + """
                QFrame#one_sugg_popup { border: 1px solid rgba(255,255,255,10); }
            """)

        # 更新内容
        if explanation is not None:
            self.expl_label.setText(explanation)
        if command is not None:
            self.cmd_label.setText(command)

        # 错误状态下隐藏命令显示
        if is_error:
            self.cmd_label.hide()
        else:
            self.cmd_label.show()

        # 计算和调整大小
        self._adjust_size()

        # 定位到输入控件
        if input_widget:
            self._position_relative_to_widget(input_widget)

        self.show()

    def _adjust_size(self):
        """调整弹窗大小"""
        fm_expl = QFontMetrics(self.expl_label.font())
        fm_cmd = QFontMetrics(self.cmd_label.font())

        expl_width = max([fm_expl.horizontalAdvance(line)
                          for line in self.expl_label.text().split('\n')] + [0])
        cmd_width = max([fm_cmd.horizontalAdvance(line)
                        for line in self.cmd_label.text().split('\n')] + [0])

        raw_width = max(expl_width, cmd_width) + 16
        min_width = 200
        desired_w = max(min_width, min(self.max_width, raw_width))

        self.expl_label.setFixedWidth(desired_w - 8)
        if not self.is_error_state:  # 错误状态下不调整命令标签
            self.cmd_label.setFixedWidth(desired_w - 8)

        self.expl_label.adjustSize()
        if not self.is_error_state:
            self.cmd_label.adjustSize()
        self.adjustSize()

    def _position_relative_to_widget(self, input_widget):
        """相对于输入控件定位"""
        rect = input_widget.rect()
        top_left = input_widget.mapToGlobal(rect.topLeft())

        x = top_left.x()
        y = top_left.y() - self.height() - 6

        screen_geo = QApplication.desktop().availableGeometry(input_widget)
        if y < screen_geo.top():
            y = input_widget.mapToGlobal(rect.bottomLeft()).y() + 6
        if x + self.width() > screen_geo.right():
            x = max(screen_geo.left(), screen_geo.right() - self.width() - 6)

        self.move(QPoint(x, y))

    def hide_suggestion(self):
        """隐藏建议并重置状态"""
        self.is_error_state = False
        self.is_loading_state = False
        self.hide()

    def start_loading_animation(self, parent_widget):
        """开始加载动画"""
        self.is_loading_state = True
        if hasattr(parent_widget, 'timer') and not parent_widget.timer.isActive():
            parent_widget.frame_index = 0
            parent_widget.timer.start(500)  # 500ms 间隔

    def stop_loading_animation(self, parent_widget):
        """停止加载动画"""
        self.is_loading_state = False
        if hasattr(parent_widget, 'timer') and parent_widget.timer.isActive():
            parent_widget.timer.stop()

    def set_font(self, font):
        self.expl_label.setFont(font)
        self.cmd_label.setFont(font)


class CommandInput(TextEdit):
    executeCommand = pyqtSignal(str)
    clear_history_ = pyqtSignal()

    def __init__(self, font_name, use_ai, parent=None):
        super().__init__(parent)
        self.use_ai = use_ai
        self.setAcceptRichText(False)
        font = QFont(font_name)
        self.partial_output = ""
        self.suggestionpopup = OneSuggestionPopup(self, max_width=440)
        self.suggestionpopup.set_font(font)
        self.setFont(font)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.frames = [".", "..", "..."]
        self.frame_index = 0
        self._history_model = QStringListModel()
        self._history_view = ListView(None)
        self._history_view.setModel(self._history_model)
        self._history_view.setSelectionMode(ListView.SingleSelection)
        self._history_view.setEditTriggers(ListView.NoEditTriggers)
        self._history_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._history_view.clicked.connect(self._on_history_index_clicked)
        self._history_view.activated.connect(self._on_history_index_activated)
        self._history_view.setFocusPolicy(Qt.NoFocus)

        flags = Qt.Tool | Qt.FramelessWindowHint
        self._history_popup = QWidget(None, flags)
        self._history_popup.setAttribute(Qt.WA_TranslucentBackground, False)
        self._history_popup.setWindowOpacity(1.0)
        self._history_popup.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._history_popup.setFocusPolicy(Qt.NoFocus)

        layout = VBoxLayout(self._history_popup)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)

        clear_btn = ToolButton(FluentIcon.BROOM, self)
        clear_btn.setFixedSize(22, 22)
        clear_btn.setFocusPolicy(Qt.NoFocus)
        clear_btn.setToolTip(self.tr("Clean History"))
        clear_btn.setStyleSheet("""
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
        clear_btn.clicked.connect(self.clear_history)

        toolbar.addStretch()
        toolbar.addWidget(clear_btn)

        layout.addLayout(toolbar)
        layout.addWidget(self._history_view)

        self._history_popup.setStyleSheet("""
            QWidget {
                background-color: rgb(29, 29, 29);
                border: 1px solid rgb(50, 50, 50);
                border-radius: 8px;
            }
            ListView::item {
                height: 24px;
                padding: 2px 8px;
                color: rgb(220, 220, 220);
            }
            ListView::item:hover {
                background-color: rgb(45, 45, 45);
                border-radius: 4px;
            }
            ListView::item:selected {
                background-color: rgb(70, 70, 70);
                border-radius: 4px;
                color: white;
            }
        """)

        self._history = []

        QApplication.instance().installEventFilter(self)

        self.textChanged.connect(self._on_text_changed)

    def add_history(self, cmd):
        if isinstance(cmd, (list, tuple)):
            for c in cmd:
                self.add_history(c)
            return

        cmd = (cmd or "").strip()
        if not cmd:
            return

        if cmd in self._history:
            self._history.remove(cmd)
        self._history.insert(0, cmd)

        self._refresh_history_model(self.toPlainText())

    def remove_history(self, cmd: str):
        while cmd in self._history:
            self._history.remove(cmd)
        self._refresh_history_model(self.toPlainText())

    def clear_history(self):
        self._history.clear()
        self._refresh_history_model(self.toPlainText())
        self.hide_history()
        self.clear_history_.emit()

    def _on_text_changed(self):
        current = self.toPlainText()
        self._refresh_history_model(current)

    def _refresh_history_model(self, filter_text: str):
        if not self._history:
            self._history_model.setStringList([])
            return

        ft = (filter_text or "").strip().lower()

        if ft == "":
            display_list = list(self._history)
        else:
            starts = []
            contains = []
            others = []
            for idx, h in enumerate(self._history):
                h_lower = h.lower()
                if h_lower.startswith(ft):
                    starts.append((idx, h))
                elif ft in h_lower:
                    contains.append((idx, h))
                else:
                    others.append((idx, h))
            display_list = [h for _, h in starts] + \
                [h for _, h in contains] + [h for _, h in others]

        self._history_model.setStringList(display_list)

        if self._history_popup.isVisible():
            if self._history_model.rowCount() > 0:
                idx0 = self._history_model.index(0, 0)
                if idx0.isValid():
                    self._history_view.setCurrentIndex(idx0)

    def show_history(self):
        if self._history_model.rowCount() == 0:
            return

        self._refresh_history_model(self.toPlainText())
        self._adjust_history_popup_position()
        self._history_popup.show()
        self._history_popup.raise_()
        self.setFocus()

        if not self._history_view.selectionModel().hasSelection():
            idx = self._history_model.index(0, 0)
            if idx.isValid():
                self._history_view.setCurrentIndex(idx)

    def hide_history(self):
        if self._history_popup.isVisible():
            self._history_popup.hide()
            self.setFocus()

    def toggle_history(self):
        if self._history_popup.isVisible():
            self.hide_history()
        else:
            self.show_history()

    def _adjust_history_popup_position(self):
        global_pos = self.mapToGlobal(QPoint(0, 0))
        input_rect = QRect(global_pos, self.size())

        screen = QApplication.screenAt(global_pos)
        screen_geom = screen.availableGeometry(
        ) if screen else QApplication.desktop().availableGeometry()

        count = max(0, self._history_model.rowCount())
        fm = self.fontMetrics()
        row_h = fm.height() + 4
        max_rows = min(10, max(1, count))
        popup_h = min(300, row_h * max_rows + 30)
        popup_w = max(self.width(), 220)

        x = input_rect.left()
        y_above = input_rect.top() - popup_h
        y_below = input_rect.bottom()

        if y_above >= screen_geom.top():
            y = y_above
        else:
            if y_below + popup_h <= screen_geom.bottom():
                y = y_below
            else:
                y = max(screen_geom.top(), screen_geom.bottom() - popup_h)

        self._history_popup.setGeometry(x, y, popup_w, popup_h)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide_history()
            self.timer.stop()
            self.suggestionpopup.hide()
            return

        # 如果 popup 可见，把方向键 / 回车 转发给 listview（即使输入框仍然聚焦）
        if self._history_popup.isVisible():
            if event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End):
                QApplication.sendEvent(self._history_view, event)
                return
            elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._on_history_index_activated()
                return

        # 已经废弃该Agent功能
        # if event.key() == Qt.Key_O and event.modifiers() == Qt.ControlModifier:

        #     print("pressed Alt+O")
        #     if self.use_ai:
        #         self._generate()
        #         return

        if event.key() == Qt.Key_Tab and self.suggestionpopup.isVisible():
            # accept suggestion
            suggested = self.suggestionpopup.cmd_label.text()
            if suggested:
                self.setText(suggested)
                self.setFocus()
                # self.setCursorPosition(len(suggested))
            self.suggestionpopup.hide()

            return

        if event.key() == Qt.Key_Up:
            cursor = self.textCursor()
            at_start = cursor.position() == 0 and cursor.blockNumber() == 0
            if at_start:
                self.show_history()
                return

        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not (event.modifiers() & Qt.ShiftModifier):
                command = self.toPlainText()
                self.executeCommand.emit(command)
                self.add_history(command)
                if command.strip():
                    self.add_history(command)
                self.clear()
                return
            else:
                super().keyPressEvent(event)
                return

        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        new_focus = QApplication.focusWidget()
        if new_focus is None or not (
            new_focus is self._history_popup
            or self._history_popup.isAncestorOf(new_focus)
            or new_focus is self
            or self.isAncestorOf(new_focus)
        ):
            self.timer.stop()
            self.hide_history()
            self.suggestionpopup.hide()
        super().focusOutEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            if self._history_popup.isVisible():
                w = QApplication.widgetAt(event.globalPos())
                if w is None:
                    self.hide_history()
                else:
                    if not (
                        w is self._history_popup
                        or self._history_popup.isAncestorOf(w)
                        or w is self
                        or self.isAncestorOf(w)
                    ):
                        self.hide_history()
        return super().eventFilter(obj, event)

    def _on_history_index_clicked(self, index):
        if index and index.isValid():
            self._fill_from_history(index.data())
            self.hide_history()

    def _on_history_index_activated(self, index=None):
        if index is None:
            index = self._history_view.currentIndex()
        if index and index.isValid():
            self._fill_from_history(index.data())
        self.hide_history()

    def _fill_from_history(self, cmd: str):
        self.setPlainText(cmd)
        cursor = self.textCursor()
        cursor.movePosition(cursor.End)
        self.setTextCursor(cursor)
        self.setFocus()

    def _on_partial_result(self, msg: str):

        self.partial_output += msg

        cmd_match = re.search(
            r'"command"\s*:\s*(\[[^\]]*\])', self.partial_output, re.S)
        if cmd_match:
            try:
                commands = json.loads(cmd_match.group(1))
                self.timer.stop()

                command, lines = commands
                if command:
                    self.suggestionpopup.show_suggestion(
                        command=command, input_widget=self)
                else:
                    self.suggestionpopup.hide()

            except Exception:
                pass

        exp_match = re.search(
            r'"explanation"\s*:\s*"([^"]*)', self.partial_output, re.S)
        if exp_match:
            print(exp_match.group(1))
            self.suggestionpopup.show_suggestion(
                explanation=exp_match.group(1), input_widget=self)

    def clear_out(self):
        self.partial_output = ""

    def suggestion_error(self, msg):
        if hasattr(self, 'timer') and self.timer.isActive():
            self.timer.stop()

        if self.suggestionpopup.isVisible():
            self.suggestionpopup.hide()

        self.suggestionpopup.show_suggestion(
            explanation=f"❌ {msg}",
            command="",
            input_widget=self,
            is_error=True
        )

    def update_frame(self):
        if not getattr(self.suggestionpopup, 'is_error_state', False):
            self.suggestionpopup.show_suggestion(
                explanation=self.frames[self.frame_index],
                command="",
                input_widget=self,
                is_loading=True
            )
            self.frame_index = (self.frame_index + 1) % len(self.frames)

    def cleanup_history(self):
        try:
            QApplication.instance().removeEventFilter(self)
        except Exception:
            pass
        try:
            self._shortcut_toggle.activated.disconnect()
            self._shortcut_toggle.setParent(None)
        except Exception:
            pass
        try:
            self._history_popup.hide()
        except Exception:
            pass
