# coding:utf-8
import os
import subprocess
import sys

from qfluentwidgets import (SwitchSettingCard, FolderListSettingCard,
                            OptionsSettingCard, PushSettingCard,
                            HyperlinkCard, PrimaryPushSettingCard, ScrollArea,
                            ComboBoxSettingCard, ExpandLayout, Theme, CustomColorSettingCard,
                            setTheme, setThemeColor, isDarkTheme, setFont,
                            CardWidget, LineEdit, StrongBodyLabel, CaptionLabel)
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import SettingCardGroup as CardGroup
from qfluentwidgets import InfoBar
from PySide6.QtCore import Qt, Signal, QUrl, QStandardPaths, QThread
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import QWidget, QLabel, QFileDialog, QVBoxLayout, QHBoxLayout

from ..common.config import cfg, isWin11
from ..common.setting import HELP_URL, FEEDBACK_URL, AUTHOR, VERSION, YEAR
from ..common.signal_bus import signalBus
from ..common.style_sheet import StyleSheet


class SettingCardGroup(CardGroup):

   def __init__(self, title: str, parent=None):
       super().__init__(title, parent)
       setFont(self.titleLabel, 14, QFont.Weight.DemiBold)


def _is_chromium_installed() -> bool:
    """检查 Playwright 的 Chromium 是否已安装"""
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return False
    ms_pw = os.path.join(local, "ms-playwright")
    if not os.path.isdir(ms_pw):
        return False
    return any(d.startswith("chromium") and os.path.isdir(os.path.join(ms_pw, d))
               for d in os.listdir(ms_pw))


class BrowserInstallThread(QThread):
    """后台线程：调用 Playwright 驱动安装 Chromium"""
    logMessage = Signal(str)
    finished = Signal(bool, str)  # (成功, 消息)

    def _run_with_log(self, cmd) -> bool:
        """执行命令并实时输出日志，返回是否成功"""
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in proc.stdout:
            line = line.strip()
            if line:
                self.logMessage.emit(line)
        proc.wait()
        return proc.returncode == 0

    _MIRRORS = [
        ("国内镜像", "https://cdn.npmmirror.com/binaries/playwright"),
        ("备用镜像", "https://registry.npmmirror.com/-/binary/playwright"),
        ("官方源", ""),  # 空字符串 = 使用 Playwright 默认源
    ]

    def _try_install(self) -> bool:
        """尝试一种安装方式，成功返回 True"""
        # 方式1: 开发环境 python -m playwright install chromium
        try:
            if self._run_with_log(
                [sys.executable, "-m", "playwright", "install", "chromium"]
            ):
                return True
        except Exception:
            pass

        # 方式2: 打包环境，通过 playwright 驱动安装
        try:
            from playwright._impl._driver import compute_driver_executable
            driver_info = compute_driver_executable()
            if isinstance(driver_info, tuple):
                node, script = driver_info
                cmd = [str(node), str(script), "install", "chromium"]
            else:
                cmd = [str(driver_info), "install", "chromium"]
            if self._run_with_log(cmd):
                return True
        except Exception:
            pass

        return False

    def run(self):
        last_error = ""

        for name, host in self._MIRRORS:
            if host:
                os.environ["PLAYWRIGHT_DOWNLOAD_HOST"] = host
            else:
                os.environ.pop("PLAYWRIGHT_DOWNLOAD_HOST", None)

            self.logMessage.emit(f"正在安装 Chromium（{name}）...")

            try:
                if self._try_install():
                    self.finished.emit(True, "Chromium 浏览器安装成功")
                    return
                last_error = f"{name}安装失败"
                self.logMessage.emit(f"{name}安装失败，尝试下一个源...")
            except Exception as e:
                last_error = str(e)
                self.logMessage.emit(f"{name}异常: {last_error}，尝试下一个源...")

        self.finished.emit(False, f"所有源均安装失败: {last_error}")


