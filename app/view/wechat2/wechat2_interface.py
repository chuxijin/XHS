# coding: utf-8
"""公众号2 UI 层。"""
import json
from PySide6.QtCore import Qt, QUrl, Signal, QRect, QPoint, QPointF
from PySide6.QtGui import (QDesktopServices, QFont, QTextCursor, QGuiApplication,
                            QPixmap, QPainter, QImage, QColor, QPen)
from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                                QLineEdit, QSizePolicy, QFileDialog,
                                QDialog, QAbstractSpinBox)
from pathlib import Path

from qfluentwidgets import (ScrollArea, ExpandLayout, PrimaryPushButton,
                            PushButton, LineEdit, setFont, TextEdit,
                            CardWidget, SubtitleLabel, InfoBar, ComboBox, CheckBox,
                            SettingCardGroup as CardGroup, StrongBodyLabel,
                            CaptionLabel, MessageBoxBase, SpinBox, MessageBox)
from qfluentwidgetspro.components.widgets.combo_box import MultiSelectionComboBox

from .wechat2_service import (IMAGE_DOWNLOAD_DIR, MaterialAccountTestThread,
                              MaterialImageUploadThread,
                              WechatImageDownloadThread, ImageCropThread,
                              list_download_folders, list_uploadable_images,
                              list_crop_images, load_material_account,
                              save_material_account, load_publish_templates)
from .wechat2_publish import Wechat2JsonPublishThread
from ..wechat.wechat_service import (get_accounts, get_today_templates_dir,
                                     get_next_day_templates_dir)


class SettingCardGroup(CardGroup):
    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        setFont(self.titleLabel, 14, QFont.Weight.DemiBold)


