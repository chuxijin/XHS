# coding: utf-8
"""微信公众号 UI 层 —— 纯界面与事件绑定"""
import json
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QAbstractTableModel, QModelIndex, QDate
from PySide6.QtGui import QFont, QDesktopServices, QTextCursor, QColor
from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                                QPlainTextEdit, QApplication, QFileDialog,
                                QHeaderView)

from qfluentwidgets import (ScrollArea, ExpandLayout, PrimaryPushButton,
                            PushButton, LineEdit, setFont, TextEdit,
                            CardWidget, SubtitleLabel, InfoBar, ComboBox,
                            CheckBox, SettingCardGroup as CardGroup, BodyLabel,
                            StrongBodyLabel, CaptionLabel, MessageBoxBase,
                            TableView, CalendarPicker)
from qfluentwidgets import FluentIcon as FIF

from .wechat_service import (get_accounts, account_exists, load_templates,
                              load_history, save_history_list,
                              get_today_templates_dir,
                              get_next_day_templates_dir,
                              get_account_dir, save_template,
                              repair_template_json,
                              PROMPT_TEXT,
                              WechatLoginThread)
from .publish_scheme1 import WechatPublishThread as Scheme1Thread
from .publish_scheme2 import Scheme2Thread

# 发布方案注册表：显示名 → Thread 类
PUBLISH_SCHEMES = {
    "方案1 - 草稿模板": Scheme1Thread,
    "方案2 - 周日汇总": Scheme2Thread,
}


# ---- 通用组件 ----

class SettingCardGroup(CardGroup):
    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        setFont(self.titleLabel, 14, QFont.Weight.DemiBold)


class AccountNameDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(self.tr("添加公众号账号"), self)
        self.descLabel = BodyLabel(
            self.tr("请输入账号名称（如：物流、财会）"), self)
        self.nameEdit = LineEdit(self)
        self.nameEdit.setPlaceholderText(self.tr("账号名称"))
        self.nameEdit.setClearButtonEnabled(True)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.descLabel)
        self.viewLayout.addWidget(self.nameEdit)
        self.widget.setMinimumWidth(360)


