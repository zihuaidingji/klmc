#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#######################################################################
#
# VidCutter - media cutter & joiner
#
# copyright © 2018 Pete Alexandrou
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#######################################################################

import logging
import os
import re
import sys
import time
from datetime import timedelta
from functools import partial
from typing import Callable, List, Optional, Union

from PyQt5.QtCore import (pyqtSignal, pyqtSlot, QBuffer, QByteArray, QDir, QFile, QFileInfo, QModelIndex, QPoint, QSize,
                          Qt, QTextStream, QTime, QTimer, QUrl)
from PyQt5.QtGui import QDesktopServices, QFont, QFontDatabase, QIcon, QKeyEvent, QPixmap, QShowEvent
from PyQt5.QtWidgets import (QAction, qApp, QApplication, QDialog, QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel,
                             QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QSizePolicy, QStyleFactory,
                             QVBoxLayout, QWidget)

import sip

# noinspection PyUnresolvedReferences
from vidcutter import resources
from vidcutter.about import About
from vidcutter.changelog import Changelog
#xn:增加人脸识别
#from vidcutter.klmc.ftest import FaceTimeMark

from vidcutter.mediainfo import MediaInfo
from vidcutter.mediastream import StreamSelector
from vidcutter.settings import SettingsDialog
from vidcutter.updater import Updater
from vidcutter.videolist import VideoList
from vidcutter.videoslider import VideoSlider
from vidcutter.videosliderwidget import VideoSliderWidget
from vidcutter.videostyle import VideoStyleDark, VideoStyleLight

from vidcutter.libs.config import Config, InvalidMediaException, VideoFilter
from vidcutter.libs.mpvwidget import mpvWidget
from vidcutter.libs.munch import Munch
from vidcutter.libs.notifications import JobCompleteNotification
from vidcutter.libs.taskbarprogress import TaskbarProgress
from vidcutter.libs.videoservice import VideoService
from vidcutter.libs.widgets import (ClipErrorsDialog, VCBlinkText, VCDoubleInputDialog, VCFilterMenuAction,
                                    VCFrameCounter, VCInputDialog, VCMessageBox, VCProgressDialog, VCTimeCounter,
                                    VCToolBarButton, VCVolumeSlider, VCRichInputDialog)

import vidcutter
import subprocess


class VideoCutter(QWidget):
    errorOccurred = pyqtSignal(str)

    timeformat = 'hh:mm:ss.zzz'
    runtimeformat = 'hh:mm:ss'

    def __init__(self, parent: QMainWindow):
        super(VideoCutter, self).__init__(parent)
        self.setObjectName('videocutter')
        self.logger = logging.getLogger(__name__)
        self.parent = parent
        self.theme = self.parent.theme
        self.workFolder = self.parent.WORKING_FOLDER
        self.settings = self.parent.settings
        self.filter_settings = Config.filter_settings()
        self.currentMedia, self.mediaAvailable, self.mpvError = None, False, False
        self.projectDirty, self.projectSaved, self.debugonstart = False, False, False
        self.smartcut_monitor, self.notify = None, None
        self.fonts = []

        self.initTheme()
        self.updater = Updater(self.parent)

        self.seekSlider = VideoSlider(self)
        self.seekSlider.sliderMoved.connect(self.setPosition)
        self.sliderWidget = VideoSliderWidget(self, self.seekSlider)
        self.sliderWidget.setLoader(True)

        self.taskbar = TaskbarProgress(self.parent)

        self.clipTimes = []
        self.inCut, self.newproject = False, False
        self.finalFilename = ''
        self.totalRuntime, self.frameRate = 0, 0
        self.notifyInterval = 1000

        self.createChapters = self.settings.value('chapters', 'on', type=str) in {'on', 'true'}
        self.enableOSD = self.settings.value('enableOSD', 'on', type=str) in {'on', 'true'}
        self.hardwareDecoding = self.settings.value('hwdec', 'on', type=str) in {'on', 'auto'}
        self.enablePBO = self.settings.value('enablePBO', 'off', type=str) in {'on', 'true'}
        self.keepRatio = self.settings.value('aspectRatio', 'keep', type=str) == 'keep'
        self.keepClips = self.settings.value('keepClips', 'off', type=str) in {'on', 'true'}
        self.nativeDialogs = self.settings.value('nativeDialogs', 'on', type=str) in {'on', 'true'}
        self.indexLayout = self.settings.value('indexLayout', 'right', type=str)
        self.timelineThumbs = self.settings.value('timelineThumbs', 'on', type=str) in {'on', 'true'}
        self.showConsole = self.settings.value('showConsole', 'off', type=str) in {'on', 'true'}
        self.smartcut = self.settings.value('smartcut', 'off', type=str) in {'on', 'true'}
        self.level1Seek = self.settings.value('level1Seek', 2, type=float)
        self.level2Seek = self.settings.value('level2Seek', 5, type=float)
        self.verboseLogs = self.parent.verboseLogs
        self.lastFolder = self.settings.value('lastFolder', QDir.homePath(), type=str)

        self.videoService = VideoService(self.settings, self)
        self.videoService.progress.connect(self.seekSlider.updateProgress)
        self.videoService.finished.connect(self.smartmonitor)
        self.videoService.error.connect(self.completeOnError)
        self.videoService.addScenes.connect(self.addScenes)

        self.project_files = {
            'edl': re.compile(r'(\d+(?:\.?\d+)?)\t(\d+(?:\.?\d+)?)\t([01])'),
            'vcp': re.compile(r'(\d+(?:\.?\d+)?)\t(\d+(?:\.?\d+)?)\t([01])\t(".*")$')
        }

        self._initIcons()
        self._initActions()

        self.appmenu = QMenu(self.parent)
        self.clipindex_removemenu, self.clipindex_contextmenu = QMenu(self), QMenu(self)

        self._initMenus()
        self._initNoVideo()

        self.cliplist = VideoList(self)
        self.cliplist.customContextMenuRequested.connect(self.itemMenu)
        self.cliplist.currentItemChanged.connect(self.selectClip)
        self.cliplist.model().rowsInserted.connect(self.setProjectDirty)
        self.cliplist.model().rowsRemoved.connect(self.setProjectDirty)
        self.cliplist.model().rowsMoved.connect(self.setProjectDirty)
        self.cliplist.model().rowsMoved.connect(self.syncClipList)

        self.listHeaderButtonL = QPushButton(self)
        self.listHeaderButtonL.setObjectName('listheaderbutton-left')
        self.listHeaderButtonL.setFlat(True)
        self.listHeaderButtonL.clicked.connect(self.setClipIndexLayout)
        self.listHeaderButtonL.setCursor(Qt.PointingHandCursor)
        self.listHeaderButtonL.setFixedSize(14, 14)
        self.listHeaderButtonL.setToolTip('向左移动')#'Move to left'
        self.listHeaderButtonL.setStatusTip('将剪辑索引列表移到播放器的左侧')#'Move the Clip Index list to the left side of player'
        self.listHeaderButtonR = QPushButton(self)
        self.listHeaderButtonR.setObjectName('listheaderbutton-right')
        self.listHeaderButtonR.setFlat(True)
        self.listHeaderButtonR.clicked.connect(self.setClipIndexLayout)
        self.listHeaderButtonR.setCursor(Qt.PointingHandCursor)
        self.listHeaderButtonR.setFixedSize(14, 14)
        self.listHeaderButtonR.setToolTip('向右移动')#'Move to right
        self.listHeaderButtonR.setStatusTip('将剪辑索引列表移到播放器的右侧')#'Move the Clip Index list to the right side of player'
        listheaderLayout = QHBoxLayout()
        listheaderLayout.setContentsMargins(6, 5, 6, 5)
        listheaderLayout.addWidget(self.listHeaderButtonL)
        listheaderLayout.addStretch(1)
        listheaderLayout.addWidget(self.listHeaderButtonR)
        self.listheader = QWidget(self)
        self.listheader.setObjectName('listheader')
        self.listheader.setFixedWidth(self.cliplist.width())
        self.listheader.setLayout(listheaderLayout)
        self._initClipIndexHeader()

        self.runtimeLabel = QLabel('<div align="right">00:00:00</div>', self)
        self.runtimeLabel.setObjectName('runtimeLabel')
        self.runtimeLabel.setToolTip('总运行时间: 00:00:00')#'total runtime: 00:00:00
        self.runtimeLabel.setStatusTip('总运行时间: 00:00:00')#'total running time: 00:00:00'

##xn:close items
##        self.clipindex_add = QPushButton(self)
##        self.clipindex_add.setObjectName('clipadd')
##        self.clipindex_add.clicked.connect(self.addExternalClips)
##        self.clipindex_add.setToolTip('添加剪辑')#'Add clips
##        self.clipindex_add.setStatusTip('仅在现有项目或空列表中添加一个或多个文件 '
##                                        '加入文件')#'Add one or more files to an existing project or an empty list if you are only ' 'joining files'
##        self.clipindex_add.setCursor(Qt.PointingHandCursor)
##        self.clipindex_remove = QPushButton(self)
##        self.clipindex_remove.setObjectName('clipremove')
##        self.clipindex_remove.setToolTip('删除剪辑')#'Remove clips'
##        self.clipindex_remove.setStatusTip('从索引中删除剪辑')#'Remove clips from your index'
##        self.clipindex_remove.setLayoutDirection(Qt.RightToLeft)
##        self.clipindex_remove.setMenu(self.clipindex_removemenu)
##        self.clipindex_remove.setCursor(Qt.PointingHandCursor)
##      
##        if sys.platform in {'win32', 'darwin'}:
##            self.clipindex_add.setStyle(QStyleFactory.create('Fusion'))
##            self.clipindex_remove.setStyle(QStyleFactory.create('Fusion'))
##
##        clipindex_layout = QHBoxLayout()
##        clipindex_layout.setSpacing(1)
##        clipindex_layout.setContentsMargins(0, 0, 0, 0)
##        clipindex_layout.addWidget(self.clipindex_add)
##        clipindex_layout.addSpacing(1)
##        clipindex_layout.addWidget(self.clipindex_remove)
##        clipindexTools = QWidget(self)
##        clipindexTools.setObjectName('clipindextools')
##        clipindexTools.setLayout(clipindex_layout)


        self.clipindexLayout = QVBoxLayout()
        self.clipindexLayout.setSpacing(0)
        self.clipindexLayout.setContentsMargins(0, 0, 0, 0)
        self.clipindexLayout.addWidget(self.listheader)
        self.clipindexLayout.addWidget(self.cliplist)
        self.clipindexLayout.addWidget(self.runtimeLabel)
        self.clipindexLayout.addSpacing(3)
