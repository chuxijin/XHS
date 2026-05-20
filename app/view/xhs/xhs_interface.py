# coding: utf-8
"""小红书 UI 层 —— 纯界面与事件绑定"""
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                                QPlainTextEdit, QFileDialog)

from qfluentwidgets import (ScrollArea, ExpandLayout, PrimaryPushButton,
                            PushButton, LineEdit, setFont,
                            CardWidget, SubtitleLabel, InfoBar, ComboBox,
                            CheckBox, SettingCardGroup as CardGroup, BodyLabel,
                            StrongBodyLabel, CaptionLabel, MessageBoxBase)
from qfluentwidgets import FluentIcon as FIF

from .xhs_service import (get_accounts, account_exists, load_history,
                           get_account_dir, get_config_names,
                           load_publish_config, save_publish_config,
                           delete_publish_config, XhsLoginThread)
from .xhs_publish import XhsPublishThread as Scheme1Thread

PUBLISH_SCHEMES = {
    "方案1 - 视频笔记": Scheme1Thread,
}


# ---- 通用组件 ----

class SettingCardGroup(CardGroup):
    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        setFont(self.titleLabel, 14, QFont.Weight.DemiBold)


class AccountNameDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(self.tr("添加小红书账号"), self)
        self.descLabel = BodyLabel(
            self.tr("请输入账号名称（如：主号、小号）"), self)
        self.nameEdit = LineEdit(self)
        self.nameEdit.setPlaceholderText(self.tr("账号名称"))
        self.nameEdit.setClearButtonEnabled(True)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.descLabel)
        self.viewLayout.addWidget(self.nameEdit)
        self.widget.setMinimumWidth(360)


