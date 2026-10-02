# coding: utf-8
"""招聘公告采集 UI 界面层 —— 严格遵循项目标准 Fluent 布局规范"""
import os
import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QFont, QDesktopServices, QTextCursor, QColor
from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                               QHeaderView, QFileDialog, QApplication,
                               QPlainTextEdit, QSizePolicy)

from qfluentwidgets import (ScrollArea, ExpandLayout, PrimaryPushButton,
                            PushButton, LineEdit, setFont, TextEdit,
                            CardWidget, SubtitleLabel, InfoBar, ComboBox,
                            CheckBox, SettingCardGroup as CardGroup, BodyLabel,
                            StrongBodyLabel, CaptionLabel, TableView,
                            RadioButton)
from qfluentwidgets import FluentIcon as FIF

from .job_crawler_service import (JobCrawlerThread, CrawlerLoginThread,
                                  load_ledger, load_credentials_file,
                                  save_credentials_file, CRAWLER_DATA_DIR,
                                  WeChatCrawlerClient)


class SettingCardGroup(CardGroup):
    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        setFont(self.titleLabel, 14, QFont.Weight.DemiBold)


class ArticleTableModel(QAbstractTableModel):
    """表格数据模型"""
    HEADERS = ["目标企业/公众号", "匹配公众号", "文章标题", "发布时间", "操作"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        item = self._data[row]

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return item.get("company", "")
            elif col == 1:
                return item.get("account", "")
            elif col == 2:
                return item.get("title", "")
            elif col == 3:
                return item.get("time_str", "")
            elif col == 4:
                return "双击打开"
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in [0, 1, 3, 4]:
                return Qt.AlignmentFlag.AlignCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        elif role == Qt.ItemDataRole.ForegroundRole and col == 4:
            return QColor("#0078D4")
        return None

    def add_item(self, item: dict):
        self.beginInsertRows(QModelIndex(), len(self._data), len(self._data))
        self._data.append(item)
        self.endInsertRows()

    def clear(self):
        self.beginResetModel()
        self._data.clear()
        self.endResetModel()

    def get_row(self, row: int) -> dict:
        if 0 <= row < len(self._data):
            return self._data[row]
        return {}


class LogPanel(CardWidget):
    """标准操作日志面板（标题栏带操作按钮）"""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.vBoxLayout = QVBoxLayout(self)

        self.headerLayout = QHBoxLayout()
        self.titleLabel = StrongBodyLabel(title, self)
        self.headerLayout.addWidget(self.titleLabel)
        self.headerLayout.addStretch(1)

        self.textEdit = QPlainTextEdit(self)
        self.textEdit.setReadOnly(True)
        self.textEdit.setPlaceholderText(self.tr("采集运行状态与抓取进度将在此显示..."))
        self.textEdit.setStyleSheet("font-size:13px;")

        self.vBoxLayout.setContentsMargins(16, 12, 16, 12)
        self.vBoxLayout.setSpacing(8)
        self.vBoxLayout.addLayout(self.headerLayout)
        self.vBoxLayout.addWidget(self.textEdit)

    def addHeaderButton(self, button):
        self.headerLayout.addWidget(button)

    def append(self, text: str):
        self.textEdit.appendPlainText(text)
        self.textEdit.moveCursor(QTextCursor.MoveOperation.End)

    def clear(self):
        self.textEdit.clear()


class ResultTableCard(CardWidget):
    """采集结果展示卡片面板（独立全宽，带工具栏与表格）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(20, 16, 20, 16)
        self.vBoxLayout.setSpacing(12)

        # 顶部工具条
        self.toolLayout = QHBoxLayout()
        self.titleLabel = StrongBodyLabel(self.tr("采集结果展示"), self)
        self.resultCountLabel = CaptionLabel(self.tr("（已采集: 0 篇）"), self)
        self.toolLayout.addWidget(self.titleLabel)
        self.toolLayout.addWidget(self.resultCountLabel)
        self.toolLayout.addStretch(1)

        self.copyLinksBtn = PushButton(self.tr("复制所有网址"), self)
        self.copyLinksBtn.setIcon(FIF.COPY)
        self.exportBtn = PushButton(self.tr("导出 Markdown"), self)
        self.exportBtn.setIcon(FIF.SAVE)
        self.clearBtn = PushButton(self.tr("清空列表"), self)
        self.clearBtn.setIcon(FIF.DELETE)

        self.toolLayout.addWidget(self.copyLinksBtn)
        self.toolLayout.addWidget(self.exportBtn)
        self.toolLayout.addWidget(self.clearBtn)
        self.vBoxLayout.addLayout(self.toolLayout)

        # 表格
        self.tableView = TableView(self)
        self.tableModel = ArticleTableModel(self)
        self.tableView.setModel(self.tableModel)
        self.tableView.setMinimumHeight(280)
        self.tableView.setSelectionMode(TableView.SelectionMode.ExtendedSelection)
        self.tableView.setSelectionBehavior(TableView.SelectionBehavior.SelectRows)

        header = self.tableView.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.tableView.setColumnWidth(0, 140)
        self.tableView.setColumnWidth(1, 140)
        self.tableView.setColumnWidth(3, 160)
        self.vBoxLayout.addWidget(self.tableView)


class JobCrawlerInterface(ScrollArea):
    """招聘公告采集主侧边栏 —— 遵循项目标准统一风格"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)
        self.titleLabel = QLabel(self.tr("招聘采集"), self)

        self.crawlerThread = None
        self.loginThread = None

        # ---------------- 1. 账号与凭据设置组 ----------------
        self.accountGroup = SettingCardGroup(self.tr("微信公众平台登录凭证"), self.scrollWidget)

        self.accountCard = CardWidget(self.accountGroup)
        self.accountCardLayout = QHBoxLayout(self.accountCard)
        self.accountCardVBox = QVBoxLayout()
        self.accountTitleLabel = StrongBodyLabel(self.tr("扫码授权与凭证状态"), self.accountCard)
        self.accountDescLabel = CaptionLabel(self.tr("点击右侧按钮启动浏览器扫码，将自动提取 Cookie 和 Token"), self.accountCard)
        self.statusTagLabel = CaptionLabel(self.tr("检测中..."), self.accountCard)

        self.loginBtn = PrimaryPushButton(self.tr("微信扫码登录"), self.accountCard)
        self.loginBtn.setIcon(FIF.QRCODE)
        self.manualTokenBtn = PushButton(self.tr("手工配置凭据"), self.accountCard)
        self.manualTokenBtn.setIcon(FIF.SETTING)

        self.accountCardVBox.setSpacing(0)
        self.accountCardVBox.addWidget(self.accountTitleLabel)
        self.accountCardVBox.addWidget(self.accountDescLabel)
        self.accountCardLayout.setContentsMargins(20, 11, 20, 11)
        self.accountCardLayout.setSpacing(12)
        self.accountCardLayout.addLayout(self.accountCardVBox)
        self.accountCardLayout.addStretch(1)
        self.accountCardLayout.addWidget(self.statusTagLabel)
        self.accountCardLayout.addWidget(self.manualTokenBtn)
        self.accountCardLayout.addWidget(self.loginBtn)
        self.accountCard.setFixedHeight(73)

        # ---------------- 2. 采集配置组 ----------------
        self.configGroup = SettingCardGroup(self.tr("目标与时间设置"), self.scrollWidget)

        # 目标输入卡片（类似下载卡片，高 120）
        self.targetCard = CardWidget(self.configGroup)
        self.targetCardLayout = QVBoxLayout(self.targetCard)
        self.targetCardLayout.setContentsMargins(20, 11, 20, 11)
        self.targetCardLayout.setSpacing(8)

        self.targetHeaderLayout = QHBoxLayout()
        self.targetTitleVBox = QVBoxLayout()
        self.targetTitleLabel = StrongBodyLabel(self.tr("目标公众号清单"), self.targetCard)
        self.targetDescLabel = CaptionLabel(self.tr("输入要抓取的目标公众号名称或企业名（支持批量，一行一个）"), self.targetCard)
        self.targetTitleVBox.setSpacing(0)
        self.targetTitleVBox.addWidget(self.targetTitleLabel)
        self.targetTitleVBox.addWidget(self.targetDescLabel)
        self.targetHeaderLayout.addLayout(self.targetTitleVBox)
        self.targetHeaderLayout.addStretch(1)

        self.importBtn = PushButton(self.tr("从文本导入"), self.targetCard)
        self.importBtn.setIcon(FIF.FOLDER)
        self.targetHeaderLayout.addWidget(self.importBtn)
        self.targetCardLayout.addLayout(self.targetHeaderLayout)

        self.targetsEdit = TextEdit(self.targetCard)
        self.targetsEdit.setPlaceholderText(self.tr("例如：\n腾讯招聘\n阿里巴巴招聘\n字节跳动招聘\n中国建筑"))
        self.targetsEdit.setMinimumHeight(80)
        self.targetCardLayout.addWidget(self.targetsEdit)
        self.targetCard.setFixedHeight(150)

        # 采集模式与时间范围卡片（标准 73px 卡片）
        self.timeCard = CardWidget(self.configGroup)
        self.timeCardLayout = QHBoxLayout(self.timeCard)
        self.timeCardVBox = QVBoxLayout()
        self.timeTitleLabel = StrongBodyLabel(self.tr("抓取范围"), self.timeCard)
        self.timeDescLabel = CaptionLabel(self.tr("选择文章发布时间的筛选方式"), self.timeCard)
        self.timeCardVBox.setSpacing(0)
        self.timeCardVBox.addWidget(self.timeTitleLabel)
        self.timeCardVBox.addWidget(self.timeDescLabel)

        self.radioIncremental = RadioButton(self.tr("增量更新（上次抓取之后）"), self.timeCard)
        self.radio1Month = RadioButton(self.tr("近 1 个月（30天）"), self.timeCard)
        self.radio7Days = RadioButton(self.tr("近 7 天"), self.timeCard)
        self.radioIncremental.setChecked(True)

        self.timeCardLayout.setContentsMargins(20, 11, 20, 11)
        self.timeCardLayout.setSpacing(16)
        self.timeCardLayout.addLayout(self.timeCardVBox)
        self.timeCardLayout.addStretch(1)
        self.timeCardLayout.addWidget(self.radioIncremental)
        self.timeCardLayout.addWidget(self.radio1Month)
        self.timeCardLayout.addWidget(self.radio7Days)
        self.timeCard.setFixedHeight(73)

        # 操作卡片（标准 73px 卡片，带开始与停止按钮）
        self.actionCard = CardWidget(self.configGroup)
        self.actionCardLayout = QHBoxLayout(self.actionCard)
        self.actionCardVBox = QVBoxLayout()
        self.actionTitleLabel = StrongBodyLabel(self.tr("执行操作"), self.actionCard)
        self.actionDescLabel = CaptionLabel(self.tr("仅抓取文章标题与网址，不下载正文，极速高效"), self.actionCard)
        self.actionCardVBox.setSpacing(0)
        self.actionCardVBox.addWidget(self.actionTitleLabel)
        self.actionCardVBox.addWidget(self.actionDescLabel)

        self.stopBtn = PushButton(self.tr("终止"), self.actionCard)
        self.stopBtn.setVisible(False)
        self.startBtn = PrimaryPushButton(self.tr("开始采集"), self.actionCard)
        self.startBtn.setFixedWidth(120)

        self.actionCardLayout.setContentsMargins(20, 11, 20, 11)
        self.actionCardLayout.setSpacing(12)
        self.actionCardLayout.addLayout(self.actionCardVBox)
        self.actionCardLayout.addStretch(1)
        self.actionCardLayout.addWidget(self.stopBtn)
        self.actionCardLayout.addWidget(self.startBtn)
        self.actionCard.setFixedHeight(73)

        # ---------------- 3. 结果呈现（独立卡片，宽展饱满） ----------------
        self.resultCard = ResultTableCard(self.scrollWidget)
        self.resultCard.setMinimumHeight(350)
        self.tableModel = self.resultCard.tableModel
        self.tableView = self.resultCard.tableView
        self.resultCountLabel = self.resultCard.resultCountLabel

        # ---------------- 4. 日志面板 ----------------
        self.logPanel = LogPanel(self.tr("运行日志"), self.scrollWidget)
        self.logPanel.setMinimumHeight(240)
        self.logPanel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.clearLogBtn = PushButton(self.tr("清空日志"))
        self.clearLogBtn.setFixedHeight(28)
        self.logPanel.addHeaderButton(self.clearLogBtn)

        self.__initWidget()

    def __initWidget(self):
        self.resize(1000, 800)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 100, 0, 20)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName("jobCrawlerInterface")

        setFont(self.titleLabel, 23, QFont.Weight.DemiBold)
        self.scrollWidget.setObjectName("scrollWidget")
        self.titleLabel.setObjectName("settingLabel")
        self.scrollWidget.setStyleSheet("#scrollWidget{background:transparent}")

        self._checkCredentialsStatus()
        self.__initLayout()
        self._connectSignalToSlot()

    def __initLayout(self):
        self.titleLabel.move(36, 50)

        self.accountGroup.addSettingCard(self.accountCard)
        self.configGroup.addSettingCard(self.targetCard)
        self.configGroup.addSettingCard(self.timeCard)
        self.configGroup.addSettingCard(self.actionCard)

        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(36, 10, 36, 0)
        self.expandLayout.addWidget(self.accountGroup)
        self.expandLayout.addWidget(self.configGroup)
        self.expandLayout.addWidget(self.resultCard)
        self.expandLayout.addWidget(self.logPanel)
        self.scrollWidget.adjustSize()

    def _connectSignalToSlot(self):
        self.loginBtn.clicked.connect(self.start_login)
        self.manualTokenBtn.clicked.connect(self.edit_credentials_manually)
        self.importBtn.clicked.connect(self.import_targets_from_file)
        self.startBtn.clicked.connect(self.start_crawl)
        self.stopBtn.clicked.connect(self.stop_crawl)
        self.resultCard.copyLinksBtn.clicked.connect(self.copy_all_links)
        self.resultCard.exportBtn.clicked.connect(self.export_markdown)
        self.resultCard.clearBtn.clicked.connect(self.clear_results)
        self.clearLogBtn.clicked.connect(self.logPanel.clear)
        self.tableView.doubleClicked.connect(self.on_table_double_clicked)

    def _checkCredentialsStatus(self):
        """检查并更新凭据状态标签"""
        cookie, token = load_credentials_file()
        if cookie and token:
            self.statusTagLabel.setText(f"✓ 凭证已就绪 (Token: {token[:8]}...)")
            self.statusTagLabel.setStyleSheet("color: #107C41; font-weight: bold;")
        else:
            self.statusTagLabel.setText("⚠️ 未就绪（请扫码或配置凭据）")
            self.statusTagLabel.setStyleSheet("color: #D83B01; font-weight: bold;")

    def start_login(self):
        """启动浏览器扫码登录，使用 wechat-article-claw 原生提取逻辑"""
        self.logPanel.append("准备启动 Chromium 浏览器，等待扫码登录微信公众号...")
        self.loginBtn.setEnabled(False)
        self.loginThread = CrawlerLoginThread(self)
        self.loginThread.log_signal.connect(self.logPanel.append)
        self.loginThread.login_success_signal.connect(self.on_login_success)
        self.loginThread.login_failed_signal.connect(self.on_login_failed)
        self.loginThread.start()
        InfoBar.info(self.tr("提示"), self.tr("浏览器已打开，请拿出手机微信扫码"), duration=5000, parent=self)

    def on_login_success(self, cookie: str, token: str):
        self.loginBtn.setEnabled(True)
        self._checkCredentialsStatus()
        self.logPanel.append("✓ 登录成功！Cookie 与 Token 已妥善保存，可直接开始采集。")
        InfoBar.success(self.tr("登录成功"), self.tr("已成功提取 Token 和 Cookie 凭据！"), duration=3000, parent=self)

    def on_login_failed(self, err: str):
        self.loginBtn.setEnabled(True)
        self._checkCredentialsStatus()
        self.logPanel.append(f"❌ 登录失败: {err}")
        InfoBar.error(self.tr("登录失败"), str(err), duration=4000, parent=self)

    def edit_credentials_manually(self):
        """支持手动配置自定义凭证 JSON"""
        cred_path = CRAWLER_DATA_DIR / "credentials.json"
        if not cred_path.exists():
            default_val = '{\n  "cookie": "",\n  "token": ""\n}'
            cred_path.write_text(default_val, encoding="utf-8")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(cred_path)))
        InfoBar.info(self.tr("提示"), f"已打开配置文件：{cred_path.name}，修改保存后重新点击采集即可", duration=5000, parent=self)

    def import_targets_from_file(self):
        """从本地 txt/csv 导入目标列表"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择目标文本文件"), "", "Text Files (*.txt *.csv)"
        )
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.targetsEdit.setPlainText(content)
                InfoBar.success(self.tr("导入成功"), f"已导入 {Path(file_path).name}", duration=2000, parent=self)
            except Exception as e:
                InfoBar.error(self.tr("导入失败"), str(e), duration=3000, parent=self)

    def start_crawl(self):
        """开始采集流程"""
        targets_text = self.targetsEdit.toPlainText().strip()
        if not targets_text:
            InfoBar.warning(self.tr("提示"), self.tr("请在上方文本框中输入至少一个目标公司或公众号名称"), duration=2000, parent=self)
            return

        targets = [line.strip() for line in targets_text.splitlines() if line.strip()]

        # 获取凭证：优先从专用的 credentials.json 中读取
        cookie, token = load_credentials_file()

        if not cookie or not token:
            InfoBar.warning(
                self.tr("未获取到有效凭证"),
                self.tr("请先点击「微信扫码登录」完成扫码，或点击「手工配置凭据」填入 token 和 cookie"),
                duration=5000,
                parent=self
            )
            return

        # 校验凭据有效性
        self.logPanel.append("正在校验凭据有效性...")
        client = WeChatCrawlerClient(cookie, token)
        if not client.verify_login():
            self.logPanel.append("❌ 凭据已失效或过期，请重新点击「微信扫码登录」。")
            self._checkCredentialsStatus()
            InfoBar.error(self.tr("凭据已失效"), self.tr("当前 Token/Cookie 已过期，请重新扫码登录"), duration=5000, parent=self)
            return
        self.logPanel.append("✓ 凭据有效，开始执行采集任务。")

        # 确定时间与模式
        use_last = self.radioIncremental.isChecked()
        days = 30
        if self.radio7Days.isChecked():
            days = 7

        self.startBtn.setEnabled(False)
        self.stopBtn.setVisible(True)

        self.crawlerThread = JobCrawlerThread(
            targets=targets,
            cookie=cookie,
            token=token,
            time_range_days=days,
            use_last_time=use_last
        )
        self.crawlerThread.log_signal.connect(self.logPanel.append)
        self.crawlerThread.article_found_signal.connect(self.on_article_found)
        self.crawlerThread.batch_finished_signal.connect(self.on_crawl_finished)
        self.crawlerThread.start()

    def stop_crawl(self):
        if self.crawlerThread and self.crawlerThread.isRunning():
            self.crawlerThread.stop()
            self.stopBtn.setEnabled(False)

    def on_article_found(self, item: dict):
        self.tableModel.add_item(item)
        count = self.tableModel.rowCount()
        self.resultCountLabel.setText(f"已采集: {count} 篇文章")

    def on_crawl_finished(self, success: bool, msg: str):
        self.startBtn.setEnabled(True)
        self.stopBtn.setVisible(False)
        self.logPanel.append(f"\n✨ {msg}")
        if success:
            InfoBar.success(self.tr("采集完成"), msg, duration=3000, parent=self)
        else:
            InfoBar.error(self.tr("采集异常"), msg, duration=4000, parent=self)

    def on_table_double_clicked(self, index: QModelIndex):
        row = index.row()
        item = self.tableModel.get_row(row)
        link = item.get("link")
        if link:
            QDesktopServices.openUrl(QUrl(link))

    def copy_all_links(self):
        links = [item.get("link", "") for item in self.tableModel._data if item.get("link")]
        if not links:
            InfoBar.warning(self.tr("提示"), self.tr("当前列表为空，暂无链接"), duration=2000, parent=self)
            return
        text = "\n".join(links)
        QApplication.clipboard().setText(text)
        InfoBar.success(self.tr("已复制"), f"已复制 {len(links)} 条文章网址到剪贴板", duration=2000, parent=self)

    def export_markdown(self):
        if not self.tableModel._data:
            InfoBar.warning(self.tr("提示"), self.tr("当前列表为空，无需导出"), duration=2000, parent=self)
            return

        out_dir = CRAWLER_DATA_DIR / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"招聘公告汇总_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        out_path = out_dir / filename

        lines = [
            f"# 招聘公告采集汇总报告",
            f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"> 汇总篇数：{len(self.tableModel._data)} 篇\n",
            "| 公司/目标 | 公众号 | 发布时间 | 文章标题与网址 |",
            "| :--- | :--- | :--- | :--- |"
        ]
        for it in self.tableModel._data:
            comp = it.get("company", "")
            acc = it.get("account", "")
            tm = it.get("time_str", "")
            title = it.get("title", "").replace("|", "—")
            link = it.get("link", "")
            lines.append(f"| {comp} | {acc} | {tm} | [{title}]({link}) |")

        out_path.write_text("\n".join(lines), encoding="utf-8")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(out_path)))
        InfoBar.success(self.tr("导出成功"), f"已导出 Markdown 报告至：{out_path.name}", duration=3000, parent=self)

    def clear_results(self):
        self.tableModel.clear()
        self.resultCountLabel.setText("已采集: 0 篇文章")

