from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor, QStandardItemModel, QStandardItem
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QSizePolicy
from qfluentwidgets import TableView, isDarkTheme, PrimaryPushButton
from widgets.network_widget import NetMonitor


class Tasks(QFrame):
    def __init__(self, font, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background: transparent;")
        self.setMinimumHeight(100)
        self.netmonitor = NetMonitor()
        self.netmonitor.setMinimumHeight(80)
        self.netmonitor.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.netmonitor.setStyleSheet("""
                QFrame#netmonitor
                {
                    background-color: rgba(220, 220, 220, 0.06);
                    border: 1px solid rgba(0,0,0,0.06);
                    border-radius: 6px;
                }
            """)
        self.font_ = font
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ✅ 使用 QFluentWidgets 的 TableView
        self.table = TableView(self)
        self.model = QStandardItemModel(0, 3, self)
        self.model.setHorizontalHeaderLabels(["RAM", "CPU", "NAME"])
        self.table.setModel(self.model)

        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(self.table.NoSelection)
        self.table.setEditTriggers(self.table.NoEditTriggers)
        self.table.setAlternatingRowColors(False)

        # 样式
        self.table.setShowGrid(False)
        self.table.setCornerButtonEnabled(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setStyleSheet("""
            TableView {
                border: none;
                background: transparent;
            }
            TableView::item {
                padding: 4px;
            }
        """)

        # 水平表头也可以透明
        self.table.horizontalHeader().setStyleSheet("""
            QHeaderView::section {
                background: transparent;
                border: none;
                color: white; /* 或者根据主题切换 */
                font-weight: bold;
                padding: 4px;
            }
        """)

        self.sysinfo_button = PrimaryPushButton("System Info")
        self.sysinfo_button.setCursor(Qt.PointingHandCursor)
        self.sysinfo_button.setStyleSheet("""
            PrimaryPushButton {
                background: transparent;
                border: none;
                color: #0078D4;
                font-weight: bold;
            }
            PrimaryPushButton:hover {
                text-decoration: underline;
            }
        """)

        layout.addWidget(self.table)
        layout.addWidget(self.sysinfo_button)
        layout.addWidget(self.netmonitor)
        self.text_color = "#ffffff" if isDarkTheme() else "#000000"

    def set_text_color(self, color_hex: str):
        self.text_color = color_hex

    def add_row(self, mem_mb, cpu, cmd):
        # if self.model.rowCount() >= 4:
        #     self.model.removeRows(0, self.model.rowCount())

        items = []

        # RAM
        try:
            mem_value = float(mem_mb)
            if mem_value >= 1024:
                mem_formatted = f"{mem_value / 1024:.1f}G"
            else:
                mem_formatted = f"{mem_value:.1f}M"
        except (ValueError, TypeError):
            mem_formatted = str(mem_mb)

        mem_item = QStandardItem(mem_formatted)
        mem_item.setTextAlignment(Qt.AlignCenter)
        mem_item.setFont(QFont(self.font_))
        mem_item.setForeground(QColor(self.text_color))
        items.append(mem_item)

        # CPU
        cpu_item = QStandardItem(str(f"{cpu} %"))
        cpu_item.setTextAlignment(Qt.AlignCenter)
        cpu_item.setFont(QFont(self.font_))
        cpu_item.setForeground(QColor(self.text_color))
        items.append(cpu_item)

        # NAME / Command
        cmd_item = QStandardItem(str(cmd))
        cmd_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        cmd_item.setFont(QFont(self.font_))
        cmd_item.setForeground(QColor(self.text_color))
        items.append(cmd_item)

        self.model.appendRow(items)

        # 可选：固定行高
        row_index = self.model.rowCount() - 1
        self.table.setRowHeight(row_index, 32)

    def _bold_font(self):
        font = QFont()
        font.setBold(True)
        return font

    # def set_netmonitor(self, upload, download):
    #     self.netmonitor.update_speed(
    #         upload_kbps=upload, download_kbps=download)

    def clear_rows(self):
        """清空表格所有行（安全）。"""
        try:
            row_count = self.model.rowCount()
            if row_count:
                self.model.removeRows(0, row_count)
        except Exception as e:
            print(f"clear_rows failed: {e}")
