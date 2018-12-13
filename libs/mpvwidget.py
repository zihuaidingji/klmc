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

import locale
import logging
import os
import sys

from OpenGL import GL

if sys.platform == 'win32':
    from PyQt5.QtOpenGL import QGLContext
elif sys.platform == 'darwin':
    from OpenGL.GLUT import glutGetProcAddress
else:
    from OpenGL.platform import PLATFORM
    from ctypes import c_char_p, c_void_p

from PyQt5.QtCore import pyqtSignal, pyqtSlot, Qt, QEvent, QTimer
from PyQt5.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PyQt5.QtWidgets import QOpenGLWidget
from PyQt5.QtWidgets import *

import vidcutter.libs.mpv as mpv


def getProcAddress(proc: bytes) -> int:
    if sys.platform == 'win32':
        _ctx = QGLContext.currentContext()
        if _ctx is None:
            return 0
        _gpa = (_ctx.getProcAddress, proc.decode())
    elif sys.platform == 'darwin':
        _gpa = (glutGetProcAddress, proc)
    else:
        # noinspection PyUnresolvedReferences
        _getProcAddress = PLATFORM.getExtensionProcedure
        _getProcAddress.argtypes = [c_char_p]
        _getProcAddress.restype = c_void_p
        _gpa = (_getProcAddress, proc)
    return _gpa[0](_gpa[1]).__int__()


class mpvWidget(QOpenGLWidget):
    positionChanged = pyqtSignal(float, int)
    durationChanged = pyqtSignal(float, int)
    initialized = pyqtSignal(str)

    def __init__(self, parent=None, file=None, **mpv_opts):
        super(mpvWidget, self).__init__(parent)
        self.parent = parent
        self.filename = file
        #self.mpvError = mpv.MPVError
        self.originalParent = None
        self.logger = logging.getLogger(__name__)
        locale.setlocale(locale.LC_NUMERIC, 'C')

        #xn self.mpv = mpv.Context()       
        self.mpv = mpv.MPV(wid=str(int(self.winId())),log_handler=print)#xn, ytdl=True, input_default_bindings=True, input_vo_keyboard=True)

        self.option('msg-level', self.msglevel)
        self.setLogLevel('terminal-default')
        self.option('config', 'no')

        def _istr(o):
            return ('yes' if o else 'no') if isinstance(o, bool) else str(o)

        
        # do not break on non-existant properties/options
        for opt, val in mpv_opts.items():
            try:
                self.option(opt.replace('_', '-'), _istr(val))
            except mpv.MPVError:
                self.logger.warning('error setting MPV option "%s" to value "%s"' % (opt, val))
             
        self.mpv.initialize()
        

        #xn:self.opengl = self.mpv.opengl_cb_api()
        self.opengl =  mpv.MpvOpenGLCbContext()
        #self.opengl.set_update_callback(self.updateHandler)
        self.mpv.register_event_callback(self.updateHandler)
        
    
        if sys.platform == 'win32':
            try:
                self.option('gpu-context', 'angle')
            except mpv.MPVError:
                self.option('opengl-backend', 'angle')

        self.frameSwapped.connect(self.swapped, Qt.DirectConnection)

        
        #xn:self.mpv.observe_property('time-pos')
        self.mpv.observe_property('time-pos', self.eventHandler)
        
        #xn:self.mpv.observe_property('duration')
        self.mpv.observe_property('duration', self.eventHandler)
        #xn:self.mpv.observe_property('eof-reached')
        self.mpv.observe_property('eof-reached', self.eventHandler)
        
        #xn:self.mpv.set_wakeup_callback(self.eventHandler)
        #self.mpv.register_event_callback(self.eventHandler)

        if file is not None:
            self.initialized.connect(self.play)

    @property
    def msglevel(self):
        if os.getenv('DEBUG', False) or getattr(self.parent, 'verboseLogs', False):
            return 'all=v'
        else:
            return 'all=error'

    def setLogLevel(self, loglevel):
        #xn:self.mpv.set_log_level(loglevel)
        self.mpv.set_loglevel(loglevel)


    def shutdown(self):
        self.makeCurrent()
        if self.opengl:
            self.opengl.set_update_callback(None)
        #self.opengl.uninit_gl()
        self.mpv.command('quit')

    def initializeGL(self):
        if self.opengl:
            self.opengl.init_gl(None, getProcAddress)
            if self.filename is not None:
                self.initialized.emit(self.filename)

    def paintGL(self):
        if self.opengl:
            GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
            self.opengl.draw(self.defaultFramebufferObject(), self.width(), -self.height())

    @pyqtSlot()
    def swapped(self):
        if self.opengl:
            self.opengl.report_flip(0)

    #xn:def updateHandler(self):
    def updateHandler(self, event):
        if self.window().isMinimized():
            self.makeCurrent()
            self.paintGL()
            self.context().swapBuffers(self.context().surface())
            self.swapped()
            self.doneCurrent()
        else:
            self.update()

    #xn:def eventHandler(self):
    def eventHandler(self, name, value):
        ##xn:while self.mpv: #need not loop because loop already in libs.mpv._event_loop
            try:
                #print('XN:mpvwidget:eventHandler:self,event...:',self, name, value)
                '''#xn:
                event = self.mpv.wait_event(.01)
                
                if event.id in {mpv.Events.none, mpv.Events.shutdown}:
                    break
                elif event.id == mpv.Events.log_message:
                    event_log = event.data
                    log_msg = '[%s] %s' % (event_log.prefix, event_log.text.strip())
                    if event_log.level in (mpv.LogLevels.fatal, mpv.LogLevels.error):
                        self.logger.critical(log_msg)
                        if event_log.level == mpv.LogLevels.fatal or 'file format' in event_log.text:
                            self.parent.errorOccurred.emit(log_msg)
                            self.parent.initMediaControls(False)
                    else:
                        self.logger.info(log_msg)
                elif event.id == mpv.Events.property_change:
                    event_prop = event.data
                    if event_prop.name == 'eof-reached' and event_prop.data:
                        self.parent.setPlayButton(False)
                        self.parent.setPosition(0)
                    elif event_prop.name == 'time-pos':
                        # if os.getenv('DEBUG', False) or getattr(self.parent, 'verboseLogs', False):
                        #     self.logger.info('time-pos property event')
                        self.positionChanged.emit(event_prop.data, self.property('estimated-frame-number'))
                    elif event_prop.name == 'duration':
                        # if os.getenv('DEBUG', False) or getattr(self.parent, 'verboseLogs', False):
                        #     self.logger.info('duration property event')
                        self.durationChanged.emit(event_prop.data, self.property('estimated-frame-count'))
                '''
                #xn: new events handle at property_change
                
