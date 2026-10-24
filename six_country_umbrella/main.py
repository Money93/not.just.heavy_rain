import asyncio
import json
import math
from itertools import combinations
import time

import cv2
import numpy as np
import websockets

# 六國貼紙的建議 HEX（用於選購或列印；實際偵測仍以攝影機拍攝後的 HSV 為準）
# 英國紅／希臘藍：保留原程式使用的 HSV 閾值。
# 葡萄牙黃 #FFDF00、波蘭綠 #00C853、南非紫 #A000E8、巴西橘 #FF8800。
COLOR_RANGES = {
    'red':    [((0, 115, 65), (8, 255, 255)), ((170, 115, 65), (179, 255, 255))],
    'blue':   [((85, 18, 55), (129, 255, 255))],
    'yellow': [((23, 85, 75), (36, 255, 255))],
    'green':  [((40, 75, 55), (80, 255, 255))],
    'purple': [((129, 70, 55), (166, 255, 255))],
    'orange': [((10, 110, 75), (22, 255, 255))],
}
BGR_DRAW = {
    'red': (0, 0, 255), 'blue': (255, 0, 0),
    'yellow': (0, 220, 255), 'green': (0, 220, 0),
    'purple': (220, 0, 170), 'orange': (0, 140, 255),
}
CAMERA_WIDTH, CAMERA_HEIGHT = 640, 480
SMOOTHING = 0.15
LOST_TIMEOUT = 0.45  # 暫時被手遮住時短暫保留，不再保持 3 秒幽靈雨傘
MIN_AREA, MAX_AREA = 90, 10000
MIN_CIRCULARITY = 0.58  # 略放寬圓形判斷，避免光線讓邊緣破碎
MAX_CANDIDATES = 12  # 允許同色干擾點存在，但只採用通過三角形驗證的組合
# 三點形狀：一點在上，兩點在下，底邊接近水平（可容許傘輕微傾斜）
MIN_TRIANGLE_SIDE = 35   # 攝影機 640x480 的初始參考值，可依實際距離調整
MAX_TRIANGLE_SIDE = 310
MIN_BASE_RATIO = 0.65  # 底邊寬度 / 兩側平均長度
MAX_BASE_RATIO = 1.65
MIN_HEIGHT_RATIO = 0.45 # 三角形高度 / 底邊寬度
MAX_HEIGHT_RATIO = 1.65
MAX_BASE_TILT = 0.38    # 底部兩點的高度差 / 底邊寬度
MAX_SIDE_IMBALANCE = 0.38  # 左右兩腰差異比例
MAX_DOT_RADIUS_RATIO = 2.0 # 三點圓的大小不得差太多
clients = set()

states = {
    key: {'smooth_x': None, 'smooth_size': None, 'center_y': 0,
          'last_seen': 0.0, 'active': False, 'points': []}
    for key in COLOR_RANGES
}


def distance(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])


def triangle_score(three):
    """回傳幾何得分，或 None（非圖中上1下2的三角形）。"""
    pts = sorted(three, key=lambda c: c['point'][1])
    apex = pts[0]
    lower = sorted(pts[1:], key=lambda c: c['point'][0])
    left, right = lower
    top = apex['point']
    a, b = left['point'], right['point']
    base = distance(a, b)
    side_l, side_r = distance(top, a), distance(top, b)
    mean_side = (side_l + side_r) / 2
    if min(base, side_l, side_r) < MIN_TRIANGLE_SIDE:
        return None
    if max(base, side_l, side_r) > MAX_TRIANGLE_SIDE:
        return None
    if not MIN_BASE_RATIO <= base / mean_side <= MAX_BASE_RATIO:
        return None
    if abs(side_l - side_r) / mean_side > MAX_SIDE_IMBALANCE:
        return None
    if abs(a[1] - b[1]) / base > MAX_BASE_TILT:
        return None
    height = ((a[1] + b[1]) / 2 - top[1])
    if not MIN_HEIGHT_RATIO <= height / base <= MAX_HEIGHT_RATIO:
        return None
    # 頂點必須大致落在底部兩點之間；允許稍微偏移
    mid_x = (a[0] + b[0]) / 2
    if abs(top[0] - mid_x) / base > 0.32:
        return None
    radii = [c['radius'] for c in three]
    if max(radii) / max(min(radii), 1) > MAX_DOT_RADIUS_RATIO:
        return None
    # 越像圖中的等腰三角形，分數越高；偏好大小接近的圓點
    return (3.0 - abs(side_l-side_r)/mean_side
            - abs(a[1]-b[1])/base
            - 0.5 * abs(top[0]-mid_x)/base
            - 0.25 * (max(radii)/min(radii)-1))


