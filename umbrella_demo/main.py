import cv2
import numpy as np
import math
import asyncio
import json
import websockets
import time


# =========================
# WebSocket
# =========================

connected_clients = set()


async def websocket_handler(websocket):

    connected_clients.add(websocket)

    print("網頁已連線！")

    try:
        await websocket.wait_closed()

    finally:

        connected_clients.remove(websocket)

        print("網頁已斷線")


async def send_data(data):

    if not connected_clients:
        return

    message = json.dumps(data)

    await asyncio.gather(
        *[
            client.send(message)
            for client in connected_clients
        ],
        return_exceptions=True
    )


async def websocket_server():

    server = await websockets.serve(
        websocket_handler,
        "127.0.0.1",
        8765
    )

    print("WebSocket 啟動")
    print("Port: 8765")

    await server.wait_closed()


# =========================
# 攝影機
# =========================

cap = cv2.VideoCapture(0)


if not cap.isOpened():

    print("無法開啟攝影機")

    exit()


# =========================
# 攝影機解析度
# =========================
#
# 這裡可以調整攝影機畫面大小
#
# 常見：
# 640 × 480
# 1280 × 720
# 1920 × 1080
#
# 如果攝影機不支援，
# OpenCV 可能會自動使用其他解析度。
#

CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480


cap.set(
    cv2.CAP_PROP_FRAME_WIDTH,
    CAMERA_WIDTH
)

cap.set(
    cv2.CAP_PROP_FRAME_HEIGHT,
    CAMERA_HEIGHT
)


# 讀取實際解析度
actual_width = int(
    cap.get(
        cv2.CAP_PROP_FRAME_WIDTH
    )
)

actual_height = int(
    cap.get(
        cv2.CAP_PROP_FRAME_HEIGHT
    )
)


print("攝影機啟動成功！")

print(
    f"實際攝影機解析度："
    f"{actual_width} × {actual_height}"
)

print("Camera 視窗可以自由拉大小")

print("按 Q 離開")


# =========================
# 設定
# =========================

SMOOTHING = 0.2


# 偵測不到完整 3 點時，
# 暫時保留雨傘的時間

LOST_TIMEOUT = 3.0


red_smooth_x = None
red_smooth_size = None


blue_smooth_x = None
blue_smooth_size = None


red_last_seen = 0
blue_last_seen = 0


red_active = False
blue_active = False


# =========================
# 基本計算
# =========================

def distance(p1, p2):

    return math.sqrt(

        (p1[0] - p2[0]) ** 2 +

        (p1[1] - p2[1]) ** 2

    )


def calculate_center(points):

    x = sum(
        p[0]
        for p in points
    ) / len(points)


    y = sum(
        p[1]
        for p in points
    ) / len(points)


    return x, y


def calculate_size(points):

    d1 = distance(
        points[0],
        points[1]
    )


    d2 = distance(
        points[0],
        points[2]
    )


    d3 = distance(
        points[1],
        points[2]
    )


    return (
        d1 +
        d2 +
        d3
    ) / 3


def smooth_value(
    old_value,
    new_value
):

    if old_value is None:

        return new_value


    return (

        old_value *
        (1 - SMOOTHING)

        +

        new_value *
        SMOOTHING

    )


# =========================
# 找圓點
# =========================

def detect_points(mask):

    contours, _ = cv2.findContours(

        mask,

        cv2.RETR_EXTERNAL,

        cv2.CHAIN_APPROX_SIMPLE

    )


    candidates = []


    for contour in contours:

        area = cv2.contourArea(
            contour
        )


        if area < 100:
            continue


        if area > 10000:
            continue


        perimeter = cv2.arcLength(

            contour,

            True

        )


        if perimeter == 0:
            continue


        circularity = (

            4 *
            math.pi *
            area

        ) / (

            perimeter *
            perimeter

        )


        if circularity < 0.65:
            continue


        (
            x,
            y
        ), radius = cv2.minEnclosingCircle(
            contour
        )


        if radius < 5:
            continue


        if radius > 80:
            continue


        candidates.append({

            "point": (

                int(x),
                int(y)

            ),

            "area": area,

            "radius": radius

        })


    # 面積大的優先

    candidates.sort(

        key=lambda item:
            item["area"],

        reverse=True

    )


    candidates = candidates[:3]


    return [

        item["point"]

        for item in candidates

    ]