##                if event['event_id'] == 22: #MpvEventID.PROPERTY_CHANGE:
##                    pc = event['event']
##                    name, value, _fmt = pc['name'], pc['value'], pc['format']
                
                print('XN:mpvwidget:eventHandler:pc:',name, value, self.property('estimated-frame-number'))                
                if name == 'eof-reached' and value:
                    #xn: open this line will CRASH at the EOF!
                    self.parent.playMedia()
                    #self.parent.setPlayButton(False)
                    self.parent.setPosition(0)
                elif name == 'time-pos':
                    self.positionChanged.emit(value, self.property('estimated-frame-number'))
                elif name == 'duration':
                    self.durationChanged.emit(value, self.property('estimated-frame-count'))
                
            except mpv.MPVError as e:
                if e.code != -10:
                    raise e

    def showText(self, msg: str, duration: int=5, level: int=0):
        self.mpv.command('show-text', msg, duration * 1000, level)

    @pyqtSlot(str, name='ewewf', )
    def play(self, filepath) -> None:
        print("xn:play...")
        if os.path.isfile(filepath):
            self.mpv.command('loadfile', filepath, 'replace')            
            

    def frameStep(self) -> None:
        self.mpv.command('frame-step')

    def frameBackStep(self) -> None:
        self.mpv.command('frame-back-step')

    def seek(self, pos, method='absolute+exact') -> None:
        self.mpv.command('seek', pos, method)

    def pause(self) -> None:
        self.property('pause', not self.property('pause'))

    def mute(self) -> None:
        self.property('mute', not self.property('mute'))

    def volume(self, vol: int) -> None:
        self.property('volume', vol)

    def codec(self, stream: str='video') -> str:
        return self.property('{}-codec'.format(stream))

    def format(self, stream: str='video') -> str:
        return self.property('audio-codec-name' if stream == 'audio' else 'video-format')

    def version(self) -> str:
        #xn:ver = self.mpv.api_version
        ver = mpv._mpv_client_api_version()
        #return '{0}.{1}'.format(ver[0], ver[1])
        return '{0}.{1}'.format(ver[1], ver[0]) 

    def option(self, option: str, val):
        if isinstance(val, bool):
            val = 'yes' if val else 'no'
        return self.mpv.set_option(option, val)
        

    def property(self, prop: str, val=None):
        if val is None:
            #xn:return self.mpv.get_property(prop)
            return self.mpv._get_property(prop)
        else:
            if isinstance(val, bool):
                val = 'yes' if val else 'no'
            #xn:return self.mpv.set_property(prop, val)
            return self.mpv._set_property(prop, val)
    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.WindowStateChange and self.isFullScreen():
            self.option('osd-align-x', 'center')
            self.showText('Press ESC or double mouse click to exit full screen')
            QTimer.singleShot(5000, self.resetOSD)
    
    def resetOSD(self) -> None:
        self.showText(' ')
        self.option('osd-align-x', 'left')