##        self.clipindexLayout.addWidget(clipindexTools)

        self.videoLayout = QHBoxLayout()
        self.videoLayout.setContentsMargins(0, 0, 0, 0)
        if self.indexLayout == 'left':
            self.videoLayout.addLayout(self.clipindexLayout)
            self.videoLayout.addSpacing(10)
            self.videoLayout.addWidget(self.novideoWidget)
        else:
            self.videoLayout.addWidget(self.novideoWidget)
            self.videoLayout.addSpacing(10)
            self.videoLayout.addLayout(self.clipindexLayout)

        
        self.timeCounter = VCTimeCounter(self)
        self.timeCounter.timeChanged.connect(lambda newtime: self.setPosition(newtime.msecsSinceStartOfDay()))
        self.frameCounter = VCFrameCounter(self)
        self.frameCounter.setReadOnly(True)

        
        countersLayout = QHBoxLayout()
        countersLayout.setContentsMargins(0, 0, 0, 0)
        countersLayout.addStretch(1)
        # noinspection PyArgumentList
        countersLayout.addWidget(QLabel('时间:', objectName='tcLabel'))#'TIME:'
        countersLayout.addWidget(self.timeCounter)
        countersLayout.addStretch(1)
        # noinspection PyArgumentList
        countersLayout.addWidget(QLabel('帧数:', objectName='fcLabel'))#'FRAME:'
        countersLayout.addWidget(self.frameCounter)
        countersLayout.addStretch(1)

        countersWidget = QWidget(self)
        countersWidget.setObjectName('counterwidgets')
        countersWidget.setContentsMargins(0, 0, 0, 0)
        countersWidget.setLayout(countersLayout)
        countersWidget.setMaximumHeight(28)
        

        self.mpvWidget = self.getMPV(self)

        self.videoplayerLayout = QVBoxLayout()
        self.videoplayerLayout.setSpacing(0)
        #xn:move down 20, show whole video. self.videoplayerLayout.setContentsMargins(0, 20, 0, 0)
        self.videoplayerLayout.setContentsMargins(0, 20, 0, 0)
        self.videoplayerLayout.addWidget(self.mpvWidget)
        self.videoplayerLayout.addWidget(countersWidget)

        self.videoplayerWidget = QFrame(self)
        self.videoplayerWidget.setObjectName('videoplayer')
        self.videoplayerWidget.setFrameStyle(QFrame.Box | QFrame.Sunken)
        self.videoplayerWidget.setLineWidth(0)
        self.videoplayerWidget.setMidLineWidth(0)
        self.videoplayerWidget.setVisible(False)
        
        self.videoplayerWidget.setLayout(self.videoplayerLayout)

        # noinspection PyArgumentList
        self.thumbnailsButton = QPushButton(self, flat=True, checkable=True, objectName='thumbnailsButton',
                                            statusTip='切换时间轴缩略图', cursor=Qt.PointingHandCursor,#'Toggle timeline thumbnails'
                                            toolTip='切换缩略图')#'Toggle thumbnails
        self.thumbnailsButton.setFixedSize(32, 29 if self.theme == 'dark' else 31)
        self.thumbnailsButton.setChecked(self.timelineThumbs)
        self.thumbnailsButton.toggled.connect(self.toggleThumbs)
        if self.timelineThumbs:
            self.seekSlider.setObjectName('nothumbs')

        # noinspection PyArgumentList
        self.osdButton = QPushButton(self, flat=True, checkable=True, objectName='osdButton', toolTip='Toggle OSD',
                                     statusTip='切换屏幕显示', cursor=Qt.PointingHandCursor)#'Toggle on-screen display'
        self.osdButton.setFixedSize(31, 29 if self.theme == 'dark' else 31)
        self.osdButton.setChecked(self.enableOSD)
        self.osdButton.toggled.connect(self.toggleOSD)

        # noinspection PyArgumentList
        self.consoleButton = QPushButton(self, flat=True, checkable=True, objectName='consoleButton',
                                         statusTip='切换控制台窗口', toolTip='切换控制台',#'Toggle console window' 'Toggle console'
                                         cursor=Qt.PointingHandCursor)
        self.consoleButton.setFixedSize(31, 29 if self.theme == 'dark' else 31)
        self.consoleButton.setChecked(self.showConsole)
        self.consoleButton.toggled.connect(self.toggleConsole)
        if self.showConsole:
            self.mpvWidget.setLogLevel('v')
            os.environ['DEBUG'] = '1'
            self.parent.console.show()

        # noinspection PyArgumentList
        self.chaptersButton = QPushButton(self, flat=True, checkable=True, objectName='chaptersButton',
                                          statusTip='自动创建每个剪辑章节', toolTip='创建章节',#'Automatically create chapters per clip' 'Create chapters'
                                          cursor=Qt.PointingHandCursor)
        self.chaptersButton.setFixedSize(31, 29 if self.theme == 'dark' else 31)
        self.chaptersButton.setChecked(self.createChapters)
        self.chaptersButton.toggled.connect(self.toggleChapters)

        # noinspection PyArgumentList
        self.smartcutButton = QPushButton(self, flat=True, checkable=True, objectName='smartcutButton',
                                          toolTip='切换智能剪辑', statusTip='切换精准剪辑',#'Toggle SmartCut' 'Toggle frame accurate cutting'
                                          cursor=Qt.PointingHandCursor)
        self.smartcutButton.setFixedSize(32, 29 if self.theme == 'dark' else 31)
        self.smartcutButton.setChecked(self.smartcut)
        self.smartcutButton.toggled.connect(self.toggleSmartCut)

        # noinspection PyArgumentList
        self.muteButton = QPushButton(objectName='muteButton', icon=self.unmuteIcon, flat=True, toolTip='静音',#'Mute'
                                      statusTip='切换音频至静音', iconSize=QSize(16, 16), clicked=self.muteAudio,
                                      cursor=Qt.PointingHandCursor)

        # noinspection PyArgumentList
        self.volSlider = VCVolumeSlider(orientation=Qt.Horizontal, toolTip='音量', statusTip='调节音量',#'Volume' 'Adjust volume level'
                                        cursor=Qt.PointingHandCursor, value=self.parent.startupvol, minimum=0,
                                        #lz:modify maximum volume# maximum=130, minimumHeight=22, sliderMoved=self.setVolume)
                                        maximum=100, minimumHeight=22, sliderMoved=self.setVolume)

        # noinspection PyArgumentList
        self.fullscreenButton = QPushButton(objectName='fullscreenButton', icon=self.fullscreenIcon, flat=True,
                                            toolTip='切换全屏', statusTip='切换到全屏视频',#'Toggle fullscreen' 'Switch to fullscreen video'
                                            iconSize=QSize(14, 14), clicked=self.toggleFullscreen,
                                            cursor=Qt.PointingHandCursor, enabled=False)

        # noinspection PyArgumentList
        self.settingsButton = QPushButton(self, toolTip='设置', cursor=Qt.PointingHandCursor, flat=True,#'Settings'
                                          statusTip='配置应用程序设置',#'Configure application settings'
                                          objectName='settingsButton', clicked=self.showSettings)
        self.settingsButton.setFixedSize(QSize(33, 32))

        # noinspection PyArgumentList

        self.streamsButton = QPushButton(self, toolTip='流媒体', cursor=Qt.PointingHandCursor, flat=True,#'Media streams'
                                         statusTip='流媒体信息',#'Select the media streams to be included'

                                         objectName='streamsButton', clicked=self.selectStreams,
                                         enabled=False)
        self.streamsButton.setFixedSize(QSize(33, 32))

        # noinspection PyArgumentList
        self.mediainfoButton = QPushButton(self, toolTip='媒体信息', cursor=Qt.PointingHandCursor, flat=True,#'Media information'
                                           statusTip='查看当前媒体文件的技术信息详情',#'View technical details about current media'
                                           objectName='mediainfoButton', clicked=self.mediaInfo, enabled=False)
        self.mediainfoButton.setFixedSize(QSize(33, 32))

        # noinspection PyArgumentList
        self.menuButton = QPushButton(self, toolTip='菜单', cursor=Qt.PointingHandCursor, flat=True,#'Menu
                                      objectName='menuButton', clicked=self.showAppMenu, statusTip='查看菜单选项')#'View menu options'
        self.menuButton.setFixedSize(QSize(33, 32))

        audioLayout = QHBoxLayout()
        audioLayout.setContentsMargins(0, 0, 0, 0)
        audioLayout.addWidget(self.muteButton)
        audioLayout.addSpacing(5)
        audioLayout.addWidget(self.volSlider)
        audioLayout.addSpacing(5)
        audioLayout.addWidget(self.fullscreenButton)

        self.toolbar_open = VCToolBarButton('Open 打开', '打开并加载媒体文件', parent=self)#'Open Media', 'Open and load a media file to begin'
        self.toolbar_open.clicked.connect(self.openMedia)
        self.toolbar_play = VCToolBarButton('Play 播放', '播放当前加载的媒体文件', parent=self)#'Play Media', 'Play currently loaded media file'
        self.toolbar_play.setEnabled(False)
        self.toolbar_play.clicked.connect(self.playMedia)
        self.toolbar_start = VCToolBarButton('Start 开始剪辑', '从当前时间线位置开始前剪辑',#'Start Clip', 'Start a new clip from the current timeline position'
                                             parent=self)
        self.toolbar_start.setEnabled(False)
        self.toolbar_start.clicked.connect(self.clipStart)
        self.toolbar_end = VCToolBarButton('End 停止剪辑', '在当前时间线位置结束新剪辑', parent=self)#'End Clip', 'End a new clip at the current timeline position'
        self.toolbar_end.setEnabled(False)
        self.toolbar_end.clicked.connect(self.clipEnd)
        self.toolbar_save = VCToolBarButton('Save 保存', '将剪辑保存到新的媒体文件', parent=self)#'Save Media', 'Save clips to a new media file'
        self.toolbar_save.setObjectName('savebutton')
        self.toolbar_save.setEnabled(False)
        self.toolbar_save.clicked.connect(self.saveMedia)

        toolbarLayout = QHBoxLayout()
        toolbarLayout.setContentsMargins(0, 0, 0, 0)
        toolbarLayout.addStretch(1)
        toolbarLayout.addWidget(self.toolbar_open)
        toolbarLayout.addStretch(1)
        toolbarLayout.addWidget(self.toolbar_play)
        toolbarLayout.addStretch(1)
        toolbarLayout.addWidget(self.toolbar_start)
        toolbarLayout.addStretch(1)
        toolbarLayout.addWidget(self.toolbar_end)
        toolbarLayout.addStretch(1)
        toolbarLayout.addWidget(self.toolbar_save)
        toolbarLayout.addStretch(1)

        self.toolbarGroup = QGroupBox()
        self.toolbarGroup.setLayout(toolbarLayout)
        self.toolbarGroup.setStyleSheet('QGroupBox { border: 0; }')

        self.setToolBarStyle(self.settings.value('toolbarLabels', 'beside', type=str))

        togglesLayout = QHBoxLayout()
        togglesLayout.setSpacing(0)
        togglesLayout.setContentsMargins(0, 0, 0, 0)
        togglesLayout.addWidget(self.consoleButton)
        togglesLayout.addWidget(self.osdButton)
        togglesLayout.addWidget(self.thumbnailsButton)
        togglesLayout.addWidget(self.chaptersButton)
        togglesLayout.addWidget(self.smartcutButton)
        togglesLayout.addStretch(1)

        settingsLayout = QHBoxLayout()
        settingsLayout.setSpacing(0)
        settingsLayout.setContentsMargins(0, 0, 0, 0)
        settingsLayout.addWidget(self.settingsButton)
        settingsLayout.addSpacing(5)
        settingsLayout.addWidget(self.streamsButton)
        settingsLayout.addSpacing(5)
        settingsLayout.addWidget(self.mediainfoButton)
        settingsLayout.addSpacing(5)
        settingsLayout.addWidget(self.menuButton)

        groupLayout = QVBoxLayout()
        groupLayout.addLayout(audioLayout)
        groupLayout.addSpacing(10)
        groupLayout.addLayout(settingsLayout)

        controlsLayout = QHBoxLayout()
        if sys.platform != 'darwin':
            controlsLayout.setContentsMargins(0, 0, 0, 0)
            controlsLayout.addSpacing(5)
        else:
            controlsLayout.setContentsMargins(10, 10, 10, 0)
        controlsLayout.addLayout(togglesLayout)
        controlsLayout.addSpacing(20)
        controlsLayout.addStretch(1)
        controlsLayout.addWidget(self.toolbarGroup)
        controlsLayout.addStretch(1)
        controlsLayout.addSpacing(20)
        controlsLayout.addLayout(groupLayout)
        if sys.platform != 'darwin':
            controlsLayout.addSpacing(5)

        layout = QVBoxLayout()  
        layout.setSpacing(0)
        layout.setContentsMargins(10, 10, 10, 0)
        layout.addLayout(self.videoLayout)
        layout.addWidget(self.sliderWidget)
        layout.addSpacing(5)
        layout.addLayout(controlsLayout)

        self.setLayout(layout)
        self.seekSlider.initStyle()

    @pyqtSlot()
    def showAppMenu(self) -> None:
        pos = self.menuButton.mapToGlobal(self.menuButton.rect().topLeft())
        pos.setX(pos.x() - self.appmenu.sizeHint().width() + 30)
        pos.setY(pos.y() - 28)
        self.appmenu.popup(pos, self.quitAction)

    def initTheme(self) -> None:
        qApp.setStyle(VideoStyleDark() if self.theme == 'dark' else VideoStyleLight())
        self.fonts = [
            QFontDatabase.addApplicationFont(':/fonts/FuturaLT.ttf'),
            QFontDatabase.addApplicationFont(':/fonts/NotoSans-Bold.ttf'),
            QFontDatabase.addApplicationFont(':/fonts/NotoSans-Regular.ttf')
        ]
        self.style().loadQSS(self.theme)
        QApplication.setFont(QFont('Noto Sans', 12 if sys.platform == 'darwin' else 10, 300))

    def getMPV(self, parent: QWidget=None, file: str=None, start: float=0, pause: bool=True, mute: bool=False,
               volume: int=None) -> mpvWidget:
        widget = vidcutter.libs.mpvwidget.mpvWidget(
            parent=parent,
            file=file,

            #xn gpu for windows:vo='opengl-cb',
            vo='gpu',
            #speed=100,
            
            pause=pause,
            start=start,
            mute=mute,
            keep_open='always',
            idle=True,
            osd_font=self._osdfont,
            osd_level=0,
            osd_align_x='left',
            osd_align_y='top',
            cursor_autohide=False,
            input_cursor=False,
            input_default_bindings=False,
            stop_playback_on_init_failure=False,
            input_vo_keyboard=False,
            sub_auto=False,
            sid=False,
            video_sync='display-vdrop',
            audio_file_auto=False,
            quiet=True,
            volume=volume if volume is not None else self.parent.startupvol,
            #xn:opengl_pbo=self.enablePBO,
            keepaspect=self.keepRatio,
            hwdec=('auto' if self.hardwareDecoding else 'no'))
        widget.durationChanged.connect(self.on_durationChanged)
        widget.positionChanged.connect(self.on_positionChanged)
        return widget

    def _initNoVideo(self) -> None:
        self.novideoWidget = QWidget(self)
        self.novideoWidget.setObjectName('novideoWidget')
        self.novideoWidget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        openmediaLabel = VCBlinkText('打开媒体文件体验吧！', self)#'open media to begin'
        openmediaLabel.setAlignment(Qt.AlignHCenter)
        _version = 'v{}'.format(qApp.applicationVersion())
        if self.parent.flatpak:
            _version += ' <font size="-1">- FLATPAK</font>'
        versionLabel = QLabel(_version, self)
        versionLabel.setObjectName('novideoversion')
        versionLabel.setAlignment(Qt.AlignRight)
        versionLayout = QHBoxLayout()
        versionLayout.setSpacing(0)
        versionLayout.setContentsMargins(0, 0, 10, 8)
        versionLayout.addWidget(versionLabel)
        novideoLayout = QVBoxLayout(self.novideoWidget)
        novideoLayout.setSpacing(0)
        novideoLayout.setContentsMargins(0, 0, 0, 0)
        novideoLayout.addStretch(20)
        novideoLayout.addWidget(openmediaLabel)
        novideoLayout.addStretch(1)
        novideoLayout.addLayout(versionLayout)

    def _initIcons(self) -> None:
        self.appIcon = qApp.windowIcon()
        self.muteIcon = QIcon(':/images/{}/muted.png'.format(self.theme))
        self.unmuteIcon = QIcon(':/images/{}/unmuted.png'.format(self.theme))
        self.chapterIcon = QIcon(':/images/chapters.png')
        self.upIcon = QIcon(':/images/up.png')
        self.downIcon = QIcon(':/images/down.png')
        self.removeIcon = QIcon(':/images/remove.png')
        self.removeAllIcon = QIcon(':/images/remove-all.png')
        self.openProjectIcon = QIcon(':/images/open.png')
        self.saveProjectIcon = QIcon(':/images/save.png')
        self.filtersIcon = QIcon(':/images/filters.png')
        self.mediaInfoIcon = QIcon(':/images/info.png')
        self.streamsIcon = QIcon(':/images/streams.png')
        #xn:改成KLMC self.changelogIcon = QIcon(':/images/changelog.png')
        self.KLMCIcon = QIcon(':/images/changelog.png')
        #xn:增加人脸识别
        self.faceMarkIcon = QIcon(':/images/changelog.png')
        self.carLicenseMarkIcon = QIcon(':/images/changelog.png')        
        self.pcMarkIcon = QIcon(':/images/changelog.png')
        self.litterMarkIcon = QIcon(':/images/changelog.png')
        #xn--------------------------------------------------------------
        self.viewLogsIcon = QIcon(':/images/viewlogs.png')
        self.updateCheckIcon = QIcon(':/images/update.png')
        self.keyRefIcon = QIcon(':/images/keymap.png')
        self.fullscreenIcon = QIcon(':/images/{}/fullscreen.png'.format(self.theme))
        self.settingsIcon = QIcon(':/images/settings.png')
        self.quitIcon = QIcon(':/images/quit.png')

    # noinspection PyArgumentList
    def _initActions(self) -> None:
        self.moveItemUpAction = QAction(self.upIcon, '向上移动剪辑', self, statusTip='在列表中向上移动剪辑位置',#'Move clip up' 'Move clip position up in list'
                                        triggered=self.moveItemUp, enabled=False)
        self.moveItemDownAction = QAction(self.downIcon, '向下移动剪辑', self, triggered=self.moveItemDown,# 'Move clip down'
                                          statusTip='在列表中向下移动剪辑位置', enabled=False)#'Move clip position down in list'
        self.removeItemAction = QAction(self.removeIcon, '删除选定的剪辑', self, triggered=self.removeItem,#'Remove selected clip'
                                        statusTip='从列表中删除选定的剪辑', enabled=False)#'Remove selected clip from list'
        self.removeAllAction = QAction(self.removeAllIcon, '删除所有剪辑', self, triggered=self.clearList,#'Remove all clips'
                                       statusTip='从列表中删除所有剪辑 ', enabled=False)#'Remove all clips from list'
        self.editChapterAction = QAction(self.chapterIcon, '编辑章节名称', self, triggered=self.editChapter,# 'Edit chapter name'
                                         statusTip='编辑选定的章节名称 ', enabled=False)#'Edit the selected chapter name'
        self.streamsAction = QAction(self.streamsIcon, '媒体流', self, triggered=self.selectStreams,#'Media streams'
                                     statusTip='选择要包含的媒体流 ', enabled=False)#'Select the media streams to be included'
        self.mediainfoAction = QAction(self.mediaInfoIcon, '媒体信息', self, triggered=self.mediaInfo,#'Media information'
                                       statusTip='查看当前媒体文件的技术信息详情', enabled=False)#'View technical details about current media'
        self.openProjectAction = QAction(self.openProjectIcon, '打开项目文件 ', self, triggered=self.openProject,# 'Open project file'
                                         statusTip='打开之前保存的项目文件 (*.vcp or *.edl)',#'Open a previously saved project file (*.vcp or *.edl)
                                         enabled=True)
        self.saveProjectAction = QAction(self.saveProjectIcon, '保存项目文件', self, triggered=self.saveProject,#'Save project file'
                                         statusTip='将当前工作保存到项目文件中 (*.vcp or *.edl)',#'Save current work to a project file (*.vcp or *.edl)'
                                         enabled=False)