class ConfigNameDialog(MessageBoxBase):
    """新增配置名称对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(self.tr("新增发布配置"), self)
        self.descLabel = BodyLabel(
            self.tr("请输入配置名称（如：招聘号、日常号）"), self)
        self.nameEdit = LineEdit(self)
        self.nameEdit.setPlaceholderText(self.tr("配置名称"))
        self.nameEdit.setClearButtonEnabled(True)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.descLabel)
        self.viewLayout.addWidget(self.nameEdit)
        self.widget.setMinimumWidth(360)


class EditConfigDialog(MessageBoxBase):
    """编辑发布配置"""
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(self.tr("编辑发布配置"), self)
        self.topicsLabel = BodyLabel(self.tr("话题标签（中英文逗号分隔，不用带#）"), self)
        self.topicsEdit = LineEdit(self)
        self.topicsEdit.setPlaceholderText(self.tr("物流实习, 供应链实习, 采购实习"))
        self.topicsEdit.setText(", ".join(config.get("topics", [])))
        self.collectionLabel = BodyLabel(self.tr("合集名称"), self)
        self.collectionEdit = LineEdit(self)
        self.collectionEdit.setPlaceholderText(self.tr("留空则不添加合集"))
        self.collectionEdit.setText(config.get("collection", ""))
        self.groupChatLabel = BodyLabel(self.tr("群聊名称"), self)
        self.groupChatEdit = LineEdit(self)
        self.groupChatEdit.setPlaceholderText(self.tr("留空则不分享到群聊"))
        self.groupChatEdit.setText(config.get("group_chat", ""))
        for w in [self.titleLabel,
                  self.topicsLabel, self.topicsEdit,
                  self.collectionLabel, self.collectionEdit,
                  self.groupChatLabel, self.groupChatEdit]:
            self.viewLayout.addWidget(w)
        self.widget.setMinimumWidth(450)

    def get_config(self) -> dict:
        import re
        topics_text = self.topicsEdit.text().strip()
        topics = [t.strip().lstrip("#") for t in re.split(r"[,，]", topics_text)
                  if t.strip()] if topics_text else []
        return {
            "topics": topics,
            "collection": self.collectionEdit.text().strip(),
            "group_chat": self.groupChatEdit.text().strip(),
        }


class HistoryDialog(MessageBoxBase):
    def __init__(self, history_text: str, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(self.tr("发布历史记录"), self)
        self.textEdit = QPlainTextEdit(self)
        self.textEdit.setReadOnly(True)
        self.textEdit.setPlainText(history_text or self.tr("暂无发布记录"))
        self.textEdit.setMinimumHeight(400)
        self.textEdit.setStyleSheet("font-size:13px;")
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.textEdit)
        self.widget.setMinimumWidth(600)
        self.cancelButton.hide()


class LogPanel(CardWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.vBoxLayout = QVBoxLayout(self)
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

class XhsInterface(ScrollArea):
    """小红书发布界面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)
        self.titleLabel = QLabel(self.tr("小红书发布"), self)

        self._videoPath = ""
        self._templatePath = ""

        # ---- 账号设置组 ----
        self.accountGroup = SettingCardGroup(
            self.tr("账号设置"), self.scrollWidget)

        self.accountCard = CardWidget(self.accountGroup)
        self.accountCardLayout = QHBoxLayout(self.accountCard)
        self.accountCardVBox = QVBoxLayout()
        self.accountTitleLabel = StrongBodyLabel(
            self.tr("发布账号"), self.accountCard)
        self.accountDescLabel = CaptionLabel(
            self.tr("选择要发布的小红书账号"), self.accountCard)
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

        # 视频文件卡片
        self.videoCard = CardWidget(self.publishGroup)
        self.videoCardLayout = QHBoxLayout(self.videoCard)
        self.videoCardVBox = QVBoxLayout()
        self.videoTitleLabel = StrongBodyLabel(
            self.tr("视频文件"), self.videoCard)
        self.videoInfoLabel = CaptionLabel(
            self.tr("请选择视频文件"), self.videoCard)
        self.selectVideoButton = PushButton(
            self.tr("选择视频"), self.videoCard)

        self.videoCardVBox.setSpacing(0)
        self.videoCardVBox.addWidget(self.videoTitleLabel)
        self.videoCardVBox.addWidget(self.videoInfoLabel)
        self.videoCardLayout.setContentsMargins(20, 11, 20, 11)
        self.videoCardLayout.setSpacing(16)
        self.videoCardLayout.addLayout(self.videoCardVBox)
        self.videoCardLayout.addStretch(1)
        self.videoCardLayout.addWidget(self.selectVideoButton)
        self.videoCard.setFixedHeight(73)

        # 模板文件卡片
        self.templateCard = CardWidget(self.publishGroup)
        self.templateCardLayout = QHBoxLayout(self.templateCard)
        self.templateCardVBox = QVBoxLayout()
        self.templateTitleLabel = StrongBodyLabel(
            self.tr("模板文件"), self.templateCard)
        self.templateInfoLabel = CaptionLabel(
            self.tr("请选择 JSON 模板文件"), self.templateCard)
        self.selectTemplateButton = PushButton(
            self.tr("选择模板"), self.templateCard)

        self.templateCardVBox.setSpacing(0)
        self.templateCardVBox.addWidget(self.templateTitleLabel)
        self.templateCardVBox.addWidget(self.templateInfoLabel)
        self.templateCardLayout.setContentsMargins(20, 11, 20, 11)
        self.templateCardLayout.setSpacing(16)
        self.templateCardLayout.addLayout(self.templateCardVBox)
        self.templateCardLayout.addStretch(1)
        self.templateCardLayout.addWidget(self.selectTemplateButton)
        self.templateCard.setFixedHeight(73)

        # 发布配置卡片
        self.configCard = CardWidget(self.publishGroup)
        self.configCardLayout = QHBoxLayout(self.configCard)
        self.configCardVBox = QVBoxLayout()
        self.configTitleLabel = StrongBodyLabel(
            self.tr("发布配置"), self.configCard)
        self.configDescLabel = CaptionLabel(
            self.tr("话题、合集、群聊"), self.configCard)
        self.configCombo = ComboBox(self.configCard)
        self.configCombo.setFixedWidth(200)
        self.newConfigButton = PushButton(
            self.tr("新增"), self.configCard)
        self.editConfigButton = PushButton(
            self.tr("编辑"), self.configCard)
        self.deleteConfigButton = PushButton(
            self.tr("删除"), self.configCard)

        self.configCardVBox.setSpacing(0)
        self.configCardVBox.addWidget(self.configTitleLabel)
        self.configCardVBox.addWidget(self.configDescLabel)
        self.configCardLayout.setContentsMargins(20, 11, 20, 11)
        self.configCardLayout.setSpacing(12)
        self.configCardLayout.addLayout(self.configCardVBox)
        self.configCardLayout.addStretch(1)
        self.configCardLayout.addWidget(self.configCombo)
        self.configCardLayout.addWidget(self.newConfigButton)
        self.configCardLayout.addWidget(self.editConfigButton)
        self.configCardLayout.addWidget(self.deleteConfigButton)
        self.configCard.setFixedHeight(73)

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
        self.pauseButton = PushButton(self.tr("暂停"), self.schemeCard)
        self.pauseButton.setVisible(False)
        self.stopButton = PushButton(self.tr("终止"), self.schemeCard)
        self.stopButton.setVisible(False)
        self.publishButton = PrimaryPushButton(
            self.tr("发布"), self.schemeCard)
        self.headlessCheck = CheckBox(
            self.tr("隐藏浏览器"), self.schemeCard)

        self.schemeCardVBox.setSpacing(0)
        self.schemeCardVBox.addWidget(self.schemeTitleLabel)
        self.schemeCardVBox.addWidget(self.schemeDescLabel)
        self.schemeCardLayout.setContentsMargins(20, 11, 20, 11)
        self.schemeCardLayout.setSpacing(12)
        self.schemeCardLayout.addLayout(self.schemeCardVBox)
        self.schemeCardLayout.addStretch(1)
        self.schemeCardLayout.addWidget(self.schemeCombo)
        self.schemeCardLayout.addWidget(self.pauseButton)
        self.schemeCardLayout.addWidget(self.stopButton)
        self.schemeCardLayout.addWidget(self.headlessCheck)
        self.schemeCardLayout.addWidget(self.publishButton)
        self.schemeCard.setFixedHeight(73)

        # ---- 操作日志 ----
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

    def _loadConfigs(self):
        self.configCombo.clear()
        names = get_config_names()
        if names:
            self.configCombo.addItems(names)
        else:
            self.configCombo.addItem(self.tr("暂无配置"))
        self._refreshConfigInfo()

    def _refreshConfigInfo(self):
        """更新配置描述，显示当前配置的具体内容"""
        name = self.configCombo.currentText()
        if not name or name == self.tr("暂无配置"):
            self.configDescLabel.setText(
                self.tr("话题、合集、群聊"))
            return
        config = load_publish_config(name)
        parts = []
        topics = config.get("topics", [])
        if topics:
            parts.append(f"话题: {', '.join(topics)}")
        collection = config.get("collection", "")
        if collection:
            parts.append(f"合集: {collection}")
        group_chat = config.get("group_chat", "")
        if group_chat:
            parts.append(f"群聊: {group_chat}")
        self.configDescLabel.setText(
            " | ".join(parts) if parts else self.tr("未设置任何配置项"))

    def _getHistoryText(self) -> str:
        account = self.accountCombo.currentText()
        if not account or account == self.tr("暂无账号"):
            return ""
        history = load_history(get_account_dir(account))
        lines = []
        for h in reversed(history[-50:]):
            status = h.get("status", "")
            mark = "OK" if status == "success" else "FAIL"
            r = h.get("replacements", {})
            company = r.get("{{公司简称}}", "") or r.get("{{公司名称}}", "")
            job = r.get("{{岗位名称}}", "")
            desc = f" {company}-{job}" if company or job else ""
            lines.append(
                f"[{h['time']}] {h['template']}{desc} → {mark}")
            if h.get("error"):
                lines.append(f"  {h['error']}")
        return "\n".join(lines)

    def __initWidget(self):
        self.resize(1000, 800)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 100, 0, 20)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName('xhsInterface')

        setFont(self.titleLabel, 23, QFont.Weight.DemiBold)
        self.scrollWidget.setObjectName('scrollWidget')
        self.titleLabel.setObjectName('settingLabel')
        self.scrollWidget.setStyleSheet(
            "#scrollWidget{background:transparent}")

        self._loadAccounts()
        self._loadConfigs()
        self.__initLayout()
        self._connectSignalToSlot()

    def __initLayout(self):
        self.titleLabel.move(36, 50)

        self.accountGroup.addSettingCard(self.accountCard)
        self.publishGroup.addSettingCard(self.videoCard)
        self.publishGroup.addSettingCard(self.templateCard)
        self.publishGroup.addSettingCard(self.configCard)
        self.publishGroup.addSettingCard(self.schemeCard)

        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(36, 10, 36, 0)
        self.expandLayout.addWidget(self.accountGroup)
        self.expandLayout.addWidget(self.publishGroup)
        self.expandLayout.addWidget(self.logPanel)

    def _connectSignalToSlot(self):
        self.loginButton.clicked.connect(self._loginNewAccount)
        self.selectVideoButton.clicked.connect(self._selectVideo)
        self.selectTemplateButton.clicked.connect(self._selectTemplate)
        self.newConfigButton.clicked.connect(self._newConfig)
        self.editConfigButton.clicked.connect(self._editConfig)
        self.deleteConfigButton.clicked.connect(self._deleteConfig)
        self.configCombo.currentTextChanged.connect(
            lambda _: self._refreshConfigInfo())
        self.publishButton.clicked.connect(self._publish)
        self.pauseButton.clicked.connect(self._pausePublish)
        self.stopButton.clicked.connect(self._stopPublish)
        self.historyButton.clicked.connect(self._showHistory)

    # ---- 事件处理 ----

    def _selectVideo(self):
        start_dir = str(Path(self._videoPath).parent) if self._videoPath else ""
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择视频文件"), start_dir,
            self.tr("视频文件 (*.mp4 *.mov *.avi *.mkv);;所有文件 (*)"))
        if path:
            self._videoPath = path
            self.videoInfoLabel.setText(Path(path).name)

    def _selectTemplate(self):
        start_dir = str(Path(self._templatePath).parent) if self._templatePath else ""
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择 JSON 模板文件"), start_dir,
            self.tr("JSON 文件 (*.json);;所有文件 (*)"))
        if path:
            self._templatePath = path
            self.templateInfoLabel.setText(Path(path).name)

    def _newConfig(self):
        dialog = ConfigNameDialog(self.window())
        if not dialog.exec():
            return
        name = dialog.nameEdit.text().strip()
        if not name:
            InfoBar.warning(self.tr("提示"), self.tr("配置名称不能为空"),
                            duration=2000, parent=self)
            return
        if name in get_config_names():
            InfoBar.warning(self.tr("提示"), self.tr("该配置已存在"),
                            duration=2000, parent=self)
            return
        save_publish_config(name, {})
        self._loadConfigs()
        idx = self.configCombo.findText(name)
        if idx >= 0:
            self.configCombo.setCurrentIndex(idx)
        InfoBar.success(self.tr("成功"),
                        self.tr("配置 {} 已创建").format(name),
                        duration=2000, parent=self)

    def _editConfig(self):
        name = self.configCombo.currentText()
        if not name or name == self.tr("暂无配置"):
            InfoBar.warning(self.tr("提示"), self.tr("请先新增配置"),
                            duration=2000, parent=self)
            return
        config = load_publish_config(name)
        dialog = EditConfigDialog(config, self.window())
        if not dialog.exec():
            return
        save_publish_config(name, dialog.get_config())
        self._refreshConfigInfo()
        InfoBar.success(self.tr("成功"),
                        self.tr("配置 {} 已保存").format(name),
                        duration=2000, parent=self)

    def _deleteConfig(self):
        name = self.configCombo.currentText()
        if not name or name == self.tr("暂无配置"):
            return
        delete_publish_config(name)
        self._loadConfigs()
        InfoBar.success(self.tr("成功"),
                        self.tr("配置 {} 已删除").format(name),
                        duration=2000, parent=self)

    def _showHistory(self):
        dialog = HistoryDialog(self._getHistoryText(), self.window())
        dialog.exec()

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
        self._loginThread = XhsLoginThread(name, self)
        self._loginThread.loginSuccess.connect(self._onLoginSuccess)
        self._loginThread.loginFailed.connect(self._onLoginFailed)
        self._loginThread.start()
        InfoBar.info(self.tr("提示"),
                     self.tr("浏览器已打开，请扫码登录小红书"),
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
        if not self._videoPath:
            InfoBar.warning(self.tr("提示"), self.tr("请先选择视频文件"),
                            duration=2000, parent=self)
            return
        if not self._templatePath:
            InfoBar.warning(self.tr("提示"), self.tr("请先选择模板文件"),
                            duration=2000, parent=self)
            return
        try:
            data = json.loads(
                Path(self._templatePath).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as e:
            InfoBar.error(self.tr("模板错误"), str(e),
                          duration=5000, parent=self)
            return

        config_name = self.configCombo.currentText()
        publish_config = {}
        if config_name and config_name != self.tr("暂无配置"):
            publish_config = load_publish_config(config_name)

        self.logPanel.clear()
        self.publishButton.setEnabled(False)
        self.publishButton.setText(self.tr("发布中..."))
        self.pauseButton.setVisible(True)
        self.stopButton.setVisible(True)

        template_name = Path(self._templatePath).stem
        ThreadClass = PUBLISH_SCHEMES[self.schemeCombo.currentText()]
        self._publishThread = ThreadClass(
            account, self._videoPath, template_name, data,
            publish_config, self,
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
                     self.tr("自动化步骤已完成，确认无误后请点击「结束流程」"),
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
