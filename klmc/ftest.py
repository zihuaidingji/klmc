import cv2
import os
import argparse
from PyQt5.QtWidgets import (QApplication, QWidget, QMessageBox)
import sys
from vidcutter.klmc.whoru import whoIsWatching


def FaceTimeMark(videoPath, skipFrames=30):
    '''
    xn: mark at time when a face found from video
    '''
    videofile = cv2.VideoCapture(videoPath)
    with open(videoPath+'.vcp', 'w') as f:
        f.write('{}\n'.format(videoPath))

        while True:
            ret, frame = videofile.read()
            if ret:
                print('xn:ftest:',videofile.get(0))#, whoIsWatching(videofile))
                if (videofile.get(7) - videofile.get(1)) < (videofile.get(5) * 4): #cv2.VideoCapture.get(5)	帧速率
                    break
                
                f.write('{:.6f}\x09{:.6f}\x09\x30\x09"{[0]}"\n'.format(
                        videofile.get(0)/1000, #cv2.VideoCapture.get(0)	视频文件的当前位置（播放）以毫秒为单位
                        videofile.get(0)/1000 + 4,
                        whoIsWatching(videofile)
                        ))
                
                videofile.set(1, videofile.get(1) + skipFrames)

            else:
                print('EOF---------------------------------')
                break

def findOne(vcpin, vcpout, theOne):

    with open(vcpin, 'r') as f1:
        with open(vcpout, 'w') as f2:          
            f2.write(f1.readline())#lz: 复制了VCP文件的第一行即文件地址和名字
            for line in f1.readlines():#lz: 把f1文件的每一行逐行读取 把找到theOne的行 复制到f2文件
                if line.find('\'{}\''.format(theOne)) != -1 :
                    f2.write(line)
                    
def timeStats(vcpin, cvsout):
    #输入人脸识别出指定的员工
    name=[]
    with open(vcpin, 'r') as f1:
        with open(cvsout, 'w') as f2:          
            f2.write(f1.readline())#lz: 复制了VCP文件的第一行即文件地址和名字
            for line in f1.readlines():#lz: 把f1文件的每一行逐行读取 把找到theOne的行 复制到f2文件
                s = line.find('[\'')
                e = line.find('\'', s + 2)
                if s != -1:
                    name.append(line[s + 2 : e])
                    while True:
                        s = line.find(', \'', e)
                        
                        if s != -1:
                            e = line.find('\'', s + 3)
                            name.append(line[s + 3 :e])
                        else:
                            break
            print(name)
            name2=[]#录入所有人脸识别到的人到excel
            i = 0
            nameCount = 0
            for i in range(0, len(name)):
                j = 0
                for j in range(0, len(name2)):
                    if name[i] == name2[j]:
                        break
                    else:
                        j += 1
                if j == len(name2):
                    name2.append(name[i])
                i += 1
            print(name2)
            a = 0#录入所有人脸识别到的人分别出现的次数到excel
            for a in range(0, len(name2)):
                nameCount = 0
                b = 0
                for b in range(0, len(name)):
                    if name[b] == name2[a]:
                        nameCount += 1
                    b += 1
                print(name2[a], nameCount)
                f2.write(name2[a] + ',' + str(nameCount)+ '\n')
                if a != len(name2):
                    a += 1

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument("-f", "--filename", help="视频文件")
    ap.add_argument("-s", "--skips", type=int, default=30, help="间隔多少帧扫描一帧")
    ap.add_argument("-o", "--theOne", type=str, default='', help="人名")    
    args = vars(ap.parse_args())
    fileName = args["filename"]
    skips = args["skips"]
    theOne = args["theOne"]
    print(os.getcwd())
    print('start /b python ./klmc/ftest.py -f {} -s {}'.format(fileName, skips))
    print('Tip:后台处理完成后，项目文件保存在{}.vcp'.format(fileName))
    print('Tip:后台处理完成后，统计文件保存在{}timeStats.csv'.format(fileName))
                                                       
    #FaceTimeMark(r'C:\Users\Jason\Desktop\ozmartian-vidcutter-784b029\vidcutter\klmc\office2.mp4', 100)
    FaceTimeMark(fileName, skips)
    if theOne != '':
        vcpout = fileName + theOne + '.vcp'
        findOne(fileName + '.vcp',vcpout , theOne)
    csvout = fileName + 'timeStats.csv'
    timeStats(fileName + '.vcp', csvout)

    app = QApplication(sys.argv)
    BackRun = QMessageBox()
    BackRun.setText("后台<a href='http://www.klmcsh.com'>KLMC可立马查</a>图像搜索完成! 项目文件保存在{}.vcp\n, 打开项目文件查看".format(fileName))
    OKButton = BackRun.addButton('OK', QMessageBox.YesRole)
    BackRun.exec_()
