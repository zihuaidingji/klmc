import cv2
import os
import argparse

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
                                                       
    #FaceTimeMark(r'C:\Users\Jason\Desktop\ozmartian-vidcutter-784b029\vidcutter\klmc\office2.mp4', 100)
    FaceTimeMark(fileName, skips)
    if theOne != '':
        vcpout = fileName + theOne + '.vcp'
        findOne(fileName + '.vcp',vcpout , theOne)
    