class AddTemplateDialog(MessageBoxBase):
    """添加模板对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(self.tr("添加模板"), self)
        self.descLabel = BodyLabel(
            self.tr("粘贴 JSON 内容，将自动保存为下一个编号的模板"), self)
        self.jsonEdit = TextEdit(self)
        self.jsonEdit.setPlaceholderText(
            '{\n  "{{公司简称}}": "示例公司",\n  "{{岗位名称}}": "示例岗位",\n  ...\n}')
        self.jsonEdit.setMinimumHeight(300)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.descLabel)
        self.viewLayout.addWidget(self.jsonEdit)
        self.widget.setMinimumWidth(500)


class _HistoryTableModel(QAbstractTableModel):
    """历史记录表格数据模型"""

    HEADERS = ["时间", "模板", "公司", "岗位", "状态", "错误信息"]

    def __init__(self, history: list[dict], parent=None):
        super().__init__(parent)
        self._data = list(reversed(history[-50:]))  # 最新的在上面

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        h = self._data[index.row()]
        col = index.column()
        r = h.get("replacements", {})

        if role == Qt.DisplayRole:
            if col == 0:
                return h.get("time", "")
            elif col == 1:
                return h.get("template", "")
            elif col == 2:
                return r.get("{{公司简称}}", "") or r.get("{{公司名称}}", "")
            elif col == 3:
                return r.get("{{岗位名称}}", "")
            elif col == 4:
                return "成功" if h.get("status") == "success" else "失败"
            elif col == 5:
                return h.get("error", "")
        elif role == Qt.ForegroundRole:
            if col == 4:
                if h.get("status") == "success":
                    return QColor("#27ae60")
                return QColor("#e74c3c")
        return None

    def removeRow(self, row, parent=QModelIndex()):
        if 0 <= row < len(self._data):
            self.beginRemoveRows(parent, row, row)
            self._data.pop(row)
            self.endRemoveRows()
            return True
        return False

    def get_remaining_history(self) -> list[dict]:
        """返回删除操作后剩余的记录（恢复为原始时间顺序）"""
        return list(reversed(self._data))


class HistoryDialog(MessageBoxBase):
    """历史记录弹窗（表格形式，支持删除）"""

    def __init__(self, history: list[dict], account_dir, parent=None):
        super().__init__(parent)
        self._account_dir = account_dir
        self._deleted = False

        self.titleLabel = SubtitleLabel(self.tr("发布历史记录"), self)

        self._model = _HistoryTableModel(history, self)
        self.tableView = TableView(self)
        self.tableView.setModel(self._model)
        self.tableView.setMinimumHeight(450)
        self.tableView.setSelectionMode(
            TableView.SelectionMode.ExtendedSelection)
        self.tableView.setSelectionBehavior(
            TableView.SelectionBehavior.SelectRows)

        # 列宽设置
        header = self.tableView.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        self.deleteButton = PushButton(self.tr("删除选中"), self)
        self.deleteButton.clicked.connect(self._deleteSelected)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.tableView)
        self.viewLayout.addWidget(self.deleteButton)
        self.widget.setMinimumWidth(800)
        self.cancelButton.hide()

    def _deleteSelected(self):
        indexes = self.tableView.selectionModel().selectedRows()
        if not indexes:
            return
        # 从后往前删，避免索引偏移
        for idx in sorted(indexes, key=lambda x: x.row(), reverse=True):
            self._model.removeRow(idx.row())
        # 回写文件
        save_history_list(
            self._account_dir, self._model.get_remaining_history())
        self._deleted = True


class LogPanel(CardWidget):
    """操作日志面板（标题栏带按钮）"""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.vBoxLayout = QVBoxLayout(self)

        # 标题行：标题 + 右侧按钮
        self.headerLayout = QHBoxLayout()
        self.titleLabel = StrongBodyLabel(title, self)
        self.headerLayout.addWidget(self.titleLabel)
        self.headerLayout.addStretch(1)

        self.textEdit = QPlainTextEdit(self)
        self.textEdit.setReadOnly(True)
        self.textEdit.setPlaceholderText(self.tr("点击发布后，日志将在此显示"))
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


# ---- 主界面 ----

class WechatInterface(ScrollArea):
    """微信公众号发布界面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)
        self.titleLabel = QLabel(self.tr("公众号发布"), self)
        self._customTemplateDir = ""

        # ---- 账号设置组 ----
        self.accountGroup = SettingCardGroup(
            self.tr("账号设置"), self.scrollWidget)

        self.accountCard = CardWidget(self.accountGroup)
        self.accountCardLayout = QHBoxLayout(self.accountCard)
        self.accountCardVBox = QVBoxLayout()
        self.accountTitleLabel = StrongBodyLabel(
            self.tr("公众号账号"), self.accountCard)
        self.accountDescLabel = CaptionLabel(
            self.tr("选择要发布的公众号"), self.accountCard)
        self.accountCombo = ComboBox(self.accountCard)
        self.accountCombo.setFixedWidth(200)
        self.loginButton = PushButton(self.tr("登录新账号"), self.accountCard)

        self.accountCardVBox.setSpacing(0)
        self.accountCardVBox.addWidget(self.accountTitleLabel)
        self.accountCardVBox.addWidget(self.accountDescLabel)
        self.accountCardLayout.setContentsMargins(20, 11, 20, 11)
        self.accountCardLayout.setSpacing(16)
        self.accountCardLayout.addLayout(self.accountCardVBox)
        self.accountCardLayout.addStretch(1)
        self.accountCardLayout.addWidget(self.accountCombo)
        self.accountCardLayout.addWidget(self.loginButton)
        self.accountCard.setFixedHeight(73)

        # ---- 发布设置组 ----
        self.publishGroup = SettingCardGroup(
            self.tr("发布设置"), self.scrollWidget)

        # 模板路径卡片
        self.publishCard = CardWidget(self.publishGroup)
        self.publishCardLayout = QHBoxLayout(self.publishCard)
        self.publishCardVBox = QVBoxLayout()
        self.templatePathLabel = StrongBodyLabel(
            self.tr("模板路径"), self.publishCard)
        self.templateInfoLabel = CaptionLabel(
            self.tr("请先选择账号"), self.publishCard)

        self.publishCardVBox.setSpacing(0)
        self.publishCardVBox.addWidget(self.templatePathLabel)
        self.publishCardVBox.addWidget(self.templateInfoLabel)

        self.openFolderButton = PushButton(
            self.tr("打开文件夹"), self.publishCard)
        self.selectFolderButton = PushButton(
            self.tr("选择目录"), self.publishCard)
        self.nextDayButton = PushButton(
            self.tr("下一天"), self.publishCard)
        self.pauseButton = PushButton(
            self.tr("暂停"), self.publishCard)
        self.pauseButton.setVisible(False)
        self.stopButton = PushButton(
            self.tr("终止"), self.publishCard)
        self.stopButton.setVisible(False)
        self.publishButton = PrimaryPushButton(
            self.tr("发布"), self.publishCard)
        self.headlessCheck = CheckBox(
            self.tr("隐藏浏览器"), self.publishCard)

        self.publishCardLayout.setContentsMargins(20, 11, 20, 11)
        self.publishCardLayout.setSpacing(12)
        self.publishCardLayout.addLayout(self.publishCardVBox)
        self.publishCardLayout.addStretch(1)
        self.publishCardLayout.addWidget(self.openFolderButton)
        self.publishCardLayout.addWidget(self.selectFolderButton)
        self.publishCardLayout.addWidget(self.nextDayButton)
        self.publishCardLayout.addWidget(self.pauseButton)
        self.publishCardLayout.addWidget(self.stopButton)
        self.publishCardLayout.addWidget(self.headlessCheck)
        self.publishCardLayout.addWidget(self.publishButton)
        self.publishCard.setFixedHeight(73)

        # 发布方案卡片
        self.schemeCard = CardWidget(self.publishGroup)
        self.schemeCardLayout = QHBoxLayout(self.schemeCard)
        self.schemeCardVBox = QVBoxLayout()
        self.schemeTitleLabel = StrongBodyLabel(
            self.tr("发布方案"), self.schemeCard)
        self.schemeDescLabel = CaptionLabel(
            self.tr("选择不同的自动化发布流程"), self.schemeCard)
        self.schemeCombo = ComboBox(self.schemeCard)
        self.schemeCombo.setFixedWidth(200)
        self.schemeCombo.addItems(list(PUBLISH_SCHEMES.keys()))

        self.schemeCardVBox.setSpacing(0)
        self.schemeCardVBox.addWidget(self.schemeTitleLabel)
        self.schemeCardVBox.addWidget(self.schemeDescLabel)
        self.schemeCardLayout.setContentsMargins(20, 11, 20, 11)
        self.schemeCardLayout.setSpacing(16)
        self.schemeCardLayout.addLayout(self.schemeCardVBox)
        self.schemeCardLayout.addStretch(1)
        self.schemeCardLayout.addWidget(self.schemeCombo)
        self.schemeCard.setFixedHeight(73)

        # 日期范围卡片（方案2 专用）
        self.dateRangeCard = CardWidget(self.publishGroup)
        self.dateRangeCardLayout = QHBoxLayout(self.dateRangeCard)
        self.dateRangeCardVBox = QVBoxLayout()
        self.dateRangeTitleLabel = StrongBodyLabel(
            self.tr("日期范围"), self.dateRangeCard)
        self.dateRangeDescLabel = CaptionLabel(
            self.tr("选择汇总的起止日期"), self.dateRangeCard)

        self.dateRangeCardVBox.setSpacing(0)
        self.dateRangeCardVBox.addWidget(self.dateRangeTitleLabel)
        self.dateRangeCardVBox.addWidget(self.dateRangeDescLabel)

        self.startDatePicker = CalendarPicker(self.dateRangeCard)
        self.startDatePicker.setFixedWidth(160)
        self.endDatePicker = CalendarPicker(self.dateRangeCard)
        self.endDatePicker.setFixedWidth(160)
        self.dateRangeSepLabel = BodyLabel("~", self.dateRangeCard)

        self.dateRangeCardLayout.setContentsMargins(20, 11, 20, 11)
        self.dateRangeCardLayout.setSpacing(12)
        self.dateRangeCardLayout.addLayout(self.dateRangeCardVBox)
        self.dateRangeCardLayout.addStretch(1)
        self.dateRangeCardLayout.addWidget(self.startDatePicker)
        self.dateRangeCardLayout.addWidget(self.dateRangeSepLabel)
        self.dateRangeCardLayout.addWidget(self.endDatePicker)
        self.dateRangeCard.setFixedHeight(73)
        self.dateRangeCard.setVisible(False)

        # 模板管理卡片
        self.templateCard = CardWidget(self.publishGroup)
        self.templateCardLayout = QHBoxLayout(self.templateCard)
        self.templateCardVBox = QVBoxLayout()
        self.templateTitleLabel = StrongBodyLabel(
            self.tr("模板管理"), self.templateCard)
        self.templateDescLabel = CaptionLabel(
            self.tr("复制 Prompt 让 AI 生成模板，或手动添加 JSON 模板"),
            self.templateCard)

        self.templateCardVBox.setSpacing(0)
        self.templateCardVBox.addWidget(self.templateTitleLabel)
        self.templateCardVBox.addWidget(self.templateDescLabel)

        self.copyPromptButton = PushButton(
            self.tr("复制 Prompt"), self.templateCard)
        self.categoryCombo = ComboBox(self.templateCard)
        self.categoryCombo.addItems(["校招", "实习"])
        self.categoryCombo.setFixedWidth(80)
        self.addTemplateButton = PushButton(
            self.tr("添加模板"), self.templateCard)

        self.templateCardLayout.setContentsMargins(20, 11, 20, 11)
        self.templateCardLayout.setSpacing(12)
        self.templateCardLayout.addLayout(self.templateCardVBox)
        self.templateCardLayout.addStretch(1)
        self.templateCardLayout.addWidget(self.copyPromptButton)
        self.templateCardLayout.addWidget(self.categoryCombo)
        self.templateCardLayout.addWidget(self.addTemplateButton)
        self.templateCard.setFixedHeight(73)

        # ---- 操作日志（全宽，标题栏带历史记录按钮）----
        self.logPanel = LogPanel(self.tr("操作日志"), self.scrollWidget)
        self.logPanel.setMinimumHeight(300)
        self.historyButton = PushButton(self.tr("查看历史记录"))
        self.historyButton.setFixedHeight(28)
        self.logPanel.addHeaderButton(self.historyButton)

        self.__initWidget()

    # ---- 初始化 ----

    def _loadAccounts(self):
        self.accountCombo.clear()
        accounts = get_accounts()
        if accounts:
            self.accountCombo.addItems(accounts)
        else:
            self.accountCombo.addItem(self.tr("暂无账号"))

    def _getTemplateDir(self):
        """获取当前模板目录：优先用户选择的，否则用默认的当天目录"""
        if self._customTemplateDir:
            return Path(self._customTemplateDir)
        account = self.accountCombo.currentText()
        if not account or account == self.tr("暂无账号"):
            return None
        tdir = get_today_templates_dir(account)
        tdir.mkdir(parents=True, exist_ok=True)
        return tdir

    def _refreshTemplateInfo(self):
        tdir = self._getTemplateDir()
        if tdir is None:
            self.templateInfoLabel.setText(self.tr("请先选择账号"))
            return
        tdir.mkdir(parents=True, exist_ok=True)
        recruit = load_templates(tdir, "校招")
        intern_ = load_templates(tdir, "实习")
        self.templateInfoLabel.setText(
            f"{tdir}  (校招 {len(recruit)} 个, 实习 {len(intern_)} 个)")

    def __initWidget(self):
        self.resize(1000, 800)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 100, 0, 20)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName('wechatInterface')

        setFont(self.titleLabel, 23, QFont.Weight.DemiBold)
        self.scrollWidget.setObjectName('scrollWidget')
        self.titleLabel.setObjectName('settingLabel')
        self.scrollWidget.setStyleSheet(
            "#scrollWidget{background:transparent}")

        self._loadAccounts()
        self._refreshTemplateInfo()
        self.__initLayout()
        self._connectSignalToSlot()

    def __initLayout(self):
        self.titleLabel.move(36, 50)

        self.accountGroup.addSettingCard(self.accountCard)
        self.publishGroup.addSettingCard(self.publishCard)
        self.publishGroup.addSettingCard(self.schemeCard)
        self.publishGroup.addSettingCard(self.dateRangeCard)
        self.publishGroup.addSettingCard(self.templateCard)

        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(36, 10, 36, 0)
        self.expandLayout.addWidget(self.accountGroup)
        self.expandLayout.addWidget(self.publishGroup)
        self.expandLayout.addWidget(self.logPanel)

    def _connectSignalToSlot(self):
        self.loginButton.clicked.connect(self._loginNewAccount)
        self.openFolderButton.clicked.connect(self._openTemplateFolder)
        self.selectFolderButton.clicked.connect(self._selectTemplateFolder)
        self.nextDayButton.clicked.connect(self._switchToNextDay)
        self.publishButton.clicked.connect(self._publish)
        self.pauseButton.clicked.connect(self._pausePublish)
        self.stopButton.clicked.connect(self._stopPublish)
        self.copyPromptButton.clicked.connect(self._copyPrompt)
        self.addTemplateButton.clicked.connect(self._addTemplate)
        self.historyButton.clicked.connect(self._showHistory)
        self.accountCombo.currentTextChanged.connect(self._onAccountChanged)
        self.schemeCombo.currentTextChanged.connect(self._onSchemeChanged)

    # ---- 事件处理 ----

    def _onSchemeChanged(self, scheme_name: str):
        """方案切换时显示/隐藏对应的 UI 控件"""
        is_scheme2 = "周日汇总" in scheme_name
        # 模板路径相关控件
        self.templatePathLabel.setVisible(not is_scheme2)
        self.templateInfoLabel.setVisible(not is_scheme2)
        self.openFolderButton.setVisible(not is_scheme2)
        self.selectFolderButton.setVisible(not is_scheme2)
        self.nextDayButton.setVisible(not is_scheme2)
        # 日期范围卡片
        self.dateRangeCard.setVisible(is_scheme2)
        # 模板管理卡片
        self.templateCard.setVisible(not is_scheme2)

    def _onAccountChanged(self, _text):
        """账号切换时重置自定义模板目录，回到新账号的当天目录"""
        self._customTemplateDir = ""
        self._refreshTemplateInfo()

    def _openTemplateFolder(self):
        tdir = self._getTemplateDir()
        if tdir is None:
            return
        tdir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(tdir)))

    def _selectTemplateFolder(self):
        tdir = self._getTemplateDir()
        start_dir = str(tdir) if tdir else ""
        folder = QFileDialog.getExistingDirectory(
            self, self.tr("选择模板目录"), start_dir)
        if folder:
            self._customTemplateDir = folder
            self._refreshTemplateInfo()

    def _switchToNextDay(self):
        tdir = self._getTemplateDir()
        if tdir is None:
            InfoBar.warning(self.tr("提示"), self.tr("请先登录账号"),
                            duration=2000, parent=self)
            return
        next_dir = get_next_day_templates_dir(tdir)
        created = not next_dir.exists()
        next_dir.mkdir(parents=True, exist_ok=True)
        self._customTemplateDir = str(next_dir)
        self._refreshTemplateInfo()
        msg = self.tr("已创建并切换到 {}") if created \
            else self.tr("已切换到 {}")
        InfoBar.success(self.tr("成功"),
                        msg.format(next_dir.name),
                        duration=3000, parent=self)

    def _copyPrompt(self):
        QApplication.clipboard().setText(PROMPT_TEXT)
        InfoBar.success(self.tr("已复制"),
                        self.tr("Prompt 已复制到剪贴板"),
                        duration=2000, parent=self)

    def _showHistory(self):
        account = self.accountCombo.currentText()
        if not account or account == self.tr("暂无账号"):
            InfoBar.warning(self.tr("提示"), self.tr("请先选择账号"),
                            duration=2000, parent=self)
            return
        account_dir = get_account_dir(account)
        history = load_history(account_dir)
        dialog = HistoryDialog(history, account_dir, self.window())
        dialog.exec()

    def _addTemplate(self):
        tdir = self._getTemplateDir()
        if tdir is None:
            InfoBar.warning(self.tr("提示"), self.tr("请先登录账号或选择模板目录"),
                            duration=2000, parent=self)
            return
        tdir.mkdir(parents=True, exist_ok=True)
        dialog = AddTemplateDialog(self.window())
        if not dialog.exec():
            return
        text = dialog.jsonEdit.toPlainText().strip()
        if not text:
            InfoBar.warning(self.tr("提示"), self.tr("内容不能为空"),
                            duration=2000, parent=self)
            return
        data, messages = repair_template_json(text)
        if data is None:
            InfoBar.error(self.tr("模板错误"),
                          "；".join(messages),
                          duration=8000, parent=self)
            return
        # 有修复消息时提示用户
        if messages:
            InfoBar.info(self.tr("自动修复"),
                         "；".join(messages),
                         duration=5000, parent=self)
        category = self.categoryCombo.currentText()
        ok, msg = save_template(tdir, data, category)
        if ok:
            self._refreshTemplateInfo()
            InfoBar.success(self.tr("成功"), msg, duration=2000, parent=self)
        else:
            InfoBar.warning(self.tr("提示"), msg, duration=2000, parent=self)

    def _loginNewAccount(self):
        dialog = AccountNameDialog(self.window())
        if not dialog.exec():
            return
        name = dialog.nameEdit.text().strip()
        if not name:
            InfoBar.warning(self.tr("提示"), self.tr("账号名称不能为空"),
                            duration=2000, parent=self)
            return
        if account_exists(name):
            InfoBar.warning(self.tr("提示"), self.tr("该账号已存在"),
                            duration=2000, parent=self)
            return
        self.loginButton.setEnabled(False)
        self.loginButton.setText(self.tr("登录中..."))
        self._loginThread = WechatLoginThread(name, self)
        self._loginThread.loginSuccess.connect(self._onLoginSuccess)
        self._loginThread.loginFailed.connect(self._onLoginFailed)
        self._loginThread.start()
        InfoBar.info(self.tr("提示"),
                     self.tr("浏览器已打开，请扫码登录微信公众号"),
                     duration=5000, parent=self)

    def _onLoginSuccess(self, account_name: str):
        self.loginButton.setEnabled(True)
        self.loginButton.setText(self.tr("登录新账号"))
        self._loadAccounts()
        idx = self.accountCombo.findText(account_name)
        if idx >= 0:
            self.accountCombo.setCurrentIndex(idx)
        InfoBar.success(self.tr("成功"),
                        self.tr("账号 {} 登录成功").format(account_name),
                        duration=3000, parent=self)

    def _onLoginFailed(self, error: str):
        self.loginButton.setEnabled(True)
        self.loginButton.setText(self.tr("登录新账号"))
        InfoBar.error(self.tr("登录失败"), error,
                      duration=5000, parent=self)

    def _publish(self):
        account = self.accountCombo.currentText()
        if not account or account == self.tr("暂无账号"):
            InfoBar.warning(self.tr("提示"), self.tr("请先登录账号"),
                            duration=2000, parent=self)
            return

        scheme_name = self.schemeCombo.currentText()

        # ---- 方案2：周日汇总 ----
        if "周日汇总" in scheme_name:
            start_qdate = self.startDatePicker.getDate()
            end_qdate = self.endDatePicker.getDate()
            if not start_qdate or not start_qdate.isValid() \
                    or not end_qdate or not end_qdate.isValid():
                InfoBar.warning(self.tr("提示"),
                                self.tr("请选择起止日期"),
                                duration=2000, parent=self)
                return
            start_d = date(start_qdate.year(), start_qdate.month(),
                           start_qdate.day())
            end_d = date(end_qdate.year(), end_qdate.month(),
                         end_qdate.day())
            if start_d > end_d:
                InfoBar.warning(self.tr("提示"),
                                self.tr("起始日期不能晚于结束日期"),
                                duration=2000, parent=self)
                return

            self.logPanel.clear()
            self.publishButton.setEnabled(False)
            self.publishButton.setText(self.tr("发布中..."))
            self.pauseButton.setVisible(True)
            self.stopButton.setVisible(True)

            self._publishThread = Scheme2Thread(
                account, start_d, end_d, self,
                headless=self.headlessCheck.isChecked())
            self._publishThread.logMessage.connect(self.logPanel.append)
            self._publishThread.publishWaiting.connect(
                self._onPublishWaiting)
            self._publishThread.publishSuccess.connect(
                self._onPublishSuccess)
            self._publishThread.publishFailed.connect(
                self._onPublishFailed)
            self._publishThread.publishStopped.connect(
                self._onPublishStopped)
            self._publishThread.start()
            return

        # ---- 方案1：草稿模板 ----
        tdir = self._getTemplateDir()
        if tdir is None:
            InfoBar.warning(self.tr("提示"), self.tr("请先选择模板目录"),
                            duration=2000, parent=self)
            return
        recruit = load_templates(tdir, "校招")
        intern_ = load_templates(tdir, "实习")
        if not recruit or not intern_:
            InfoBar.warning(self.tr("提示"),
                            self.tr("校招和实习都需要有模板"),
                            duration=3000, parent=self)
            return
        self.logPanel.clear()
        self.publishButton.setEnabled(False)
        self.publishButton.setText(self.tr("发布中..."))
        self.pauseButton.setVisible(True)
        self.stopButton.setVisible(True)
        ThreadClass = PUBLISH_SCHEMES[self.schemeCombo.currentText()]
        self._publishThread = ThreadClass(
            account, tdir, self,
            headless=self.headlessCheck.isChecked())
        self._publishThread.logMessage.connect(self.logPanel.append)
        self._publishThread.publishWaiting.connect(self._onPublishWaiting)
        self._publishThread.publishSuccess.connect(self._onPublishSuccess)
        self._publishThread.publishFailed.connect(self._onPublishFailed)
        self._publishThread.publishStopped.connect(self._onPublishStopped)
        self._publishThread.start()

    def _onPublishWaiting(self):
        self.pauseButton.setVisible(False)
        self.stopButton.setEnabled(True)
        self.stopButton.setText(self.tr("结束流程"))
        self.stopButton.setVisible(True)
        self.publishButton.setText(self.tr("等待结束"))
        InfoBar.info(self.tr("提示"),
                     self.tr("全部完成，确认无误后请点击「结束流程」"),
                     duration=8000, parent=self)

    def _onPublishSuccess(self):
        self.publishButton.setEnabled(True)
        self.publishButton.setText(self.tr("发布"))
        self.pauseButton.setVisible(False)
        self.stopButton.setVisible(False)
        InfoBar.success(self.tr("完成"), self.tr("发布任务已完成"),
                        duration=3000, parent=self)

    def _onPublishFailed(self, error: str):
        self.publishButton.setEnabled(True)
        self.publishButton.setText(self.tr("发布"))
        self.pauseButton.setVisible(False)
        self.stopButton.setVisible(False)
        self.logPanel.append(f"[错误] {error}")
        InfoBar.error(self.tr("发布失败"), error,
                      duration=5000, parent=self)

    def _pausePublish(self):
        if not hasattr(self, '_publishThread') or not self._publishThread.isRunning():
            return
        if self._publishThread._pause_requested:
            self._publishThread.request_resume()
            self.pauseButton.setText(self.tr("暂停"))
            self.logPanel.append("[操作] 已继续")
        else:
            self._publishThread.request_pause()
            self.pauseButton.setText(self.tr("继续"))
            self.logPanel.append("[操作] 已暂停，点击「继续」恢复")

    def _stopPublish(self):
        if hasattr(self, '_publishThread') and self._publishThread.isRunning():
            self._publishThread.request_stop()
            self.stopButton.setEnabled(False)
            self.stopButton.setText(self.tr("终止中..."))

    def _onPublishStopped(self):
        self.publishButton.setEnabled(True)
        self.publishButton.setText(self.tr("发布"))
        self.pauseButton.setVisible(False)
        self.pauseButton.setText(self.tr("暂停"))
        self.stopButton.setVisible(False)
        self.stopButton.setEnabled(True)
        self.stopButton.setText(self.tr("终止"))
        InfoBar.warning(self.tr("已停止"), self.tr("发布任务已手动停止"),
                        duration=3000, parent=self)
