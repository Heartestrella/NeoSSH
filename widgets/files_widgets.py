
from PyQt5.QtWidgets import (QApplication, QWidget, QLayout, QSizePolicy, QLabel,
                             QRubberBand,  QVBoxLayout, QTableView, QHeaderView, QAbstractItemDelegate, QStyledItemDelegate, QStyle, QFileDialog)
from PyQt5.QtGui import QFont, QPainter, QColor, QStandardItemModel, QStandardItem
from PyQt5.QtCore import Qt, QRect, QSize, QPoint, pyqtSignal
from qfluentwidgets import RoundMenu, Action, FluentIcon as FIF, LineEdit, ScrollArea, TableView, CheckableMenu
import os
import time
from qfluentwidgets import isDarkTheme
from tools.setting_config import SCM

configer = SCM()


def _format_size(size_bytes):
    """Format size in bytes to a human-readable string."""
    try:
        # Convert to int, treating None, empty string, etc. as 0
        if size_bytes is None or size_bytes == '':
            size_bytes = 0
        else:
            size_bytes = int(size_bytes)

        if size_bytes == 0:
            return "0 B"

        size_names = ("B", "KB", "MB", "GB", "TB")
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        return f"{round(size_bytes, 2)} {size_names[i]}"
    except (ValueError, TypeError):
        return "0 B"  # Return "0 B" for any conversion errors


def _normalize_files_data(files):
    """Normalize different input formats to a standard list of tuples."""
    entries = []
    if not files:
        return entries

    if isinstance(files, dict):
        # Assuming dict provides {name: is_dir}
        for name, val in files.items():
            is_dir = True if (
                val is True or isinstance(val, dict)) else False
            entries.append(
                (str(name), is_dir, '', '', '', ''))
    elif isinstance(files, (list, tuple)):
        for entry in files:
            if isinstance(entry, dict):
                name = entry.get("name", "")
                is_dir = entry.get("is_dir", False)
                size = entry.get("size", 0)
                mod_time = entry.get("mtime", "")
                perms = entry.get("perms", "")
                owner = entry.get("owner", "")
                entries.append(
                    (name, is_dir, size, mod_time, perms, owner))
            elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                # Basic ("name", is_dir) provided
                name, is_dir = entry[0], bool(entry[1])
                entries.append(
                    (str(name), is_dir, '', '', '', ''))
    return entries


# ---------------- FlowLayout ----------------


class FlowLayout(QLayout):

    def __init__(self, parent=None, margin=10, spacing=20):
        super().__init__(parent)
        self.itemList = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):
        self.itemList.append(item)

    def count(self):
        return len(self.itemList)

    def itemAt(self, index):
        return self.itemList[index] if 0 <= index < len(self.itemList) else None

    def takeAt(self, index):
        return self.itemList.pop(index) if 0 <= index < len(self.itemList) else None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.doLayout(rect, False)

    def sizeHint(self):
        return QSize(400, 300)

    def doLayout(self, rect, testOnly):
        x, y = rect.x(), rect.y()
        lineHeight = 0
        for item in self.itemList:
            wid = item.widget()
            spaceX = self.spacing()
            spaceY = self.spacing()
            nextX = x + wid.sizeHint().width() + spaceX
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spaceY
                nextX = x + wid.sizeHint().width() + spaceX
                lineHeight = 0
            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), wid.sizeHint()))
            x = nextX
            lineHeight = max(lineHeight, wid.sizeHint().height())
        return y + lineHeight - rect.y()


class FileActionsManager:
    """Manages the creation and connection of file operation actions."""

    def __init__(self, action_emitter, rename_handler, action_factory):
        """
        Initializes the action manager.

        Args:
            action_emitter (callable): A function to call when an action is triggered.
                                     It should accept action_type and an optional parameter.
            rename_handler (callable): A specific function to call for the rename action.
            action_factory (callable): A function that returns a dictionary of new QActions.
        """
        self.actions = action_factory()
        self.pick = self.actions["pick"]
        self.copy = self.actions["copy"]
        self.delete = self.actions["delete"]
        self.cut = self.actions["cut"]
        self.download = self.actions["download"]
        self.download_compression = self.actions["download_compression"]
        self.copy_path = self.actions["copy_path"]
        self.info = self.actions["info"]
        self.rename = self.actions["rename"]

        self.pick.triggered.connect(lambda: action_emitter('pick'))
        self.copy.triggered.connect(lambda: action_emitter('copy'))
        self.delete.triggered.connect(lambda: action_emitter('delete'))
        self.cut.triggered.connect(lambda: action_emitter('cut'))
        self.download.triggered.connect(lambda: action_emitter('download'))
        self.download_compression.triggered.connect(
            lambda: action_emitter('download', True))
        self.copy_path.triggered.connect(
            lambda: action_emitter('copy_path'))
        self.info.triggered.connect(lambda: action_emitter('info'))
        self.rename.triggered.connect(rename_handler)

    def get_all_actions(self):
        """Returns a list of all managed actions for menu creation."""
        return [
            self.pick,
            self.copy,
            self.cut,
            self.delete,
            self.download,
            self.download_compression,
            self.copy_path,
            self.info,
            self.rename
        ]
# ---------------- FileItem ----------------

# Icons mode


