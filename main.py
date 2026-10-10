import cv2

camera = cv2.VideoCapture(0)

if not camera.isOpened():
    raise RuntimeError("Could not open the webcam")

while True:
    success, frame = camera.read()

    if not success:
        break

    cv2.imshow("Paper Plane Tracker", frame)

    # Press Q to close the window
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()