##xn:改成KLMC  self.changelogAction = QAction(self.changelogIcon, '查看变更日志', self, triggered=self.viewChangelog,# 'View changelog'
##                                       statusTip='查看日志变更信息')#'View log of changes
        self.KLMCAction = QAction(self.KLMCIcon, '关于KLMC', self, triggered=self.viewKLMC,# 'View changelog'
                                       statusTip='KLMC视频事件，可立马查')#'View log of changes

        #xn: 增加人脸识别...
        self.faceMarkAction = QAction(self.faceMarkIcon, '人脸识别', self, triggered=self.faceMark,
                                       statusTip='在视频中搜索认识的人脸')
        self.carLicenseMarkAction = QAction(self.carLicenseMarkIcon, '车牌识别', self, triggered=self.carLicense,
                                       statusTip='按照牌照搜索车辆')
        self.pcAction = QAction(self.pcMarkIcon, '框图搜图', self, triggered=self.pcSearch,
                                       statusTip='在视频中框图搜图，找事件发生点！')
        self.litterAction = QAction(self.faceMarkIcon, '高空抛物搜索', self, triggered=self.litterMark,
                                       statusTip='在监控视频中，查找高空抛物线索')
        #xn:--------------------------------------
        
        self.viewLogsAction = QAction(self.viewLogsIcon, '查看日志文件', self, triggered=VideoCutter.viewLogs,#'View log file''View log of changes'
                                      statusTip='查看应用程序的日志文件')
        self.updateCheckAction = QAction(self.updateCheckIcon, '检查更新...', self,# 'Check for updates...'
                                         statusTip='检查应用程序更新', triggered=self.updater.check)#'Check for application updates'
        self.aboutQtAction = QAction('关于 Qt', self, triggered=qApp.aboutQt, statusTip='关于 Qt')#'About Qt' 'About Qt'
        self.aboutAction = QAction('关于{}'.format(qApp.applicationName()), self, triggered=self.aboutApp,#'About {}'
                                   statusTip='关于{}'.format(qApp.applicationName()))#'About {}'
        self.keyRefAction = QAction(self.keyRefIcon, '键盘快捷键 ', self, triggered=self.showKeyRef,# 'Keyboard shortcuts'
                                    statusTip='查看快捷键绑定 ')#'View shortcut key bindings'
        self.settingsAction = QAction(self.settingsIcon, '设置', self, triggered=self.showSettings,#'Settings'
                                      statusTip='配置应用程序设置')#'Configure application settings'
        self.fullscreenAction = QAction(self.fullscreenIcon, '切换全屏', self, triggered=self.toggleFullscreen,# 'Toggle fullscreen'
                                        statusTip='切换全屏显示模式', enabled=False)#'Toggle fullscreen display mode'
        self.quitAction = QAction(self.quitIcon, '退出', self, triggered=self.parent.close,#'Quit'
                                  statusTip='退出应用程序')#'Quit the application'

    @property
    def _filtersMenu(self) -> QMenu:
        menu = QMenu('视频滤镜', self)#video filters
        self.blackdetectAction = VCFilterMenuAction(QPixmap(':/images/blackdetect.png'), '黑色检测',#'BLACKDETECT'
                                                    '通过黑色帧检测创建剪辑，',#'Create clips via black frame detection'
                                                    '有助于跳过广告或检测场景转换',# 'Useful for skipping commercials or detecting scene transitions'
                                                    self)
        if sys.platform == 'darwin':
            self.blackdetectAction.triggered.connect(lambda: self.configFilters(VideoFilter.BLACKDETECT),
                                                     Qt.QueuedConnection)
        else:
            self.blackdetectAction.triggered.connect(lambda: self.configFilters(VideoFilter.BLACKDETECT),
                                                     Qt.DirectConnection)
        self.blackdetectAction.setEnabled(False)
        menu.setIcon(self.filtersIcon)
        menu.addAction(self.blackdetectAction)
        return menu

    def _initMenus(self) -> None:
        self.appmenu.addAction(self.openProjectAction)
        self.appmenu.addAction(self.saveProjectAction)
        self.appmenu.addSeparator()
        #xn: 增加人脸识别...
        self.appmenu.addAction(self.faceMarkAction)
        self.appmenu.addAction(self.carLicenseMarkAction)
        self.appmenu.addAction(self.pcAction)
        self.appmenu.addAction(self.litterAction)
        #xn:---------------------------------------------

        self.appmenu.addMenu(self._filtersMenu)
        self.appmenu.addSeparator()
        self.appmenu.addAction(self.fullscreenAction)
        self.appmenu.addAction(self.streamsAction)
        self.appmenu.addAction(self.mediainfoAction)
        self.appmenu.addAction(self.keyRefAction)
        self.appmenu.addSeparator()
        self.appmenu.addAction(self.settingsAction)
        self.appmenu.addSeparator()
        self.appmenu.addAction(self.viewLogsAction)
        ##xn:self.appmenu.addAction(self.updateCheckAction)
        self.appmenu.addSeparator()
        ##xn:self.appmenu.addAction(self.changelogAction)
        self.appmenu.addAction(self.KLMCAction)

        self.appmenu.addAction(self.aboutQtAction)
        self.appmenu.addAction(self.aboutAction)
        self.appmenu.addSeparator()
        self.appmenu.addAction(self.quitAction)

        self.clipindex_contextmenu.addAction(self.editChapterAction)
        self.clipindex_contextmenu.addSeparator()
        self.clipindex_contextmenu.addAction(self.moveItemUpAction)
        self.clipindex_contextmenu.addAction(self.moveItemDownAction)
        self.clipindex_contextmenu.addSeparator()
        self.clipindex_contextmenu.addAction(self.removeItemAction)
        self.clipindex_contextmenu.addAction(self.removeAllAction)

        self.clipindex_removemenu.addActions([self.removeItemAction, self.removeAllAction])
        self.clipindex_removemenu.aboutToShow.connect(self.initRemoveMenu)

        if sys.platform in {'win32', 'darwin'}:
            self.appmenu.setStyle(QStyleFactory.create('Fusion'))
            self.clipindex_contextmenu.setStyle(QStyleFactory.create('Fusion'))
            self.clipindex_removemenu.setStyle(QStyleFactory.create('Fusion'))

    def _initClipIndexHeader(self) -> None:
        if self.indexLayout == 'left':
            self.listHeaderButtonL.setVisible(False)
            self.listHeaderButtonR.setVisible(True)
        else:
            self.listHeaderButtonL.setVisible(True)
            self.listHeaderButtonR.setVisible(False)

    @pyqtSlot()
    def setClipIndexLayout(self) -> None:
        self.indexLayout = 'left' if self.indexLayout == 'right' else 'right'
        self.settings.setValue('indexLayout', self.indexLayout)
        left = self.videoLayout.takeAt(0)
        spacer = self.videoLayout.takeAt(0)
        right = self.videoLayout.takeAt(0)
        if isinstance(left, QVBoxLayout):
            if self.indexLayout == 'left':
                self.videoLayout.addItem(left)
                self.videoLayout.addItem(spacer)
                self.videoLayout.addItem(right)
            else:
                self.videoLayout.addItem(right)
                self.videoLayout.addItem(spacer)
                self.videoLayout.addItem(left)
        else:
            if self.indexLayout == 'left':
                self.videoLayout.addItem(right)
                self.videoLayout.addItem(spacer)
                self.videoLayout.addItem(left)
            else:
                self.videoLayout.addItem(left)
                self.videoLayout.addItem(spacer)
                self.videoLayout.addItem(right)
        self._initClipIndexHeader()

    def setToolBarStyle(self, labelstyle: str = 'beside') -> None:
        buttonlist = self.toolbarGroup.findChildren(VCToolBarButton)
        [button.setLabelStyle(labelstyle) for button in buttonlist]

    def setRunningTime(self, runtime: str) -> None:
        self.runtimeLabel.setText('<div align="right">{}</div>'.format(runtime))
        self.runtimeLabel.setToolTip('总运行时间: {}'.format(runtime))#'total runtime: {}'
        self.runtimeLabel.setStatusTip('总运行时间: {}'.format(runtime))#'total running time: {}'

    def getFileDialogOptions(self) -> QFileDialog.Options:
        options = QFileDialog.HideNameFilterDetails
        if not self.nativeDialogs:
            options |= QFileDialog.DontUseNativeDialog
        # noinspection PyTypeChecker
        return options

    @pyqtSlot()
    def showSettings(self):
        settingsDialog = SettingsDialog(self.videoService, self)
        settingsDialog.exec_()

    @pyqtSlot()
    def initRemoveMenu(self):
        self.removeItemAction.setEnabled(False)
        self.removeAllAction.setEnabled(False)
        if self.cliplist.count():
            self.removeAllAction.setEnabled(True)
            if len(self.cliplist.selectedItems()):
                self.removeItemAction.setEnabled(True)

    def itemMenu(self, pos: QPoint) -> None:
        globalPos = self.cliplist.mapToGlobal(pos)
        self.editChapterAction.setEnabled(False)
        self.moveItemUpAction.setEnabled(False)
        self.moveItemDownAction.setEnabled(False)
        self.initRemoveMenu()
        index = self.cliplist.currentRow()
        if index != -1:
            if len(self.cliplist.selectedItems()):
                self.editChapterAction.setEnabled(self.createChapters)
            if not self.inCut:
                if index > 0:
                    self.moveItemUpAction.setEnabled(True)
                if index < self.cliplist.count() - 1:
                    self.moveItemDownAction.setEnabled(True)
        self.clipindex_contextmenu.exec_(globalPos)

    def editChapter(self) -> None:
        index = self.cliplist.currentRow()
        name = self.clipTimes[index][4]
        name = name if name is not None else 'Chapter {}'.format(index + 1)
        dialog = VCInputDialog(self, '编辑章节名称', '章节名称:', name)#'Edit chapter name', 'Chapter name:'
        dialog.accepted.connect(lambda: self.on_editChapter(index, dialog.input.text()))
        dialog.exec_()

    def on_editChapter(self, index: int, text: str) -> None:
        self.clipTimes[index][4] = text
        self.renderClipIndex()

    def moveItemUp(self) -> None:
        index = self.cliplist.currentRow()
        if index != -1:
            tmpItem = self.clipTimes[index]
            del self.clipTimes[index]
            self.clipTimes.insert(index - 1, tmpItem)
            self.showText('剪辑向上移动')#'clip moved up'
            self.renderClipIndex()

    def moveItemDown(self) -> None:
        index = self.cliplist.currentRow()
        if index != -1:
            tmpItem = self.clipTimes[index]
            del self.clipTimes[index]
            self.clipTimes.insert(index + 1, tmpItem)
            self.showText('剪辑向下移动')#'clip moved down'
            self.renderClipIndex()

    def removeItem(self) -> None:
        index = self.cliplist.currentRow()
        if self.mediaAvailable:
            if self.inCut and index == self.cliplist.count() - 1:
                self.inCut = False
                self.initMediaControls()
        elif len(self.clipTimes) == 0:
            self.initMediaControls(False)
        del self.clipTimes[index]
        self.cliplist.takeItem(index)
        self.showText('删除剪辑')#'clip removed'
        self.renderClipIndex()

    def clearList(self) -> None:
        self.clipTimes.clear()
        self.cliplist.clear()
        self.showText('清除所有剪辑')#'all clips cleared'
        if self.mediaAvailable:
            self.inCut = False
            self.initMediaControls(True)
        else:
            self.initMediaControls(False)
        self.renderClipIndex()

    def projectFilters(self, savedialog: bool = False) -> str:
        if savedialog:
            return 'VidCutter Project (*.vcp);;MPlayer EDL (*.edl)'
        elif self.mediaAvailable:
            return 'Project files (*.edl *.vcp);;VidCutter Project (*.vcp);;MPlayer EDL (*.edl);;All files (*)'
        else:
            return 'VidCutter Project (*.vcp);;All files (*)'

    @staticmethod
    def mediaFilters(initial: bool = False) -> str:
        filters = 'All media files (*.{})'.format(' *.'.join(VideoService.config.filters.get('all')))
        if initial:
            return filters
        filters += ';;{};;All files (*)'.format(';;'.join(VideoService.config.filters.get('types')))
        return filters

    def openMedia(self) -> Optional[Callable]:
        cancel, callback = self.saveWarning()
        if cancel:
            if callback is not None:
                return callback()
            else:
                return
        filename, _ = QFileDialog.getOpenFileName(
            parent=self.parent,
            caption='打开媒体文件',#'Open media file'
            filter=self.mediaFilters(),
            initialFilter=self.mediaFilters(True),
            directory=(self.lastFolder if os.path.exists(self.lastFolder) else QDir.homePath()),
            options=self.getFileDialogOptions())
        if filename is not None and len(filename.strip()):
            self.lastFolder = QFileInfo(filename).absolutePath()
            self.loadMedia(filename)
        

    # noinspection PyUnusedLocal
    def openProject(self, checked: bool = False, project_file: str = None) -> Optional[Callable]:
        cancel, callback = self.saveWarning()
        if cancel:
            if callback is not None:
                return callback()
            else:
                return
        initialFilter = 'Project files (*.edl *.vcp)' if self.mediaAvailable else 'VidCutter Project (*.vcp)'
        if project_file is None:
            project_file, _ = QFileDialog.getOpenFileName(
                parent=self.parent,
                caption='打开项目文件',#'Open project file'
                filter=self.projectFilters(),
                initialFilter=initialFilter,
                directory=(self.lastFolder if os.path.exists(self.lastFolder) else QDir.homePath()),
                options=self.getFileDialogOptions())
        if project_file is not None and len(project_file.strip()):
            if project_file != os.path.join(QDir.tempPath(), self.parent.TEMP_PROJECT_FILE):
                self.lastFolder = QFileInfo(project_file).absolutePath()
            file = QFile(project_file)
            info = QFileInfo(file)
            project_type = info.suffix()
            if not file.open(QFile.ReadOnly | QFile.Text):
                QMessageBox.critical(self.parent, '打开项目文件',# 'Open project file'
                                     '无法读取项目文件 {0}:\n\n{1}'.format(project_file, file.errorString()))# 'Cannot read project file {0}:\n\n{1}'
                return
            qApp.setOverrideCursor(Qt.WaitCursor)
            self.clipTimes.clear()
            linenum = 1
            while not file.atEnd():
                # noinspection PyUnresolvedReferences
                line = file.readLine().trimmed()
                if line.length() > 0:
                    try:
                        line = line.data().decode()
                    except UnicodeDecodeError:
                        qApp.restoreOverrideCursor()
                        self.logger.error('选择的是无效的项目文件', exc_info=True)#'Invalid project file was selected'
                        sys.stderr.write('选择的是无效的项目文件')#'Invalid project file was selected'
                        QMessageBox.critical(self.parent, '无效的项目文件',# 'Invalid project file'
                                             '无法识别所选项目文件，请尝试在文本编辑器中查看此文件，以确保其有效且无无损坏。')
                        # 'Could not make sense of the selected project file. Try viewing it in a ' 'text editor to ensure it is valid and not corrupted.'
                        return
                    if project_type == 'vcp' and linenum == 1:
                        self.loadMedia(line)
                        time.sleep(1)
                    else:
                        mo = self.project_files[project_type].match(line)
                        if mo:
                            start, stop, _, chapter = mo.groups()
                            clip_start = self.delta2QTime(float(start))
                            clip_end = self.delta2QTime(float(stop))
                            clip_image = self.captureImage(self.currentMedia, clip_start)
                            if project_type == 'vcp' and self.createChapters and len(chapter):
                                chapter = chapter[1:len(chapter) - 1]
                                if not len(chapter):
                                    chapter = None
                            else:
                                chapter = None
                            self.clipTimes.append([clip_start, clip_end, clip_image, '', chapter])
                        else:
                            qApp.restoreOverrideCursor()
                            QMessageBox.critical(self.parent, '无效的项目文件',# 'Invalid project file'
                                                 'Invalid entry at line {0}:\n\n{1}'.format(linenum, line))
                            return
                linenum += 1
            self.toolbar_start.setEnabled(True)
            self.toolbar_end.setDisabled(True)
            self.seekSlider.setRestrictValue(0, False)
            self.blackdetectAction.setEnabled(True)
            self.inCut = False
            self.newproject = True
            QTimer.singleShot(2000, self.selectClip)
            qApp.restoreOverrideCursor()
            if project_file != os.path.join(QDir.tempPath(), self.parent.TEMP_PROJECT_FILE):
                self.showText('项目加载')#'project loaded'
 

            #xn: render clip list right now
            self.renderClipIndex()
            #self.seekSlider.setFocus()

    def saveProject(self, reboot: bool = False) -> None:
        if self.currentMedia is None:
            return
        if self.hasExternals():
            h2color = '#C681D5' if self.theme == 'dark' else '#642C68'
            acolor = '#EA95FF' if self.theme == 'dark' else '#441D4E'
            nosavetext = '''
                <style>
                    h2 {{
                        color: {h2color};
                        font-family: "Futura LT", sans-serif;
                        font-weight: normal;
                    }}
                    a {{
                        color: {acolor};
                        text-decoration: none;
                        font-weight: bold;
                    }}
                </style>
                <table border="0" cellpadding="6" cellspacing="0" width="350">
                    <tr>
                        <td><h2>无法保存当前文件</h2></td> 
                    </tr>
                    <tr>
                        <td>
                            <p>无法保存包含外部媒体文件的项目，删除所有外部添加的媒体
                            文件，然后再试一次。</p>
                        </td>
                    </tr>
                </table>'''.format(**locals())
            nosave = QMessageBox(QMessageBox.Critical, '无法保存项目', nosavetext, parent=self.parent)#'Cannot save project'
            nosave.setStandardButtons(QMessageBox.Ok)
            nosave.exec_()
            return
        project_file, _ = os.path.splitext(self.currentMedia)
        if reboot:
            project_save = os.path.join(QDir.tempPath(), self.parent.TEMP_PROJECT_FILE)
            ptype = 'VidCutter Project (*.vcp)'
        else:
            project_save, ptype = QFileDialog.getSaveFileName(
                parent=self.parent,
                caption='保存项目',#'Save project'
                directory='{}.vcp'.format(project_file),
                filter=self.projectFilters(True),
                initialFilter='VidCutter Project (*.vcp)',
                options=self.getFileDialogOptions())
        if project_save is not None and len(project_save.strip()):
            file = QFile(project_save)
            if not file.open(QFile.WriteOnly | QFile.Text):
                QMessageBox.critical(self.parent, '无法保存项目',#'Cannot save project'
                                     'Cannot save project file at {0}:\n\n{1}'.format(project_save, file.errorString()))
                return
            qApp.setOverrideCursor(Qt.WaitCursor)
            if ptype == 'VidCutter Project (*.vcp)':
                # noinspection PyUnresolvedReferences
                QTextStream(file) << '{}\n'.format(self.currentMedia)
            for clip in self.clipTimes:
                start_time = timedelta(hours=clip[0].hour(), minutes=clip[0].minute(), seconds=clip[0].second(),
                                       milliseconds=clip[0].msec())
                stop_time = timedelta(hours=clip[1].hour(), minutes=clip[1].minute(), seconds=clip[1].second(),
                                      milliseconds=clip[1].msec())
                if ptype == 'VidCutter Project (*.vcp)':
                    if self.createChapters:
                        chapter = '"{}"'.format(clip[4]) if clip[4] is not None else '""'
                    else:
                        #xn: chapter = ''
                        chapter = '""'
                    # noinspection PyUnresolvedReferences
                    QTextStream(file) << '{0}\t{1}\t{2}\t{3}\n'.format(self.delta2String(start_time),
                                                                       self.delta2String(stop_time), 0, chapter)
                else:
                    
                    # noinspection PyUnresolvedReferences

                    #xn:don't know why save 3 paramater not 4? QTextStream(file) << '{0}\t{1}\t{2}\n'.format(self.delta2String(start_time),
                    #                                              self.delta2String(stop_time), 0)
                    QTextStream(file) << '{0}\t{1}\t{2}\t{3}\n'.format(self.delta2String(start_time),
                                                                       self.delta2String(stop_time), 0, chapter)
            qApp.restoreOverrideCursor()
            self.projectSaved = True
            if not reboot:
                self.showText('保存项目文件')#'project file saved'

    def loadMedia(self, filename: str) -> None:
        if not os.path.isfile(filename):
            return
        self.currentMedia = filename
        self.initMediaControls(True)
        self.projectDirty, self.projectSaved = False, False
        self.cliplist.clear()
        self.clipTimes.clear()
        self.totalRuntime = 0
        self.setRunningTime(self.delta2QTime(self.totalRuntime).toString(self.runtimeformat))
        self.seekSlider.clearRegions()
        self.taskbar.init()
        self.parent.setWindowTitle('{0} - {1}'.format(qApp.applicationName(), os.path.basename(self.currentMedia)))
        if not self.mediaAvailable:
            self.videoLayout.replaceWidget(self.novideoWidget, self.videoplayerWidget)
            self.novideoWidget.hide()
            self.novideoWidget.deleteLater()
            self.videoplayerWidget.show()
            
            self.mediaAvailable = True
        try:
            self.videoService.setMedia(self.currentMedia)
            self.seekSlider.setFocus()
            self.mpvWidget.play(self.currentMedia)
        except InvalidMediaException:
            qApp.restoreOverrideCursor()
            self.initMediaControls(False)
            self.logger.error('无法加载媒体文件', exc_info=True)#'Could not load media file'
            QMessageBox.critical(self.parent, '无法加载媒体文件',# 'Could not load media file'
                                 '<h3>选定的媒体文件无效</h3><p>所有对文件有意义的尝试都失败了， '
                                 '请尝试在另一个媒体播放器中查看此文件，如果文件正常播放，则将其'
                                 '视为是本软件的一个bug。请在本软件菜单选项的链接里详细描述错误情况， '
                                 '上报当前的操作系统、视频卡、无效的媒体文件以及本软件的版本等信息。</p>')
            # '<h3>Invalid media file selected</h3><p>All attempts to make sense of the file have '
            # 'failed. Try viewing it in another media player and if it plays as expected please '
            # 'report it as a bug. Use the link in the About VidCutter menu option for details '
            # 'and make sure to include your operating system, video card, the invalid media file '
            # 'and the version of VidCutter you are currently using.</p>')
            

    def setPlayButton(self, playing: bool=False) -> None:
        #xn:self.toolbar_play.setup('{} Media'.format('Pause' if playing else 'Play'),
        self.toolbar_play.setup('{} 播放'.format('Pause' if playing else 'Play'),#'{} Media'
                                '暂停播放当前媒体文件' if playing else '播放当前加载的媒体文件',#'Pause currently playing media''Play currently loaded media'
                                True)

    def playMedia(self) -> None:
        playstate = self.mpvWidget.property('pause')
        self.setPlayButton(playstate)
        self.taskbar.setState(playstate)
        self.timeCounter.clearFocus()
        self.frameCounter.clearFocus()
        self.mpvWidget.pause()

    def showText(self, text: str, duration: int = 3, override: bool = False) -> None:
        if self.mediaAvailable:
            if not self.osdButton.isChecked() and not override:
                return
            if len(text.strip()):
                self.mpvWidget.showText(text, duration)

    def initMediaControls(self, flag: bool = True) -> None:
        self.toolbar_play.setEnabled(flag)
        self.toolbar_start.setEnabled(flag)
        self.toolbar_end.setEnabled(False)
        self.toolbar_save.setEnabled(False)
        self.streamsAction.setEnabled(flag)
        self.streamsButton.setEnabled(flag)
        self.mediainfoAction.setEnabled(flag)
        self.mediainfoButton.setEnabled(flag)
        self.fullscreenButton.setEnabled(flag)
        self.fullscreenAction.setEnabled(flag)
        self.seekSlider.clearRegions()
        self.blackdetectAction.setEnabled(flag)
        #xn: 增加人脸识别
        self.faceMarkAction.setEnabled(flag)
        self.KLMCAction.setEnabled(flag)
        
        if flag:
            self.seekSlider.setRestrictValue(0)
        else:
            self.seekSlider.setValue(0)
            self.seekSlider.setRange(0, 0)
            self.timeCounter.reset()
            self.frameCounter.reset()
        self.openProjectAction.setEnabled(flag)
        self.saveProjectAction.setEnabled(False)

    @pyqtSlot(int)
    def setPosition(self, position: int) -> None:
        if position >= self.seekSlider.restrictValue:
            self.mpvWidget.seek(position / 1000)

    @pyqtSlot(float, int)
    def on_positionChanged(self, progress: float, frame: int) -> None:
        progress *= 1000
        if self.seekSlider.restrictValue < progress or progress == 0:
            self.seekSlider.setValue(int(progress))
            self.timeCounter.setTime(self.delta2QTime(round(progress)).toString(self.timeformat))
            self.frameCounter.setFrame(frame)
            if self.seekSlider.maximum() > 0:
                self.taskbar.setProgress(float(progress / self.seekSlider.maximum()), True)

    @pyqtSlot(float, int)
    def on_durationChanged(self, duration: float, frames: int) -> None:
        duration *= 1000
        self.seekSlider.setRange(0, int(duration))
        self.timeCounter.setDuration(self.delta2QTime(round(duration)).toString(self.timeformat))
        self.frameCounter.setFrameCount(frames)

    @pyqtSlot()
    @pyqtSlot(QListWidgetItem)
    def selectClip(self, item: QListWidgetItem = None) -> None:
        # noinspection PyBroadException
        try:
            row = self.cliplist.row(item) if item is not None else 0
            if item is None:
                self.cliplist.item(row).setSelected(True)
            if not len(self.clipTimes[row][3]):
                self.seekSlider.selectRegion(row)
                self.setPosition(self.clipTimes[row][0].msecsSinceStartOfDay())
        except Exception:
            self.doPass()

    def muteAudio(self) -> None:
        if self.mpvWidget.property('mute'):
            self.showText('启用音频')#'audio enabled'
            self.muteButton.setIcon(self.unmuteIcon)
            self.muteButton.setToolTip('静音')#'Mute'
        else:
            self.showText('禁用音频')#'audio disabled'
            self.muteButton.setIcon(self.muteIcon)
            self.muteButton.setToolTip('取消静音')#'Unmute'
        self.mpvWidget.mute()

    def setVolume(self, vol: int) -> None:
        self.settings.setValue('音量', vol)#'volume'
        if self.mediaAvailable:
            self.mpvWidget.volume(vol)
            self.showText('音量：'+ str(vol))#lz: show text
        
            

    @pyqtSlot(bool)
    def toggleThumbs(self, checked: bool) -> None:
        self.seekSlider.showThumbs = checked
        self.saveSetting('timelineThumbs', checked)
        if checked:
            self.showText('启用缩略图')#'thumbnails enabled'
            self.seekSlider.initStyle()
            if self.mediaAvailable:
                self.seekSlider.reloadThumbs()
        else:
            self.showText('禁用缩略图')#'thumbnails disabled'
            self.seekSlider.removeThumbs()
            self.seekSlider.initStyle()

    @pyqtSlot(bool)
    def toggleConsole(self, checked: bool) -> None:
        if not hasattr(self, 'debugonstart'):
            self.debugonstart = os.getenv('DEBUG', False)
        if checked:
            self.mpvWidget.setLogLevel('v')
            os.environ['DEBUG'] = '1'
            self.parent.console.show()
        else:
            if not self.debugonstart:
                os.environ['DEBUG'] = '0'
                self.mpvWidget.setLogLevel('error')
            self.parent.console.hide()
        self.saveSetting('showConsole', checked)

    @pyqtSlot(bool)
    def toggleChapters(self, checked: bool) -> None:
        self.createChapters = checked
        self.saveSetting('chapters', self.createChapters)
        self.chaptersButton.setChecked(self.createChapters)
        self.showText('{}章节'.format('创建' if checked else '不创建'))#self.showText('chapters {}'.format('enabled' if checked else 'disabled'))
        if checked:
            exist = False
            for clip in self.clipTimes:
                if clip[4] is not None:
                    exist = True
                    break
            if exist:
                chapterswarn = VCMessageBox('恢复章节名称', '之前设置的章节名称',#'Restore chapter names', 'Chapter names found in memory',
                                            '要还原之前设置的章节名称吗？ ',#'Would you like to restore previously set chapter names?'
                                            buttons=QMessageBox.Yes | QMessageBox.No, parent=self)
                if chapterswarn.exec_() == QMessageBox.No:
                    for clip in self.clipTimes:
                        clip[4] = None
        self.renderClipIndex()

    @pyqtSlot(bool)
    def toggleSmartCut(self, checked: bool) -> None:
        self.smartcut = checked
        self.saveSetting('smartcut', self.smartcut)
        self.smartcutButton.setChecked(self.smartcut)
        self.showText('{}智能剪辑'.format('启用' if checked else '不启用'))#self.showText('SmartCut {}'.format('enabled' if checked else 'disabled'))

    @pyqtSlot(list)
    def addScenes(self, scenes: List[list]) -> None:
        if len(scenes):
            [
                self.clipTimes.append([scene[0], scene[1], self.captureImage(self.currentMedia, scene[0]), '', None])
                for scene in scenes if len(scene)
            ]
            self.renderClipIndex()
        self.filterProgressBar.done(VCProgressDialog.Accepted)

    @pyqtSlot(VideoFilter)
    def configFilters(self, name: VideoFilter) -> None:
        if name == VideoFilter.BLACKDETECT:
            desc = '<p>Detect video intervals that are (almost) completely black. Can be useful to detect chapter ' \
                   'transitions, commercials, or invalid recordings. You can set the minimum duration of ' \
                   'a detected black interval above to adjust the sensitivity.</p>' \
                   '<p><b>WARNING:</b> 根据源媒体的长度和质量，这可能需要很长时间才能完成。</p> ' 
            d = VCDoubleInputDialog(self, 'BLACKDETECT - Filter settings', 'Minimum duration for black scenes:',
                                    self.filter_settings.blackdetect.default_duration,
                                    self.filter_settings.blackdetect.min_duration, 999.9, 1, 0.1, desc, 'secs')
            d.buttons.accepted.connect(
                lambda: self.startFilters('检测场景(按ESC取消) ',
                                          partial(self.videoService.blackdetect, d.value), d))
            d.setFixedSize(435, d.sizeHint().height())
            d.exec_()

    @pyqtSlot(str, partial, QDialog)
    def startFilters(self, progress_text: str, filter_func: partial, config_dialog: QDialog) -> None:
        config_dialog.close()
        self.parent.lock_gui(True)
        self.filterProgress(progress_text)
        filter_func()

    @pyqtSlot()
    def stopFilters(self) -> None:
        self.videoService.killFilterProc()
        self.parent.lock_gui(False)

    def filterProgress(self, msg: str) -> None:
        self.filterProgressBar = VCProgressDialog(self, modal=False)
        self.filterProgressBar.finished.connect(self.stopFilters)
        self.filterProgressBar.setText(msg)
        self.filterProgressBar.setMinimumWidth(600)
        self.filterProgressBar.show()

    @pyqtSlot()
    def addExternalClips(self) -> None:
        clips, _ = QFileDialog.getOpenFileNames(
            parent=self.parent,
            caption='增加媒体文件',#'Add media files'
            filter=self.mediaFilters(),
            initialFilter=self.mediaFilters(True),
            directory=(self.lastFolder if os.path.exists(self.lastFolder) else QDir.homePath()),
            options=self.getFileDialogOptions())
        if clips is not None and len(clips):
            self.lastFolder = QFileInfo(clips[0]).absolutePath()
            filesadded = False
            cliperrors = list()
            for file in clips:
                if len(self.clipTimes) > 0:
                    lastItem = self.clipTimes[len(self.clipTimes) - 1]
                    file4Test = lastItem[3] if len(lastItem[3]) else self.currentMedia
                    if self.videoService.testJoin(file4Test, file):
                        self.clipTimes.append([QTime(0, 0), self.videoService.duration(file),
                                               self.captureImage(file, QTime(0, 0, second=2), True), file])
                        filesadded = True
                    else:
                        cliperrors.append((file,
                                           (self.videoService.lastError if len(self.videoService.lastError) else '')))
                        self.videoService.lastError = ''
                else:
                    self.clipTimes.append([QTime(0, 0), self.videoService.duration(file),
                                           self.captureImage(file, QTime(0, 0, second=2), True), file])
                    filesadded = True
            if len(cliperrors):
                detailedmsg = '''<p>The file(s) listed were found to be incompatible for inclusion to the clip index as
                            they failed to join in simple tests used to ensure their compatibility. This is
                            commonly due to differences in frame size, audio/video formats (codecs), or both.</p>
                            <p>You can join these files as they currently are using traditional video editors like
                            OpenShot, Kdenlive, ShotCut, Final Cut Pro or Adobe Premiere. They can re-encode media
                            files with mixed properties so that they are then matching and able to be joined but
                            be aware that this can be a time consuming process and almost always results in
                            degraded video quality.</p>
                            <p>Re-encoding video is not going to ever be supported by VidCutter because those tools
                            are already available for you both free and commercially.</p>'''
                errordialog = ClipErrorsDialog(cliperrors, self)
                errordialog.setDetailedMessage(detailedmsg)
                errordialog.show()
            if filesadded:
                self.showText('媒体添加到索引')#'media added to index'
                self.renderClipIndex()

    def hasExternals(self) -> bool:
        return True in [len(item[3]) > 0 for item in self.clipTimes]

    def clipStart(self) -> None:
        starttime = self.delta2QTime(self.seekSlider.value())
        self.clipTimes.append([starttime, '', self.captureImage(self.currentMedia, starttime), '', None])
        self.timeCounter.setMinimum(starttime.toString(self.timeformat))
        self.frameCounter.lockMinimum()
        self.toolbar_start.setDisabled(True)
        self.toolbar_end.setEnabled(True)