class FileItem(QWidget):
    WIDTH, HEIGHT = 80, 100
    selected_sign = pyqtSignal(dict)
    # Operation type, file name, directory or not,parameter (download_compression)
    action_triggered = pyqtSignal(str, object, bool, object)
    # Operation type, original file name, new file name, whether it is a directory
    rename_action = pyqtSignal(str, str, str, str)
    # new_dir_name
    mkdir_action = pyqtSignal(str)
    # new file name
    mkfile_action = pyqtSignal(str)

    def __init__(self, name, is_dir, parent=None, explorer=None):
        super().__init__(parent)
        self.name = name
        self.is_dir = is_dir
        self.selected = False
        self.parent_explorer = explorer
        self.mkdir = False
        self.mkfile = False
        icons = self._get_icons()
        self.icon = icons.Folder_Icon if is_dir else icons.File_Icon
        self.setMinimumSize(self.WIDTH, self.HEIGHT)

        self._update_style()
        self.rename_edit = LineEdit(self)
        self.rename_edit.setText(self.name)
        self.rename_edit.setAlignment(Qt.AlignCenter)
        self.rename_edit.hide()
        # self.rename_edit.returnPressed.connect(self._apply_rename)
        self.rename_edit.editingFinished.connect(self._apply_rename)
        self._rename_applied = False
        self._init_actions()

    def _get_icons(self):
        parent = self.parent()
        while parent:
            if hasattr(parent, 'icons'):
                return parent.icons
            parent = parent.parent()

    def _update_style(self):
        """Update styles based on the theme"""
        if isDarkTheme():
            self.setStyleSheet("""
                FileItem {
                    color: white;
                    background: transparent;
                }
                FileItem:hover {
                    background: rgba(255, 255, 255, 0.1);
                }
            """)
        else:
            self.setStyleSheet("""
                FileItem {
                    color: black;
                    background: transparent;
                }
                FileItem:hover {
                    background: rgba(0, 0, 0, 0.05);
                }
            """)

    def sizeHint(self):
        return QSize(self.WIDTH, self.HEIGHT)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self.selected:
            painter.setBrush(QColor("#cce8ff"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(self.rect(), 5, 5)

        painter.drawPixmap(
            (self.width() - self.icon.width()) // 2, 5, self.icon)

        font = QFont("Segoe UI", 8)
        painter.setFont(font)

        metrics = painter.fontMetrics()
        text_width = metrics.width(self.name)
        available_width = self.width() - 10

        display_text = self.name
        if text_width > available_width:

            display_text = metrics.elidedText(
                self.name, Qt.ElideMiddle, available_width)

        if isDarkTheme():
            painter.setPen(QColor(255, 255, 255))
        else:
            painter.setPen(QColor(0, 0, 0))

        painter.drawText(QRect(5, 70, self.width()-10, 30),
                         Qt.AlignCenter, display_text)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            ctrl = QApplication.keyboardModifiers() & Qt.ControlModifier
            self.parent_explorer.select_item(self, ctrl)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.selected_sign.emit({self.name: self.is_dir})
            print(f"Double-click to open: {self.name}")

    def _init_actions(self):
        self.actions_manager = FileActionsManager(
            action_emitter=self._emit_action,
            rename_handler=self._start_rename,
            action_factory=self.parent_explorer._create_file_op_actions
        )

    def _create_context_menu(self):
        """Creates and returns the context menu for the file item."""
        menu = RoundMenu(parent=self)
        menu.addActions(self.actions_manager.get_all_actions())
        return menu

    def contextMenuEvent(self, e):
        # Ensure the item is selected before showing the context menu
        if not self.selected:
            self.parent_explorer.select_item(self)

        menu = self._create_context_menu()
        menu.exec(e.globalPos())

    def _emit_action(self, action_type, parameter=None):
        if action_type == "rename":
            self._start_rename()
        else:
            copy_cut_paths = []
            if self.parent_explorer:
                for item in self.parent_explorer.selected_items:
                    if action_type in ("copy", "cut") or action_type == "download" and parameter:
                        copy_cut_paths.append(item.name)
                    else:
                        self.action_triggered.emit(
                            action_type, item.name, item.is_dir, parameter
                        )
            if copy_cut_paths:
                if action_type != "download":
                    self.action_triggered.emit(
                        action_type, copy_cut_paths, False, parameter
                    )
                else:
                    # if action_type == "download" and parameter:
                    self.action_triggered.emit(
                        action_type, copy_cut_paths, False, parameter)
                    return

    def _start_rename(self):
        self._rename_applied = False
        self.rename_edit.setText(self.name)
        self.rename_edit.setGeometry(5, 70, self.width()-10, 25)
        self.rename_edit.show()
        self.rename_edit.setFocus()
        self.rename_edit.selectAll()

    def _apply_rename(self):
        print("Apply rename")
        if self._rename_applied:
            return

        self._rename_applied = True
        new_name = self.rename_edit.text().strip()
        if self.mkdir:
            self.mkdir_action.emit(new_name)
            self.mkdir = False
            self.rename_edit.hide()
            self.update()
        if self.mkfile:
            self.mkfile_action.emit(new_name)
            self.mkfile = False
            self.rename_edit.hide()
            self.update()
        else:

            if new_name and new_name != self.name:
                self.rename_action.emit(
                    "rename", self.name, new_name, str(self.is_dir))
            self.rename_edit.hide()
            self.update()


class NameDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        if option.state & QStyle.State_HasFocus:
            option.state = option.state ^ QStyle.State_HasFocus
        # Add 5px left padding
        option.rect.adjust(5, 0, 0, 0)
        super().paint(painter, option, index)


class CenteredDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        if option.state & QStyle.State_HasFocus:
            option.state = option.state ^ QStyle.State_HasFocus
        option.displayAlignment = Qt.AlignCenter | Qt.AlignVCenter
        super().paint(painter, option, index)


# Detail Mode


class DetailItem(QWidget):
    # type , file_name/file_names, is_dir , new_name/compression
    action_triggered = pyqtSignal(str, object, bool, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Details view
        self.details_model = QStandardItemModel(self)
        self.details_view = TableView(self)
        self.details_view.setAlternatingRowColors(False)
        self.details_view.verticalHeader().setDefaultSectionSize(24)
        self.details_view.setModel(self.details_model)
        self.details_view.setVisible(False)  # Default hidden
        self.details_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.details_view.setEditTriggers(QTableView.NoEditTriggers)
        self.details_view.setSelectionBehavior(QTableView.SelectRows)
        self.details_view.setSelectionMode(QTableView.ExtendedSelection)
        self.details_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.details_view.setItemDelegateForColumn(0, NameDelegate(self))
        centered_delegate = CenteredDelegate(self)
        self.details_view.setItemDelegateForColumn(1, centered_delegate)
        self.details_view.setItemDelegateForColumn(2, centered_delegate)
        self.details_view.setItemDelegateForColumn(3, centered_delegate)
        self.details_view.setItemDelegateForColumn(4, centered_delegate)

        self.details_view.customContextMenuRequested.connect(
            self._show_context_menu)
        self.details_view.doubleClicked.connect(
            self._on_row_double_click)
        self.details_view.verticalHeader().setVisible(False)
        self.details_model.setHorizontalHeaderLabels([
            self.tr('Name'),
            self.tr('Size'),
            self.tr('Modified Time'),
            self.tr('Permissions'),
            self.tr('User/Group')
        ])

        if isDarkTheme():
            self.details_view.setStyleSheet("""
                QTableView {
                    color: white;
                    background-color: transparent;
                    border: none;
                    gridline-color: #454545;
                }
                QTableView::item {
                    border-bottom: 1px solid #454545;
                }
                QTableView::item:selected {
                    background-color: #6A5ACD;
                    color: white;
                }
                QHeaderView::section {
                    background-color: transparent;
                    color: white;
                    border: none;
                    border-bottom: 1px solid #555;
                }
            """)
        else:
            self.details_view.setStyleSheet("""
                QTableView {
                    color: black;
                    background-color: transparent;
                    border: none;
                    gridline-color: #DCDCDC;
                }
                QTableView::item {
                     border-bottom: 1px solid #DCDCDC;
                }
                QTableView::item:selected {
                    background-color: #cce8ff;
                    color: black;
                }
                QHeaderView::section {
                    background-color: transparent;
                    color: black;
                    border: none;
                    border-bottom: 1px solid #ccc;
                }
            """)

        self.actions_manager = FileActionsManager(
            action_emitter=self._emit_action,
            rename_handler=self.rename_selected_item,
            action_factory=self.parent()._create_file_op_actions
        )
        self.details_model.dataChanged.connect(self._on_data_changed)
        self._rename_old_name = None
        self.is_mkdir = False
        self.is_mkfile = False
        self._editing_index = None
        self.details_view.itemDelegate().closeEditor.connect(
            lambda editor, hint: self._on_editor_closed(editor, hint))

    def _emit_action(self, action_type, parameter=None):
        indexes = self.details_view.selectionModel().selectedRows()
        if not indexes:
            return

        copy_cut_paths = []  # maybe its download list
        for index in indexes:
            name_item = self.details_model.item(index.row(), 0)
            file_name = name_item.text()
            is_dir = name_item.data(Qt.UserRole)

            # download_compression
            if action_type in ("copy", "cut",) or action_type == "download" and parameter:
                copy_cut_paths.append(file_name)
            else:
                self.action_triggered.emit(action_type, file_name, is_dir, "")

        if copy_cut_paths:
            if action_type != "download":
                self.action_triggered.emit(
                    action_type, copy_cut_paths, False, "")
            else:
                # if action_type == "download" and parameter:
                self.action_triggered.emit(
                    action_type, copy_cut_paths, False, parameter)
                return

    def _on_row_double_click(self, index):
        if not index.isValid():
            return
        name_item = self.details_model.item(index.row(), 0)
        file_name = name_item.text()
        is_dir = name_item.data(Qt.UserRole)
        self.action_triggered.emit("open", file_name, is_dir, "")
        print(file_name, "mode", is_dir)

    def _show_context_menu(self, pos):
        index = self.details_view.indexAt(pos)
        if index.isValid():
            self._show_item_context_menu(pos, index)
        else:
            # Show the general context menu for blank areas, provided by the parent
            menu = self.parent()._get_menus()
            menu.exec_(self.details_view.viewport().mapToGlobal(pos))

    def _show_item_context_menu(self, pos, index):
        """Show context menu for a specific item in the details view."""
        selection_model = self.details_view.selectionModel()

        if not selection_model.isSelected(index):
            selection_model.clearSelection()
            selection_model.select(
                index,
                selection_model.Select | selection_model.Rows
            )

        menu = self._get_details_menus()
        menu.exec_(self.details_view.viewport().mapToGlobal(pos))

    def _get_details_menus(self):
        menu = RoundMenu(parent=self)
        menu.addActions(self.actions_manager.get_all_actions())
        return menu

    def _add_files_to_details_view(self, files, clear_old=True):
        self.details_model.setRowCount(0)
        entries = _normalize_files_data(files)
        # Sort by name, with directories first
        entries.sort(key=lambda x: (not x[1], x[0].lower()))

        for name, is_dir, size, mod_time, perms, owner in entries:
            # For files, always format size (even if 0 or empty)
            # For directories, show empty string
            size_str = _format_size(size) if not is_dir else ""
            item_name = QStandardItem(name)
            # Store is_dir flag in the item itself for later retrieval
            item_name.setData(is_dir, Qt.UserRole)

            row = [
                item_name,
                QStandardItem(size_str),
                QStandardItem(mod_time),
                QStandardItem(perms),
                QStandardItem(owner)
            ]

            self.details_model.appendRow(row)

    def rename_selected_item(self):
        """Make the selected file name editable"""
        indexes = self.details_view.selectionModel().selectedRows()
        if not indexes:
            return

        index = indexes[0]  # Only rename the first selected item
        name_item = self.details_model.item(index.row(), 0)

        self._rename_old_name = name_item.text()  # Record old name
        self._editing_index = index
        name_item.setEditable(True)

        self.details_view.edit(index)

    def _on_data_changed(self, topLeft, bottomRight, roles):
        """Fired when the user finishes editing"""
        if roles and Qt.EditRole not in roles:
            return

        if topLeft.column() != 0:
            return

        row = topLeft.row()
        model = self.details_model
        item = model.item(row, 0)
        if not item:
            return

        new_name = item.text().strip()
        old_name = self._rename_old_name

        # Always finish editing first
        item.setEditable(False)
        self._rename_old_name = None

        if self.is_mkdir:
            self.is_mkdir = False
            model.removeRow(row)
            if new_name:
                self.action_triggered.emit("mkdir", new_name, True, "")
        if self.is_mkfile:
            self.is_mkfile = False
            model.removeRow(row)
            if new_name:
                self.action_triggered.emit("mkfile", new_name, True, "")

        elif old_name and new_name and new_name != old_name:
            is_dir = item.data(Qt.UserRole)
            self.apply_rename(old_name, new_name, is_dir)

    def apply_rename(self, old_name, new_name, is_dir):
        print(f"Rename: {old_name} -> {new_name}")
        self.action_triggered.emit("rename", old_name, is_dir, new_name)
        self.details_view.clearSelection()

    def _on_editor_closed(self, editor, hint):
        """Handle editor closing, for mkdir when name is not changed."""
        if not self._editing_index or not self.is_mkdir or not self.is_mkfile:
            return

        index_row = self._editing_index.row()
        self._editing_index = None  # Reset

        # On cancel (ESC)
        if hint == QAbstractItemDelegate.RevertModelCache:
            self.details_model.removeRow(index_row)
            self.is_mkdir = False
            self.is_mkfile = False
            return

        # Handle submit when name is unchanged (dataChanged won't fire)
        item = self.details_model.item(index_row, 0)
        if not item:
            return

        new_name = editor.text().strip()
        old_name = item.text()

        if new_name == old_name:
            self.details_model.removeRow(index_row)
            if self.is_mkdir:
                self.is_mkdir = False
                if new_name:
                    self.action_triggered.emit("mkdir", new_name, True, "")
            elif self.is_mkfile:
                self.is_mkfile = False
                if new_name:
                    self.action_triggered.emit("mkfile", new_name, True, "")

    # def _show_general_context_menu_on_blank(self, pos):
    #     """Show general context menu when clicking on a blank area of the details view."""
    #     # Check if the click is on an item. If so, do nothing.
    #     if self.details_view.indexAt(pos).isValid():
    #         return

    #     menu = RoundMenu(parent=self)
    #     menu.addActions([
    #         self.paste, self.make_dir, self.refreshaction, self.uploads, self.upload,
    #     ])
    #     menu.addSeparator()
    #     menu.addActions([self.details_view_action, self.icon_view_action])
    #     menu.exec_(self.details_view.viewport().mapToGlobal(pos))

# ---------------- FileExplorer ----------------


class FileExplorer(QWidget):
    selected = pyqtSignal(dict)
    # action type , path , copy_to path , cut?/ download_compression
    file_action = pyqtSignal(str, object, str, bool)
    # Source path , Target path , compression
    upload_file = pyqtSignal(object, str, bool)
    refresh_action = pyqtSignal()
    dataRefreshed = pyqtSignal()

    def __init__(self, parent=None, path=None):
        super().__init__(parent)
        self.view_mode = "icon"  # "icon" or "details"
        self.copy_file_path = None
        self.cut_ = False
        self.path = path
        self._is_loading = False

        self.label = QLabel(
            self.tr("The directory is empty or does not exist"))
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)

        font = self.label.font()
        font.setPointSize(40)
        font.setBold(True)
        self.label.setFont(font)

        self.label.setStyleSheet("QLabel { color: red; }")
        self.label.setMinimumSize(400, 100)
        self.label.hide()

        # Icon view
        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.container = QWidget()
        self.flow_layout = FlowLayout(self.container)
        self.container.setLayout(self.flow_layout)
        self.scroll_area.setWidget(self.container)

        # detaile
        self.details = DetailItem(self)
        self.details.action_triggered.connect(
            lambda type_, name, is_dir, new_name: self._handle_file_action(type_, name, is_dir, new_name=new_name))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.label)
        main_layout.addWidget(self.scroll_area)
        main_layout.addWidget(self.details.details_view)
        self.setLayout(main_layout)
        self.selected_items = set()
        self.rubberBand = QRubberBand(QRubberBand.Rectangle, self)
        self.dragging = False
        self.start_pos = None
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

        # self.make_dir.triggered.connect(
        #     lambda: self._handle_file_action("mkdir", "", ""))
        self._init_actions()

    def _request_directory_change(self, item_info):
        print(item_info)
        is_dir = list(item_info.values())[0]
        if not is_dir:
            self.selected.emit(item_info)
            return

        if self._is_loading:
            return
        self._is_loading = True
        self.selected.emit(item_info)

    def _handle_mkdir(self):
        """Create a new folder placeholder and enter rename mode."""
        new_folder_name = "NewFolder"

        if self.view_mode == "icon":
            existing_names = {self.flow_layout.itemAt(
                i).widget().name for i in range(self.flow_layout.count())}
            counter = 1
            candidate_name = new_folder_name
            while candidate_name in existing_names:
                candidate_name = f"{new_folder_name} ({counter})"
                counter += 1

            self.add_files([(candidate_name, True)], clear_old=False)

            new_item = self.flow_layout.itemAt(
                self.flow_layout.count() - 1).widget()

            self.select_item(new_item)
            new_item.mkdir = True
            new_item._start_rename()
        else:  # Details view
            model = self.details.details_model
            existing_names = {model.item(
                i, 0).text() for i in range(model.rowCount())}
            counter = 1
            candidate_name = new_folder_name
            while candidate_name in existing_names:
                candidate_name = f"{new_folder_name} ({counter})"
                counter += 1

            item_name = QStandardItem(candidate_name)
            item_name.setData(True, Qt.UserRole)  # is_dir = True

            row_items = [
                item_name, QStandardItem(""), QStandardItem(""),
                QStandardItem(""), QStandardItem("")
            ]

            # Maintain sort order: insert at the correct position
            entries = []
            for r in range(model.rowCount()):
                name = model.item(r, 0).text()
                is_dir = model.item(r, 0).data(Qt.UserRole)
                entries.append((name, is_dir))

            entries.append((candidate_name, True))
            entries.sort(key=lambda x: (not x[1], x[0].lower()))
            new_row_index = entries.index((candidate_name, True))

            model.insertRow(new_row_index, row_items)
            new_item_index = model.index(new_row_index, 0)

            # Select and scroll to the new item
            selection_model = self.details.details_view.selectionModel()
            selection_model.clearSelection()
            selection_model.select(
                new_item_index, selection_model.Select | selection_model.Rows)
            self.details.details_view.scrollTo(new_item_index)

            # Start the renaming process
            self.details.is_mkdir = True
            self.details.rename_selected_item()

    def _handle_mkfile(self):
        """Create a new file placeholder and enter rename mode."""
        new_file_name = "NewFile.txt"

        if self.view_mode == "icon":
            existing_names = {self.flow_layout.itemAt(
                i).widget().name for i in range(self.flow_layout.count())}
            counter = 1
            candidate_name = new_file_name
            while candidate_name in existing_names:
                candidate_name = f"NewFile ({counter}).txt"
                counter += 1

            # 添加文件，第四个参数为 False 表示文件
            self.add_files([(candidate_name, False)], clear_old=False)

            new_item = self.flow_layout.itemAt(
                self.flow_layout.count() - 1).widget()

            self.select_item(new_item)
            new_item.mkfile = True  # 标记为新建文件
            new_item._start_rename()
        else:  # Details view
            model = self.details.details_model
            existing_names = {model.item(
                i, 0).text() for i in range(model.rowCount())}
            counter = 1
            candidate_name = new_file_name
            while candidate_name in existing_names:
                candidate_name = f"NewFile ({counter}).txt"
                counter += 1

            item_name = QStandardItem(candidate_name)
            item_name.setData(False, Qt.UserRole)  # is_dir = False

            row_items = [
                item_name, QStandardItem(""), QStandardItem(""),
                QStandardItem(""), QStandardItem("")
            ]

            # Maintain sort order: insert at the correct position
            entries = []
            for r in range(model.rowCount()):
                name = model.item(r, 0).text()
                is_dir = model.item(r, 0).data(Qt.UserRole)
                entries.append((name, is_dir))

            entries.append((candidate_name, False))
            entries.sort(key=lambda x: (not x[1], x[0].lower()))
            new_row_index = entries.index((candidate_name, False))

            model.insertRow(new_row_index, row_items)
            new_item_index = model.index(new_row_index, 0)

            # Select and scroll to the new item
            selection_model = self.details.details_view.selectionModel()
            selection_model.clearSelection()
            selection_model.select(
                new_item_index, selection_model.Select | selection_model.Rows)
            self.details.details_view.scrollTo(new_item_index)

            # Start the renaming process
            self.details.is_mkfile = True
            self.details.rename_selected_item()

    def _create_file_op_actions(self):
        """Creates a dictionary of file operation actions."""
        return {
            "pick": Action(FIF.EDIT, self.tr("Pick app to open")),
            "copy": Action(FIF.COPY, self.tr("Copy")),
            "delete": Action(FIF.DELETE, self.tr("Delete")),
            "cut": Action(FIF.CUT, self.tr("Cut")),
            "download": Action(FIF.DOWNLOAD, self.tr("Download")),
            "download_compression": Action(
                FIF.DOWNLOAD, self.tr("Download (compression)")
            ),
            "copy_path": Action(FIF.FLAG, self.tr("Copy Path")),
            "info": Action(FIF.INFO, self.tr("File permissions settings")),
            "rename": Action(FIF.LABEL, self.tr("Rename")),
        }

    def switch_view(self, view_type):
        """Switch between icon and details view."""
        if view_type == "icon":
            self.view_mode = "icon"
            self.scroll_area.setVisible(True)
            self.details.details_view.setVisible(False)
        elif view_type == "details":
            self.view_mode = "details"
            self.scroll_area.setVisible(False)
            self.details.details_view.setVisible(True)
        # Refresh the view with current files
        self.refresh_action.emit()

    def _clear_all_items(self):

        if self.view_mode == "icon":
            while self.flow_layout.count():
                item = self.flow_layout.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            self.selected_items.clear()

        else:
            self.details.details_model.removeRows(
                0, self.details.details_model.rowCount())
            self.details.details_view.selectionModel().clearSelection()

    def add_files(self, files, clear_old=True):
        """
    Accepts:
    - dict: {name: bool_or_marker} (True for directories, False for files)
    - list: [{"name": ..., "is_dir": True/False}, ...]
    - list of tuples: [("name", True), ...]
    Sorts directories first, files last, in ascending order by name (case-insensitive).
        """
        if clear_old:
            self._clear_all_items()
        if not files:
            self._clear_all_items()
            self.label.show()
            self.label.raise_()
            return
        else:
            self.label.hide()
        start_time = time.perf_counter()
        if self.view_mode == "icon":
            self._add_files_to_icon_view(files, False)
        else:
            self.details._add_files_to_details_view(files, clear_old)
        self._is_loading = False
        self.dataRefreshed.emit()
        end_time = time.perf_counter()
        print(f"渲染文件列表到视图耗时: {end_time - start_time:.4f} 秒")

    def _add_files_to_icon_view(self, files, clear_old=True):
        self.container.setUpdatesEnabled(False)
        if clear_old:
            while self.flow_layout.count():
                item = self.flow_layout.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            self.selected_items.clear()

        entries = _normalize_files_data(files)
        entries.sort(key=lambda x: (not x[1], x[0].lower()))

        for name, is_dir, *_ in entries:
            item_widget = FileItem(
                name, is_dir, parent=self.container, explorer=self)
            item_widget.selected_sign.connect(self._request_directory_change)
            item_widget.action_triggered.connect(self._handle_file_action)
            item_widget.rename_action.connect(
                lambda type_, name, new_name, is_dir: self._handle_file_action(
                    action_type=type_, file_name=name, is_dir=is_dir, new_name=new_name))
            item_widget.mkdir_action.connect(
                lambda new_dir_name: self._handle_file_action(
                    action_type="mkdir", file_name=new_dir_name))
            item_widget.mkfile_action.connect(
                lambda new_file_name: self._handle_file_action(
                    action_type="mkfile", file_name=new_file_name)
            )
            item_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.flow_layout.addWidget(item_widget)

        self.container.setUpdatesEnabled(True)
        self.container.update()

    def select_item(self, item, ctrl=False):
        if ctrl:
            if item in self.selected_items:
                self.selected_items.remove(item)
                item.selected = False
            else:
                self.selected_items.add(item)
                item.selected = True
        else:
            for i in self.selected_items:
                i.selected = False
                i.update()
            self.selected_items = {item}
            item.selected = True
        item.update()

    # new_name/compression
    def _handle_file_action(self, action_type, file_name, is_dir=None, new_name=None):
        # try:
        #     file_name = list(file_name)  # Check if it's iterable
        #     if not len(file_name) > 1:
        #         KeyError
        #     full_path = []
        #     more_than_one = True
        # except Exception:
        #     more_than_one = False
        full_path = []
        if isinstance(file_name, list):
            for name in file_name:
                full_path_ = self._get_full_path(name)
                full_path.append(full_path_)
        else:
            full_path = self._get_full_path(file_name)

        if action_type == "pick":
            app_path = self.handle_pick_app()
            if app_path:
                configer.revise_config("external_editor", app_path)
                configer.read_config("open_mode", True)
                self._request_directory_change({file_name: is_dir})
                return

        if action_type == "download" and new_name == True:
            self.file_action.emit(action_type, full_path, "", True)
            return
        # Only for detail mode
        if action_type == "open":
            self._request_directory_change({file_name: is_dir})
            return

        if action_type == "paste":
            if self.copy_file_path:  # A list of paths copied/cut earlier
                if isinstance(self.copy_file_path, list):
                    for path in self.copy_file_path:
                        self.file_action.emit(
                            action_type, path, self.path, self.cut_)
                else:
                    self.file_action.emit(
                        action_type, self.copy_file_path, self.path, self.cut_)

                self.cut_ = False
                self.copy_file_path = []  # Reset after paste
            return

        if action_type in ["rename", "mkdir", "mkfile"]:
            full_path = full_path
            if action_type == "rename" and new_name:
                self.file_action.emit(action_type, full_path, new_name, False)
            elif action_type == "mkdir" and file_name:
                self.file_action.emit(action_type, full_path, "", False)
            elif action_type == "mkfile" and file_name:
                self.file_action.emit(action_type, full_path, "", False)
            return
        print(action_type, full_path, new_name, )
        if action_type == "copy":
            self.copy_file_path = full_path
            self.cut_ = False
        elif action_type == "cut":
            self.copy_file_path = full_path
            self.cut_ = True
        else:  # Covers "delete", "download", "info", "copy_path", etc.
            self.file_action.emit(action_type, full_path, "", False)

    def _show_details_view_context_menu(self, pos):
        index = self.details_view.indexAt(pos)
        if not index.isValid():
            # Clicked on empty space, show the general context menu
            menu = self._create_general_context_menu()
            menu.exec_(self.details_view.viewport().mapToGlobal(pos))
            return

        selection_model = self.details_view.selectionModel()
        # If the clicked item is not already part of the selection,
        # clear the previous selection and select only the clicked item.
        if not selection_model.isSelected(index):
            selection_model.clearSelection()
            selection_model.select(
                index, self.details_view.selectionModel().Select | self.details_view.selectionModel().Rows)

        # Now the selection is correct, proceed to show the menu.
        name_item = self.details_model.item(index.row(), 0)
        file_name = name_item.text()
        is_dir = name_item.data(Qt.UserRole)

        # Create a temporary FileItem to generate and show the context menu
        # This reuses the menu logic and now _emit_action handles multi-select
        # temp_item = FileItem(
        #     file_name, is_dir, explorer=self, icons=self.icons)
        # # Connect the signal from the temporary item to the actual handler
        # temp_item.action_triggered.connect(self._handle_file_action)
        menu = self.details_context_menu()
        menu.exec_(self.details_view.viewport().mapToGlobal(pos))

    def mousePressEvent(self, event):
        # This event is for the icon view's rubber band selection
        if self.view_mode == 'details':
            super().mousePressEvent(event)
            return
        if event.button() == Qt.LeftButton:
            ctrl = QApplication.keyboardModifiers() & Qt.ControlModifier
            in_item = False
            for i in range(self.flow_layout.count()):
                widget = self.flow_layout.itemAt(i).widget()
                if widget.geometry().contains(event.pos()):
                    in_item = True
                    break
            if not in_item:
                self.dragging = True
                self.start_pos = event.pos()
                if not ctrl:
                    for item in self.selected_items:
                        item.selected = False
                        item.update()
                    self.selected_items.clear()
                self.rubberBand.setGeometry(QRect(self.start_pos, QSize()))
                self.rubberBand.show()

    def mouseMoveEvent(self, event):
        if self.dragging:
            rect = QRect(self.start_pos, event.pos()).normalized()
            self.rubberBand.setGeometry(rect)
            for i in range(self.flow_layout.count()):
                widget = self.flow_layout.itemAt(i).widget()
                if rect.intersects(widget.geometry()):
                    if widget not in self.selected_items:
                        self.selected_items.add(widget)
                        widget.selected = True
                        widget.update()
                else:
                    if widget in self.selected_items and not (Qt.ControlModifier & QApplication.keyboardModifiers()):
                        self.selected_items.remove(widget)
                        widget.selected = False
                        widget.update()

    def mouseReleaseEvent(self, event):
        if self.dragging:
            self.dragging = False
            self.rubberBand.hide()

    # ---------------- Drag-in file event ----------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        file_paths = [url.toLocalFile() for url in urls]
        # file_dict = {}
        # for url in urls:
        #     path = url.toLocalFile()
        #     print("Drag in the file path:", path)
        #     is_dir = os.path.isdir(path)
        #     filename = os.path.basename(path)
        #     file_dict[filename] = is_dir
        if file_paths:
            # print(file_paths, type(file_paths))
            self.upload_file.emit(
                file_paths, self.path, configer.read_config()["compress_upload"])
        event.acceptProposedAction()

    def _init_actions(self):
        config = configer.read_config()
        self.refreshaction = Action(FIF.UPDATE, self.tr('Refresh the page'))
        self.details_view_action = Action(FIF.VIEW, self.tr('Details View'))
        self.icon_view_action = Action(FIF.APPLICATION, self.tr('Icon View'))
        self.paste = Action(FIF.PASTE, self.tr("Paste"))
        self.make_dir = Action(FIF.FOLDER_ADD, self.tr("New Folder"))
        self.make_file = Action(FIF.DOCUMENT, self.tr("New file"))
        self.upload_mode_switch = Action(
            FIF.UP, self.tr("Upload files(compression mode)"), checkable=True)
        self.upload_mode_switch.setChecked(
            config["compress_upload"])

        self.open_external = Action(
            FIF.TAG, self.tr("External"), checkable=True)
        self.open_internal = Action(
            FIF.REMOVE, self.tr("Internal"), checkable=True)
        self.switch_open_mode(config["open_mode"])
        self.open_external.triggered.connect(
            lambda: self.switch_open_mode(True))
        self.open_internal.triggered.connect(
            lambda: self.switch_open_mode(False))

        self.refreshaction.triggered.connect(
            lambda: self.refresh_action.emit())
        self.details_view_action.triggered.connect(
            lambda: self.switch_view("details"))
        self.icon_view_action.triggered.connect(
            lambda: self.switch_view("icon"))
        self.paste.triggered.connect(
            lambda: self._handle_file_action("paste", "", ""))
        self.make_dir.triggered.connect(self._handle_mkdir)
        self.make_file.triggered.connect(self._handle_mkfile)
        self.upload_mode_switch.toggled.connect(lambda checked:
                                                configer.revise_config("compress_upload", checked))

    def switch_open_mode(self, external: bool):
        """Switches the open mode actions based on the external flag."""
        self.open_external.setChecked(external)
        self.open_internal.setChecked(not external)
        configer.revise_config("open_mode", external)

    def _get_menus(self):
        menu = CheckableMenu(parent=self)
        menu.addActions(
            [self.refreshaction, self.paste, self.make_dir, self.make_file, self.upload_mode_switch])

        submenu = CheckableMenu(self.tr("Open mode"), self)
        submenu.setIcon(FIF.SEND)
        submenu.addActions([self.open_external, self.open_internal])
        menu.addMenu(submenu)

        menu.addSeparator()
        menu.addActions(
            [self.details_view_action, self.icon_view_action])
        return menu

    def contextMenuEvent(self, e):
        # This event now only handles the icon view's empty space.
        # Details view empty space is handled in _show_details_view_context_menu.
        if self.view_mode == 'icon':
            menu = self._get_menus()
            menu.exec_(e.globalPos())

    def _get_full_path(self, file_name):
        path = os.path.join(self.path, file_name)
        return os.path.normpath(path).replace('\\', '/')

    def keyPressEvent(self, event):
        def get_selected_names():
            if self.view_mode == 'icon':
                if not self.selected_items:
                    return []
                return [item.name for item in self.selected_items]
            elif self.view_mode == 'details':
                indexes = self.details.details_view.selectionModel().selectedRows()
                if not indexes:
                    return []
                return [self.details.details_model.item(
                    index.row(), 0).text() for index in indexes]
            return []

        if event.modifiers() & Qt.ControlModifier:
            selected_names = get_selected_names()

            if not selected_names and not self.copy_file_path:
                return

            full_path = []

            if isinstance(selected_names, list):
                for name in selected_names:
                    full_path_ = self._get_full_path(name)
                    full_path.append(full_path_)
            else:
                full_path = self._get_full_path(selected_names)

            if event.key() == Qt.Key_C:
                print(f"copy {full_path}")
                self.copy_file_path = full_path
                self.cut_ = False

            elif event.key() == Qt.Key_V:
                print(f"paste {full_path}")
                if self.copy_file_path:  # A list of paths copied/cut earlier
                    if isinstance(self.copy_file_path, list):
                        for path in self.copy_file_path:
                            self.file_action.emit(
                                "paste", path, self.path, self.cut_)
                    else:
                        self.file_action.emit(
                            "paste", self.copy_file_path, self.path, self.cut_)

                    self.cut_ = False
                    self.copy_file_path = []  # Reset after paste

            elif event.key() == Qt.Key_X:
                print(f"cut {full_path}")
                self.copy_file_path = full_path
                self.cut_ = True
            else:
                super().keyPressEvent(event)
            return

        if event.key() == Qt.Key_Delete:
            selected_names = get_selected_names()

            if selected_names:
                self._handle_file_action('delete', selected_names, False, None)

        elif event.key() == Qt.Key_F2:
            # F2 rename should only work for a single selection
            if self.view_mode == 'icon' and len(self.selected_items) == 1:
                item = list(self.selected_items)[0]
                item._start_rename()
            elif self.view_mode == 'details' and len(self.details.details_view.selectionModel().selectedRows()) == 1:
                self.details.rename_selected_item()

        elif event.key() == Qt.Key_F5:
            self.refresh_action.emit()
        elif event.key() == Qt.Key_Backspace:
            self.selected.emit({'..': True})
        elif event.key() == Qt.Key_A and (event.modifiers() & Qt.ControlModifier):
            if self.view_mode == 'icon':
                self.selected_items.clear()
                for i in range(self.flow_layout.count()):
                    widget = self.flow_layout.itemAt(i).widget()
                    widget.selected = True
                    widget.update()
                    self.selected_items.add(widget)
        else:
            super().keyPressEvent(event)

    def handle_pick_app(self):
        file_path, _ = QFileDialog.getOpenFileName(
            None,
            self.tr("Select executable program"),
            self.tr("C:\\Program Files"),
            self.tr("Executable files (*.exe);;All files (*.*)")
        )
        return file_path
