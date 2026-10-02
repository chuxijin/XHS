# coding: utf-8
import base64
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QBuffer, QByteArray
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                                QFileDialog, QApplication, QSizePolicy)
from qfluentwidgets import (ScrollArea, SingleDirectionScrollArea, ExpandLayout,
                            PrimaryPushButton, PushButton, TransparentToolButton,
                            PlainTextEdit, setFont, CardWidget, InfoBar, InfoBarPosition,
                            ComboBox, SettingCardGroup as CardGroup, BodyLabel,
                            StrongBodyLabel, CaptionLabel)
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgetspro import DropMultiFilesWidget

from ...common.config import cfg
from .image_gen_service import ImageGenThread, ImageGenHistoryManager, SAVE_DIR


class SettingCardGroup(CardGroup):
    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        setFont(self.titleLabel, 14, QFont.Weight.DemiBold)


class ImageCard(CardWidget):
    """生成结果图片卡片（带下载和删除按钮）"""
    removed = None

    def __init__(self, index: int, b64_data: str, mime: str, parent=None):
        super().__init__(parent)
        self.index = index
        self.b64_data = b64_data
        self.mime = mime

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.preview = QLabel(self)
        self.preview.setFixedHeight(180)
        self.preview.setScaledContents(True)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        pixmap = QPixmap()
        pixmap.loadFromData(base64.b64decode(b64_data), mime.split("/")[-1].upper() if mime else "PNG")
        self.preview.setPixmap(pixmap)
        layout.addWidget(self.preview)

        info_layout = QHBoxLayout()
        info_layout.setSpacing(4)
        self.index_label = BodyLabel(f"第 {index + 1} 张", self)
        self.index_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        info_layout.addWidget(self.index_label)

        self.size_label = CaptionLabel(f"{pixmap.width()}x{pixmap.height()}px", self)
        self.size_label.setStyleSheet("color: gray;")
        info_layout.addWidget(self.size_label)
        info_layout.addStretch(1)

        # 下载按钮
        self.save_btn = PushButton("下载", self)
        self.save_btn.setIcon(FIF.DOWNLOAD)
        self.save_btn.clicked.connect(self._save)
        info_layout.addWidget(self.save_btn)

        # 删除按钮
        self.del_btn = TransparentToolButton(FIF.DELETE, self)
        self.del_btn.setToolTip("删除")
        self.del_btn.setFixedSize(28, 28)
        self.del_btn.clicked.connect(self._delete)
        info_layout.addWidget(self.del_btn)

        layout.addLayout(info_layout)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存图片", str(SAVE_DIR / f"image_{self.index + 1}.png"),
            "图片 (*.png *.jpg *.jpeg *.webp)",
        )
        if path:
            Path(path).write_bytes(base64.b64decode(self.b64_data))
            InfoBar.success(
                title="保存成功", content=f"已保存到 {path}",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self,
            )

    def _delete(self):
        self.setParent(None)
        self.deleteLater()
        if callable(self.removed):
            self.removed(self)