##xn:closed        self.clipindex_add.setDisabled(True)
        self.seekSlider.setRestrictValue(self.seekSlider.value(), True)
        self.blackdetectAction.setDisabled(True)
        self.inCut = True
        self.showText('视频于{}开始剪辑'.format(starttime.toString(self.timeformat))) #'clip started at {}'
        self.renderClipIndex()
        self.cliplist.scrollToBottom()

    def clipEnd(self) -> None:
        item = self.clipTimes[len(self.clipTimes) - 1]
        endtime = self.delta2QTime(self.seekSlider.value())
        if endtime.__lt__(item[0]):
            QMessageBox.critical(self.parent, '无效结束时间',#'Invalid END Time'
                                 '剪辑结束时间必须在它的开始时间之后，请再试一次 。')#'The clip end time must come AFTER it\'s start time. Please try again.'
            return
        item[1] = endtime
        self.toolbar_start.setEnabled(True)
        self.toolbar_end.setDisabled(True)
##xn:closed        self.clipindex_add.setEnabled(True)
        self.timeCounter.setMinimum()
        self.seekSlider.setRestrictValue(0, False)
        self.blackdetectAction.setEnabled(True)
        self.inCut = False
        self.showText('视频于{}结束剪辑'.format(endtime.toString(self.timeformat)))#'clip ends at {}'
        self.renderClipIndex()
        self.cliplist.scrollToBottom()
