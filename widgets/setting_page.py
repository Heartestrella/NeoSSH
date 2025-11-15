# setting_page.py
import logging
import os
from PyQt5.QtCore import Qt, pyqtSignal, QCoreApplication, QTimer, QThread
from PyQt5.QtGui import QFontDatabase, QFont, QColor, QPalette, QKeySequence, QIntValidator
from PyQt5.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QPushButton, QShortcut,
    QSizePolicy, QFrame, QFileDialog
)

from qfluentwidgets import (
    FluentIcon, ComboBoxSettingCard, OptionsConfigItem, SearchLineEdit, ScrollArea,
    SwitchSettingCard, PushSettingCard, QConfig, InfoBar, InfoBarPosition,
    LineEdit, RangeConfigItem, RangeValidator, RangeSettingCard,
    OptionsValidator, ColorDialog, SettingCard
)

from tools.font_config import font_config
from tools.setting_config import SCM


logger = logging.getLogger(__name__)

configer = SCM()

llm_models = {
    "ChatGPT": 0,
    "DeepSeek": 1,
    "Local ollama": 2
}


class Config(QConfig):
    background_color = OptionsConfigItem(
        "MainWindow", "Color",
        QCoreApplication.translate("Config", "Follow system settings"),
        OptionsValidator([
            QCoreApplication.translate("Config", "Light"),
            QCoreApplication.translate("Config", "Dark"),
            QCoreApplication.translate("Config", "Follow system settings")
        ]),
        restart=True
    )
    sizes = OptionsConfigItem(
        "MainWindow", "Sizes", "15",
        OptionsValidator([str(i) for i in range(12, 31)]),
        restart=True
    )
    opacity = RangeConfigItem("MainWindow", "Opacity",
                              100, RangeValidator(0, 100))

    language = OptionsConfigItem(
        "MainWindow", "Language",
        QCoreApplication.translate("Config", "English"),
        OptionsValidator([
            QCoreApplication.translate("Config", "English"),
            QCoreApplication.translate("Config", "简体中文"),
            QCoreApplication.translate("Config", "繁體中文"),
            QCoreApplication.translate("Config", "日本語"),
            QCoreApplication.translate("Config", "Русский")
        ]),
        restart=True
    )

    default_view = OptionsConfigItem(
        "Files", "DefaultView", "Icon", OptionsValidator(["Icon", "Info"]), restart=False
    )

    page_animation = OptionsConfigItem(
        "MainWindow", "PageAnimation", "Slide Fade",
        OptionsValidator([
            "Slide Fade", "Zoom In", "Zoom Out", "Cross Fade",
            "Bounce", "Elastic", "Fade Scale", "Slide Scale", "Stack"
        ]),
        restart=False
    )

    update_channel = OptionsConfigItem(
        "Updates", "Channel", "none",
        OptionsValidator(["none", "stable", "insider"]),
        restart=False
    )


