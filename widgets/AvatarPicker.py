from qfluentwidgets import AvatarWidget, FluentIcon
from PyQt5.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, pyqtProperty, QBuffer
from PyQt5.QtGui import QPixmap, QPainter, QColor, QMouseEvent, QPainterPath, QDragEnterEvent, QDropEvent
from PyQt5.QtWidgets import QFileDialog
import os


class AvatarPickerWidget(AvatarWidget):
    """基于 AvatarWidget 的图片选择器组件：点击或拖拽选择图片，支持悬浮显示相机图标并发出 imageSelected 信号。"""

    imageSelected = pyqtSignal(str)

    def __init__(self, image_path: str = "", size: int = 80, parent=None):
        """
        初始化头像选择器。
        :param image_path: 初始头像图片路径（如果有的话）
        :param size: 控件的尺寸（正方形，单位：像素）
        :param parent: 父组件
        """
        super().__init__(parent)
        self._size = size
        self._camera_opacity = 0.0
        self._is_setting_image = False
        self.setFixedSize(size, size)
        self.setRadius(size // 2)
        self.setCursor(Qt.PointingHandCursor)

        # 设置动画效果
        self.animation = QPropertyAnimation(self, b"cameraOpacity")
        self.animation.setDuration(180)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)

        # 拖拽支持
        self.setAcceptDrops(True)

        # 设置初始图片（如果有的话）
        if image_path and os.path.exists(image_path):
            self._setImageDirectly(image_path)
        else:
            self.setDefaultAvatar()

    def setDefaultAvatar(self):
        """
        设置默认头像：一个灰色圆形背景，中央有一个用户图标（👤）。
        """
        pixmap = QPixmap(self._size, self._size)
        pixmap.fill(QColor(230, 230, 230))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(180, 180, 180))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, self._size, self._size)

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(self.font())
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "👤")
        painter.end()

        self._setPixmapDirectly(pixmap)

    def getCameraOpacity(self):
        """
        获取相机图标的透明度。
        :return: 相机图标的透明度（0.0 到 1.0）
        """
        return self._camera_opacity

    def setCameraOpacity(self, opacity):
        """
        设置相机图标的透明度。
        :param opacity: 透明度值（0.0 到 1.0）
        """
        self._camera_opacity = opacity
        self.update()

    cameraOpacity = pyqtProperty(float, getCameraOpacity, setCameraOpacity)

    def enterEvent(self, event):
        """
        鼠标悬浮事件：显示相机图标。
        """
        self.startAnimation(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        """
        鼠标离开事件：隐藏相机图标。
        """
        self.startAnimation(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        """
        鼠标点击事件：打开文件选择器。
        """
        if event.button() == Qt.LeftButton:
            self.openPicker()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        """
        键盘按键事件：按回车或空格打开文件选择器。
        """
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.openPicker()
        else:
            super().keyPressEvent(event)

    def startAnimation(self, target_opacity):
        """
        启动动画，改变相机图标的透明度。
        :param target_opacity: 目标透明度值（0.0 到 1.0）
        """
        self.animation.stop()
        self.animation.setStartValue(self._camera_opacity)
        self.animation.setEndValue(target_opacity)
        self.animation.start()

    def openPicker(self):
        """
        打开文件选择对话框，允许用户选择头像图片，并设置该图片。
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择头像图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif);;所有文件 (*.*)"
        )
        if file_path and os.path.exists(file_path):
            self._setImageDirectly(file_path)
            self.imageSelected.emit(file_path)

    def setImage(self, image):
        """
        设置头像图片（可以传入 QPixmap 或 图片路径）。
        :param image: 图片的路径或 QPixmap 实例
        """
        if self._is_setting_image:
            return

        pixmap = None
        if isinstance(image, QPixmap):
            pixmap = image
        elif isinstance(image, str) and os.path.exists(image):
            pixmap = QPixmap(image)
        else:
            return

        if pixmap.isNull():
            return

        self._is_setting_image = True
        try:
            circular = self.createCircularPixmap(pixmap)
            super(AvatarPickerWidget, self).setImage(circular)
            self.update()
        finally:
            self._is_setting_image = False

    def _setImageDirectly(self, image_path: str):
        """
        内部方法：直接设置图片路径，不触发递归。
        :param image_path: 图片文件路径
        """
        if os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                self._setPixmapDirectly(pixmap)

    def _setPixmapDirectly(self, pixmap: QPixmap):
        """
        内部方法：设置圆形头像图片。
        :param pixmap: 图片
        """
        if pixmap.isNull():
            return
        circular_pixmap = self.createCircularPixmap(pixmap)
        super(AvatarPickerWidget, self).setImage(circular_pixmap)
        self.update()

    def createCircularPixmap(self, pixmap: QPixmap) -> QPixmap:
        """
        创建圆形裁剪的图片。
        :param pixmap: 原始图片
        :return: 圆形裁剪后的 QPixmap
        """
        scaled = pixmap.scaled(
            self._size, self._size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation
        )

        circular = QPixmap(self._size, self._size)
        circular.fill(Qt.transparent)

        painter = QPainter(circular)
        painter.setRenderHint(QPainter.Antialiasing)

        path = QPainterPath()
        path.addEllipse(0, 0, self._size, self._size)
        painter.setClipPath(path)

        x = (self._size - scaled.width()) // 2
        y = (self._size - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()

        return circular

    def paintEvent(self, event):
        """
        重绘事件：绘制头像和覆盖层以及相机图标。
        """
        super().paintEvent(event)

        if self._camera_opacity > 0:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)

            overlay_color = QColor(0, 0, 0, int(120 * self._camera_opacity))
            painter.setBrush(overlay_color)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(0, 0, self.width(), self.height())

            camera_color = QColor(
                255, 255, 255, int(255 * self._camera_opacity))
            icon_size = max(16, self._size // 3)
            x = (self.width() - icon_size) // 2
            y = (self.height() - icon_size) // 2

            icon = FluentIcon.CAMERA
            pixmap = icon.icon(color=camera_color).pixmap(icon_size, icon_size)
            painter.drawPixmap(x, y, pixmap)
            painter.end()

    def dragEnterEvent(self, event: QDragEnterEvent):
        """
        拖拽事件：判断拖入的文件是否为图片文件。
        """
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].toLocalFile().lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        """
        拖拽放下事件：加载拖入的图片。
        """
        if event.mimeData().hasUrls():
            file_path = event.mimeData().urls()[0].toLocalFile()
            if os.path.exists(file_path):
                self._setImageDirectly(file_path)
                self.imageSelected.emit(file_path)
                event.acceptProposedAction()
                return
        event.ignore()
