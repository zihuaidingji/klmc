#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#Porting by renxn. 2018.12

import os
import cv2
import argparse

from PyQt5.QtWidgets import (QApplication, QWidget, QMessageBox)
import sys

#Standard pix
Pix = (640, 360)
#HD pix
#Pix = (1920, 1080)
#for high building
#Pix = (360, 640)

#Show windows or not, used between other files.
showWindows = 0

def mkdir(path):
    folder = os.path.exists(path)

    if not folder:          # 判断是否存在文件夹如果不存在则创建为文件夹
        os.makedirs(path)   # makedirs 创建文件时如果路径不存在会创建这个路径
        print("---  New folder  ---")
        return True

    else:
        print("---  The folder already exists!  ---")
        return False


def frameDiff(videoName, points, min_area, threshold, path, refframe, skipFrames = 32):
    videoName.set(1, refframe)
    _ret, ref = videoName.read()
    ref = cv2.resize(ref, Pix, interpolation = cv2.INTER_CUBIC)
    ref = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    #调整对比度
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    ref = clahe.apply(ref)
    ref = cv2.GaussianBlur(ref, (min_area, min_area), 0)

    videoName.set(1, 0) #vedio position point to beginning frame 0
    skipF = 0
    while True:
        (grabbed, frame) = videoName.read()
        #videoName.set(1, videoName.get(1) + skipFrames) #skip some frames to read
        #videoName.set(0, videoName.get(0) + 1000) #skip some frames to read

        if skipF < skipFrames:
            skipF += 1
            continue
        skipF = 0
        
        #print(videoName.get(1),videoName.get(5))
        print('makeMask function processing frame:%d/%d' %(videoName.get(1), videoName.get(7)))

        #文件结束就退出循环
        if grabbed == False:
            break

        frame = cv2.resize(frame, Pix, interpolation = cv2.INTER_CUBIC)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        #调整对比度
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        gray = clahe.apply(gray)
        gray = cv2.GaussianBlur(gray, (min_area, min_area), 0)

        # 对两帧图像进行 absdiff 操作
        #frameDelta = cv2.absdiff(ref, gray)
        refCorp = ref[points[0][1]: points[0][3], points[0][0]:points[0][2]]
        grayCorp= gray[points[0][1]: points[0][3], points[0][0]:points[0][2]]
        frameDelta = cv2.absdiff(refCorp, grayCorp)
        
        # diff 之后的图像进行二值化，args.t亮度阀值25-55，把亮度低的滤掉了
        thresh = cv2.threshold(frameDelta, threshold, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)

        if showWindows:
            cv2.imshow("refFrame", ref)
            cv2.imshow("Original", frame)
            cv2.imshow("Delta", frameDelta)
            cv2.imshow("Thresh", thresh)
            cv2.imshow("refCorp", refCorp)

        #cv2.waitKey(0)     
        #取轮廓
        cnts = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]

        if len(cnts) == 0:
            with open(path +'diff.vcp', 'w') as f:
                f.write(path+'\n')
                f.write('{:.6f}\x09{:.6f}\x09\x30\x09"match"\n'.format(
                        videoName.get(0)/1000 - 0.1,        
                        videoName.get(0)/1000 + 0.1                    
                        ))


            app = QApplication(sys.argv)
   
            BackRun = QMessageBox()
            BackRun.setText("后台<a href='http://www.klmcsh.com'>KLMC可立马查</a>图像搜索完成! 项目文件保存在{}diff.vcp\n, 打开项目文件查看".format(path))

            OKButton = BackRun.addButton('OK', QMessageBox.YesRole)
            BackRun.exec_()

            #return sys.exit(app.exec_())
            return True


##        # 遍历轮廓
##        for c in cnts:
##            if cv2.contourArea(c) > min_area :  #如果有大块不同就跳出           
##                break
##            elif c == cnts[-1]:                               #全是小不同，就是找到了
##                #如果两个Frame差别很小，就记录下
##                with open(path +'diff.vcp', 'w') as f:
##                    f.write(path+'\n')
##                    f.write('{:.6f}\x09{:.6f}\x09\x30\x09"match"\n'.format(
##                            videoName.get(0)/1000 - 0.1,        
##                            videoName.get(0)/1000 + 0.1                    
##                            ))
##                
##                return True

##            # 计算轮廓的边界框，在当前帧中画出该框, fill 0 in bounding
##            (x, y, w, h) = cv2.boundingRect(c)
##            cv2.rectangle(maskFrame, (x-5, y-5), (x + w + 5, y + h + 5), (0, 0, 0), thickness=-1)
##            #break #just save 1 contour
        
    return False