##xn:add 
        self.seekSlider.setFocus()

    @pyqtSlot()
    @pyqtSlot(bool)
    def setProjectDirty(self, dirty: bool=True) -> None:
        self.projectDirty = dirty

    # noinspection PyUnusedLocal,PyUnusedLocal,PyUnusedLocal
    @pyqtSlot(QModelIndex, int, int, QModelIndex, int)
    def syncClipList(self, parent: QModelIndex, start: int, end: int, destination: QModelIndex, row: int) -> None:
        index = row - 1 if start < row else row
        clip = self.clipTimes.pop(start)
        self.clipTimes.insert(index, clip)
        if not len(clip[3]):
            self.seekSlider.switchRegions(start, index)
        self.showText('更新剪辑顺序')#'clip order updated'
        self.renderClipIndex()

    def renderClipIndex(self) -> None:
        self.seekSlider.clearRegions()
        self.totalRuntime = 0
        externals = self.cliplist.renderClips(self.clipTimes)
        if len(self.clipTimes) and not self.inCut and externals != 1:
            self.toolbar_save.setEnabled(True)
            self.saveProjectAction.setEnabled(True)
        if self.inCut or len(self.clipTimes) == 0 or not isinstance(self.clipTimes[0][1], QTime):
            self.toolbar_save.setEnabled(False)
            self.saveProjectAction.setEnabled(False)
        self.setRunningTime(self.delta2QTime(self.totalRuntime).toString(self.runtimeformat))

    @staticmethod
    def delta2QTime(msecs: Union[float, int]) -> QTime:
        if isinstance(msecs, float):
            msecs = round(msecs * 1000)
        t = QTime(0, 0)
        return t.addMSecs(msecs)

    @staticmethod
    def qtime2delta(qtime: QTime) -> float:
        return timedelta(hours=qtime.hour(), minutes=qtime.minute(), seconds=qtime.second(),
                         milliseconds=qtime.msec()).total_seconds()

    @staticmethod
    def delta2String(td: timedelta) -> str:
        if td is None or td == timedelta.max:
            return ''
        else:
            return '%f' % (td.days * 86400 + td.seconds + td.microseconds / 1000000.)

    def captureImage(self, source: str, frametime: QTime, external: bool = False) -> QPixmap:
        return VideoService.captureFrame(self.settings, source, frametime.toString(self.timeformat), external=external)

    def saveMedia(self) -> None:
        clips = len(self.clipTimes)
        source_file, source_ext = os.path.splitext(self.currentMedia if self.currentMedia is not None
                                                   else self.clipTimes[0][3])
        suggestedFilename = '{0}_EDIT{1}'.format(source_file, source_ext)
        filefilter = '视频文件 (*{0})'.format(source_ext)#'Video files (*{0})'
        if clips > 0:
            self.finalFilename, _ = QFileDialog.getSaveFileName(
                parent=self.parent,
                caption='保存视频文件',#'Save media file'
                directory=suggestedFilename,
                filter=filefilter,
                options=self.getFileDialogOptions())
            if self.finalFilename is None or not len(self.finalFilename.strip()):
                return
            file, ext = os.path.splitext(self.finalFilename)
            if len(ext) == 0 and len(source_ext):
                self.finalFilename += source_ext
                #xn: ffmpeg cut HKVision file failed! change output file extname to .avi is working
                #self.finalFilename += '.avi'
                
            self.lastFolder = QFileInfo(self.finalFilename).absolutePath()
            self.toolbar_save.setDisabled(True)
            if not os.path.isdir(self.workFolder):
                os.mkdir(self.workFolder)
            '''xn: didn't work
            if self.smartcut:
                self.seekSlider.showProgress(6 if clips > 1 else 5)
                self.parent.lock_gui(True)
                self.videoService.smartinit(clips)
                self.smartcutter(file, source_file, source_ext)
                return
            '''
            steps = 3 if clips > 1 else 2
            self.seekSlider.showProgress(steps)
            self.parent.lock_gui(True)
            filename, filelist = '', []
            for index, clip in enumerate(self.clipTimes):
                self.seekSlider.updateProgress(index)
                if len(clip[3]):
                    filelist.append(clip[3])
                else:
                    duration = self.delta2QTime(clip[0].msecsTo(clip[1])).toString(self.timeformat)
                    #xn: ffmpeg cut HKVision file failed! change output file extname to .avi is working
                    filename = '{0}_{1}{2}'.format(file, '{0:0>2}'.format(index), source_ext)
                    #filename = '{0}_{1}{2}'.format(file, '{0:0>2}'.format(index), '.avi')
                    if not self.keepClips:
                        filename = os.path.join(self.workFolder, os.path.basename(filename))
                    filename = QDir.toNativeSeparators(filename)
                    filelist.append(filename)
                    if not self.videoService.cut(source='{0}{1}'.format(source_file, source_ext),
                                                 output=filename,
                                                 frametime=clip[0].toString(self.timeformat),
                                                 duration=duration,
                                                 allstreams=True):
                        self.completeOnError('<p>Failed to cut media file, assuming media is invalid or corrupt. '
                                             'Attempts are made to work around problematic media files, even '
                                             'when keyframes are incorrectly set or missing.</p><p>If you feel this '
                                             'is a bug in the software then please take the time to report it '
                                             'at our <a href="{}">GitHub Issues page</a> so that it can be fixed.</p>'
                                             .format(vidcutter.__bugreport__))
                        return
            self.joinMedia(filelist)
            print('xn:videocutter.savemedia:filename, filelist', filename, filelist)

    def smartcutter(self, file: str, source_file: str, source_ext: str) -> None:
        self.smartcut_monitor = Munch(clips=[], results=[], externals=0)
        for index, clip in enumerate(self.clipTimes):
            if len(clip[3]):
                self.smartcut_monitor.clips.append(clip[3])
                self.smartcut_monitor.externals += 1
                if index == len(self.clipTimes):
                    self.smartmonitor()
            else:
                filename = '{0}_{1}{2}'.format(file, '{0:0>2}'.format(index), source_ext)
                if not self.keepClips:
                    filename = os.path.join(self.workFolder, os.path.basename(filename))
                filename = QDir.toNativeSeparators(filename)
                self.smartcut_monitor.clips.append(filename)
                self.videoService.smartcut(index=index,
                                           source='{0}{1}'.format(source_file, source_ext),
                                           output=filename,
                                           start=VideoCutter.qtime2delta(clip[0]),
                                           end=VideoCutter.qtime2delta(clip[1]),
                                           allstreams=True)

    @pyqtSlot(bool, str)
    def smartmonitor(self, success: bool = None, outputfile: str = None) -> None:
        if success is not None:
            if not success:
                self.logger.error('SmartCut failed for {}'.format(outputfile))
            self.smartcut_monitor.results.append(success)
        if len(self.smartcut_monitor.results) == len(self.smartcut_monitor.clips) - self.smartcut_monitor.externals:
            if False not in self.smartcut_monitor.results:
                self.joinMedia(self.smartcut_monitor.clips)

    def joinMedia(self, filelist: list) -> None:
        if len(filelist) > 1:
            self.seekSlider.updateProgress()
            rc = False
            chapters = None
            if self.createChapters:
                chapters = []
                [
                    chapters.append(clip[4] if clip[4] is not None else 'Chapter {}'.format(index + 1))
                    for index, clip in enumerate(self.clipTimes)
                ]
            if self.videoService.isMPEGcodec(filelist[0]):
                self.logger.info('source file is MPEG based so join via MPEG-TS')
                rc = self.videoService.mpegtsJoin(filelist, self.finalFilename, chapters)
            if not rc or QFile(self.finalFilename).size() < 1000:
                self.logger.info('MPEG-TS based join failed, will retry using standard concat')
                rc = self.videoService.join(filelist, self.finalFilename, True, chapters)
            if not rc or QFile(self.finalFilename).size() < 1000:
                self.logger.info('join resulted in 0 length file, trying again without all stream mapping')
                self.videoService.join(filelist, self.finalFilename, False, chapters)
            if not self.keepClips:
                for f in filelist:
                    clip = self.clipTimes[filelist.index(f)]
                    if not len(clip[3]) and os.path.isfile(f):
                        QFile.remove(f)
            self.complete(False)
        else:
            self.complete(True, filelist[-1])

    def complete(self, rename: bool=True, filename: str=None) -> None:
        if rename and filename is not None:
            # noinspection PyCallByClass
            QFile.remove(self.finalFilename)
            # noinspection PyCallByClass
            QFile.rename(filename, self.finalFilename)
        self.videoService.finalize(self.finalFilename)
        self.seekSlider.updateProgress()
        self.toolbar_save.setEnabled(True)
        self.parent.lock_gui(False)
        self.notify = JobCompleteNotification(
            self.finalFilename,
            self.sizeof_fmt(int(QFileInfo(self.finalFilename).size())),
            self.delta2QTime(self.totalRuntime).toString(self.runtimeformat),
            self.getAppIcon(encoded=True),
            self)
        self.notify.closed.connect(self.seekSlider.clearProgress)
        self.notify.show()
        if self.smartcut:
            QTimer.singleShot(1000, self.cleanup)
        self.setProjectDirty(False)

    @pyqtSlot(str)
    def completeOnError(self, errormsg: str) -> None:
        if self.smartcut:
            self.videoService.smartabort()
            QTimer.singleShot(1500, self.cleanup)
        self.parent.lock_gui(False)
        self.seekSlider.clearProgress()
        self.toolbar_save.setEnabled(True)
        self.parent.errorHandler(errormsg)

    def cleanup(self) -> None:
        if hasattr(self.videoService, 'smartcut_jobs'):
            delattr(self.videoService, 'smartcut_jobs')
        if hasattr(self, 'smartcut_monitor'):
            delattr(self, 'smartcut_monitor')
        self.videoService.smartcutError = False

    def saveSetting(self, setting: str, checked: bool) -> None:
        self.settings.setValue(setting, 'on' if checked else 'off')

    @pyqtSlot()
    def mediaInfo(self) -> None:
        if self.mediaAvailable:
            if self.videoService.backends.mediainfo is None:
                self.logger.error('mediainfo could not be found on the system')
                QMessageBox.critical(self.parent, 'Missing mediainfo utility',
                                     'The <b>mediainfo</b> command could not be found on your system which '
                                     'is required for this feature to work.<br/><br/>Linux users can simply '
                                     'install the <b>mediainfo</b> package using the package manager you use to '
                                     'install software (e.g. apt, pacman, dnf, zypper, etc.)')
                return
            mediainfo = MediaInfo(media=self.currentMedia, parent=self)
            mediainfo.show()

    @pyqtSlot()
    def selectStreams(self) -> None:
        if self.mediaAvailable and self.videoService.streams:
            if self.hasExternals():
                nostreamstext = '''
                    <style>
                        h2 {{
                            color: {0};
                            font-family: "Futura LT", sans-serif;
                            font-weight: normal;
                        }}
                    </style>
                    <table border="0" cellpadding="6" cellspacing="0" width="350">
                        <tr>
                            <td><h2>Cannot configure stream selection</h2></td>
                        </tr>
                        <tr>
                            <td>
                                Stream selection cannot be configured when external media files
                                are added to your clip index. Remove all external files from your
                                clip index and try again.
                            </td>
                        </tr>
                    </table>'''.format('#C681D5' if self.theme == 'dark' else '#642C68')
                nostreams = QMessageBox(QMessageBox.Critical,
                                        'Stream selection is unavailable',
                                        nostreamstext,
                                        parent=self.parent)
                nostreams.setStandardButtons(QMessageBox.Ok)
                nostreams.exec_()
                return
            streamSelector = StreamSelector(self.videoService, self)
            streamSelector.show()

    def saveWarning(self) -> tuple:
        if self.mediaAvailable and self.projectDirty and not self.projectSaved:
            savewarn = VCMessageBox('提示', '项目中的修改未保存',#'Warning', 'Unsaved changes found in project'
                                    '要保存你的修改吗?', parent=self)#'Would you like to save your project?'
            savebutton = savewarn.addButton('保存', QMessageBox.YesRole)
            savewarn.addButton('不保存', QMessageBox.NoRole)#'Do not save'
            cancelbutton = savewarn.addButton('取消', QMessageBox.RejectRole)#'Cancel'
            savewarn.exec_()
            res = savewarn.clickedButton()
            if res == savebutton:
                return True, self.saveProject
            elif res == cancelbutton:
                return True, None
        return False, None

    @pyqtSlot()
    def showKeyRef(self) -> None:
        msgtext = '<img src=":/images/{}/shortcuts.png" />'.format(self.theme)
        msgbox = QMessageBox(QMessageBox.NoIcon, '键盘快捷键', msgtext, QMessageBox.Ok, self,#'Keyboard shortcuts'
                             Qt.Window | Qt.Dialog | Qt.WindowCloseButtonHint)
        msgbox.setObjectName('shortcuts')
        msgbox.setContentsMargins(10, 10, 10, 10)
        msgbox.setMinimumWidth(400 if self.parent.scale == 'LOW' else 600)
        msgbox.exec_()

    @pyqtSlot()
    def aboutApp(self) -> None:
        about = About(self.videoService, self.mpvWidget, self)
        about.exec_()

    @staticmethod
    def getAppIcon(encoded: bool=False):
        icon = QIcon.fromTheme(qApp.applicationName().lower(), QIcon(':/images/vidcutter-small.png'))
        if not encoded:
            return icon
        iconimg = icon.pixmap(82, 82).toImage()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QBuffer.WriteOnly)
        iconimg.save(buffer, 'PNG')
        base64enc = str(data.toBase64().data(), 'latin1')
        icon = 'data:vidcutter.png;base64,{}'.format(base64enc)
        return icon

    @staticmethod
    def sizeof_fmt(num: float, suffix: chr='B') -> str:
        for unit in ['', 'K', 'M', 'G', 'T', 'P', 'E', 'Z']:
            if abs(num) < 1024.0:
                return "%3.1f %s%s" % (num, unit, suffix)
            num /= 1024.0
        return "%.1f %s%s" % (num, 'Y', suffix)