class SettingInterface(ScrollArea):
    """ Setting interface """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)

        # setting label
        self.settingLabel = QLabel(self.tr("Settings"), self)

        # ---- 浏览器管理 ----
        self.browserGroup = SettingCardGroup(
            self.tr('浏览器管理'), self.scrollWidget)
        self.browserCard = PushSettingCard(
            self.tr('下载浏览器'),
            FIF.DOWNLOAD,
            self.tr('Chromium 浏览器'),
            self.tr('检测中...'),
            self.browserGroup
        )

        # ---- 生图设置 ----
        self.imageGenGroup = SettingCardGroup(
            self.tr('生图设置'), self.scrollWidget)

        self.imageGenBaseUrlCard = CardWidget(self.imageGenGroup)
        _urlLayout = QHBoxLayout(self.imageGenBaseUrlCard)
        _urlVBox = QVBoxLayout()
        _urlVBox.addWidget(StrongBodyLabel(self.tr('API 地址'), self.imageGenBaseUrlCard))
        _urlVBox.addWidget(CaptionLabel(self.tr('如 https://api.openai.com'), self.imageGenBaseUrlCard))
        self.imageGenBaseUrlInput = LineEdit(self.imageGenBaseUrlCard)
        self.imageGenBaseUrlInput.setText(cfg.get(cfg.imageGenBaseUrl))
        _urlLayout.setContentsMargins(20, 11, 20, 11)
        _urlLayout.addLayout(_urlVBox)
        _urlLayout.addStretch(1)
        _urlLayout.addWidget(self.imageGenBaseUrlInput)
        self.imageGenBaseUrlCard.setFixedHeight(73)

        self.imageGenApiKeyCard = CardWidget(self.imageGenGroup)
        _keyLayout = QHBoxLayout(self.imageGenApiKeyCard)
        _keyVBox = QVBoxLayout()
        _keyVBox.addWidget(StrongBodyLabel(self.tr('API Key'), self.imageGenApiKeyCard))
        _keyVBox.addWidget(CaptionLabel(self.tr('Bearer 令牌'), self.imageGenApiKeyCard))
        self.imageGenApiKeyInput = LineEdit(self.imageGenApiKeyCard)
        self.imageGenApiKeyInput.setText(cfg.get(cfg.imageGenApiKey))
        self.imageGenApiKeyInput.setEchoMode(LineEdit.EchoMode.Password)
        _keyLayout.setContentsMargins(20, 11, 20, 11)
        _keyLayout.addLayout(_keyVBox)
        _keyLayout.addStretch(1)
        _keyLayout.addWidget(self.imageGenApiKeyInput)
        self.imageGenApiKeyCard.setFixedHeight(73)

        self.imageGenModelCard = CardWidget(self.imageGenGroup)
        _modelLayout = QHBoxLayout(self.imageGenModelCard)
        _modelVBox = QVBoxLayout()
        _modelVBox.addWidget(StrongBodyLabel(self.tr('模型'), self.imageGenModelCard))
        _modelVBox.addWidget(CaptionLabel(self.tr('如 gpt-image-2, dall-e-3'), self.imageGenModelCard))
        self.imageGenModelInput = LineEdit(self.imageGenModelCard)
        self.imageGenModelInput.setText(cfg.get(cfg.imageGenModel))
        _modelLayout.setContentsMargins(20, 11, 20, 11)
        _modelLayout.addLayout(_modelVBox)
        _modelLayout.addStretch(1)
        _modelLayout.addWidget(self.imageGenModelInput)
        self.imageGenModelCard.setFixedHeight(73)

        # personalization
        self.personalGroup = SettingCardGroup(
            self.tr('Personalization'), self.scrollWidget)
        self.micaCard = SwitchSettingCard(
            FIF.TRANSPARENT,
            self.tr('Mica effect'),
            self.tr('Apply semi transparent to windows and surfaces'),
            cfg.micaEnabled,
            self.personalGroup
        )
        self.themeCard = ComboBoxSettingCard(
            cfg.themeMode,
            FIF.BRUSH,
            self.tr('Application theme'),
            self.tr("Change the appearance of your application"),
            texts=[
                self.tr('Light'), self.tr('Dark'),
                self.tr('Use system setting')
            ],
            parent=self.personalGroup
        )
        self.zoomCard = ComboBoxSettingCard(
            cfg.dpiScale,
            FIF.ZOOM,
            self.tr("Interface zoom"),
            self.tr("Change the size of widgets and fonts"),
            texts=[
                "100%", "125%", "150%", "175%", "200%",
                self.tr("Use system setting")
            ],
            parent=self.personalGroup
        )
        self.languageCard = ComboBoxSettingCard(
            cfg.language,
            FIF.LANGUAGE,
            self.tr('Language'),
            self.tr('Set your preferred language for UI'),
            texts=['简体中文', '繁體中文', 'English', self.tr('Use system setting')],
            parent=self.personalGroup
        )

        # update software
        self.updateSoftwareGroup = SettingCardGroup(
            self.tr("Software update"), self.scrollWidget)
        self.updateOnStartUpCard = SwitchSettingCard(
            FIF.UPDATE,
            self.tr('Check for updates when the application starts'),
            self.tr('The new version will be more stable and have more features'),
            configItem=cfg.checkUpdateAtStartUp,
            parent=self.updateSoftwareGroup
        )

        # application
        self.aboutGroup = SettingCardGroup(self.tr('About'), self.scrollWidget)
        self.helpCard = HyperlinkCard(
            HELP_URL,
            self.tr('Open help page'),
            FIF.HELP,
            self.tr('Help'),
            self.tr(
                'Discover new features and learn useful tips about Fluent Client'),
            self.aboutGroup
        )
        self.feedbackCard = PrimaryPushSettingCard(
            self.tr('Provide feedback'),
            FIF.FEEDBACK,
            self.tr('Provide feedback'),
            self.tr('Help us improve Fluent Client by providing feedback'),
            self.aboutGroup
        )
        self.aboutCard = PrimaryPushSettingCard(
            self.tr('Check update'),
            ":/qfluentwidgets/images/logo.png",
            self.tr('About'),
            '© ' + self.tr('Copyright') + f" {YEAR}, {AUTHOR}. " +
            self.tr('Version') + " " + VERSION,
            self.aboutGroup
        )

        self.__initWidget()

    def __initWidget(self):
        self.resize(1000, 800)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 100, 0, 20)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName('settingInterface')

        # initialize style sheet
        setFont(self.settingLabel, 23, QFont.Weight.DemiBold)
        self.scrollWidget.setObjectName('scrollWidget')
        self.settingLabel.setObjectName('settingLabel')
        StyleSheet.SETTING_INTERFACE.apply(self)
        self.scrollWidget.setStyleSheet("QWidget{background:transparent}")

        self.micaCard.setEnabled(isWin11())

        # 检查浏览器状态
        self._refreshBrowserStatus()

        # initialize layout
        self.__initLayout()
        self._connectSignalToSlot()

    def __initLayout(self):
        self.settingLabel.move(36, 50)

        self.browserGroup.addSettingCard(self.browserCard)

        self.imageGenGroup.addSettingCard(self.imageGenBaseUrlCard)
        self.imageGenGroup.addSettingCard(self.imageGenApiKeyCard)
        self.imageGenGroup.addSettingCard(self.imageGenModelCard)

        self.personalGroup.addSettingCard(self.micaCard)
        self.personalGroup.addSettingCard(self.themeCard)
        self.personalGroup.addSettingCard(self.zoomCard)
        self.personalGroup.addSettingCard(self.languageCard)

        self.updateSoftwareGroup.addSettingCard(self.updateOnStartUpCard)

        self.aboutGroup.addSettingCard(self.helpCard)
        self.aboutGroup.addSettingCard(self.feedbackCard)
        self.aboutGroup.addSettingCard(self.aboutCard)

        # add setting card group to layout
        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(36, 10, 36, 0)
        self.expandLayout.addWidget(self.browserGroup)
        self.expandLayout.addWidget(self.imageGenGroup)
        self.expandLayout.addWidget(self.personalGroup)
        self.expandLayout.addWidget(self.updateSoftwareGroup)
        self.expandLayout.addWidget(self.aboutGroup)

    def _refreshBrowserStatus(self):
        if _is_chromium_installed():
            self.browserCard.setContent(self.tr('已安装'))
            self.browserCard.button.setText(self.tr('重新安装'))
        else:
            self.browserCard.setContent(self.tr('未安装 (首次使用前需要下载)'))
            self.browserCard.button.setText(self.tr('下载浏览器'))

    def _installBrowser(self):
        self.browserCard.button.setEnabled(False)
        self.browserCard.button.setText(self.tr('安装中...'))
        self.browserCard.setContent(self.tr('正在下载 Chromium，请稍候...'))
        self._installThread = BrowserInstallThread(self)
        self._installThread.logMessage.connect(
            lambda msg: self.browserCard.setContent(msg))
        self._installThread.finished.connect(self._onInstallFinished)
        self._installThread.start()

    def _onInstallFinished(self, success: bool, message: str):
        self.browserCard.button.setEnabled(True)
        self._refreshBrowserStatus()
        if success:
            InfoBar.success(self.tr('成功'), message,
                            duration=3000, parent=self)
        else:
            InfoBar.error(self.tr('失败'), message,
                          duration=5000, parent=self)

    def _showRestartTooltip(self):
        """ show restart tooltip """
        InfoBar.success(
            self.tr('Updated successfully'),
            self.tr('Configuration takes effect after restart'),
            duration=1500,
            parent=self
        )

    def _connectSignalToSlot(self):
        """ connect signal to slot """
        cfg.appRestartSig.connect(self._showRestartTooltip)

        # browser
        self.browserCard.clicked.connect(self._installBrowser)

        # image gen
        self.imageGenBaseUrlInput.textChanged.connect(
            lambda v: cfg.set(cfg.imageGenBaseUrl, v))
        self.imageGenApiKeyInput.textChanged.connect(
            lambda v: cfg.set(cfg.imageGenApiKey, v))
        self.imageGenModelInput.textChanged.connect(
            lambda v: cfg.set(cfg.imageGenModel, v))

        # personalization
        cfg.themeChanged.connect(setTheme)
        self.micaCard.checkedChanged.connect(signalBus.micaEnableChanged)

        # check update
        self.aboutCard.clicked.connect(signalBus.checkUpdateSig)

        # about
        self.feedbackCard.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(FEEDBACK_URL)))