# =========================
# 啟動 WebSocket
# =========================

loop = asyncio.new_event_loop()

asyncio.set_event_loop(loop)


loop.create_task(
    websocket_server()
)


# =========================
# 主迴圈
# =========================

while True:

    loop.run_until_complete(

        asyncio.sleep(0)

    )


    ret, frame = cap.read()


    if not ret:

        print(
            "無法讀取畫面"
        )

        break


    # =========================
    # 鏡像
    # =========================

    frame = cv2.flip(
        frame,
        1
    )


    # =========================
    # 取得目前畫面尺寸
    # =========================

    frame_height, frame_width = \
        frame.shape[:2]


    # =========================
    # HSV
    # =========================

    hsv = cv2.cvtColor(

        frame,

        cv2.COLOR_BGR2HSV

    )


    # =========================
    # 紅色
    # =========================

    lower_red1 = np.array([

        0,
        150,
        80

    ])


    upper_red1 = np.array([

        10,
        255,
        255

    ])


    lower_red2 = np.array([

        170,
        150,
        80

    ])


    upper_red2 = np.array([

        180,
        255,
        255

    ])


    red_mask1 = cv2.inRange(

        hsv,

        lower_red1,

        upper_red1

    )


    red_mask2 = cv2.inRange(

        hsv,

        lower_red2,

        upper_red2

    )


    red_mask = (

        red_mask1 |
        red_mask2

    )


    # =========================
    # 藍色
    # =========================

    lower_blue = np.array([

        90,
        120,
        70

    ])


    upper_blue = np.array([

        135,
        255,
        255

    ])


    blue_mask = cv2.inRange(

        hsv,

        lower_blue,

        upper_blue

    )


    # =========================
    # 偵測
    # =========================

    red_points = detect_points(

        red_mask

    )


    blue_points = detect_points(

        blue_mask

    )


    now = time.time()


    # =====================================================
    # 紅色玩家
    # =====================================================

    red_center_x = 0
    red_center_y = 0
    red_size = 0


    if len(red_points) >= 3:

        center_x, center_y = \
            calculate_center(
                red_points
            )


        size = calculate_size(
            red_points
        )


        red_smooth_x = smooth_value(

            red_smooth_x,

            center_x

        )


        red_smooth_size = smooth_value(

            red_smooth_size,

            size

        )


        red_center_x = red_smooth_x

        red_center_y = center_y

        red_size = red_smooth_size


        red_last_seen = now

        red_active = True


    else:

        if (

            red_active and

            now -
            red_last_seen >
            LOST_TIMEOUT

        ):

            red_active = False


    # =====================================================
    # 藍色玩家
    # =====================================================

    blue_center_x = 0
    blue_center_y = 0
    blue_size = 0


    if len(blue_points) >= 3:

        center_x, center_y = \
            calculate_center(
                blue_points
            )


        size = calculate_size(
            blue_points
        )


        blue_smooth_x = smooth_value(

            blue_smooth_x,

            center_x

        )


        blue_smooth_size = smooth_value(

            blue_smooth_size,

            size

        )


        blue_center_x = blue_smooth_x

        blue_center_y = center_y

        blue_size = blue_smooth_size


        blue_last_seen = now

        blue_active = True


    else:

        if (

            blue_active and

            now -
            blue_last_seen >
            LOST_TIMEOUT

        ):

            blue_active = False


    # =====================================================
    # 傳給網頁
    # =====================================================

    data = {

        # =========================
        # Camera 尺寸
        # =========================

        "camera": {

            "width":
                frame_width,

            "height":
                frame_height

        },


        # =========================
        # 紅色
        # =========================

        "red": {

            "visible":
                red_active,

            "x":
                red_smooth_x
                if red_smooth_x is not None
                else 0,

            "y":
                red_center_y,

            "size":
                red_smooth_size
                if red_smooth_size is not None
                else 60

        },


        # =========================
        # 藍色
        # =========================

        "blue": {

            "visible":
                blue_active,

            "x":
                blue_smooth_x
                if blue_smooth_x is not None
                else 0,

            "y":
                blue_center_y,

            "size":
                blue_smooth_size
                if blue_smooth_size is not None
                else 60

        }

    }


    loop.run_until_complete(

        send_data(data)

    )


    # =====================================================
    # Camera 上顯示紅點
    # =====================================================

    for i, point in enumerate(
        red_points
    ):

        cv2.circle(

            frame,

            point,

            8,

            (0, 0, 255),

            -1

        )


        cv2.putText(

            frame,

            f"R{i + 1}",

            (

                point[0] + 10,

                point[1]

            ),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.7,

            (0, 255, 0),

            2

        )


        # 顯示每一點座標

        cv2.putText(

            frame,

            f"({point[0]}, {point[1]})",

            (

                point[0] + 10,

                point[1] + 25

            ),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.45,

            (0, 255, 0),

            1

        )


    # =====================================================
    # Camera 上顯示藍點
    # =====================================================

    for i, point in enumerate(
        blue_points
    ):

        cv2.circle(

            frame,

            point,

            8,

            (255, 0, 0),

            -1

        )


        cv2.putText(

            frame,

            f"B{i + 1}",

            (

                point[0] + 10,

                point[1]

            ),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.7,

            (0, 255, 0),

            2

        )


        # 顯示每一點座標

        cv2.putText(

            frame,

            f"({point[0]}, {point[1]})",

            (

                point[0] + 10,

                point[1] + 25

            ),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.45,

            (0, 255, 0),

            1

        )


    # =====================================================
    # 顯示目前解析度
    # =====================================================

    cv2.putText(

        frame,

        f"CAMERA: {frame_width} x {frame_height}",

        (20, 35),

        cv2.FONT_HERSHEY_SIMPLEX,

        0.75,

        (255, 255, 255),

        2

    )


    # =====================================================
    # 顯示紅色資訊
    # =====================================================

    red_text = (

        f"RED  "

        f"{len(red_points)}/3  "

        f"X:{red_smooth_x:.1f}  "

        f"SIZE:{red_smooth_size:.1f}"

        if red_smooth_x is not None

        else

        f"RED  "

        f"{len(red_points)}/3"

    )


    cv2.putText(

        frame,

        red_text,

        (20, 70),

        cv2.FONT_HERSHEY_SIMPLEX,

        0.65,

        (0, 0, 255),

        2

    )


    # =====================================================
    # 顯示藍色資訊
    # =====================================================

    blue_text = (

        f"BLUE  "

        f"{len(blue_points)}/3  "

        f"X:{blue_smooth_x:.1f}  "

        f"SIZE:{blue_smooth_size:.1f}"

        if blue_smooth_x is not None

        else

        f"BLUE  "

        f"{len(blue_points)}/3"

    )


    cv2.putText(

        frame,

        blue_text,

        (20, 105),

        cv2.FONT_HERSHEY_SIMPLEX,

        0.65,

        (255, 0, 0),

        2

    )


    # =====================================================
    # 顯示 Y
    # =====================================================

    if red_active:

        cv2.putText(

            frame,

            f"RED CENTER Y: {red_center_y:.1f}",

            (20, 140),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.6,

            (0, 0, 255),

            2

        )


    if blue_active:

        cv2.putText(

            frame,

            f"BLUE CENTER Y: {blue_center_y:.1f}",

            (20, 170),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.6,

            (255, 0, 0),

            2

        )


    # =====================================================
    # 顯示
    # =====================================================

    cv2.imshow(

        "Umbrella Camera",

        frame

    )


    cv2.imshow(

        "Red Mask",

        red_mask

    )


    cv2.imshow(

        "Blue Mask",

        blue_mask

    )


    # =====================================================
    # Q
    # =====================================================

    if (

        cv2.waitKey(1) & 0xFF

        == ord("q")

    ):

        break


# =========================
# 結束
# =========================

cap.release()

cv2.destroyAllWindows()