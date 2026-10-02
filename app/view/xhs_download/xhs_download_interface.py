# coding: utf-8
"""小红书下载 UI。"""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QTextCursor
from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                                QSizePolicy)

from qfluentwidgets import (ScrollArea, ExpandLayout, PrimaryPushButton,
                            PushButton, LineEdit, setFont, TextEdit,
                            CardWidget, InfoBar, SettingCardGroup as CardGroup,
                            StrongBodyLabel, CaptionLabel)

from .xhs_download_service import XHS_DOWNLOAD_DIR, XhsNoteDownloadThread


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
        self.textEdit.setPlaceholderText(self.tr("下载结果会显示在这里"))
        self.textEdit.setMinimumHeight(360)
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


class XhsDownloadInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)
        self.titleLabel = QLabel(self.tr("下载"), self)
        self._downloadThread = None
        self._lastSaveDir = ""

        self.downloadGroup = SettingCardGroup(
            self.tr("小红书下载"), self.scrollWidget)

        self.downloadCard = CardWidget(self.downloadGroup)
        self.downloadCardLayout = QHBoxLayout(self.downloadCard)
        self.downloadCardVBox = QVBoxLayout()
        self.downloadTitleLabel = StrongBodyLabel(
            self.tr("小红书链接"), self.downloadCard)
        self.downloadDescLabel = CaptionLabel(
            self.tr("输入链接，下载图片并提取标题、文案和标签"),
            self.downloadCard)
        self.urlEdit = LineEdit(self.downloadCard)
        self.urlEdit.setPlaceholderText(
            self.tr("https://www.xiaohongshu.com/explore/... 或 xhslink.com/..."))
        self.urlEdit.setClearButtonEnabled(True)
        self.urlEdit.setMinimumWidth(420)
        self.downloadButton = PrimaryPushButton(
            self.tr("下载"), self.downloadCard)
        self.openFolderButton = PushButton(
            self.tr("打开目录"), self.downloadCard)

        self.downloadCardVBox.setSpacing(0)
        self.downloadCardVBox.addWidget(self.downloadTitleLabel)
        self.downloadCardVBox.addWidget(self.downloadDescLabel)
        self.downloadCardLayout.setContentsMargins(20, 11, 20, 11)
        self.downloadCardLayout.setSpacing(12)
        self.downloadCardLayout.addLayout(self.downloadCardVBox)
        self.downloadCardLayout.addWidget(self.urlEdit, 1)
        self.downloadCardLayout.addWidget(self.openFolderButton)
        self.downloadCardLayout.addWidget(self.downloadButton)
        self.downloadCard.setFixedHeight(82)

        self.logPanel = LogPanel(self.tr("下载结果"), self.scrollWidget)
        self.logPanel.setMinimumHeight(440)
        self.logPanel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.__initWidget()

    def __initWidget(self):
        self.resize(1000, 800)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 100, 0, 20)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName("xhsDownloadInterface")

        setFont(self.titleLabel, 23, QFont.Weight.DemiBold)
        self.scrollWidget.setObjectName("scrollWidget")
        self.titleLabel.setObjectName("settingLabel")
        self.scrollWidget.setStyleSheet(
            "#scrollWidget{background:transparent}")

        self.__initLayout()
        self._connectSignalToSlot()

    def __initLayout(self):
        self.titleLabel.move(36, 50)
        self.downloadGroup.addSettingCard(self.downloadCard)
        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(36, 10, 36, 0)
        self.expandLayout.addWidget(self.downloadGroup)
        self.expandLayout.addWidget(self.logPanel)
        self.scrollWidget.adjustSize()

    def _connectSignalToSlot(self):
        self.downloadButton.clicked.connect(self._download)
        self.openFolderButton.clicked.connect(self._openDownloadFolder)
        self.urlEdit.returnPressed.connect(self._download)

    def _download(self):
        url = self.urlEdit.text().strip()
        if not url:
            InfoBar.warning(self.tr("提示"), self.tr("请输入小红书链接"),
                            duration=2000, parent=self)
            return

        self.logPanel.clear()
        self.logPanel.append(f"准备下载：{url}")
        self.downloadButton.setEnabled(False)
        self.downloadButton.setText(self.tr("下载中..."))

        self._downloadThread = XhsNoteDownloadThread(url, self)
        self._downloadThread.logMessage.connect(self.logPanel.append)
        self._downloadThread.downloadSuccess.connect(self._onDownloadSuccess)
        self._downloadThread.downloadFailed.connect(self._onDownloadFailed)
        self._downloadThread.start()

    def _onDownloadSuccess(self, save_dir: str, fields: dict):
        self.downloadButton.setEnabled(True)
        self.downloadButton.setText(self.tr("下载"))
        self._lastSaveDir = save_dir
        tags = fields.get("tags") or []
        tag_text = " ".join(tags) if isinstance(tags, list) else str(tags)
        self.logPanel.append("")
        self.logPanel.append(f"标题：{fields.get('title', '')}")
        self.logPanel.append(f"文案：{fields.get('desc', '')}")
        self.logPanel.append(f"标签：{tag_text}")
        self.logPanel.append(f"保存目录：{save_dir}")
        InfoBar.success(self.tr("下载完成"),
                        self.tr("已保存图片和作品信息"),
                        duration=3000, parent=self)

    def _onDownloadFailed(self, error: str):
        self.downloadButton.setEnabled(True)
        self.downloadButton.setText(self.tr("下载"))
        self.logPanel.append(f"[错误] {error}")
        InfoBar.error(self.tr("下载失败"), error,
                      duration=5000, parent=self)

    def _openDownloadFolder(self):
        path = self._lastSaveDir or str(XHS_DOWNLOAD_DIR)
        XHS_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