##xn: 改成KLMC介绍
##    @pyqtSlot()
##    def viewChangelog(self) -> None:
##        changelog = Changelog(self)
##        changelog.exec_()
##
    @pyqtSlot()
    def viewKLMC(self) -> None:
        klmc = VCMessageBox('KLMC', '<a href="http://www.klmcsh.com">KLMC可立马查</a>',
                            'KLMC可立马查是使用AI人工智能技术和CV计算机视觉技术，快速分析搜索视频中的关键内容的一系列高效工具！\
                             人工搜索时间缩短几十倍，节省人力，提高大数据利用率。\n\
                             KLMC 最新发布的工具请关注 <a href="http://www.klmcsh.com">http://www.klmcsh.com</a> ', parent=self)
        OKButton = klmc.addButton('确认', QMessageBox.YesRole)
        
        klmc.exec_()
        #klmc.clickedButton()
        

    #xn: 增加人脸识别...------------------
    @pyqtSlot()
    def faceMark(self) -> None:
       

        desc = ('<a href="http://www.klmcsh.com">KLMC可立马查</a>是使用AI人工智能技术和CV计算机视觉技术，快速分析搜索视频中的关键内容的一系列高效工具！'\
                '搜索时间缩短几十倍，节省人力，提高大数据利用率。\n'\

                'KLMC 最新发布的工具请关注 <a href="http://www.klmcsh.com">http://www.klmcsh.com</a> 。'\
                '根据视频长度和电脑性能的不同，后台处理过程需要几分钟到几小时，\n'\
                '后台处理完成后，项目文件保存在{}.vcp\n, 要启动吗?'.format(self.currentMedia))
        
        d = VCRichInputDialog(self, '工效统计', '对象名字:','帧数设置:',
                                self.filter_settings.blackdetect.default_duration,
                                '', 999.9, 1, 0.1, desc, 'secs')

        d.buttons.accepted.connect(lambda: self.cmdFoo(d))
        d.setFixedSize(480, d.sizeHint().height())
        d.le2.setText('150')
        d.exec_()

    def cmdFoo(self, d):
        d.close()
        if d.le.text() != '' :
            cmd = 'start /b python ./klmc/ftest.py -f {} -s {} -o {}'.format(self.currentMedia, d.le2.text(), d.le.text())
        else :
            cmd = 'start /b python ./klmc/ftest.py -f {} -s {}'.format(self.currentMedia, d.le2.text())
        print(cmd)
        print('Tip:后台处理完成后，项目文件保存在{}.vcp'.format(self.currentMedia))
        os.system(cmd)
        
    
    @pyqtSlot()
    def carLicense(self) -> None:
        BackRun = VCMessageBox('提示', '在后台启动<a href="http://www.klmcsh.com">KLMC可立马查</a>人脸识别对视频打标处理',#'Warning', 'Unsaved changes found in project'
                                'KLMC可立马查是使用AI人工智能技术和CV计算机视觉技术，快速分析搜索视频中的关键内容的一系列高效工具！\
                                 搜索时间缩短几十倍，节省人力，提高大数据利用率。\n\
                                 KLMC 最新发布的工具请关注 <a href="http://www.klmcsh.com">http://www.klmcsh.com</a> 。\
                                 根据视频长度和电脑性能的不同，后台处理过程需要几分钟到几小时，\n\
                                后台处理完成后，项目文件保存在{}.vcp\n, 要启动吗?'.format(self.currentMedia), parent=self)#'Would you like to save your project?'
        OKButton = BackRun.addButton('启动', QMessageBox.YesRole)
        NoButton = BackRun.addButton('取消', QMessageBox.RejectRole)#'Cancel'
        print('lz:vidcutter.carlicense:...')

        BackRun.exec_()

        res = BackRun.clickedButton()
        if res == OKButton:
            ##xn: 前台处理模式，自动打开处理后的.vcp，前台独占
            #FaceTimeMark(self.currentMedia, 150)
            #self.openProject(False, self.currentMedia + '.vcp')
            ##xn：前台模式--------------------------------------

            ##xn: 后台处理模式            cmd = 'start /b python ./klmc/ftest.py -f {} -s {}'.format(self.currentMedia, 150)
            print(cmd)
            print('Tip:后台处理完成后，项目文件保存在{}.vcp'.format(self.currentMedia))
            os.system(cmd)
            ##xn: 后台模式--------------------------------------

            return True

        elif res == NoButton:
            return True, None
    
    @pyqtSlot()
    def pcSearch(self) -> None:

        desc = ('<a href="http://www.klmcsh.com">KLMC可立马查</a>是使用AI人工智能技术和CV计算机视觉技术，快速分析搜索视频中的关键内容的一系列高效工具！'\
                '搜索时间缩短几十倍，节省人力，提高大数据利用率。\n'\
                'KLMC 最新发布的工具请关注 <a href="http://www.klmcsh.com">http://www.klmcsh.com</a> 。'\
                '根据视频长度和电脑性能的不同，后台处理过程需要几分钟到几小时，\n'\
                '后台处理完成后，项目文件保存在{}diff.vcp\n, 要启动吗?'.format(self.currentMedia))
        
        d = VCRichInputDialog(self, '框图搜图', '开始搜索帧:','对比帧:',
                                self.filter_settings.blackdetect.default_duration,
                                '', 999.9, 1, 0.1, desc, 'secs')

        d.buttons.accepted.connect(lambda: self.cmdPCSearch(d))
        d.setFixedSize(480, d.sizeHint().height())
        d.le.setText('0') #默认从头开始搜
        d.le2.setText(str(self.mpvWidget.property('estimated-frame-number')))#默认对比当前帧
        d.exec_()

    def cmdPCSearch(self, d):
        d.close()
        if d.le.text() != '' :
            cmd = 'start /b python ./klmc/diff.py -v {} -r {} -s {}'.format(self.currentMedia, d.le2.text(), d.le.text())
        else :
            cmd = 'start /b python ./klmc/diff.py -v {} -r {}'.format(self.currentMedia, d.le2.text())
        print(cmd)
        print('Tip:后台处理完成后，项目文件保存在{}diff.vcp'.format(self.currentMedia))
        os.system(cmd)
        #diff = subprocess.Popen(cmd, shell=True)
        
    @pyqtSlot()
    def litterMark(self) -> None:
        BackRun = VCMessageBox('提示', '在后台启动<a href="http://www.klmcsh.com">KLMC可立马查</a>对目录中的所有视频分析处理,抓取抛物轨迹。',#'Warning', 'Unsaved changes found in project'
                                'KLMC可立马查是使用AI人工智能技术和CV计算机视觉技术，快速分析搜索视频中的关键内容的一系列高效工具！\
                                 人工搜索时间缩短几十倍，节省人力，提高大数据利用率。\n\
                                 KLMC 最新发布的工具请关注 <a href="http://www.klmcsh.com">http://www.klmcsh.com</a> 。\
                                 根据视频长度和电脑性能的不同，后台处理过程需要几分钟到几小时，\n\
                                后台处理完成后，项目文件保存在{}.vcp\n, 要启动吗?'.format(self.currentMedia), parent=self)#'Would you like to save your project?'
        OKButton = BackRun.addButton('启动', QMessageBox.YesRole)
        NoButton = BackRun.addButton('取消', QMessageBox.RejectRole)#'Cancel'
        BackRun.exec_()

        res = BackRun.clickedButton()
        if res == OKButton:
            ##xn: 前台处理模式，自动打开处理后的.vcp，前台独占
            #FaceTimeMark(self.currentMedia, 150)
            #self.openProject(False, self.currentMedia + '.vcp')
            ##xn：前台模式--------------------------------------

            ##xn: 后台处理模式
            cmd = 'start /b ./klmc/klmc.exe -d {}'.format(os.path.dirname(self.currentMedia))
            print(cmd)
            print('Tip:后台处理完成后，项目文件保存在{}.vcp'.format(self.currentMedia))
            os.system(cmd)
            ##xn: 后台模式--------------------------------------

            return True

        elif res == NoButton:
            return True, None
    
 
    #xn:-------------------------------
        
    @staticmethod
    @pyqtSlot()
    def viewLogs() -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(logging.getLoggerClass().root.handlers[0].baseFilename))

    @pyqtSlot()
    def toggleFullscreen(self) -> None:
        #xn:return
        if self.mediaAvailable:
            pause = self.mpvWidget.property('pause')
            mute = self.mpvWidget.property('mute')
            vol = self.mpvWidget.property('volume')
            pos = self.seekSlider.value() / 1000
            if self.mpvWidget.originalParent is not None:
                '''XN: new method, reduce screen flash. Q.SubWindow <-> Q.Window 
                self.mpvWidget.shutdown()
                sip.delete(self.mpvWidget)
                del self.mpvWidget
                self.mpvWidget = self.getMPV(parent=self, file=self.currentMedia, start=pos, pause=pause, mute=mute,
                                             volume=vol)
                self.videoplayerLayout.insertWidget(0, self.mpvWidget)
                self.mpvWidget.originalParent = None
                self.parent.show()
                '''
                self.mpvWidget.setWindowFlags(Qt.SubWindow)
                self.videoplayerLayout.insertWidget(0, self.mpvWidget)
                self.mpvWidget.originalParent = None
                self.mpvWidget.showMaximized()
               
            elif self.mpvWidget.parentWidget() != 0:
                
                '''XN:new method, reduce screen flash. Q.SubWindow <-> Q.Window 
                self.parent.hide()
                
                self.mpvWidget.shutdown()
                self.videoplayerLayout.removeWidget(self.mpvWidget)
                sip.delete(self.mpvWidget)
                del self.mpvWidget
                self.mpvWidget = self.getMPV(file=self.currentMedia, start=pos, pause=pause, mute=mute, volume=vol)
                self.mpvWidget.originalParent = self
                
                self.mpvWidget.setGeometry(qApp.desktop().screenGeometry(self))
                '''
                #self.mpvWidget.setWindowFlags(Qt.FramelessWindowHint)
                self.mpvWidget.setWindowFlags(Qt.Window)
            
                self.mpvWidget.originalParent = self
                self.mpvWidget.setGeometry(qApp.desktop().screenGeometry(self))
