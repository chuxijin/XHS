# coding: utf-8
import os
import time
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog
from qfluentwidgets import (TitleLabel, PushButton, PrimaryPushButton, 
                            TextEdit, ProgressBar, InfoBar, InfoBarPosition, 
                            CardWidget, SubtitleLabel, BodyLabel, ScrollArea)

import core.config as config

class VideoCutThread(QThread):
    """
    后台视频剪辑工作线程，防止 UI 主界面挂起假死
    """
    log_signal = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(self, video_path):
        super().__init__()
        self.video_path = video_path

    def run(self):
        def custom_log(msg):
            self.log_signal.emit(msg)

        try:
            from core.workflow import process_video_workflow
            success, result = process_video_workflow(
                video_path=self.video_path,
                log_func=custom_log
            )
            self.finished_signal.emit(success, result)
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class VideoCutInterface(QWidget):
    """
    智能视频剪辑包装侧边栏界面类 (自动扫描 Downloads 列表极简版)
    """
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("VideoCutInterface")
        self.initUI()
        self.refreshVideoList()  # 首次加载扫描目录

    def initUI(self):
        # 主垂直布局
        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setSpacing(15)
        self.mainLayout.setContentsMargins(30, 30, 30, 30)

        # 1. 顶部大标题与介绍
        self.titleLabel = TitleLabel("智能视频剪辑", self)
        self.subtitleLabel = SubtitleLabel("自动扫描 Downloads 目录，按时间排序。一键合并物流片尾并随机混音 BGM", self)
        self.subtitleLabel.setStyleSheet("color: gray; font-size: 13px;")
        self.mainLayout.addWidget(self.titleLabel)
        self.mainLayout.addWidget(self.subtitleLabel)

        # 2. 刷新按钮和扫描目录说明行
        self.infoLayout = QHBoxLayout()
        self.dirLabel = BodyLabel(f"当前监控目录: {config.SCAN_DIR}", self)
        self.dirLabel.setStyleSheet("color: #0078d4; font-weight: bold;")
        self.refreshButton = PushButton("刷新列表", self)
        self.refreshButton.clicked.connect(self.refreshVideoList)
        
        self.infoLayout.addWidget(self.dirLabel, 1)
        self.infoLayout.addWidget(self.refreshButton)
        self.mainLayout.addLayout(self.infoLayout)

        # 3. 动态列表滚动区 (ScrollArea)
        self.scrollArea = ScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        
        # 放置列表内容的容器 Widget
        self.scrollContent = QWidget()
        self.scrollContentLayout = QVBoxLayout(self.scrollContent)
        self.scrollContentLayout.setSpacing(10)
        self.scrollContentLayout.setContentsMargins(0, 0, 10, 0)
        self.scrollContentLayout.setAlignment(Qt.AlignTop)
        
        self.scrollArea.setWidget(self.scrollContent)
        self.mainLayout.addWidget(self.scrollArea, 2)  # 给列表分配较大的拉伸权重

        # 4. 进度条 (Busy Bar)
        self.progressBar = ProgressBar(self)
        self.progressBar.setValue(0)
        self.progressBar.hide()
        self.mainLayout.addWidget(self.progressBar)

        # 5. 日志面板区域
        self.logLabel = SubtitleLabel("实时运行日志 (Terminal)", self)
        self.mainLayout.addWidget(self.logLabel)

        self.logTextEdit = TextEdit(self)
        self.logTextEdit.setReadOnly(True)
        self.logTextEdit.setPlaceholderText("点击上方视频项目的“处理”按钮后，此处将展示 FFmpeg 合成日志...")
        self.logTextEdit.setStyleSheet("""
            TextEdit {
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                background-color: #1e1e1e;
                color: #e0e0e0;
                border-radius: 8px;
                border: 1px solid #333333;
            }
        """)
        self.mainLayout.addWidget(self.logTextEdit, 1)  # 分配稍小的权重

    def refreshVideoList(self):
        """
        清空现有列表并重新扫描 Downloads 文件夹，动态绘制卡片条目
        """
        # 1. 清空旧条目
        while self.scrollContentLayout.count():
            item = self.scrollContentLayout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # 2. 检查目录是否存在
        scan_dir = config.SCAN_DIR
        if not os.path.exists(scan_dir):
            self.showNoVideosMessage("未找到 Downloads 目录，请检查配置。")
            return

        # 3. 扫描并过滤视频
        video_extensions = ('.mp4', '.mov', '.avi', '.mkv', '.MOV')
        files = []
        try:
            for file_name in os.listdir(scan_dir):
                file_path = os.path.join(scan_dir, file_name)
                # 排除目录、不是视频的、以及被排除的特定视频 (物流模板、final成品等)
                if not os.path.isfile(file_path):
                    continue
                if not file_name.endswith(video_extensions):
                    continue
                if file_name == os.path.basename(config.APPEND_VIDEO_PATH):
                    continue
                if file_name.endswith("_final.mp4"):
                    continue
                
                # 获取修改时间用于排序
                mtime = os.path.getmtime(file_path)
                files.append((file_path, file_name, mtime))
        except Exception as e:
            self.showNoVideosMessage(f"扫描目录失败: {e}")
            return

        if not files:
            self.showNoVideosMessage("监控目录中暂无可处理的原始视频文件。")
            return

        # 4. 按修改时间从新到旧（降序）排序
        files.sort(key=lambda x: x[2], reverse=True)

        # 5. 动态生成界面卡片
        for file_path, file_name, mtime in files:
            # 格式化日期与大小
            date_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))
            size_mb = os.path.getsize(file_path) / (1024 * 1024)

            # 创建条目卡片
            itemCard = CardWidget(self.scrollContent)
            itemLayout = QHBoxLayout(itemCard)
            itemLayout.setContentsMargins(15, 10, 15, 10)
            itemLayout.setSpacing(15)

            # 视频详情标签列
            infoLayout = QVBoxLayout()
            infoLayout.setSpacing(4)
            
            nameLabel = BodyLabel(file_name, itemCard)
            nameLabel.setStyleSheet("font-weight: bold; font-size: 14px;")
            
            metaLabel = BodyLabel(f"修改时间: {date_str}   |   文件大小: {size_mb:.2f} MB", itemCard)
            metaLabel.setStyleSheet("color: gray; font-size: 11px;")
            
            infoLayout.addWidget(nameLabel)
            infoLayout.addWidget(metaLabel)
            
            itemLayout.addLayout(infoLayout, 1)

            # 动作按钮
            actionLayout = QHBoxLayout()
            actionLayout.setSpacing(10)

            # 特别绑定 lambda 参数捕获当前 file_path
            processBtn = PrimaryPushButton("处理", itemCard)
            processBtn.clicked.connect(lambda checked=False, p=file_path: self.processVideo(p))
            
            deleteBtn = PushButton("删除", itemCard)
            deleteBtn.clicked.connect(lambda checked=False, p=file_path: self.deleteVideo(p))
            
            actionLayout.addWidget(processBtn)
            actionLayout.addWidget(deleteBtn)
            
            itemLayout.addLayout(actionLayout)
            self.scrollContentLayout.addWidget(itemCard)

    def showNoVideosMessage(self, text):
        """
        列表为空时的提示占位
        """
        placeholderLabel = BodyLabel(text, self.scrollContent)
        placeholderLabel.setAlignment(Qt.AlignCenter)
        placeholderLabel.setStyleSheet("color: gray; font-style: italic; padding: 20px;")
        self.scrollContentLayout.addWidget(placeholderLabel)

    def processVideo(self, video_path):
        """
        开始对指定的视频路径执行后台合并配乐处理
        """
        # 清除旧日志并加锁控件
        self.logTextEdit.clear()
        self.setWidgetsEnabled(False)
        self.progressBar.setRange(0, 0)
        self.progressBar.show()

        # 启动工作线程
        self.thread = VideoCutThread(video_path)
        self.thread.log_signal.connect(self.onLogReceived)
        self.thread.finished_signal.connect(self.onProcessingFinished)
        self.thread.start()

    def deleteVideo(self, video_path):
        """
        物理删除磁盘上的原始视频文件，并刷新列表
        """
        file_name = os.path.basename(video_path)
        try:
            os.remove(video_path)
            InfoBar.success(
                title="删除成功",
                content=f"已成功将原始视频 '{file_name}' 从磁盘物理删除！",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self
            )
        except Exception as e:
            InfoBar.error(
                title="删除失败",
                content=f"无法删除文件: {e}",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self
            )
        self.refreshVideoList()

    def onLogReceived(self, text):
        self.logTextEdit.append(text)
        scrollbar = self.logTextEdit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def onProcessingFinished(self, success, result_msg):
        # 解锁控件，隐藏进度条，刷新列表
        self.setWidgetsEnabled(True)
        self.progressBar.hide()
        self.refreshVideoList()

        if success:
            InfoBar.success(
                title="草稿生成完成",
                content=f"剪映本地草稿已同步拼装完成！请直接打开剪映客户端导出成片。",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=6000,
                parent=self
            )
        else:
            InfoBar.error(
                title="处理失败",
                content=f"发生错误: {result_msg}",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=6000,
                parent=self
            )

    def setWidgetsEnabled(self, enabled):
        """
        加锁/解锁界面所有条目卡片中的动作按钮以及刷新按钮
        """
        self.refreshButton.setEnabled(enabled)
        # 遍历 ScrollArea 中的所有卡片 Widget
        for i in range(self.scrollContentLayout.count()):
            item = self.scrollContentLayout.itemAt(i)
            card = item.widget()
            if card and isinstance(card, CardWidget):
                # 卡片内部子项加锁
                for child in card.findChildren(PushButton) + card.findChildren(PrimaryPushButton):
                    child.setEnabled(enabled)