class LogPanel(CardWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.vBoxLayout = QVBoxLayout(self)
        self.headerLayout = QHBoxLayout()
        self.titleLabel = StrongBodyLabel(title, self)
        self.headerLayout.addWidget(self.titleLabel)
        self.headerLayout.addStretch(1)

        self.textEdit = TextEdit(self)
        self.textEdit.setReadOnly(True)
        self.textEdit.setPlaceholderText(self.tr("点击下载后，日志将在此显示"))
        self.textEdit.setMinimumHeight(260)
        self.textEdit.setStyleSheet("font-size:13px;")

        self.vBoxLayout.setContentsMargins(16, 12, 16, 12)
        self.vBoxLayout.setSpacing(8)
        self.vBoxLayout.addLayout(self.headerLayout)
        self.vBoxLayout.addWidget(self.textEdit)

    def append(self, text: str):
        self.textEdit.append(text)
        self.textEdit.moveCursor(QTextCursor.MoveOperation.End)

    def clear(self):
        self.textEdit.clear()


class MaterialAccountDialog(MessageBoxBase):
    """素材账号配置，仅在需要编辑时显示密钥。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        account = load_material_account()
        self._testThread = None

        self.titleLabel = SubtitleLabel(self.tr("素材账号设置"), self)
        self.descLabel = CaptionLabel(
            self.tr("通过 admin.yzxj.vip 中转上传，可与发布目标账号不同"), self)
        self.nameEdit = LineEdit(self)
        self.nameEdit.setPlaceholderText(self.tr("账号名称，如：图片仓库号"))
        self.nameEdit.setText(account.get("name", ""))
        self.appIdEdit = LineEdit(self)
        self.appIdEdit.setPlaceholderText(self.tr("AppID"))
        self.appIdEdit.setText(account.get("appid", ""))
        self.appSecretEdit = LineEdit(self)
        self.appSecretEdit.setPlaceholderText(self.tr("AppSecret"))
        self.appSecretEdit.setText(account.get("appsecret", ""))
        self.appSecretEdit.setEchoMode(QLineEdit.EchoMode.Password)
        self.testButton = PushButton(self.tr("测试连接"), self)

        for widget in (
            self.titleLabel,
            self.descLabel,
            self.nameEdit,
            self.appIdEdit,
            self.appSecretEdit,
            self.testButton,
        ):
            self.viewLayout.addWidget(widget)
        self.widget.setMinimumWidth(440)
        self.yesButton.setText(self.tr("保存"))
        self.cancelButton.setText(self.tr("取消"))
        self.testButton.clicked.connect(self._testConnection)

    def account(self) -> dict:
        return {
            "name": self.nameEdit.text().strip(),
            "appid": self.appIdEdit.text().strip(),
            "appsecret": self.appSecretEdit.text().strip(),
        }

    def validate(self) -> bool:
        data = self.account()
        if not data["appid"] or not data["appsecret"]:
            InfoBar.warning(self.tr("提示"), self.tr("请填写 AppID 和 AppSecret"),
                            duration=2000, parent=self)
            return False
        return True

    def _testConnection(self):
        data = self.account()
        if not data["appid"] or not data["appsecret"]:
            InfoBar.warning(self.tr("提示"), self.tr("请填写 AppID 和 AppSecret"),
                            duration=2000, parent=self)
            return
        self.testButton.setEnabled(False)
        self.testButton.setText(self.tr("测试中..."))
        self._testThread = MaterialAccountTestThread(
            data["appid"], data["appsecret"], self)
        self._testThread.testSuccess.connect(self._onTestSuccess)
        self._testThread.testFailed.connect(self._onTestFailed)
        self._testThread.start()

    def _onTestSuccess(self, server: str):
        self.testButton.setEnabled(True)
        self.testButton.setText(self.tr("测试连接"))
        InfoBar.success(self.tr("测试成功"),
                        self.tr("已连接素材中转服务器：{}")
                        .format(server), duration=3000, parent=self)

    def _onTestFailed(self, error: str):
        self.testButton.setEnabled(True)
        self.testButton.setText(self.tr("测试连接"))
        InfoBar.error(self.tr("测试失败"), error, duration=5000, parent=self)


class UploadUrlsDialog(MessageBoxBase):
    """显示素材上传后的图片裸地址弹窗，支持一键复制。"""

    def __init__(self, urls_text: str, count: int, parent=None):
        super().__init__(parent)
        self._urls_text = urls_text

        self.titleLabel = SubtitleLabel(self.tr("图片素材上传成功"), self)
        self.descLabel = CaptionLabel(
            self.tr("已上传 {} 张图片，纯地址如下（每行一个）：").format(count), self)

        self.urlsEdit = TextEdit(self)
        self.urlsEdit.setReadOnly(True)
        self.urlsEdit.setPlainText(urls_text)
        self.urlsEdit.setMinimumHeight(240)
        self.urlsEdit.setStyleSheet("font-size:13px; font-family: Consolas, Monaco, monospace;")

        self.copyButton = PushButton(self.tr("复制全部地址"), self)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.descLabel)
        self.viewLayout.addWidget(self.urlsEdit)
        self.viewLayout.addWidget(self.copyButton)

        self.widget.setMinimumWidth(560)
        self.yesButton.setText(self.tr("确定"))
        self.cancelButton.hide()

        self.copyButton.clicked.connect(self._copyAllUrls)

    def _copyAllUrls(self):
        QGuiApplication.clipboard().setText(self._urls_text)
        InfoBar.success(
            self.tr("已复制"),
            self.tr("已将所有裸地址复制到剪贴板"),
            duration=2000,
            parent=self,
        )


class CropPreviewWidget(QWidget):
    """自定义绘图的裁切预览控件，鼠标拖拽框选保留区域。"""

    selectionMade = Signal(tuple)

    def __init__(self, image_path: Path, parent=None):
        super().__init__(parent)
        self.image = QImage(str(image_path))
        self._origin = None
        self._current = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setMinimumSize(400, 300)

    def _image_bounds(self) -> QRect:
        if self.image.isNull():
            return QRect()
        pix = QPixmap.fromImage(self.image)
        scaled = pix.scaled(self.size(), Qt.KeepAspectRatio,
                            Qt.SmoothTransformation)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        return QRect(x, y, scaled.width(), scaled.height())

    def _to_image_coords(self, pt: QPoint) -> QPointF:
        r = self._image_bounds()
        if r.width() < 1 or r.height() < 1:
            return QPointF(0, 0)
        fx = (pt.x() - r.x()) / r.width()
        fy = (pt.y() - r.y()) / r.height()
        return QPointF(fx * self.image.width(), fy * self.image.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        r = self._image_bounds()
        if not r.isNull():
            pix = QPixmap.fromImage(self.image)
            painter.drawPixmap(r, pix)

        if self._origin and self._current:
            rect = QRect(self._origin, self._current).normalized()
            painter.setPen(QPen(QColor(0, 120, 215), 2))
            painter.setBrush(QColor(0, 120, 215, 50))
            painter.drawRect(rect)

            p1 = self._to_image_coords(rect.topLeft())
            p2 = self._to_image_coords(rect.bottomRight())
            label = (f"选区: ({int(p1.x())}, {int(p1.y())}) "
                     f"{int(p2.x()-p1.x())}x{int(p2.y()-p1.y())}")
            painter.setPen(Qt.white)
            painter.setFont(QFont("Consolas", 11))
            painter.drawText(rect.topLeft() + QPoint(6, -6), label)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._origin = event.pos()
            self._current = event.pos()
            self.update()

    def mouseMoveEvent(self, event):
        if self._origin:
            self._current = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._origin:
            self._current = event.pos()
            rect = QRect(self._origin, self._current).normalized()
            self._origin = None
            self._current = None
            self.update()
            if rect.width() < 5 or rect.height() < 5:
                return
            p1 = self._to_image_coords(rect.topLeft())
            p2 = self._to_image_coords(rect.bottomRight())
            x = max(0, int(p1.x()))
            y = max(0, int(p1.y()))
            w = min(int(p2.x() - p1.x()), self.image.width() - x)
            h = min(int(p2.y() - p1.y()), self.image.height() - y)
            if w < 1 or h < 1:
                return
            top = y
            bottom = self.image.height() - y - h
            left = x
            right = self.image.width() - x - w
            self.selectionMade.emit((top, bottom, left, right))


class CropPreviewDialog(QDialog):
    """显示参考图，让用户拖拽框选要保留的区域，返回裁剪边距。"""

    def __init__(self, image_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("选择裁剪区域"))
        self.setMinimumSize(800, 600)
        self.resize(960, 720)

        self.image_path = image_path
        self.crop_margins = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.crop_widget = CropPreviewWidget(image_path, self)
        self.crop_widget.selectionMade.connect(self._on_selection)
        layout.addWidget(self.crop_widget, 1)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.info_label = CaptionLabel(
            self.tr("在图片上拖拽选择要保留的区域，裁剪边距会自动计算"), self)
        bar.addWidget(self.info_label, 1)
        self.dim_label = CaptionLabel(
            f"{self.crop_widget.image.width()}x{self.crop_widget.image.height()}",
            self)
        self.dim_label.setStyleSheet("color: gray;")
        bar.addWidget(self.dim_label)
        self.cancel_btn = PushButton(self.tr("取消"), self)
        self.cancel_btn.clicked.connect(self.reject)
        bar.addWidget(self.cancel_btn)
        self.confirm_btn = PrimaryPushButton(self.tr("应用此裁剪到所有图片"), self)
        self.confirm_btn.clicked.connect(self._confirm)
        bar.addWidget(self.confirm_btn)
        layout.addLayout(bar)

    def _on_selection(self, margins):
        self.crop_margins = margins
        top, bottom, left, right = margins
        self.info_label.setText(
            self.tr("选区完成 → 边距: 上{} 下{} 左{} 右{} px")
            .format(top, bottom, left, right))

    def _confirm(self):
        if self.crop_margins is None:
            InfoBar.warning(self.tr("提示"), self.tr("请先在图片上拖拽选择裁剪区域"),
                            duration=2000, parent=self)
            return
        self.accept()


class Wechat2Interface(ScrollArea):
    """公众号增强工具界面。"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)
        self.titleLabel = QLabel(self.tr("公众号2"), self)
        self._downloadThread = None
        self._testThread = None
        self._uploadThread = None
        self._downloadFolders = []
        self._cropThread = None
        self._cropFolders = []
        self._customCropImages = []
        self._customCropDesc = ""
        self._templatePath = ""
        self._customTemplateDir = ""
        self._publishThread = None

        self.accountGroup = SettingCardGroup(
            self.tr("账号设置"), self.scrollWidget)

        self.accountCard = CardWidget(self.accountGroup)
        self.accountCardLayout = QHBoxLayout(self.accountCard)
        self.accountCardVBox = QVBoxLayout()
        self.accountTitleLabel = StrongBodyLabel(self.tr("主账号"), self.accountCard)
        self.accountDescLabel = CaptionLabel(
            self.tr("选择公众号页已登录的账号"), self.accountCard)
        self.accountCombo = ComboBox(self.accountCard)
        self.accountCombo.setFixedWidth(220)
        self.refreshAccountButton = PushButton(self.tr("刷新"), self.accountCard)
        self.accountCardVBox.setSpacing(0)
        self.accountCardVBox.addWidget(self.accountTitleLabel)
        self.accountCardVBox.addWidget(self.accountDescLabel)
        self.accountCardLayout.setContentsMargins(20, 11, 20, 11)
        self.accountCardLayout.addLayout(self.accountCardVBox)
        self.accountCardLayout.addStretch(1)
        self.accountCardLayout.addWidget(self.accountCombo)
        self.accountCardLayout.addWidget(self.refreshAccountButton)
        self.accountCard.setFixedHeight(73)

        self.materialCard = CardWidget(self.accountGroup)
        self.materialCardLayout = QHBoxLayout(self.materialCard)
        self.materialCardVBox = QVBoxLayout()
        self.materialTitleLabel = StrongBodyLabel(
            self.tr("素材账号"), self.materialCard)
        self.materialDescLabel = CaptionLabel(
            self.tr("未配置"), self.materialCard)
        self.materialSettingsButton = PushButton(
            self.tr("设置素材账号"), self.materialCard)
        self.materialCardVBox.setSpacing(0)
        self.materialCardVBox.addWidget(self.materialTitleLabel)
        self.materialCardVBox.addWidget(self.materialDescLabel)
        self.materialCardLayout.setContentsMargins(20, 11, 20, 11)
        self.materialCardLayout.addLayout(self.materialCardVBox)
        self.materialCardLayout.addStretch(1)
        self.materialCardLayout.addWidget(self.materialSettingsButton)
        self.materialCard.setFixedHeight(73)

        self.downloadGroup = SettingCardGroup(
            self.tr("下载图片"), self.scrollWidget)

        self.downloadCard = CardWidget(self.downloadGroup)
        self.downloadCardLayout = QVBoxLayout(self.downloadCard)
        self.downloadCardLayout.setContentsMargins(20, 11, 20, 11)
        self.downloadCardLayout.setSpacing(6)

        self.downloadRow1 = QHBoxLayout()
        self.downloadRow1.setSpacing(12)
        self.downloadCardVBox = QVBoxLayout()
        self.downloadTitleLabel = StrongBodyLabel(
            self.tr("公众号文章链接"), self.downloadCard)
        self.downloadDescLabel = CaptionLabel(
            self.tr("输入文章链接，下载正文图片到本地"), self.downloadCard)
        self.urlEdit = LineEdit(self.downloadCard)
        self.urlEdit.setPlaceholderText(
            self.tr("https://mp.weixin.qq.com/s/..."))
        self.urlEdit.setClearButtonEnabled(True)
        self.urlEdit.setMinimumWidth(360)
        self.downloadCountCombo = ComboBox(self.downloadCard)
        self.downloadCountCombo.setFixedWidth(100)
        self.downloadCountCombo.addItems(["全部"] + [f"{i}张" for i in range(1, 11)])
        self.downloadCountCombo.setCurrentText("全部")

        self.downloadButton = PrimaryPushButton(
            self.tr("下载"), self.downloadCard)
        self.openFolderButton = PushButton(
            self.tr("打开目录"), self.downloadCard)

        self.downloadCardVBox.setSpacing(0)
        self.downloadCardVBox.addWidget(self.downloadTitleLabel)
        self.downloadCardVBox.addWidget(self.downloadDescLabel)
        self.downloadRow1.addLayout(self.downloadCardVBox)
        self.downloadRow1.addWidget(self.urlEdit, 1)
        self.downloadRow1.addWidget(self.downloadCountCombo)
        self.downloadRow1.addWidget(self.openFolderButton)
        self.downloadRow1.addWidget(self.downloadButton)
        self.downloadCardLayout.addLayout(self.downloadRow1)

        self.downloadRow2 = QHBoxLayout()
        self.autoCropCheck = CheckBox(
            self.tr("下载后自动裁掉底部 80px"), self.downloadCard)
        self.autoCropCheck.setChecked(True)
        self.downloadRow2.addWidget(self.autoCropCheck)
        self.downloadRow2.addStretch(1)
        self.downloadCardLayout.addLayout(self.downloadRow2)
        self.downloadCard.setFixedHeight(106)

        self.cropCard = CardWidget(self.downloadGroup)
        self.cropCardLayout = QVBoxLayout(self.cropCard)
        self.cropCardLayout.setContentsMargins(20, 11, 20, 11)
        self.cropCardLayout.setSpacing(6)

        self.cropHeaderLayout = QHBoxLayout()
        self.cropCardVBox = QVBoxLayout()
        self.cropTitleLabel = StrongBodyLabel(
            self.tr("批量裁剪"), self.cropCard)
        self.cropDescLabel = CaptionLabel(
            self.tr("选择文件或文件夹，用第一张图框选裁剪区域，批量应用并直接覆盖原图"),
            self.cropCard)
        self.cropCardVBox.setSpacing(0)
        self.cropCardVBox.addWidget(self.cropTitleLabel)
        self.cropCardVBox.addWidget(self.cropDescLabel)
        self.selectCropFilesButton = PushButton(
            self.tr("选择文件"), self.cropCard)
        self.selectCropFolderButton = PushButton(
            self.tr("选择文件夹"), self.cropCard)
        self.cropFolderCombo = ComboBox(self.cropCard)
        self.cropFolderCombo.setMinimumWidth(180)
        self.refreshCropFolderButton = PushButton(
            self.tr("刷新"), self.cropCard)
        self.cropHeaderLayout.addLayout(self.cropCardVBox)
        self.cropHeaderLayout.addStretch(1)
        self.cropHeaderLayout.addWidget(self.selectCropFilesButton)
        self.cropHeaderLayout.addWidget(self.selectCropFolderButton)
        self.cropHeaderLayout.addWidget(self.cropFolderCombo)
        self.cropHeaderLayout.addWidget(self.refreshCropFolderButton)
        self.cropCardLayout.addLayout(self.cropHeaderLayout)

        self.cropActionLayout = QHBoxLayout()
        self.cropActionLayout.setSpacing(8)
        self.cropSelectButton = PrimaryPushButton(
            self.tr("选择裁剪区域"), self.cropCard)
        self.cropActionLayout.addWidget(self.cropSelectButton)
        self.cropActionLayout.addStretch(1)
        self.cropMarginLabel = CaptionLabel(
            self.tr("边距（px）  上"), self.cropCard)
        self.topSpin = SpinBox(self.cropCard)
        self.topSpin.setRange(0, 2000)
        self.topSpin.setSuffix(self.tr(" px"))
        self.topSpin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.bottomSpin = SpinBox(self.cropCard)
        self.bottomSpin.setRange(0, 2000)
        self.bottomSpin.setSuffix(self.tr(" px"))
        self.bottomSpin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.leftSpin = SpinBox(self.cropCard)
        self.leftSpin.setRange(0, 2000)
        self.leftSpin.setSuffix(self.tr(" px"))
        self.leftSpin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.rightSpin = SpinBox(self.cropCard)
        self.rightSpin.setRange(0, 2000)
        self.rightSpin.setSuffix(self.tr(" px"))
        self.rightSpin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.cropButton = PrimaryPushButton(self.tr("开始裁剪"), self.cropCard)
        self.cropActionLayout.addWidget(self.cropMarginLabel)
        self.cropActionLayout.addWidget(self.topSpin)
        self.cropActionLayout.addWidget(StrongBodyLabel(
            self.tr("下"), self.cropCard))
        self.cropActionLayout.addWidget(self.bottomSpin)
        self.cropActionLayout.addWidget(StrongBodyLabel(
            self.tr("左"), self.cropCard))
        self.cropActionLayout.addWidget(self.leftSpin)
        self.cropActionLayout.addWidget(StrongBodyLabel(
            self.tr("右"), self.cropCard))
        self.cropActionLayout.addWidget(self.rightSpin)
        self.cropActionLayout.addWidget(self.cropButton)
        self.cropCardLayout.addLayout(self.cropActionLayout)
        self.cropCard.setFixedHeight(116)

        self.publishGroup = SettingCardGroup(
            self.tr("发布设置"), self.scrollWidget)

        self.uploadCard = CardWidget(self.publishGroup)
        self.uploadCardLayout = QHBoxLayout(self.uploadCard)
        self.uploadCardVBox = QVBoxLayout()
        self.uploadTitleLabel = StrongBodyLabel(
            self.tr("文章素材"), self.uploadCard)
        self.uploadDescLabel = CaptionLabel(
            self.tr("选择已下载的文章目录和需要上传的图片张数"),
            self.uploadCard)
        self.folderCombo = ComboBox(self.uploadCard)
        self.folderCombo.setMinimumWidth(260)
        self.countCombo = ComboBox(self.uploadCard)
        self.countCombo.setFixedWidth(100)
        self.refreshFolderButton = PushButton(
            self.tr("刷新"), self.uploadCard)
        self.uploadButton = PrimaryPushButton(
            self.tr("上传"), self.uploadCard)

        self.uploadCardVBox.setSpacing(0)
        self.uploadCardVBox.addWidget(self.uploadTitleLabel)
        self.uploadCardVBox.addWidget(self.uploadDescLabel)
        self.uploadCardLayout.setContentsMargins(20, 11, 20, 11)
        self.uploadCardLayout.setSpacing(12)
        self.uploadCardLayout.addLayout(self.uploadCardVBox)
        self.uploadCardLayout.addWidget(self.folderCombo, 1)
        self.uploadCardLayout.addWidget(self.countCombo)
        self.uploadCardLayout.addWidget(self.refreshFolderButton)
        self.uploadCardLayout.addWidget(self.uploadButton)
        self.uploadCard.setFixedHeight(82)

        self.templateCard = CardWidget(self.publishGroup)
        self.templateCardLayout = QHBoxLayout(self.templateCard)
        self.templateCardVBox = QVBoxLayout()
        self.templateTitleLabel = StrongBodyLabel(
            self.tr("模板路径"), self.templateCard)
        self.templateInfoLabel = CaptionLabel(
            self.tr("请选择公众号模板根目录（支持日期/分类子目录）"),
            self.templateCard)
        self.selectTemplateButton = PushButton(
            self.tr("选择目录"), self.templateCard)
        self.openTemplateButton = PushButton(
            self.tr("打开文件夹"), self.templateCard)
        self.nextTemplateDayButton = PushButton(
            self.tr("下一天"), self.templateCard)
        self.templateCardVBox.setSpacing(0)
        self.templateCardVBox.addWidget(self.templateTitleLabel)
        self.templateCardVBox.addWidget(self.templateInfoLabel)
        self.templateCardLayout.setContentsMargins(20, 11, 20, 11)
        self.templateCardLayout.setSpacing(12)
        self.templateCardLayout.addLayout(self.templateCardVBox)
        self.templateCardLayout.addStretch(1)
        self.templateCardLayout.addWidget(self.openTemplateButton)
        self.templateCardLayout.addWidget(self.selectTemplateButton)
        self.templateCardLayout.addWidget(self.nextTemplateDayButton)
        self.templateCard.setFixedHeight(82)

        self.publishTargetGroup = SettingCardGroup(
            self.tr("同时发布到"), self.scrollWidget)
        self.targetCard = CardWidget(self.publishTargetGroup)
        self.targetCardLayout = QHBoxLayout(self.targetCard)
        self.targetCardVBox = QVBoxLayout()
        self.targetTitleLabel = StrongBodyLabel(self.tr("发布目标"), self.targetCard)
        self.targetDescLabel = CaptionLabel(
            self.tr("选择要接收当前文章内容的公众号"), self.targetCard)
        self.accountMultiCombo = MultiSelectionComboBox(self.targetCard)
        self.accountMultiCombo.setFixedWidth(300)
        self.targetCardVBox.setSpacing(0)
        self.targetCardVBox.addWidget(self.targetTitleLabel)
        self.targetCardVBox.addWidget(self.targetDescLabel)
        self.targetCardLayout.setContentsMargins(20, 11, 20, 11)
        self.targetCardLayout.addLayout(self.targetCardVBox)
        self.targetCardLayout.addStretch(1)
        self.targetCardLayout.addWidget(self.accountMultiCombo)
        self.targetCard.setFixedHeight(73)

        self.actionCard = CardWidget(self.publishTargetGroup)
        self.actionCardLayout = QHBoxLayout(self.actionCard)
        self.actionCardVBox = QVBoxLayout()
        self.actionTitleLabel = StrongBodyLabel(self.tr("发布"), self.actionCard)
        self.actionDescLabel = CaptionLabel(
            self.tr("校验文章、图片和发布目标后准备发布"), self.actionCard)

        self.headlessCheck = CheckBox(self.tr("隐藏浏览器"), self.actionCard)
        self.headlessCheck.setChecked(True)

        self.pausePublishButton = PushButton(self.tr("暂停"), self.actionCard)
        self.pausePublishButton.setVisible(False)

        self.stopPublishButton = PushButton(self.tr("终止"), self.actionCard)
        self.stopPublishButton.setVisible(False)

        self.preparePublishButton = PrimaryPushButton(self.tr("发布"), self.actionCard)

        self.actionCardVBox.setSpacing(0)
        self.actionCardVBox.addWidget(self.actionTitleLabel)
        self.actionCardVBox.addWidget(self.actionDescLabel)
        self.actionCardLayout.setContentsMargins(20, 11, 20, 11)
        self.actionCardLayout.setSpacing(12)
        self.actionCardLayout.addLayout(self.actionCardVBox)
        self.actionCardLayout.addStretch(1)
        self.actionCardLayout.addWidget(self.headlessCheck)
        self.actionCardLayout.addWidget(self.pausePublishButton)
        self.actionCardLayout.addWidget(self.stopPublishButton)
        self.actionCardLayout.addWidget(self.preparePublishButton)
        self.actionCard.setFixedHeight(73)

        self.logPanel = LogPanel(self.tr("下载日志"), self.scrollWidget)
        self.logPanel.setMinimumHeight(340)
        self.logPanel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._loadAccounts()
        self._refreshMaterialAccountSummary()
        self._refreshDownloadFolders()
        self._refreshCropFolders()
        self.__initWidget()

    def __initWidget(self):
        self.resize(1000, 800)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 100, 0, 20)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName("wechat2Interface")

        setFont(self.titleLabel, 23, QFont.Weight.DemiBold)
        self.scrollWidget.setObjectName("scrollWidget")
        self.titleLabel.setObjectName("settingLabel")
        self.scrollWidget.setStyleSheet(
            "#scrollWidget{background:transparent}")

        self.__initLayout()
        self._connectSignalToSlot()

    def __initLayout(self):
        self.titleLabel.move(36, 50)
        self.accountGroup.addSettingCard(self.accountCard)
        self.accountGroup.addSettingCard(self.materialCard)
        self.downloadGroup.addSettingCard(self.downloadCard)
        self.downloadGroup.addSettingCard(self.cropCard)
        self.publishGroup.addSettingCard(self.uploadCard)
        self.publishGroup.addSettingCard(self.templateCard)
        self.publishTargetGroup.addSettingCard(self.targetCard)
        self.publishTargetGroup.addSettingCard(self.actionCard)
        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(36, 10, 36, 0)
        self.expandLayout.addWidget(self.accountGroup)
        self.expandLayout.addWidget(self.downloadGroup)
        self.expandLayout.addWidget(self.publishGroup)
        self.expandLayout.addWidget(self.publishTargetGroup)
        self.expandLayout.addWidget(self.logPanel)
        self.scrollWidget.adjustSize()

    def _connectSignalToSlot(self):
        self.refreshAccountButton.clicked.connect(self._loadAccounts)
        self.materialSettingsButton.clicked.connect(self._openMaterialAccountDialog)
        self.downloadButton.clicked.connect(self._downloadImages)
        self.openFolderButton.clicked.connect(self._openDownloadFolder)
        self.urlEdit.returnPressed.connect(self._downloadImages)
        self.selectCropFilesButton.clicked.connect(self._selectCropFiles)
        self.selectCropFolderButton.clicked.connect(self._selectCropFolder)
        self.cropFolderCombo.currentIndexChanged.connect(self._onCropFolderChanged)
        self.refreshCropFolderButton.clicked.connect(self._refreshCropFolders)
        self.cropSelectButton.clicked.connect(self._openCropPreview)
        self.cropButton.clicked.connect(self._startCrop)
        self.refreshFolderButton.clicked.connect(self._refreshDownloadFolders)
        self.folderCombo.currentIndexChanged.connect(self._refreshUploadCounts)
        self.uploadButton.clicked.connect(self._uploadSelectedImages)
        self.openTemplateButton.clicked.connect(self._openTemplateFolder)
        self.selectTemplateButton.clicked.connect(self._selectTemplate)
        self.nextTemplateDayButton.clicked.connect(self._switchToNextTemplateDay)
        self.accountCombo.currentTextChanged.connect(self._onAccountChanged)
        self.preparePublishButton.clicked.connect(self._preparePublish)
        self.pausePublishButton.clicked.connect(self._pausePublish)
        self.stopPublishButton.clicked.connect(self._stopPublish)

    def _getTemplateDir(self):
        if self._customTemplateDir:
            return Path(self._customTemplateDir)
        account = self.accountCombo.currentText()
        if not account or account == self.tr("暂无已登录账号"):
            return None
        template_dir = get_today_templates_dir(account)
        template_dir.mkdir(parents=True, exist_ok=True)
        return template_dir

    def _refreshTemplateInfo(self):
        template_dir = self._getTemplateDir()
        if template_dir is None:
            self._templatePath = ""
            self.templateInfoLabel.setText(self.tr("请先选择账号"))
            return
        template_dir.mkdir(parents=True, exist_ok=True)
        self._templatePath = str(template_dir)
        json_count = len(list(template_dir.rglob("*.json")))
        self.templateInfoLabel.setText(
            f"{template_dir}（{json_count} 个 JSON）"
        )

    def _onAccountChanged(self, _text):
        self._customTemplateDir = ""
        self._refreshTemplateInfo()

    def _openTemplateFolder(self):
        template_dir = self._getTemplateDir()
        if template_dir is None:
            InfoBar.warning(self.tr("提示"), self.tr("请先选择账号"),
                            duration=2000, parent=self)
            return
        template_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(template_dir)))

    def _selectTemplate(self):
        template_dir = self._getTemplateDir()
        path = QFileDialog.getExistingDirectory(
            self,
            self.tr("选择模板目录"),
            str(template_dir) if template_dir else "",
        )
        if not path:
            return
        self._customTemplateDir = path
        self._refreshTemplateInfo()
        self.logPanel.append(f"[模板] 已切换目录：{path}")

    def _switchToNextTemplateDay(self):
        template_dir = self._getTemplateDir()
        if template_dir is None:
            InfoBar.warning(self.tr("提示"), self.tr("请先选择账号"),
                            duration=2000, parent=self)
            return
        next_dir = get_next_day_templates_dir(template_dir)
        created = not next_dir.exists()
        next_dir.mkdir(parents=True, exist_ok=True)
        self._customTemplateDir = str(next_dir)
        self._refreshTemplateInfo()
        message = self.tr("已创建并切换到 {}") if created \
            else self.tr("已切换到 {}")
        InfoBar.success(self.tr("成功"), message.format(next_dir.name),
                        duration=3000, parent=self)

    def _loadAccounts(self):
        self._customTemplateDir = ""
        accounts = get_accounts()
        self.accountCombo.clear()
        self.accountMultiCombo.clear()
        if accounts:
            self.accountCombo.addItems(accounts)
            self.accountMultiCombo.addItems(accounts)
            self.accountMultiCombo.addSelectedIndex(0)
        else:
            self.accountCombo.addItem(self.tr("暂无已登录账号"))
        self._refreshTemplateInfo()

    def _refreshMaterialAccountSummary(self):
        account = load_material_account()
        name = account.get("name", "").strip()
        configured = bool(account.get("appid") and account.get("appsecret"))
        if configured:
            self.materialDescLabel.setText(
                self.tr("当前素材账号：{}{}").format(
                    name or self.tr("未命名"), self.tr("（已配置）")
                )
            )
        else:
            self.materialDescLabel.setText(self.tr("未配置素材账号"))

    def _openMaterialAccountDialog(self):
        dialog = MaterialAccountDialog(self.window())
        if dialog.exec():
            save_material_account(dialog.account())
            self._refreshMaterialAccountSummary()
            self.logPanel.append("[素材账号] 配置已保存")
            InfoBar.success(self.tr("已保存"), self.tr("素材账号配置已保存到本地"),
                            duration=2000, parent=self)

    def _downloadImages(self):
        url = self.urlEdit.text().strip()
        if not url:
            InfoBar.warning(self.tr("提示"), self.tr("请输入公众号文章链接"),
                            duration=2000, parent=self)
            return

        count_text = self.downloadCountCombo.currentText()
        max_count = 0
        if count_text != "全部" and count_text.endswith("张"):
            try:
                max_count = int(count_text[:-1])
            except ValueError:
                max_count = 0

        self.logPanel.clear()
        self.logPanel.append(f"准备下载：{url}")
        self.downloadButton.setEnabled(False)
        self.downloadButton.setText(self.tr("下载中..."))

        crop_bottom = 80 if self.autoCropCheck.isChecked() else 0
        if crop_bottom:
            self.logPanel.append(
                f"[自动裁剪] 已启用，裁掉底部 {crop_bottom}px")

        self._downloadThread = WechatImageDownloadThread(
            url, max_count, crop_bottom=crop_bottom, parent=self)
        self._downloadThread.logMessage.connect(self.logPanel.append)
        self._downloadThread.downloadSuccess.connect(self._onDownloadSuccess)
        self._downloadThread.downloadFailed.connect(self._onDownloadFailed)
        self._downloadThread.start()

    def _onDownloadSuccess(self, save_dir: str, count: int):
        self.downloadButton.setEnabled(True)
        self.downloadButton.setText(self.tr("下载"))
        self.logPanel.append(f"完成：共下载 {count} 张图片")
        self.logPanel.append(f"保存目录：{save_dir}")
        self._refreshDownloadFolders(save_dir)
        self._customCropImages = []
        self._customCropDesc = ""
        self._refreshCropFolders(save_dir)
        InfoBar.success(self.tr("下载完成"),
                        self.tr("已保存正文和 {} 张图片").format(count),
                        duration=3000, parent=self)

    def _onDownloadFailed(self, error: str):
        self.downloadButton.setEnabled(True)
        self.downloadButton.setText(self.tr("下载"))
        self.logPanel.append(f"[错误] {error}")
        InfoBar.error(self.tr("下载失败"), error,
                      duration=5000, parent=self)

    def _openDownloadFolder(self):
        IMAGE_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(IMAGE_DOWNLOAD_DIR)))

    def _refreshDownloadFolders(self, selected_path: str = ""):
        self._downloadFolders = list_download_folders()
        self.folderCombo.blockSignals(True)
        self.folderCombo.clear()
        if not self._downloadFolders:
            self.folderCombo.addItem(self.tr("暂无已下载文件夹"))
        else:
            self.folderCombo.addItems([path.name for path in self._downloadFolders])
            if selected_path:
                for index, path in enumerate(self._downloadFolders):
                    if str(path) == selected_path:
                        self.folderCombo.setCurrentIndex(index)
                        break
        self.folderCombo.blockSignals(False)
        self._refreshUploadCounts()

    def _getSelectedFolder(self):
        index = self.folderCombo.currentIndex()
        if 0 <= index < len(self._downloadFolders):
            return self._downloadFolders[index]
        return None

    def _selectCropFiles(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            self.tr("选择要裁剪的图片文件"),
            "",
            self.tr("图片文件 (*.jpg *.jpeg *.png *.webp *.bmp *.gif);;所有文件 (*.*)"),
        )
        if not file_paths:
            return
        self._customCropImages = [Path(f) for f in file_paths]
        names_preview = Path(file_paths[0]).name if len(file_paths) == 1 else f"{Path(file_paths[0]).name} 等 {len(file_paths)} 张"
        self._customCropDesc = self.tr("已选择 {} 个文件（{}）").format(len(file_paths), names_preview)
        self.cropDescLabel.setText(self._customCropDesc)
        self.logPanel.append(f"[快速裁剪] 已选择 {len(file_paths)} 个图片文件")
        InfoBar.success(self.tr("已选择文件"),
                        self.tr("共选择 {} 张图片，点击「选择裁剪区域」设置边距").format(len(file_paths)),
                        duration=2500, parent=self)

    def _selectCropFolder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            self.tr("选择要裁剪的图片文件夹"),
            "",
        )
        if not folder:
            return
        folder_path = Path(folder)
        images = list_crop_images(folder_path)
        if not images:
            InfoBar.warning(self.tr("提示"), self.tr("所选文件夹中没有可裁剪的图片"),
                            duration=2500, parent=self)
            return
        self._customCropImages = images
        self._customCropDesc = self.tr("已选择文件夹：{}（共 {} 张图片）").format(folder_path.name, len(images))
        self.cropDescLabel.setText(self._customCropDesc)
        self.logPanel.append(f"[快速裁剪] 已选择文件夹：{folder}（共 {len(images)} 张图片）")
        InfoBar.success(self.tr("已选择文件夹"),
                        self.tr("找到 {} 张图片，点击「选择裁剪区域」设置边距").format(len(images)),
                        duration=2500, parent=self)

    def _onCropFolderChanged(self, index: int):
        self._customCropImages = []
        self._customCropDesc = ""
        self._updateCropDesc()

    def _updateCropDesc(self):
        if self._customCropDesc:
            self.cropDescLabel.setText(self._customCropDesc)
            return
        folder = self._getSelectedCropFolder()
        if folder:
            images = list_crop_images(folder)
            self.cropDescLabel.setText(
                self.tr("当前下载目录：{}（共 {} 张图片）").format(folder.name, len(images)))
        else:
            self.cropDescLabel.setText(
                self.tr("选择文件或文件夹，用第一张图框选裁剪区域，批量应用并直接覆盖原图"))

    def _refreshCropFolders(self, selected_path: str = ""):
        self._cropFolders = list_download_folders()
        self.cropFolderCombo.blockSignals(True)
        self.cropFolderCombo.clear()
        if not self._cropFolders:
            self.cropFolderCombo.addItem(self.tr("暂无已下载文件夹"))
        else:
            self.cropFolderCombo.addItems(
                [path.name for path in self._cropFolders])
            if selected_path:
                for index, path in enumerate(self._cropFolders):
                    if str(path) == selected_path:
                        self.cropFolderCombo.setCurrentIndex(index)
                        break
        self.cropFolderCombo.blockSignals(False)
        self._updateCropDesc()

    def _getSelectedCropFolder(self):
        index = self.cropFolderCombo.currentIndex()
        if 0 <= index < len(self._cropFolders):
            return self._cropFolders[index]
        return None

    def _getCropImages(self) -> list[Path]:
        if self._customCropImages:
            return [p for p in self._customCropImages if p.is_file()]
        folder = self._getSelectedCropFolder()
        if folder:
            return list_crop_images(folder)
        return []

    def _openCropPreview(self):
        images = self._getCropImages()
        if not images:
            InfoBar.warning(self.tr("提示"), self.tr("请先选择图片文件或文件夹"),
                            duration=2000, parent=self)
            return

        dialog = CropPreviewDialog(images[0], self.window())
        if dialog.exec():
            top, bottom, left, right = dialog.crop_margins
            self.topSpin.setValue(top)
            self.bottomSpin.setValue(bottom)
            self.leftSpin.setValue(left)
            self.rightSpin.setValue(right)
            self.logPanel.append(
                f"[快速裁剪] 参考图：{images[0].name}，"
                f"边距：上{top} 下{bottom} 左{left} 右{right} px")
            InfoBar.success(self.tr("边距检测完成"),
                            self.tr("已根据参考图自动计算裁剪边距，可手动微调"),
                            duration=3000, parent=self)

    def _startCrop(self):
        images = self._getCropImages()
        if not images:
            InfoBar.warning(self.tr("提示"), self.tr("请先选择图片文件或文件夹"),
                            duration=2000, parent=self)
            return
        top = self.topSpin.value()
        bottom = self.bottomSpin.value()
        left = self.leftSpin.value()
        right = self.rightSpin.value()
        if top == 0 and bottom == 0 and left == 0 and right == 0:
            InfoBar.warning(self.tr("提示"), self.tr("请先点击「选择裁剪区域」设置边距"),
                            duration=2000, parent=self)
            return

        dialog = MessageBox(
            self.tr("确认裁剪"),
            self.tr("将对 {} 张图片按边距（上 {} / 下 {} / 左 {} / 右 {} px）"
                    "批量裁剪并直接覆盖原图，原图无法恢复。是否继续？")
            .format(len(images), top, bottom, left, right),
            self.window())
        dialog.yesButton.setText(self.tr("开始裁剪"))
        dialog.cancelButton.setText(self.tr("取消"))
        if not dialog.exec():
            return

        self.cropButton.setEnabled(False)
        self.cropButton.setText(self.tr("裁剪中..."))
        self._cropThread = ImageCropThread(
            images, top, bottom, left, right, self)
        self._cropThread.logMessage.connect(self.logPanel.append)
        self._cropThread.cropSuccess.connect(self._onCropSuccess)
        self._cropThread.cropFailed.connect(self._onCropFailed)
        self._cropThread.start()

    def _onCropSuccess(self, total: int, cropped: int, failed: int):
        self.cropButton.setEnabled(True)
        self.cropButton.setText(self.tr("开始裁剪"))
        self.logPanel.append(
            f"[快速裁剪] 完成：共 {total} 张，成功 {cropped} 张，跳过 {failed} 张")
        if failed:
            InfoBar.warning(self.tr("裁剪完成"),
                            self.tr("成功 {} 张，跳过 {} 张")
                            .format(cropped, failed),
                            duration=4000, parent=self)
        else:
            InfoBar.success(self.tr("裁剪完成"),
                            self.tr("已裁剪 {} 张图片").format(cropped),
                            duration=3000, parent=self)

    def _onCropFailed(self, error: str):
        self.cropButton.setEnabled(True)
        self.cropButton.setText(self.tr("开始裁剪"))
        self.logPanel.append(f"[快速裁剪错误] {error}")
        InfoBar.error(self.tr("裁剪失败"), error,
                      duration=5000, parent=self)

    def _refreshUploadCounts(self):
        folder = self._getSelectedFolder()
        images = list_uploadable_images(folder) if folder else []
        self.countCombo.clear()
        if not images:
            self.countCombo.addItem(self.tr("0张"))
            return
        self.countCombo.addItem(self.tr("全部"))
        self.countCombo.addItems([f"{i}张" for i in range(1, len(images) + 1)])

    def _getSelectedUploadCount(self):
        text = self.countCombo.currentText()
        if text == self.tr("全部"):
            return None
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else 0

    def _uploadSelectedImages(self):
        folder = self._getSelectedFolder()
        if folder is None:
            InfoBar.warning(self.tr("提示"), self.tr("请选择图片文件夹"),
                            duration=2000, parent=self)
            return
        count = self._getSelectedUploadCount()
        if count == 0:
            InfoBar.warning(self.tr("提示"), self.tr("当前文件夹没有可上传图片"),
                            duration=2000, parent=self)
            return

        self.uploadButton.setEnabled(False)
        self.uploadButton.setText(self.tr("上传中..."))
        self.logPanel.append(f"[上传设置] 文件夹：{folder}")
        self.logPanel.append(
            f"[上传设置] 张数：{'全部' if count is None else count}")

        self._uploadThread = MaterialImageUploadThread(folder, count, self)
        self._uploadThread.logMessage.connect(self.logPanel.append)
        self._uploadThread.uploadSuccess.connect(self._onUploadSuccess)
        self._uploadThread.uploadFailed.connect(self._onUploadFailed)
        self._uploadThread.start()

    def _preparePublish(self):
        selected_indexes = self.accountMultiCombo.selectedIndexes()
        targets = [
            self.accountMultiCombo.itemText(index)
            for index in selected_indexes
        ]
        if not targets:
            InfoBar.warning(self.tr("提示"), self.tr("请选择至少一个发布目标"),
                            duration=2000, parent=self)
            return

        if not self._templatePath:
            InfoBar.warning(self.tr("提示"), self.tr("请先选择模板目录"),
                            duration=2500, parent=self)
            return
        try:
            paths, missing_by_file = load_publish_templates(Path(self._templatePath))
        except ValueError as error:
            InfoBar.error(self.tr("模板错误"), str(error),
                          duration=5000, parent=self)
            return
        if missing_by_file:
            missing = "；".join(
                f"{name}: {'、'.join(fields)}"
                for name, fields in missing_by_file.items()
            )
            InfoBar.warning(self.tr("模板字段不完整"),
                            self.tr("字段不完整：{}" ).format(missing),
                            duration=5000, parent=self)
            return
        self.logPanel.append(f"[发布准备] 目标：{'、'.join(targets)}")
        self.logPanel.append(
            f"[发布准备] 模板：{self._templatePath}（{len(paths)} 个 JSON）"
        )
        headless = self.headlessCheck.isChecked()
        self.preparePublishButton.setEnabled(False)
        self.preparePublishButton.setText(self.tr("发布中..."))
        self.pausePublishButton.setVisible(True)
        self.pausePublishButton.setText(self.tr("暂停"))
        self.stopPublishButton.setVisible(True)
        self.stopPublishButton.setEnabled(True)
        self.stopPublishButton.setText(self.tr("终止"))

        self._publishThread = Wechat2JsonPublishThread(targets, paths, headless=headless, parent=self)
        self._publishThread.logMessage.connect(self.logPanel.append)
        self._publishThread.publishSuccess.connect(self._onPublishSuccess)
        self._publishThread.publishFailed.connect(self._onPublishFailed)
        self._publishThread.publishStopped.connect(self._onPublishStopped)
        self._publishThread.publishWaiting.connect(self._onPublishWaiting)
        self._publishThread.start()

    def _pausePublish(self):
        if not self._publishThread:
            return
        if self.pausePublishButton.text() == self.tr("暂停"):
            self._publishThread.pause()
            self.pausePublishButton.setText(self.tr("继续"))
        else:
            self._publishThread.resume()
            self.pausePublishButton.setText(self.tr("暂停"))

    def _stopPublish(self):
        if self._publishThread:
            self._publishThread.stop()
            self.stopPublishButton.setEnabled(False)
            self.stopPublishButton.setText(self.tr("正在停止..."))

    def _resetPublishButtons(self):
        self.preparePublishButton.setEnabled(True)
        self.preparePublishButton.setText(self.tr("发布"))
        self.pausePublishButton.setVisible(False)
        self.pausePublishButton.setText(self.tr("暂停"))
        self.stopPublishButton.setVisible(False)
        self.stopPublishButton.setEnabled(True)
        self.stopPublishButton.setText(self.tr("终止"))

    def _onPublishSuccess(self, success_count: int, failed_count: int):
        self._resetPublishButtons()
        self.logPanel.append(
            f"[发布完成] 成功 {success_count} 篇，失败 {failed_count} 篇"
        )
        if failed_count:
            InfoBar.warning(self.tr("发布完成"),
                            self.tr("成功 {} 篇，失败 {} 篇")
                            .format(success_count, failed_count),
                            duration=5000, parent=self)
        else:
            InfoBar.success(self.tr("发布完成"),
                            self.tr("已创建 {} 篇草稿")
                            .format(success_count),
                            duration=4000, parent=self)

    def _onPublishFailed(self, error: str):
        self._resetPublishButtons()
        self.logPanel.append(f"[发布失败] {error}")
        InfoBar.error(self.tr("发布失败"), error,
                      duration=6000, parent=self)

    def _onPublishStopped(self):
        self._resetPublishButtons()
        self.logPanel.append("[发布流程] 已终止")
        InfoBar.info(self.tr("已终止"), self.tr("发布流程已终止"),
                     duration=3000, parent=self)

    def _onPublishWaiting(self):
        self.pausePublishButton.setVisible(False)
        self.stopPublishButton.setText(self.tr("结束流程"))
        self.stopPublishButton.setEnabled(True)
        self.stopPublishButton.setVisible(True)

    def _onUploadSuccess(self, output: str, count: int):
        self.uploadButton.setEnabled(True)
        self.uploadButton.setText(self.tr("上传"))
        self.logPanel.append(f"[上传设置] 完成：已上传 {count} 张")
        self.logPanel.append(f"[上传设置] URL 清单：{output}")
        InfoBar.success(self.tr("上传完成"),
                        self.tr("已上传 {} 张图片").format(count),
                        duration=3000, parent=self)

        try:
            output_path = Path(output)
            if output_path.exists():
                text = output_path.read_text(encoding="utf-8").strip()
                if output_path.suffix.lower() == ".json":
                    try:
                        mapping = json.loads(text)
                        if isinstance(mapping, dict):
                            urls = list(mapping.values())
                        else:
                            urls = [line.strip() for line in text.splitlines() if line.strip()]
                    except Exception:
                        urls = [line.strip() for line in text.splitlines() if line.strip()]
                else:
                    urls = [line.strip() for line in text.splitlines() if line.strip()]

                raw_urls_text = "\n".join(urls)
                dialog = UploadUrlsDialog(raw_urls_text, len(urls), self.window())
                dialog.exec()
        except Exception as error:
            self.logPanel.append(f"[展示地址弹窗失败] {error}")

    def _onUploadFailed(self, error: str):
        self.uploadButton.setEnabled(True)
        self.uploadButton.setText(self.tr("上传"))
        self.logPanel.append(f"[上传设置错误] {error}")
        InfoBar.error(self.tr("上传失败"), error,
                      duration=5000, parent=self)