class FontSelectorDialog(QDialog):
    """
    Robust FontSelectorDialog that force-paints its own visible content area
    to avoid being turned into a 'black box' by global QSS.
    Replace your old FontSelectorDialog with this one.
    """
    fontSelected = pyqtSignal(str)

    def __init__(self, parent=None,
                 title=QCoreApplication.translate(
                     "FontSelectorDialog", "Select Font"),
                 prompt=QCoreApplication.translate("FontSelectorDialog", "Choose a system font")):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.selected_font = None
        self.setModal(True)
        self.resize(760, 520)

        # ---------------------------
        # Force window-level safe flags (avoid translucent backgrounds)
        # ---------------------------
        try:
            # ensure window isn't transparent due to global flags
            self.setAttribute(Qt.WA_TranslucentBackground, False)
            self.setWindowOpacity(1.0)
        except Exception:
            pass

        # ---------------------------
        # Build a content frame that we fully control the painting for.
        # We'll put all UI into `self.content` and force its palette/QSS.
        # ---------------------------
        self.content = QFrame(self)
        self.content.setObjectName("font_selector_content")
        self.content.setAutoFillBackground(True)
        self.content.setAttribute(Qt.WA_StyledBackground, True)

        # Choose explicit bg/text colors (white bg, dark text)
        self._bg = QColor("#ffffff")
        self._text = QColor("#111111")

        # Apply palette to content to ensure it paints background
        pal = self.content.palette()
        pal.setColor(QPalette.Window, self._bg)
        pal.setColor(QPalette.WindowText, self._text)
        pal.setColor(QPalette.Base, self._bg)
        pal.setColor(QPalette.Text, self._text)
        self.content.setPalette(pal)

        # Locally scoped stylesheet to further ensure visibility (targets only our content subtree)
        content_qss = f"""
        QFrame#font_selector_content {{ background: {self._bg.name()}; color: {self._text.name()}; }}
        QLineEdit {{ background: #ffffff; color: #000000; border: 1px solid rgba(0,0,0,0.12); border-radius:6px; }}
        QListWidget {{ background: #ffffff; color: #000000; }}
        QLabel {{ color: #000000; }}
        """
        # apply to the content frame only (this will style its children that inherit)
        self.content.setStyleSheet(content_qss)

        # main layout attaches the content frame
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.content)

        # content layout
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(10)

        # ---------------------------
        # Search box (prefer SearchLineEdit, fallback to LineEdit)
        # ---------------------------
        try:
            if 'SearchLineEdit' in globals() and SearchLineEdit is not None:
                self.search_box = SearchLineEdit(self.content)
            else:
                raise Exception()
        except Exception:
            # LineEdit imported in your module header earlier
            self.search_box = LineEdit(self.content)
            self.search_box.setPlaceholderText(self.tr("Search fonts..."))

        self.search_box.setFixedHeight(36)
        # enforce background/placeholder/text visibility
        self.search_box.setAutoFillBackground(True)
        self.search_box.setAttribute(Qt.WA_StyledBackground, True)
        # Palette
        sp = self.search_box.palette()
        sp.setColor(QPalette.Base, QColor("#ffffff"))
        sp.setColor(QPalette.Text, QColor("#000000"))
        try:
            sp.setColor(QPalette.PlaceholderText, QColor("#777777"))
        except Exception:
            pass
        self.search_box.setPalette(sp)
        # add explicit stylesheet to avoid global QSS interference
        self.search_box.setStyleSheet("""
            QLineEdit { background: #ffffff; color: #000000; border: 1px solid rgba(0,0,0,0.12); padding:6px; border-radius:6px; }
            QLineEdit:focus { border: 1px solid #168be6; }
        """)
        content_layout.addWidget(self.search_box)

        # ---------------------------
        # Central area: list + preview
        # ---------------------------
        hbox = QHBoxLayout()
        hbox.setSpacing(10)

        # font list
        self.list_widget = QListWidget(self.content)
        self.list_widget.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.list_widget.setAutoFillBackground(True)
        self.list_widget.setAttribute(Qt.WA_StyledBackground, True)

        # ensure viewport paints background
        try:
            vp = self.list_widget.viewport()
            vp.setAutoFillBackground(True)
            vpal = vp.palette()
            vpal.setColor(QPalette.Base, QColor("#ffffff"))
            vpal.setColor(QPalette.Text, QColor("#000000"))
            vp.setPalette(vpal)
        except Exception:
            pass

        hbox.addWidget(self.list_widget, 3)

        # preview
        preview_frame = QFrame(self.content)
        preview_frame.setAutoFillBackground(True)
        preview_frame.setAttribute(Qt.WA_StyledBackground, True)
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.setSpacing(8)

        preview_label_title = QLabel(self.tr("Preview"), preview_frame)
        preview_label_title.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(preview_label_title)

        self.preview_label = QLabel(
            "The quick brown fox jumps over the lazy dog 0123456789", preview_frame)
        self.preview_label.setWordWrap(True)
        self.preview_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.preview_label.setMinimumWidth(260)
        self.preview_label.setMinimumHeight(140)
        self.preview_label.setStyleSheet(
            "color: #000000; background: transparent;")
        preview_layout.addWidget(self.preview_label, 1)

        self.size_label = QLabel(self.tr("Preview size: 14"), preview_frame)
        self.size_label.setStyleSheet("color: #000000;")
        preview_layout.addWidget(self.size_label)
        hbox.addWidget(preview_frame, 2)

        content_layout.addLayout(hbox)

        # ---------------------------
        # Bottom controls: circular OK/Cancel (right aligned)
        # ---------------------------
        bottom_widget = QWidget(self.content)
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addStretch(1)

        # OK circular button
        self.ok_btn = QPushButton("✓", bottom_widget)
        self.ok_btn.setToolTip(self.tr("OK (Enter)"))
        self.ok_btn.setCursor(Qt.PointingHandCursor)
        self.ok_btn.clicked.connect(self._on_ok)
        self.ok_btn.setDefault(True)
        self.ok_btn.setAutoDefault(True)
        self.ok_btn.setFixedSize(48, 48)
        self.ok_btn.setStyleSheet("""
            QPushButton {
                border-radius: 24px;
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #39a0ff, stop:1 #0078d4);
                color: white; font-weight:700; font-size:18px;
            }
            QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #4db3ff, stop:1 #168be6); }
            QPushButton:pressed { background: #006bb3; }
        """)
        bottom_layout.addWidget(self.ok_btn)
        bottom_layout.addSpacing(12)

        # Cancel circular button
        self.cancel_btn = QPushButton("✕", bottom_widget)
        self.cancel_btn.setToolTip(self.tr("Cancel (Esc)"))
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setFixedSize(48, 48)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                border-radius: 24px;
                background: transparent;
                border: 2px solid rgba(0,0,0,0.12);
                color: #222222; font-weight:700; font-size:16px;
            }
            QPushButton:hover { background: rgba(0,0,0,0.04); }
        """)
        bottom_layout.addWidget(self.cancel_btn)

        content_layout.addWidget(bottom_widget)

        # ---------------------------
        # Initialize fonts & signals
        # ---------------------------
        self._preview_size = 14
        self._load_system_fonts()
        self._apply_preview_font()

        self.search_box.textChanged.connect(self._filter_fonts)
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(
            self._on_item_double_clicked)

        # Esc shortcut
        try:
            self.cancel_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
            self.cancel_shortcut.activated.connect(self._on_cancel)
        except Exception:
            pass

    # ---------------------------
    # font list helpers
    # ---------------------------
    def _load_system_fonts(self):
        db = QFontDatabase()
        families = db.families()
        families = sorted(families, key=lambda s: s.lower())
        self.all_families = families
        self._populate_list(self.all_families)

    def _populate_list(self, families):
        self.list_widget.clear()
        for fam in families:
            item = QListWidgetItem(fam)
            # explicitly set visible foreground
            item.setForeground(QColor("#000000"))
            self.list_widget.addItem(item)

    def _filter_fonts(self, text):
        if not text:
            self._populate_list(self.all_families)
            return
        lowered = text.lower()
        filtered = [f for f in self.all_families if lowered in f.lower()]
        self._populate_list(filtered)

    # ---------------------------
    # interaction
    # ---------------------------
    def _on_selection_changed(self, current, previous=None):
        if current:
            self._update_preview(current.text())

    def _on_item_double_clicked(self, item):
        if item:
            self.selected_font = item.text()
            try:
                self.fontSelected.emit(self.selected_font)
            except Exception:
                pass
            self.accept()

    def _update_preview(self, family):
        try:
            font = QFont(family, self._preview_size)
            self.preview_label.setFont(font)
            self.size_label.setText(
                self.tr(f"Preview font size: {self._preview_size}"))
        except Exception:
            pass

    def _apply_preview_font(self):
        cur = self.list_widget.currentItem()
        if cur:
            self._update_preview(cur.text())
        else:
            if self.list_widget.count() > 0:
                self.list_widget.setCurrentRow(0)
                self._update_preview(self.list_widget.item(0).text())

    def _on_ok(self):
        cur = self.list_widget.currentItem()
        if cur:
            self.selected_font = cur.text()
            try:
                self.fontSelected.emit(self.selected_font)
            except Exception:
                pass
        self.accept()

    def _on_cancel(self):
        self.selected_font = None
        self.reject()


class SettingPage(ScrollArea):
    themeChanged = pyqtSignal(str)
    themeColorChanged = pyqtSignal(str)  # Signal to emit the new theme color

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Setting")
        self.logger = logging.getLogger("setting")
        # configer = SCM()
        self.config = configer.read_config()
        self.font_ = font_config()
        self.cfg = Config()
        self.parent_class = parent
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setAlignment(Qt.AlignTop)
        self.init_window_size = False

        # ----------------- Search box (NEW) -----------------
        self.search_box = LineEdit()
        self.search_box.setPlaceholderText(self.tr("Search settings..."))
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search_text_changed)
        self.search_box.returnPressed.connect(self._jump_to_first_match)
        layout.addWidget(self.search_box)

        self._no_results_label = QLabel(self.tr("No matching settings"))
        self._no_results_label.setVisible(False)
        layout.addWidget(self._no_results_label)

        # internal structure to hold searchable items
        # each item: { 'widget': QWidget, 'title': str, 'keywords': [str] }
        self._search_items = []

        # helpers for highlight timer
        self._highlight_timers = {}

        # ----------------- Original settings -----------------
        self.language_card = ComboBoxSettingCard(
            configItem=self.cfg.language,
            icon=FluentIcon.GLOBE,
            title=self.tr("Language"),
            content=self.tr("Change application language (need to restart)"),
            texts=[
                self.tr("System Default"),
                "English",
                "简体中文",
                "日本語",
                "Русский"
            ]
        )
        self.language_card.comboBox.currentIndexChanged.connect(
            self._change_language)
        layout.addWidget(self.language_card)

        self._register_searchable(self.language_card, self.tr("Language"),
                                  ["language", "语言", "lang", "system default", "english", "中文", "简体中文", "日本語", "русский"])

        self.update_channel_card = ComboBoxSettingCard(
            configItem=self.cfg.update_channel,
            icon=FluentIcon.UPDATE,
            title=self.tr("Update Channel"),
            content=self.tr("Choose the update channel for the application"),
            texts=[
                self.tr("None"),
                self.tr("Stable"),
                self.tr("Insider")
            ]
        )
        self.update_channel_card.comboBox.currentIndexChanged.connect(
            self._on_update_channel_changed)
        layout.addWidget(self.update_channel_card)
        self._register_searchable(self.update_channel_card, self.tr("Update Channel"),
                                  ["update", "channel", "stable", "insider", "更新", "渠道"])

        self.right_panel_ai_chat_card = SwitchSettingCard(
            icon=FluentIcon.CHAT,
            title=self.tr("Enable Right Panel AI Chat"),
            content=self.tr(
                "Enable the AI chat panel on the right side (requires restart)"),
            parent=self
        )
        self.right_panel_ai_chat_card.checkedChanged.connect(
            lambda checked: configer.revise_config(
                "right_panel_ai_chat", checked)
        )
        layout.addWidget(self.right_panel_ai_chat_card)
        self._register_searchable(self.right_panel_ai_chat_card, self.tr("Enable Right Panel AI Chat"), [
                                  "ai", "chat", "panel", "right"])

        self.Color_card = ComboBoxSettingCard(
            configItem=self.cfg.background_color,
            icon=FluentIcon.BRUSH,
            title=self.tr("Background Color"),
            content=self.tr("Adjust background color"),
            texts=[self.tr("Light"), self.tr("Dark"),
                   self.tr("Follow system settings")]
        )
        layout.addWidget(self.Color_card)
        self._register_searchable(self.Color_card, self.tr("Background Color"), [
                                  "background", "color", "theme", "light", "dark"])

        self.bgCard = PushSettingCard(
            self.tr("Choose Background Image"),
            FluentIcon.PHOTO,
            self.tr("Custom Background"),
            self.tr("Set a custom background image"),
        )

        self.bgCard.clicked.connect(self._pick_bg)
        layout.addWidget(self.bgCard)
        self._register_searchable(self.bgCard, self.tr("Choose Background Image"), [
                                  "background", "image", "photo", "custom background"])

        self.opacityEdit = RangeSettingCard(
            self.cfg.opacity,
            FluentIcon.TRANSPARENT,
            title=self.tr("Background Opacity"),
            content=self.tr("Adjust background image opacity")
        )

        self.opacityEdit.valueChanged.connect(self._save_opacity_value)
        layout.addWidget(self.opacityEdit)
        self._register_searchable(self.opacityEdit, self.tr(
            "Background Opacity"), ["opacity", "transparent", "alpha"])

        self.clearBgCard = PushSettingCard(
            self.tr("Clear Background"),
            FluentIcon.DELETE,
            self.tr("Remove Custom Background"),
            self.tr("Restore default theme background"),
        )

        self.clearBgCard.clicked.connect(
            self.parent_class.clear_global_background)
        self.clearBgCard.clicked.connect(self._clear_bg_pic_to_config)
        layout.addWidget(self.clearBgCard)
        self._register_searchable(self.clearBgCard, self.tr("Clear Background"), [
                                  "clear", "remove", "background", "restore"])

        self.lock_ratio_card = SwitchSettingCard(
            icon=FluentIcon.LINK,
            title=self.tr("Lock Aspect Ratio"),
            content=self.tr("Affects the proportion of background image"),
            parent=self
        )

        self.lock_ratio_card.checkedChanged.connect(self.on_lock_ratio_changed)
        layout.addWidget(self.lock_ratio_card)
        self._register_searchable(self.lock_ratio_card, self.tr(
            "Lock Aspect Ratio"), ["lock", "ratio", "aspect", "比例"])

        self.cd_follow = SwitchSettingCard(
            icon=FluentIcon.ACCEPT,
            title=self.tr("Follow CD Directory"),
            content=self.tr(
                "When enabled, file manager follows new CD directory (Beta)"),
            parent=self
        )
        self.cd_follow.checkedChanged.connect(self._set_cd_follow)
        layout.addWidget(self.cd_follow)
        self._register_searchable(self.cd_follow, self.tr("Follow CD Directory"), [
                                  "cd", "directory", "follow", "file manager"])

        self.font_select = PushSettingCard(
            self.tr("Set Font"),
            FluentIcon.FONT,
            self.tr("Change terminal font (requires restart)"),
        )
        self.font_select.clicked.connect(self._select_font)
        layout.addWidget(self.font_select)
        self._register_searchable(self.font_select, self.tr(
            "Set Font"), ["font", "terminal", "typeface"])

        self.font_size = ComboBoxSettingCard(
            configItem=self.cfg.sizes,
            icon=FluentIcon.FONT_SIZE,
            title=self.tr("Font Size"),
            content=self.tr("Change terminal font size (requires restart)"),
            texts=[str(i) for i in range(12, 31)]
        )
        self.font_size.comboBox.currentIndexChanged.connect(
            self._set_font_size)
        layout.addWidget(self.font_size)
        self._register_searchable(self.font_size, self.tr(
            "Font Size"), ["size", "fontsize", "字号"])

        self.setWidget(container)
        self.setWidgetResizable(True)
        self.setStyleSheet("border: none;")

        self.cfg.background_color.valueChanged.connect(self._on_card_changed)

        self.default_view_card = ComboBoxSettingCard(
            configItem=self.cfg.default_view,
            icon=FluentIcon.VIEW,
            title=self.tr("Default file manager view"),
            content=self.tr("Set the default view of the file manager"),
            texts=[self.tr("Icon"), self.tr("Info")]
        )
        self.default_view_card.comboBox.currentIndexChanged.connect(
            self._on_default_view_changed)
        layout.addWidget(self.default_view_card)
        self._register_searchable(self.default_view_card, self.tr("Default file manager view"), [
                                  "view", "default view", "file manager", "icon", "info"])

        self.single_click_card = SwitchSettingCard(
            icon=FluentIcon.FINGERPRINT,
            title=self.tr("Single-click to open items"),
            content=self.tr(
                "When enabled, single-clicking an item in the file tree will open it."),
            parent=self
        )
        self.single_click_card.checkedChanged.connect(
            self._on_single_click_changed)
        layout.addWidget(self.single_click_card)
        self._register_searchable(self.single_click_card, self.tr("Single-click to open items"), [
                                  "single", "click", "open", "file", "tree", "单击"])

        self.animation_card = ComboBoxSettingCard(
            configItem=self.cfg.page_animation,
            icon=FluentIcon.ROTATE,
            title=self.tr("Page Animation Effect"),
            content=self.tr("Set the animation effect for page transitions"),
            texts=[
                self.tr("Slide Fade"),
                self.tr("Zoom In"),
                self.tr("Zoom Out"),
                self.tr("Cross Fade"),
                self.tr("Bounce"),
                self.tr("Elastic"),
                self.tr("Fade Scale"),
                self.tr("Slide Scale"),
                self.tr("Stack")
            ]
        )
        self.animation_card.comboBox.currentIndexChanged.connect(
            self._on_animation_changed)
        layout.addWidget(self.animation_card)
        self._register_searchable(self.animation_card, self.tr("Page Animation Effect"), [
                                  "animation", "effect", "transition", "动画", "效果"])

        self.choose_color = PushSettingCard(
            self.tr("Open Color Picker"),
            FluentIcon.PENCIL_INK,
            self.tr("Set Font Color"),
            self.tr("Set SSH session font color (global)")
        )
        self.choose_color.clicked.connect(self._open_color_dialog)
        layout.addWidget(self.choose_color)
        self._register_searchable(self.choose_color, self.tr("Open Color Picker"), [
                                  "color", "picker", "font color", "ssh"])

        self.unbelievable_button = PushSettingCard(
            self.tr("Click me to delay school"),
            FluentIcon.FONT,
            self.tr("Literal meaning")
        )
        self.unbelievable_button.clicked.connect(self._unbelievable)
        layout.addWidget(self.unbelievable_button)
        self._register_searchable(self.unbelievable_button, self.tr(
            "Click me to delay school"), ["delay", "school", "click me"])

        # Create a custom setting card with a LineEdit for direct input
        self.transfer_card = SettingCard(
            FluentIcon.SPEED_HIGH,
            self.tr("Max Concurrent Transfers"),
            self.tr(
                "Set the maximum number of concurrent uploads/downloads (must be > 0 and ≤ 50000)"),
        )
        self.transfer_edit = LineEdit(self.transfer_card)
        self.transfer_edit.setValidator(QIntValidator(1, 50000))
        self.transfer_edit.setFixedWidth(150)
        self.transfer_edit.editingFinished.connect(
            self._save_transfer_value_from_edit)
        self.transfer_card.hBoxLayout.addWidget(
            self.transfer_edit, 0, Qt.AlignRight)
        layout.addWidget(self.transfer_card)

        self._register_searchable(self.transfer_card, self.tr("Max Concurrent Transfers"), [
                                  "transfer", "concurrent", "uploads", "downloads", "concurrency"])

        # External Editor Setting Card
        self.external_editor_card = SettingCard(
            FluentIcon.EDIT,
            self.tr("External Editor"),
            self.tr(
                "Set the path to external editor executable (e.g., C:\\Program Files\\Notepad++\\notepad++.exe)"),
        )
        self.external_editor_edit = LineEdit(self.external_editor_card)
        self.external_editor_edit.setPlaceholderText(
            self.tr("Enter the full path to external editor executable"))
        self.external_editor_edit.setClearButtonEnabled(True)
        self.external_editor_edit.setMinimumWidth(300)
        self.external_editor_edit.editingFinished.connect(
            self._save_external_editor)
        self.external_editor_card.hBoxLayout.addWidget(
            self.external_editor_edit, 0, Qt.AlignRight)
        layout.addWidget(self.external_editor_card)
        self._register_searchable(self.external_editor_card, self.tr("External Editor"), [
                                  "external", "editor", "外置编辑器", "编辑器", "vscode", "notepad"])

        self._restore_saved_settings()

    # ----------------- Search helpers -----------------
    def _register_searchable(self, widget: QWidget, title: str, keywords=None):
        keywords = keywords or []
        self._search_items.append({
            'widget': widget,
            'title': title,
            'keywords': [k.lower() for k in keywords]
        })

    def _on_search_text_changed(self, text: str):
        q = text.strip().lower()
        any_visible = False
        if q == "":
            # show all
            for it in self._search_items:
                it['widget'].setVisible(True)
            self._no_results_label.setVisible(False)
            return

        for it in self._search_items:
            title = it['title'].lower() if it['title'] else ""
            kws = it['keywords']
            widget = it['widget']
            matched = q in title or any(q in kw for kw in kws)
            widget.setVisible(matched)
            if matched:
                any_visible = True
        self._no_results_label.setVisible(not any_visible)

    def _jump_to_first_match(self):
        # Scroll to first visible matching widget
        for it in self._search_items:
            if it['widget'].isVisible():
                target = it['widget']
                try:
                    self.ensureWidgetVisible(target)
                except Exception:
                    # fallback: try parent
                    target.parent().setFocus()
                # briefly highlight the widget
                self._highlight_widget(target)
                return

    def _highlight_widget(self, widget: QWidget, duration_ms: int = 1500):
        # apply temporary stylesheet to highlight a widget, then restore
        old = widget.styleSheet()
        highlight_ss = "border: 2px solid #0078d4; border-radius: 6px;"
        widget.setStyleSheet(old + "\n" + highlight_ss)

        # clear any previous timer
        if widget in self._highlight_timers:
            try:
                self._highlight_timers[widget].stop()
            except Exception:
                pass

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: widget.setStyleSheet(old))
        timer.start(duration_ms)
        self._highlight_timers[widget] = timer

    # ----------------- rest of your existing methods (unchanged) -----------------
    def _save_opacity_value(self, value: int):
        configer.revise_config("background_opacity", value)

    def _save_transfer_value_from_edit(self):
        text = self.transfer_edit.text()
        if text.isdigit():
            value = int(text)
            if value > 0:
                configer.revise_config("max_concurrent_transfers", value)

    def _on_default_view_changed(self, index: int):
        view_map = {0: ("icon", "图标"), 1: ("details", "详情")}
        value_to_save, display_name = view_map.get(index, ("icon", "图标"))
        configer.revise_config("default_view", value_to_save)

    def _on_single_click_changed(self, checked: bool):
        configer.revise_config("file_tree_single_click", checked)

    def _unbelievable(self):
        InfoBar.error(
            title=self.tr('What are you thinking'),
            content=self.tr(
                "Failed to set date \n date.set(month=7,day=1) \n Permissions error: Insufficient permissions"
            ),
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=10000,
            parent=self
        )

    def _change_language(self, lang: str):
        if lang == 0:
            lang = "system"
        elif lang == 1:
            lang = "EN"
        elif lang == 2:
            lang = "CN"
        elif lang == 3:
            lang = "JP"
        elif lang == 4:
            lang = "RU"

        print(f"Selected language: {lang}")
        configer.revise_config("language", lang)

    def _set_cd_follow(self):
        self.follow_ = self.cd_follow.switchButton.isChecked()
        configer.revise_config("follow_cd", self.follow_)

    def _clear_bg_pic_to_config(self):
        configer.revise_config("bg_pic", None)
        configer.revise_config("bg_theme_color", None)
        default_color = "#cccccc"
        self.themeColorChanged.emit(default_color)

    def on_lock_ratio_changed(self):
        self._lock_ratio = self.lock_ratio_card.switchButton.isChecked()
        configer.revise_config("locked_ratio", self._lock_ratio)

    def _get_language_from_config(self):
        lang = self.config["language"]
        if lang == "system":
            return 0
        elif lang == "EN":
            return 1
        elif lang == "CN":
            return 2
        elif lang == "JP":
            return 3
        elif lang == "RU":
            return 4
        else:
            return 0

    def _restore_saved_settings(self):

        # Change interface value
        self.language_card.comboBox.setCurrentIndex(
            self._get_language_from_config())
        self.cfg.background_color.value = self.config["bg_color"]
        self.cfg.sizes.value = self.config["font_size"]
        self.lock_ratio_card.setChecked(self.config["locked_ratio"])
        self.cd_follow.setChecked(self.config["follow_cd"])
        self.single_click_card.setChecked(
            self.config.get("file_tree_single_click", False))
        self.parent_class.set_global_background(self.config["bg_pic"])
        self.opacityEdit.setValue(self.config["background_opacity"])
        self.cfg.default_view.value = "Icon" if self.config.get(
            "default_view", "icon") == "icon" else "Info"
        self.transfer_edit.setText(
            str(self.config.get("max_concurrent_transfers", 4)))
        self.external_editor_edit.setText(
            self.config.get("external_editor", ""))
        # Achieve results
        self._lock_ratio = self.config["locked_ratio"]
        self._restore_background_opacity(self.config["background_opacity"])
        self._set_window_size(
            (self.config["window_last_width"], self.config["window_last_height"]))

        animation_map = {
            "slide_fade": 0, "zoom_in": 1, "zoom_out": 2, "cross_fade": 3,
            "bounce": 4, "elastic": 5, "fade_scale": 6, "slide_scale": 7, "stack": 8
        }
        animation_type = self.config.get("page_animation", "slide_fade")
        self.animation_card.comboBox.setCurrentIndex(
            animation_map.get(animation_type, 0))

        update_channel_map = {"none": 0, "stable": 1, "insider": 2}
        current_channel = self.config.get("update_channel", "none")
        self.update_channel_card.comboBox.setCurrentIndex(
            update_channel_map.get(current_channel, 0))

    def _restore_background_opacity(self, value):
        parent = self.parent()
        while parent:
            if hasattr(parent, "set_background_opacity"):
                parent.set_background_opacity(value)
                break
            parent = parent.parent()

    def _set_color(self, color: str):
        parent = self.parent()
        while parent:
            if hasattr(parent, "set_ssh_session_text_color"):
                parent.set_ssh_session_text_color(color)
                break
            parent = parent.parent()
        configer.revise_config("ssh_widget_text_color", color)
        InfoBar.success(
            title=self.tr('Color changed successfully'),
            content='',
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=2000,
            parent=self
        )

    def _open_color_dialog(self):
        dlg = ColorDialog(QColor(0, 255, 255), self.tr("Choose Color"),
                          self.window(), enableAlpha=False)

        dlg.colorChanged.connect(lambda color: self._set_color(color.name()))
        dlg.exec_()

    def _on_card_changed(self, value):
        print(value)
        self.themeChanged.emit(value)
        configer.revise_config("bg_color", value)

    def _set_font_size(self, index: int):
        size = int(self.font_size.comboBox.currentText())
        # print("选择的字号:", size)
        self.font_.write_font(font_size=size)
        configer.revise_config("font_size", str(size))

    def _pick_bg(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select a background image"),
            "",
            self.tr("Image files (*.png *.jpg *.jpeg *.bmp *.gif)")
        )
        print(f"Background file selected: {path}")
        if not path:
            return
        else:
            configer.revise_config("bg_pic", path)
            self.parent_class.set_global_background(path)

    def _save_external_editor(self):
        path = self.external_editor_edit.text().strip()
        if path:
            if not os.path.isfile(path):
                InfoBar.error(
                    title=self.tr('Invalid file path'),
                    content=self.tr(
                        'The specified file does not exist or is not a valid file'),
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=3000,
                    parent=self
                )
                return
        configer.revise_config("external_editor", path)

    def _select_font(self):
        font_dialog = FontSelectorDialog(self)
        font_dialog.fontSelected.connect(self.on_font_selected)
        font_dialog.exec_()

    def on_font_selected(self, font_name):
        print(f"Selected font: {font_name}")
        self.font_.write_font(font_path=font_name)

    def save_window_size(self, sizes: tuple):
        width, height = sizes
        configer.revise_config("window_last_width", width)
        configer.revise_config("window_last_height", height)

    def _set_window_size(self, sizes: tuple):
        width, height = sizes
        self.parent().resize(width, height)
        self.init_window_size = True

    def _on_animation_changed(self, index: int):
        animation_map = {
            0: "slide_fade", 1: "zoom_in", 2: "zoom_out", 3: "cross_fade",
            4: "bounce", 5: "elastic", 6: "fade_scale", 7: "slide_scale", 8: "stack"
        }
        animation_type = animation_map.get(index, "slide_fade")
        configer.revise_config("page_animation", animation_type)

    def _on_update_channel_changed(self, index: int):
        channel_map = {0: "none", 1: "stable", 2: "insider"}
        value_to_save = channel_map.get(index, "stable")
        configer.revise_config("update_channel", value_to_save)

    def _restart(self):
        pass