class HistoryRecordCard(CardWidget):
    """历史记录单个项卡片（限制宽度 + 提示词单行自动省略 ...）"""
    applyRecord = None
    deleteRecord = None

    def __init__(self, record: dict, parent=None):
        super().__init__(parent)
        self.record = record

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(6)

        # Header
        header_layout = QHBoxLayout()
        header_layout.setSpacing(4)
        time_label = CaptionLabel(record.get("timestamp", ""), self)
        time_label.setStyleSheet("color: #888888; font-weight: bold; font-size: 11px;")
        header_layout.addWidget(time_label)

        header_layout.addStretch(1)

        self.apply_btn = TransparentToolButton(FIF.EDIT, self)
        self.apply_btn.setToolTip("载入参数")
        self.apply_btn.setFixedSize(24, 24)
        self.apply_btn.clicked.connect(self._on_apply)
        header_layout.addWidget(self.apply_btn)

        self.copy_btn = TransparentToolButton(FIF.COPY, self)
        self.copy_btn.setToolTip("复制提示词")
        self.copy_btn.setFixedSize(24, 24)
        self.copy_btn.clicked.connect(self._on_copy)
        header_layout.addWidget(self.copy_btn)

        self.del_btn = TransparentToolButton(FIF.DELETE, self)
        self.del_btn.setToolTip("删除记录")
        self.del_btn.setFixedSize(24, 24)
        self.del_btn.clicked.connect(self._on_delete)
        header_layout.addWidget(self.del_btn)

        main_layout.addLayout(header_layout)

        # Prompt
        prompt_raw = record.get("prompt", "").replace("\n", " ").strip()
        self.prompt_label = BodyLabel(prompt_raw, self)
        self.prompt_label.setWordWrap(False)
        self.prompt_label.setToolTip(prompt_raw)
        self.prompt_label.setStyleSheet("font-size: 12px;")
        main_layout.addWidget(self.prompt_label)

        # Images
        images = record.get("images", [])
        if images:
            img_container = QWidget(self)
            img_layout = QHBoxLayout(img_container)
            img_layout.setContentsMargins(0, 2, 0, 0)
            img_layout.setSpacing(6)
            img_layout.setAlignment(Qt.AlignLeft)

            for img_item in images:
                file_path = img_item.get("file_path", "")
                b64 = img_item.get("b64", "")
                img_lbl = QLabel(img_container)
                img_lbl.setFixedSize(70, 70)
                img_lbl.setScaledContents(True)
                pixmap = QPixmap()
                if file_path and Path(file_path).exists():
                    pixmap.load(file_path)
                elif b64:
                    pixmap.loadFromData(base64.b64decode(b64))

                if not pixmap.isNull():
                    img_lbl.setPixmap(pixmap)
                    img_layout.addWidget(img_lbl)

            main_layout.addWidget(img_container)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        prompt_raw = self.record.get("prompt", "").replace("\n", " ").strip()
        avail_w = max(60, self.width() - 24)
        elided = self.fontMetrics().elidedText(prompt_raw, Qt.ElideRight, avail_w)
        self.prompt_label.setText(elided)

    def _on_apply(self):
        if callable(self.applyRecord):
            self.applyRecord(self.record)

    def _on_copy(self):
        prompt = self.record.get("prompt", "")
        QApplication.clipboard().setText(prompt)
        InfoBar.success(
            title="提示", content="提示词已复制到剪切板",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=2000, parent=self,
        )

    def _on_delete(self):
        if callable(self.deleteRecord):
            self.deleteRecord(self.record.get("id"))


class ImageGenInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)
        self.titleLabel = QLabel("AI 生图", self)

        self._thread: ImageGenThread | None = None
        self._image_cards: list[ImageCard] = []
        self._ref_files: list[str] = []
        self._history_cards: list[HistoryRecordCard] = []

        self._build_ui()
        self._load_history_records()

    def _build_ui(self):
        # ---- 1. 生图参数组 ----
        self.paramGroup = SettingCardGroup("生图参数", self.scrollWidget)

        # 提示词 Card
        self.promptCard = CardWidget(self.paramGroup)
        promptLayout = QVBoxLayout(self.promptCard)
        promptLayout.setContentsMargins(20, 11, 20, 11)
        promptLayout.setSpacing(8)
        promptLayout.addWidget(StrongBodyLabel("提示词", self.promptCard))
        self.promptInput = PlainTextEdit(self.promptCard)
        self.promptInput.setPlaceholderText("输入生图提示词...")
        self.promptInput.setFixedHeight(110)
        promptLayout.addWidget(self.promptInput)
        self.promptCard.setFixedHeight(165)

        # 参考图 Card (只包含官方纯粹的 DropMultiFilesWidget 组件)
        self.refCard = CardWidget(self.paramGroup)
        refLayout = QVBoxLayout(self.refCard)
        refLayout.setContentsMargins(20, 11, 20, 11)
        refLayout.setSpacing(8)

        refHeader = QHBoxLayout()
        refHeader.addWidget(StrongBodyLabel("参考图", self.refCard))
        refHeader.addStretch(1)
        refLayout.addLayout(refHeader)

        # 官方标准的 DropMultiFilesWidget 组件
        self.dropWidget = DropMultiFilesWidget(self.refCard)
        self.dropWidget.setSuffixes(["png", "jpg", "jpeg", "webp", "bmp"])
        self.dropWidget.filesDropped.connect(self._on_files_dropped)
        self.dropWidget.setFixedHeight(155)
        refLayout.addWidget(self.dropWidget)

        self.refCard.setFixedHeight(210)

        # 尺寸与质量
        self.sizeQualityCard = CardWidget(self.paramGroup)
        sqLayout = QHBoxLayout(self.sizeQualityCard)
        sqLayout.setContentsMargins(20, 11, 20, 11)
        sqLayout.setSpacing(16)

        sqLeft = QVBoxLayout()
        sqLeft.setSpacing(2)
        sqLeft.addWidget(StrongBodyLabel("尺寸", self.sizeQualityCard))
        sqLeft.addWidget(CaptionLabel("auto / 1:1 / 1024x1024", self.sizeQualityCard))
        self.sizeCombo = ComboBox(self.sizeQualityCard)
        self.sizeCombo.addItems(["auto", "1:1", "4:5", "3:4", "2:3", "3:2", "4:3", "16:9", "9:16", "21:9", "1024x1024", "1200x675", "928x1664", "3000x1000"])
        self.sizeCombo.setCurrentText("auto")
        sqLeft.addWidget(self.sizeCombo)

        sqRight = QVBoxLayout()
        sqRight.setSpacing(2)
        sqRight.addWidget(StrongBodyLabel("质量", self.sizeQualityCard))
        sqRight.addWidget(CaptionLabel("auto / standard / hd", self.sizeQualityCard))
        self.qualityCombo = ComboBox(self.sizeQualityCard)
        self.qualityCombo.addItems(["auto", "standard", "hd", "high", "medium", "low"])
        self.qualityCombo.setCurrentText("auto")
        sqRight.addWidget(self.qualityCombo)

        sqLayout.addLayout(sqLeft, 1)
        sqLayout.addLayout(sqRight, 1)
        self.sizeQualityCard.setFixedHeight(100)

        # 返回格式与张数
        self.formatCountCard = CardWidget(self.paramGroup)
        fcLayout = QHBoxLayout(self.formatCountCard)
        fcLayout.setContentsMargins(20, 11, 20, 11)
        fcLayout.setSpacing(16)

        fcLeft = QVBoxLayout()
        fcLeft.setSpacing(2)
        fcLeft.addWidget(StrongBodyLabel("返回格式", self.formatCountCard))
        fcLeft.addWidget(CaptionLabel("b64_json / url", self.formatCountCard))
        self.formatCombo = ComboBox(self.formatCountCard)
        self.formatCombo.addItems(["b64_json", "url"])
        self.formatCombo.setCurrentText("b64_json")
        fcLeft.addWidget(self.formatCombo)

        fcRight = QVBoxLayout()
        fcRight.setSpacing(2)
        fcRight.addWidget(StrongBodyLabel("生成张数", self.formatCountCard))
        fcRight.addWidget(CaptionLabel("1-10 张", self.formatCountCard))
        self.countCombo = ComboBox(self.formatCountCard)
        self.countCombo.addItems([str(i) for i in range(1, 11)])
        self.countCombo.setCurrentText("1")
        fcRight.addWidget(self.countCombo)

        fcLayout.addLayout(fcLeft, 1)
        fcLayout.addLayout(fcRight, 1)
        self.formatCountCard.setFixedHeight(100)

        # ---- 2. 操作组 ----
        self.actionGroup = SettingCardGroup("操作", self.scrollWidget)
        self.actionCard = CardWidget(self.actionGroup)
        actionLayout = QHBoxLayout(self.actionCard)
        actionLayout.setContentsMargins(20, 11, 20, 11)
        self.generateButton = PrimaryPushButton("生成图片", self.actionCard)
        self.generateButton.setIcon(FIF.PALETTE)
        self.generateButton.clicked.connect(self._generate)
        self.clearButton = PushButton("清空结果", self.actionCard)
        self.clearButton.setIcon(FIF.DELETE)
        self.clearButton.clicked.connect(self._clear_results)
        actionLayout.addWidget(self.generateButton)
        actionLayout.addWidget(self.clearButton)
        self.actionCard.setFixedHeight(73)

        # ---- 3. 同一行三列常驻展示组（生成结果 | 运行日志 | 生图历史） ----
        self.infoGroup = SettingCardGroup("生成信息与历史", self.scrollWidget)

        self.threeColumnContainer = CardWidget(self.infoGroup)
        self.threeColumnContainer.setMinimumHeight(450)

        self.threeColumnLayout = QHBoxLayout(self.threeColumnContainer)
        self.threeColumnLayout.setContentsMargins(12, 12, 12, 12)
        self.threeColumnLayout.setSpacing(12)

        # ===== 列 1: 生成结果 =====
        self.resultCard = CardWidget(self.threeColumnContainer)
        resultLayout = QVBoxLayout(self.resultCard)
        resultLayout.setContentsMargins(14, 12, 14, 12)
        resultLayout.setSpacing(8)

        resHeader = QHBoxLayout()
        resHeader.addWidget(StrongBodyLabel("生成结果", self.resultCard))
        resHeader.addStretch(1)
        resultLayout.addLayout(resHeader)

        self.resultScroll = SingleDirectionScrollArea(self.resultCard, orient=Qt.Vertical)
        self.resultScroll.setWidgetResizable(True)
        self.resultScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.resultScroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.resultContent = QWidget()
        self.resultContentLayout = QVBoxLayout(self.resultContent)
        self.resultContentLayout.setAlignment(Qt.AlignTop)
        self.resultContentLayout.setSpacing(8)

        self.emptyResultLabel = CaptionLabel("暂无生成结果", self.resultContent)
        self.emptyResultLabel.setStyleSheet("color: #888888; font-size: 12px;")
        self.emptyResultLabel.setAlignment(Qt.AlignCenter)
        self.resultContentLayout.addWidget(self.emptyResultLabel)

        self.resultScroll.setWidget(self.resultContent)
        resultLayout.addWidget(self.resultScroll)
        self.resultCard.setMinimumHeight(400)

        # ===== 列 2: 运行日志 =====
        self.logCard = CardWidget(self.threeColumnContainer)
        logLayout = QVBoxLayout(self.logCard)
        logLayout.setContentsMargins(14, 12, 14, 12)
        logLayout.setSpacing(8)

        logHeader = QHBoxLayout()
        logHeader.addWidget(StrongBodyLabel("运行日志", self.logCard))
        logHeader.addStretch(1)
        logLayout.addLayout(logHeader)

        self.logText = PlainTextEdit(self.logCard)
        self.logText.setReadOnly(True)
        self.logText.setPlaceholderText("运行日志将在此实时显示...")
        logLayout.addWidget(self.logText)
        self.logCard.setMinimumHeight(400)

        # ===== 列 3: 生图历史 =====
        self.historyCard = CardWidget(self.threeColumnContainer)
        hisLayout = QVBoxLayout(self.historyCard)
        hisLayout.setContentsMargins(14, 12, 14, 12)
        hisLayout.setSpacing(8)

        hisHeader = QHBoxLayout()
        hisHeader.addWidget(StrongBodyLabel("生图历史", self.historyCard))
        hisHeader.addStretch(1)
        self.clearHistoryBtn = TransparentToolButton(FIF.DELETE, self.historyCard)
        self.clearHistoryBtn.setToolTip("清空历史")
        self.clearHistoryBtn.setFixedSize(26, 26)
        self.clearHistoryBtn.clicked.connect(self._clear_history)
        hisHeader.addWidget(self.clearHistoryBtn)
        hisLayout.addLayout(hisHeader)

        self.historyScroll = SingleDirectionScrollArea(self.historyCard, orient=Qt.Vertical)
        self.historyScroll.setWidgetResizable(True)
        self.historyScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.historyScroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.historyContent = QWidget()
        self.historyContentLayout = QVBoxLayout(self.historyContent)
        self.historyContentLayout.setAlignment(Qt.AlignTop)
        self.historyContentLayout.setSpacing(8)
        self.historyScroll.setWidget(self.historyContent)
        hisLayout.addWidget(self.historyScroll)
        self.historyCard.setMinimumHeight(400)

        # 将 3 列加到 3 列布局中
        self.threeColumnLayout.addWidget(self.resultCard, 1)
        self.threeColumnLayout.addWidget(self.logCard, 1)
        self.threeColumnLayout.addWidget(self.historyCard, 1)

        self._init_layout()

    def _init_layout(self):
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 100, 0, 20)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName("imageGenInterface")

        setFont(self.titleLabel, 23, QFont.Weight.DemiBold)
        self.scrollWidget.setObjectName("scrollWidget")
        self.titleLabel.setObjectName("titleLabel")
        self.scrollWidget.setStyleSheet("QWidget{background:transparent}")
        self.titleLabel.move(36, 50)

        self.paramGroup.addSettingCard(self.promptCard)
        self.paramGroup.addSettingCard(self.refCard)
        self.paramGroup.addSettingCard(self.sizeQualityCard)
        self.paramGroup.addSettingCard(self.formatCountCard)

        self.actionGroup.addSettingCard(self.actionCard)
        self.infoGroup.addSettingCard(self.threeColumnContainer)

        self.expandLayout.setSpacing(8)
        self.expandLayout.setContentsMargins(36, 10, 36, 36)
        self.expandLayout.addWidget(self.paramGroup)
        self.expandLayout.addWidget(self.actionGroup)
        self.expandLayout.addWidget(self.infoGroup)

    def _on_files_dropped(self, files: list[str]):
        """响应官方 DropMultiFilesWidget 拖拽/选择文件回调"""
        self._ref_files = [f for f in files if Path(f).is_file()]

    def _generate(self):
        base_url = cfg.get(cfg.imageGenBaseUrl).strip()
        api_key = cfg.get(cfg.imageGenApiKey).strip()
        model = cfg.get(cfg.imageGenModel).strip()
        prompt = self.promptInput.toPlainText().strip()
        size = self.sizeCombo.currentText().strip()
        quality = self.qualityCombo.currentText().strip()
        response_format = self.formatCombo.currentText().strip()
        n = int(self.countCombo.currentText().strip())

        # 从 DropMultiFilesWidget 选中的参考图读取 Base64
        refs = []
        for file_path in getattr(self, "_ref_files", []):
            try:
                with open(file_path, "rb") as f:
                    refs.append(base64.b64encode(f.read()).decode())
            except Exception as e:
                print(f"读取参考图 {file_path} 失败: {e}")

        if not base_url:
            InfoBar.warning(title="提示", content="请先在设置中填写 API 地址",
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=3000, parent=self)
            return
        if not api_key:
            InfoBar.warning(title="提示", content="请先在设置中填写 API Key",
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=3000, parent=self)
            return
        if not prompt:
            InfoBar.warning(title="提示", content="请输入提示词",
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=3000, parent=self)
            return

        self._clear_results()
        self.logText.clear()
        self.generateButton.setEnabled(False)
        self.generateButton.setText("生成中...")

        self._thread = ImageGenThread(base_url, api_key, model, prompt, size, quality, response_format, n, refs)
        self._thread.logMessage.connect(self._on_log)
        self._thread.imageGenerated.connect(self._on_image)
        self._thread.finished.connect(self._on_finished)
        self._thread.start()

    def _on_log(self, text: str):
        self.logText.appendPlainText(text)
        scrollbar = self.logText.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_image(self, index: int, b64_data: str, mime: str):
        self.emptyResultLabel.setVisible(False)
        card = ImageCard(index, b64_data, mime, self.resultContent)
        card.removed = self._remove_result_card
        self._image_cards.append(card)
        self.resultContentLayout.addWidget(card)

    def _remove_result_card(self, card: ImageCard):
        if card in self._image_cards:
            self._image_cards.remove(card)
        if not self._image_cards:
            self.emptyResultLabel.setVisible(True)

    def _on_finished(self, success: bool, message: str, record: dict):
        self.generateButton.setEnabled(True)
        self.generateButton.setText("生成图片")
        if success:
            InfoBar.success(
                title="成功", content=message,
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=5000, parent=self,
            )
            self._load_history_records()
        else:
            InfoBar.error(
                title="失败", content=message,
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=8000, parent=self,
            )

    def _clear_results(self):
        for card in self._image_cards:
            card.deleteLater()
        self._image_cards.clear()
        self.emptyResultLabel.setVisible(True)

    # ---- 历史记录相关功能 ----
    def _load_history_records(self):
        for card in self._history_cards:
            card.deleteLater()
        self._history_cards.clear()

        records = ImageGenHistoryManager.load_history()
        for record in records:
            card = HistoryRecordCard(record, self.historyContent)
            card.applyRecord = self._apply_history_record
            card.deleteRecord = self._delete_history_record
            self._history_cards.append(card)
            self.historyContentLayout.addWidget(card)

    def _apply_history_record(self, record: dict):
        if record.get("prompt"):
            self.promptInput.setPlainText(record.get("prompt"))
        if record.get("size"):
            idx = self.sizeCombo.findText(record.get("size"))
            if idx >= 0:
                self.sizeCombo.setCurrentIndex(idx)
        if record.get("quality"):
            idx = self.qualityCombo.findText(record.get("quality"))
            if idx >= 0:
                self.qualityCombo.setCurrentIndex(idx)
        InfoBar.info(
            title="提示", content="已载入该生图历史参数",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=2000, parent=self,
        )

    def _delete_history_record(self, record_id: str):
        ImageGenHistoryManager.delete_record(record_id)
        self._load_history_records()
        InfoBar.success(
            title="成功", content="已删除该条历史记录",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=2000, parent=self,
        )

    def _clear_history(self):
        ImageGenHistoryManager.clear_history()
        self._load_history_records()
        InfoBar.success(
            title="成功", content="已清空所有生图历史",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=2000, parent=self,
        )