##xn: send key press to parent to process
##    def keyPressEvent(self, event: QKeyEvent) -> None:
##        if event.key() in {Qt.Key_F, Qt.Key_Escape}:
##            event.accept()
##            if self.parent is None:
##                self.originalParent.toggleFullscreen()
##            else:
##                self.parent.toggleFullscreen()
##        elif self.isFullScreen():
##            self.originalParent.keyPressEvent(event)
##            
##        #xn: add new shortcut key binding
##        elif event.key() in {Qt.Key_P, Qt.Key_Space}:
##            event.accept()
##            self.pause()
##
##        
##        elif event.key() in {Qt.Key_Z, Qt.Key_X}:
##            #lz: add Key_Z & Key_X for zoom in & out
##            zoom = self.property('video-zoom')
##            print('lz:videocutter.py zoom:' ,zoom)
##            if event.key() == Qt.Key_Z and zoom < 4:
##                zoom += 0.5 
##                self.option('video-zoom', str(zoom))
##                self.showText('缩放比例：'+ str(zoom*100) + '%')
##
##            if event.key() == Qt.Key_X and zoom > -4:
##                zoom -= 0.5 
##                self.option('video-zoom', str(zoom))
##                self.showText('缩放比例：'+ str(zoom*100) + '%')
##        
##        elif event.key() in {Qt.Key_1, Qt.Key_2}:#lz: add Key_2 & Key_1 for  increase and decrease contrast
##            contrast = self.property('contrast')
##            if event.key() == Qt.Key_2 and contrast < 100:
##                contrast += 1 
##                self.option('contrast', str(contrast))
##                self.showText('对比度：'+ str(contrast))
##
##            if event.key() == Qt.Key_1 and contrast > -100:
##                contrast -= 1 
##                self.option('contrast', str(contrast))
##                self.showText('对比度：'+ str(contrast))
##        
##        elif event.key() in {Qt.Key_3, Qt.Key_4}:#lz: add Key_4 & Key_3 for  increase and decrease brightness
##            brightness = self.property('brightness')
##            if event.key() == Qt.Key_4 and brightness < 100:
##                brightness += 1 
##                self.option('brightness', str(brightness))
##                self.showText('亮度：'+ str(brightness))
##
##            if event.key() == Qt.Key_3 and brightness > -100:
##                brightness -= 1 
##                self.option('brightness', str(brightness))
##                self.showText('亮度：'+ str(brightness))
##        
##        elif event.key() in {Qt.Key_A, Qt.Key_D}:#lz: add Key_D & Key_A for increase and decrease playback sp
##            speed = self.property('speed')
##            if event.key() == Qt.Key_D and speed < 16:
##                speed *= 2
##                self.option('speed', str(speed))
##                self.showText('播放速度：'+ str(speed) +'x' )
##
##            if event.key() == Qt.Key_A and speed > 0.125:
##                speed *= 0.5
##                self.option('speed', str(speed))
##                self.showText('播放速度：'+ str(speed) +'x' )
##        
##        #xn: add Key_P for pause, O for OSD, D&A for speed up or down
##        #xn: ;' for smaller or bigger 
##        elif event.key() == Qt.Key_O:
##            self.parent.enableOSD = not self.parent.enableOSD
##            self.parent.toggleOSD(self.parent.enableOSD)
##            self.parent.osdButton.setChecked(self.parent.enableOSD)
##
##        elif event.key() == Qt.Key_Home:
##            self.parent.setPosition(self.parent.seekSlider.minimum())
##
##        elif event.key() == Qt.Key_End:
##            self.parent.setPosition(self.parent.seekSlider.maximum())
##
##        elif event.key() == Qt.Key_Left:
##            self.frameBackStep()
##            self.parent.setPlayButton(False)
##
##        elif event.key() == Qt.Key_Down:
##            if qApp.queryKeyboardModifiers() == Qt.ShiftModifier:
##                self.seek(-self.parent.level2Seek, 'relative+exact')
##            else:
##                self.seek(-self.parent.level1Seek, 'relative+exact')
##
##        elif event.key() == Qt.Key_Right:
##            self.frameStep()
##            self.parent.setPlayButton(False)
##
##        elif event.key() == Qt.Key_Up:
##            if qApp.queryKeyboardModifiers() == Qt.ShiftModifier:
##                self.seek(self.parent.level2Seek, 'relative+exact')
##            else:
##                self.seek(self.parent.level1Seek, 'relative+exact')
##                
##        else:
##            super(mpvWidget, self).keyPressEvent(event)

##xn: send key press to parent to process
    def keyPressEvent(self, event: QKeyEvent) -> None:

        qApp.sendEvent(self.parent, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        event.accept()
        if event.button() == Qt.LeftButton:
            if self.parent is None:
                self.originalParent.playMedia()
            else:
                self.parent.playMedia()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        event.accept()
        if self.parent is None:
            self.originalParent.toggleFullscreen()
        else:
            self.parent.toggleFullscreen()

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.parent.seekSlider.wheelEvent(event)

