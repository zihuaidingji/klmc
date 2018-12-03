import face_recognition
import cv2
import os

# This is a demo of running face recognition on live video from your webcam. It's a little more complicated than the
# other example, but it includes some basic performance tweaks to make things run a lot faster:
#   1. Process each video frame at 1/4 resolution (though still display it at full resolution)
#   2. Only detect faces in every other frame of video.

# PLEASE NOTE: This example requires OpenCV (the `cv2` library) to be installed only to read from your webcam.
# OpenCV is *not* required to use the face_recognition library. It's only required if you want to run this
# specific demo. If you have trouble installing it, try any of the other demos that don't require it instead.

print(os.getcwd())
# Load a sample picture and learn how to recognize it.
obama_image = face_recognition.load_image_file("./klmc/whoHasKnown/renxn.png")
obama_face_encoding = face_recognition.face_encodings(obama_image)[0]

# Load a second sample picture and learn how to recognize it.
biden_image = face_recognition.load_image_file("./klmc/whoHasKnown/susan5.png")
biden_face_encoding = face_recognition.face_encodings(biden_image)[0]

# Load a second sample picture and learn how to recognize it.
biden2_image = face_recognition.load_image_file("./klmc/whoHasKnown/jason1.png")
biden2_face_encoding = face_recognition.face_encodings(biden2_image)[0]

# Load a second sample picture and learn how to recognize it.
biden3_image = face_recognition.load_image_file("./klmc/whoHasKnown/xiaofang.png")
biden3_face_encoding = face_recognition.face_encodings(biden3_image)[0]

# Load a second sample picture and learn how to recognize it.
biden4_image = face_recognition.load_image_file("./klmc/whoHasKnown/chunyan.png")
biden4_face_encoding = face_recognition.face_encodings(biden4_image)[0]

# Load a second sample picture and learn how to recognize it.
biden5_image = face_recognition.load_image_file("./klmc/whoHasKnown/james.png")
biden5_face_encoding = face_recognition.face_encodings(biden5_image)[0]

# Load a second sample picture and learn how to recognize it.
biden6_image = face_recognition.load_image_file("./klmc/whoHasKnown/laomao.jpg")
biden6_face_encoding = face_recognition.face_encodings(biden6_image)[0]

# Load a second sample picture and learn how to recognize it.
biden7_image = face_recognition.load_image_file("./klmc/whoHasKnown/yisong.jpg")
biden7_face_encoding = face_recognition.face_encodings(biden7_image)[0]

# Load a second sample picture and learn how to recognize it.
biden8_image = face_recognition.load_image_file("./klmc/whoHasKnown/qinqin.jpg")
biden8_face_encoding = face_recognition.face_encodings(biden8_image)[0]

# Create arrays of known face encodings and their names，＃renxn：增加到6个人
known_face_encodings = [
    obama_face_encoding,
    biden_face_encoding,
    biden2_face_encoding,
    biden3_face_encoding,
    biden4_face_encoding,
    biden5_face_encoding,
    biden6_face_encoding,
    biden7_face_encoding,
    biden8_face_encoding
]
known_face_names = [
    "Renxn",
    "Susan",
    "Jason",
    "Xiaofang",
    "Chunyan",
    "James",
    "Laomao",
    "Yisong",
    "Qinqin"
    
]

# Initialize some variables
face_locations = []
face_encodings = []
face_names = []
process_this_frame = True


def whoIsWatching(video_capture):
    # Get a reference to webcam #0 (the default one)
    #video_capture = cv2.VideoCapture(0)
    # Grab a single frame of video
    
    ret, frame = video_capture.read()
 
    # Resize frame of video to 1/4 size for faster face recognition processing
    small_frame = cv2.resize(frame, (0, 0), fx=1, fy=1)

    # Convert the image from BGR color (which OpenCV uses) to RGB color (which face_recognition uses)
    rgb_small_frame = small_frame[:, :, ::-1]

    # Find all the faces and face encodings in the current frame of video
    face_locations = face_recognition.face_locations(rgb_small_frame)
    face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

    face_names = []
    for face_encoding in face_encodings:
        # See if the face is a match for the known face(s) #renxn：tolerance 原来默认0.6，我改了0.5，错认低多了 
        #matches = face_recognition.compare_faces(known_face_encodings, face_encoding, tolerance=0.4)
        matches = face_recognition.face_distance(known_face_encodings, face_encoding) 
        name = "Unknown"

        # If a match was found in known_face_encodings, just use the first one.
        
        
##        if True in matches:
##            first_match_index = matches.index(True)                
##            name = known_face_names[first_match_index]
        
        #第一个不一定是最像的一个，看看哪个距离更近
        bb = matches.tolist()                       #matches是numpy array, 先转list
        first_match_index = bb.index(min(bb))       #取出list中数值最小的行号
        
        if (matches[first_match_index] <= 0.5):
            name = known_face_names[first_match_index] 

        face_names.append(name)    

    #video_capture.release()

    return face_names, face_locations


if __name__ == "__main__":
    
    # Get a reference to webcam #0 (the default one)
    video_capture = cv2.VideoCapture(0)

    while True:
        # Grab a single frame of video
        ret, frame = video_capture.read() 
        # Resize frame of video to 1/4 size for faster face recognition processing
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)

        # Convert the image from BGR color (which OpenCV uses) to RGB color (which face_recognition uses)
        rgb_small_frame = small_frame[:, :, ::-1]

        # Only process every other frame of video to save time
        if process_this_frame:
            # Find all the faces and face encodings in the current frame of video
            face_locations = face_recognition.face_locations(rgb_small_frame)
            face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

            face_names = []
            for face_encoding in face_encodings:
                # See if the face is a match for the known face(s) #renxn：tolerance 原来默认0.6，我改了0.5，错认低多了 
                #matches = face_recognition.compare_faces(known_face_encodings, face_encoding, tolerance=0.4)
                matches = face_recognition.face_distance(known_face_encodings, face_encoding) 
                name = "Unknown"

                # If a match was found in known_face_encodings, just use the first one.

                #if True in matches:
##              #      first_match_index = matches.index(True)                

                #第一个不一定是最像的一个，看看哪个距离更近
                bb = matches.tolist()                       #matches是numpy array, 先转list
                first_match_index = bb.index(min(bb))       #取出list中数值最小的行号
                    
                if (matches[first_match_index] <= 0.6):
                    name = known_face_names[first_match_index] 

                face_names.append(name)

        process_this_frame = not process_this_frame


        # Display the results
        for (top, right, bottom, left), name in zip(face_locations, face_names):
            # Scale back up face locations since the frame we detected in was scaled to 1/4 size
            top *= 4
            right *= 4
            bottom *= 4
            left *= 4

            # Draw a box around the face
            cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 255), 2)

            # Draw a label with a name below the face
            cv2.rectangle(frame, (left, bottom - 35), (right, bottom), (0, 0, 255), cv2.FILLED)
            font = cv2.FONT_HERSHEY_DUPLEX
            cv2.putText(frame, name, (left + 6, bottom - 6), font, 1.0, (255, 255, 255), 1)

        # Display the resulting image
        cv2.imshow('Video', frame)
        cv2.moveWindow('Video', 0, 0)

        # Hit 'q' on the keyboard to quit!
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Release handle to the webcam
    video_capture.release()
    cv2.destroyAllWindows()
