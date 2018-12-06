#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#Porting by renxn. 2018.12

import os
import cv2
import argparse

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


def frameDiff(videoName, min_area, threshold, path, refframe, skipFrames = 32):
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
        frameDelta = cv2.absdiff(ref, gray)
        # diff 之后的图像进行二值化，args.t亮度阀值25-55，把亮度低的滤掉了
        thresh = cv2.threshold(frameDelta, threshold, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)

        #取轮廓
        cnts = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]

        if len(cnts) == 0:
            with open(path +'diff.vcp', 'w') as f:
                f.write(path+'\n')
                f.write('{:.6f}\x09{:.6f}\x09\x30\x09"match"\n'.format(
                        videoName.get(0)/1000 - 0.1,        
                        videoName.get(0)/1000 + 0.1                    
                        ))
            
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
        
        if showWindows:
            cv2.imshow("refFrame", ref)
            cv2.imshow("Original", frame)
            cv2.imshow("Delta", frameDelta)
            cv2.imshow("Thresh", thresh)

        #cv2.waitKey(0)     
    return False


if __name__ == "__main__":
    # 创建参数解析器并解析参数
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--video", help="视频文件名")
    ap.add_argument("-a", "--min_area", type=int, default=11, help="最小比对面积")
    ap.add_argument("-t", "--threshold", type=int, default=55, help="亮度阀值")
    ap.add_argument("-p", "--playback", type=int, default=False, help="显示处理窗口")
    ap.add_argument("-r", "--refframe", type=int, help="参考帧号")

    args = vars(ap.parse_args())

    # 我们读取一个视频文件
    file = args["video"]
    camera = cv2.VideoCapture(file)

    if args['playback'] == True:
        showWindows = 1

    frameDiff(camera, args['min_area'], args['threshold'], file, args['refframe'], 0) #6秒比对一次图像
    
    camera.release()
    cv2.destroyAllWindows()