def detect_points(mask, previous_x=None, previous_size=None):
    """從所有同色候選中尋找有效三角形，而不是取最大的三點。"""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if not MIN_AREA <= area <= MAX_AREA:
            continue
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0 or 4 * math.pi * area / (perimeter * perimeter) < MIN_CIRCULARITY:
            continue
        (x, y), radius = cv2.minEnclosingCircle(contour)
        if 5 <= radius <= 80:
            candidates.append({'area': area, 'point': (int(x), int(y)), 'radius': radius})
    candidates.sort(key=lambda c: c['area'], reverse=True)
    candidates = candidates[:MAX_CANDIDATES]
    best_points, best_score = [], float('-inf')
    for three in combinations(candidates, 3):
        score = triangle_score(three)
        if score is None:
            continue
        center_x = sum(c['point'][0] for c in three) / 3
        size = sum(distance(three[i]['point'], three[j]['point'])
                   for i, j in ((0,1),(0,2),(1,2))) / 3
        # 保持目前追蹤的雨傘優先，避免有雜點時突然跳到另一組
        if previous_x is not None:
            score -= min(abs(center_x - previous_x) / 200, 2)
        if previous_size is not None:
            score -= min(abs(size - previous_size) / 150, 1)
        if score > best_score:
            best_score = score
            best_points = [c['point'] for c in three]
    return best_points


def update_state(state, points, now):
    state['points'] = points
    if len(points) == 3:
        x = sum(p[0] for p in points) / 3
        y = sum(p[1] for p in points) / 3
        size = sum(distance(points[i], points[j]) for i, j in ((0,1),(0,2),(1,2))) / 3
        state['smooth_x'] = x if state['smooth_x'] is None else (1-SMOOTHING)*state['smooth_x']+SMOOTHING*x
        state['smooth_size'] = size if state['smooth_size'] is None else (1-SMOOTHING)*state['smooth_size']+SMOOTHING*size
        state['center_y'] = y
        state['last_seen'] = now
        state['active'] = True
    elif state['active'] and now-state['last_seen']>LOST_TIMEOUT:
        state['active'] = False
        state['smooth_x'] = None
        state['smooth_size'] = None


def make_payload(width, height):
    data = {'camera': {'width': width, 'height': height}}
    for key, state in states.items():
        data[key] = {
            'visible': state['active'],
            'x': state['smooth_x'] if state['smooth_x'] is not None else 0,
            'y': state['center_y'],
            'size': state['smooth_size'] if state['smooth_size'] is not None else 60,
        }
    return data


async def handle_client(websocket):
    clients.add(websocket)
    print('網頁已連線！')
    try:
        await websocket.wait_closed()
    finally:
        clients.discard(websocket)
        print('網頁已斷線')


async def main():
    # WebSocket 和攝影機在同一個 asyncio 迴圈中運作，不影響即時傳送。
    async with websockets.serve(handle_client, '127.0.0.1', 8765):
        print('六國 WebSocket 啟動：ws://127.0.0.1:8765')
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print('無法開啟攝影機；請確認裝置編號或攝影機權限。')
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        print('攝影機啟動成功；按 Q 結束')
        kernel = np.ones((3, 3), np.uint8)
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    print('無法讀取攝影機畫面')
                    break
                frame = cv2.flip(frame, 1)
                height, width = frame.shape[:2]
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                now = time.time()
                for key, ranges in COLOR_RANGES.items():
                    mask = np.zeros((height, width), dtype=np.uint8)
                    for lower, upper in ranges:
                        mask = cv2.bitwise_or(mask, cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8)))
                    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
                    points = detect_points(mask, states[key]['smooth_x'], states[key]['smooth_size'])
                    state = states[key]
                    update_state(state, points, now)
                    if len(points) == 3:
                        triangle = sorted(points, key=lambda p: p[1])
                        base = sorted(triangle[1:], key=lambda p: p[0])
                        cv2.polylines(frame, [np.array([triangle[0], base[0], base[1]], dtype=np.int32)],
                                      True, BGR_DRAW[key], 2)
                        for i, point in enumerate([triangle[0], *base]):
                            cv2.circle(frame, point, 8, BGR_DRAW[key], -1)
                            cv2.putText(frame, f'{key.upper()}{i+1}', (point[0]+10, point[1]),
                                        cv2.FONT_HERSHEY_SIMPLEX, .55, BGR_DRAW[key], 2)
                data = make_payload(width, height)
                if clients:
                    message = json.dumps(data)
                    await asyncio.gather(*(ws.send(message) for ws in tuple(clients)), return_exceptions=True)
                cv2.putText(frame, f'CAMERA: {width} x {height}', (10, 26), cv2.FONT_HERSHEY_SIMPLEX, .65, (255,255,255), 2)
                for i, (key, state) in enumerate(states.items()):
                    pcount = len(state['points'])
                    suffix = f' X:{state["smooth_x"]:.0f} SIZE:{state["smooth_size"]:.0f}' if state['smooth_x'] is not None else ''
                    cv2.putText(frame, f'{key.upper()} {pcount}/3{suffix}', (10, 55+i*27), cv2.FONT_HERSHEY_SIMPLEX, .56, BGR_DRAW[key], 2)
                cv2.imshow('Umbrella Camera - Six Countries', frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                await asyncio.sleep(0.001)
        finally:
            cap.release()
            cv2.destroyAllWindows()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