def getPoint(im, multi=False):
    im_disp = im.copy()
    im_draw = im.copy()
    window_name = "选择搜索区域."
    cv2.namedWindow(window_name)
    cv2.imshow(window_name, im_draw)

    # List containing top-left and bottom-right to crop the image.
    pts_1 = []
    pts_2 = []

    rects = []
    getPoint.mouse_down = False

    def callback(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
                if multi == False and len(pts_2) == 1:
                    print("WARN: Cannot select another object in SINGLE OBJECT TRACKING MODE.")
                    print("Delete the previously selected object using key`d` to mark a new location.")
                    return
                getPoint.mouse_down = True
                pts_1.append((x, y))
        elif event == cv2.EVENT_LBUTTONUP and getPoint.mouse_down == True:
            getPoint.mouse_down = False
            pts_2.append((x, y))
            print("Object selected at [{}, {}]".format(pts_1[-1], pts_2[-1]))
        elif event == cv2.EVENT_MOUSEMOVE and getPoint.mouse_down == True:
            im_draw = im.copy()
            cv2.rectangle(im_draw, pts_1[-1], (x, y), (255,255,255), 2)
            cv2.imshow(window_name, im_draw)

    print("鼠标选择搜索区域.")
    cv2.setMouseCallback(window_name, callback)

    print("按'p'键继续.")
    print("按'd'键重新选区域.")
    print("按'q'键退出.")

    while True:
##        # Draw the rectangular boxes on the image
##        window_name_2 = "Objects to be tracked."
##        for pt1, pt2 in zip(pts_1, pts_2):
##            rects.append([pt1[0],pt2[0], pt1[1], pt2[1]])
##            cv2.rectangle(im_disp, pt1, pt2, (255, 255, 255), 3)
##        # Display the cropped images
##        cv2.namedWindow(window_name_2, cv2.WINDOW_NORMAL)
##        cv2.imshow(window_name_2, im_disp)
        key = cv2.waitKey(30)
        if key == ord('p'):
            # Press key `s` to return the selected points
            cv2.destroyAllWindows()
            point= [(tl + br) for tl, br in zip(pts_1, pts_2)]
            corrected_point=check_point(point)
            return corrected_point
        elif key == ord('q'):
            # Press key `q` to quit the program
            print("Quitting without saving.")
            exit()
        elif key == ord('d'):
            # Press ket `d` to delete the last rectangular region
            if getPoint.mouse_down == False and pts_1:
                print("Object deleted at  [{}, {}]".format(pts_1[-1], pts_2[-1]))
                pts_1.pop()
                pts_2.pop()
                im_disp = im.copy()
            else:
                print("No object to delete.")
    cv2.destroyAllWindows()
    point= [(tl + br) for tl, br in zip(pts_1, pts_2)]
    corrected_point=check_point(point)
    return corrected_point

def check_point(points):
    out=[]
    for point in points:
        #to find min and max x coordinates
        if point[0]<point[2]:
            minx=point[0]
            maxx=point[2]
        else:
            minx=point[2]
            maxx=point[0]
        #to find min and max y coordinates
        if point[1]<point[3]:
            miny=point[1]
            maxy=point[3]
        else:
            miny=point[3]
            maxy=point[1]
        out.append((minx,miny,maxx,maxy))

    return out


if __name__ == "__main__":
    # 创建参数解析器并解析参数
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--video", help="视频文件名")
    ap.add_argument("-a", "--min_area", type=int, default=5, help="最小比对面积")
    ap.add_argument("-t", "--threshold", type=int, default=35, help="亮度阀值")
    ap.add_argument("-p", "--playback", type=int, default=False, help="显示处理窗口")
    ap.add_argument("-r", "--refframe", type=int, help="参考帧号")

    args = vars(ap.parse_args())

    # 我们读取一个视频文件
    file = args["video"]
    camera = cv2.VideoCapture(file)

    if args['playback'] == True:
        showWindows = 1
    
    camera.set(1, args['refframe'])
    _ret, img = camera.read()
    img = cv2.resize(img, Pix, interpolation = cv2.INTER_CUBIC)
    
    points = getPoint(img)
    frameDiff(camera, points, args['min_area'], args['threshold'], file, args['refframe'], 0) #6秒比对一次图像
    
    camera.release()
    cv2.destroyAllWindows()