##                #print(qApp.desktop().screenGeometry(self))
##                
##                #self.mpvWidget.setGeometry(0,0,1440, 990)
##                #self.mpvWidget.resize(1440, 990)
                self.mpvWidget.showNormal()

##                #don't show the close button to user! self.mpvWidget.showMaximized()
##                
##                #self.mpvWidget.showFullScreen()
##                #self.mpvWidget.hide()
##                #self.mpvWidget.setFocus()
##                #self.mpvWidget.setVisible()

    def toggleOSD(self, checked: bool) -> None:     
        self.showText('{}屏幕显示'.format('启用' if checked else '不启用'), override=True)#'on-screen display {}' 'enabled''disabled'
        self.saveSetting('enableOSD', checked)

    @property
    def _osdfont(self) -> str:
        fontdb = QFontDatabase()
        return 'DejaVu Sans' if 'DejaVu Sans' in fontdb.families(QFontDatabase.Latin) else 'Noto Sans'

    def doPass(self) -> None:
        pass

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.mediaAvailable:

            if event.key() in {Qt.Key_Space, Qt.Key_P}: #xn: add Key_P 
                self.playMedia()
                return

            if event.key() == Qt.Key_Escape and self.isFullScreen():
                self.toggleFullscreen()
                return

            if event.key() in {Qt.Key_F, Qt.Key_Escape}:  
                self.toggleFullscreen()
                return

            if event.key() in {Qt.Key_Z, Qt.Key_X}:#lz: add Key_X & Key_Z for zoom in & out
                zoom = self.mpvWidget.property('video-zoom')
                print('lz:videocutter.py zoom:' ,zoom)
                if event.key() == Qt.Key_X and zoom < 4:
                    zoom += 0.5 
                    self.mpvWidget.option('video-zoom', str(zoom))
                    self.showText('缩放比例：'+ '{:.2f}'.format(2**zoom) + 'x')

                if event.key() == Qt.Key_Z and zoom > -4:
                    zoom -= 0.5 
                    self.mpvWidget.option('video-zoom', str(zoom))
                    self.showText('缩放比例：'+ '{:.2f}'.format(2**zoom) + 'x')

                return

            if event.key() in {Qt.Key_A, Qt.Key_D}:#lz: add Key_A & Key_D for pan move on X axis
                panX = self.mpvWidget.property('video-pan-x')
                #print('lz:videocutter.py zoom:' ,zoom)
                if event.key() == Qt.Key_D and panX < 1:
                    panX += 0.1 
                    self.mpvWidget.option('video-pan-x', str(panX))
                    #self.showText('右平移：'+ '{:.1f}'.format(panX))
                                  
                if event.key() == Qt.Key_A and panX > -1:
                    panX -= 0.1 
                    self.mpvWidget.option('video-pan-x', str(panX))
                    #self.showText('左平移：'+ '{:.1f}'.format(panX))

                return

            if event.key() in {Qt.Key_W, Qt.Key_S}:#lz: add Key_W & Key_S for pan move on Y axis
                panY = self.mpvWidget.property('video-pan-y')
                #print('lz:videocutter.py zoom:' ,zoom)
                if event.key() == Qt.Key_S and panY < 1:
                    panY += 0.1 
                    self.mpvWidget.option('video-pan-y', str(panY))
                    #self.showText('右平移：'+ '{:.1f}'.format(panY))
                                  
                if event.key() == Qt.Key_W and panY > -1:
                    panY -= 0.1 
                    self.mpvWidget.option('video-pan-y', str(panY))
                    #self.showText('左平移：'+ '{:.1f}'.format(panY))

                return
            

            if event.key() in {Qt.Key_1, Qt.Key_2}:#lz: add Key_2 & Key_1 for  increase and decrease contrast
                contrast = self.mpvWidget.property('contrast')
                if event.key() == Qt.Key_2 and contrast < 100:
                    contrast += 1 
                    self.mpvWidget.option('contrast', str(contrast))
                    self.showText('对比度：'+ str(contrast))

                if event.key() == Qt.Key_1 and contrast > -100:
                    contrast -= 1 
                    self.mpvWidget.option('contrast', str(contrast))
                    self.showText('对比度：'+ str(contrast))
                return
            
            if event.key() in {Qt.Key_3, Qt.Key_4}:#lz: add Key_4 & Key_3 for  increase and decrease brightness
                brightness = self.mpvWidget.property('brightness')
                if event.key() == Qt.Key_4 and brightness < 100:
                    brightness += 1 
                    self.mpvWidget.option('brightness', str(brightness))
                    self.showText('亮度：'+ str(brightness))

                if event.key() == Qt.Key_3 and brightness > -100:
                    brightness -= 1 
                    self.mpvWidget.option('brightness', str(brightness))
                    self.showText('亮度：'+ str(brightness))
                return
            
            if event.key() in {Qt.Key_E, Qt.Key_Q}:#lz: add Key_E & Key_Q for increase and decrease playback speed
                speed = self.mpvWidget.property('speed')
                if event.key() == Qt.Key_E and speed < 16:
                    speed *= 2
                    self.mpvWidget.option('speed', str(speed))
                    self.showText('播放速度：'+ str(speed) +'x' )

                if event.key() == Qt.Key_Q and speed > 0.125:
                    speed *= 0.5
                    self.mpvWidget.option('speed', str(speed))
                    self.showText('播放速度：'+ str(speed) +'x' )
                    
                return
            
            
            #xn: add Key_P for pause, O for OSD, D&A for speed up or down
            #xn: ;' for smaller or bigger 
            if event.key() == Qt.Key_O:
                self.enableOSD = not self.enableOSD
                self.toggleOSD(self.enableOSD)
                self.osdButton.setChecked(self.enableOSD)
                return

            if event.key() == Qt.Key_Home:
                self.setPosition(self.seekSlider.minimum())
                return

            if event.key() == Qt.Key_End:
                self.setPosition(self.seekSlider.maximum())
                return

            if event.key() == Qt.Key_Left:
                self.mpvWidget.frameBackStep()
                self.setPlayButton(False)
                return

            if event.key() == Qt.Key_Down:
                if qApp.queryKeyboardModifiers() == Qt.ShiftModifier:
                    self.mpvWidget.seek(-self.level2Seek, 'relative+exact')
                else:
                    self.mpvWidget.seek(-self.level1Seek, 'relative+exact')
                return

            if event.key() == Qt.Key_Right:
                self.mpvWidget.frameStep()
                self.setPlayButton(False)
                return

            if event.key() == Qt.Key_Up:
                if qApp.queryKeyboardModifiers() == Qt.ShiftModifier:
                    self.mpvWidget.seek(self.level2Seek, 'relative+exact')
                else:
                    self.mpvWidget.seek(self.level1Seek, 'relative+exact')
                return

            if event.key() in {Qt.Key_Return, Qt.Key_Enter} and \
                    (not self.timeCounter.hasFocus() and not self.frameCounter.hasFocus()):
                if self.toolbar_start.isEnabled():
                    self.clipStart()
                elif self.toolbar_end.isEnabled():
                    self.clipEnd()
                return
            
            if event.key() in {Qt.Key_9, Qt.Key_0}:#lz: add Key_0 & Key_9 for increase and decrease volume
                volume = self.mpvWidget.property('volume')
                if event.key() == Qt.Key_0 and volume < 100:
                    volume += 1
                    self.mpvWidget.option('volume', str(volume))
                    self.showText('音量：'+ str(volume))
                    self.volSlider.setValue(volume)
                    
                if event.key() == Qt.Key_9 and volume > 0:
                    volume -= 1
                    self.mpvWidget.option('volume', str(volume))
                    self.showText('音量：'+ str(volume))
                    self.volSlider.setValue(volume)
                return
        super(VideoCutter, self).keyPressEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        if hasattr(self, 'filterProgressBar') and self.filterProgressBar.isVisible():
            self.filterProgressBar.update()
        super(VideoCutter, self).showEvent(event)
