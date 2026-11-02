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
MIN_AREA, MAX_AREA = 90, 10000
MIN_CIRCULARITY = 0.58  # 略放寬圓形判斷，避免光線讓邊緣破碎
# 正面攝影機：三點幾何以旋轉不變的邊長比例判斷，允許 ±65° 傾斜。
MIN_TRIANGLE_SIDE = 26
MAX_TRIANGLE_SIDE = 320
MIN_HEIGHT_RATIO = 0.53       # 頂點到底邊的垂直高度 / 底邊
MAX_HEIGHT_RATIO = 1.10
MAX_SIDE_IMBALANCE = 0.22
MAX_DOT_RADIUS_RATIO = 2.0
MAX_CANDIDATES = 14
CONFIRM_FRAMES = 4           # 連續四次完整三點才正式啟用
LOST_TIMEOUT = 1.5       # 偶爾遮到圓點時保留已確認的雨傘 0.85 秒
MAX_TRACK_JUMP = 130         # 跟蹤時優先靠近上一次位置
TILT_MAX_DEGREES = 68
clients = set()

states = {
    key: {'smooth_x': None, 'smooth_y': None, 'smooth_size': None,
          'smooth_angle': None, 'center_y': 0, 'last_seen': 0.0,
          'active': False, 'valid_streak': 0, 'points': []}
    for key in COLOR_RANGES
}


def distance(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])


def identify_triangle(three):
    """以最長邊當底邊、對角點當頂點；以邊長比例判定、與畫面方向無關。"""
    p = [c['point'] for c in three]
    pairs = [(distance(p[i], p[j]), i, j) for i,j in ((0,1),(0,2),(1,2))]
    base, i, j = max(pairs)
    apex_i = 3-i-j
    left, right = p[i], p[j]
    apex = p[apex_i]
    side_a = distance(apex, left)
    side_b = distance(apex, right)
    if min(base,side_a,side_b) < MIN_TRIANGLE_SIDE or max(base,side_a,side_b) > MAX_TRIANGLE_SIDE:
        return None
    if abs(side_a-side_b) / max((side_a+side_b)/2,1) > MAX_SIDE_IMBALANCE:
        return None
    midpoint = ((left[0]+right[0])/2, (left[1]+right[1])/2)
    height = math.hypot(apex[0]-midpoint[0], apex[1]-midpoint[1])
    ratio = height/base
    if not MIN_HEIGHT_RATIO <= ratio <= MAX_HEIGHT_RATIO:
        return None
    radii = [c['radius'] for c in three]
    if max(radii)/max(min(radii),1) > MAX_DOT_RADIUS_RATIO:
        return None
    # 從底邊中點指向頂點：正上方為 0°，向右為正。
    angle = math.degrees(math.atan2(apex[0]-midpoint[0], midpoint[1]-apex[1]))
    if abs(angle) > TILT_MAX_DEGREES:
        return None
    quality = 3.0 - 3*abs(ratio-0.80) - 2*abs(side_a-side_b)/max(base,1)
    return quality, angle, apex, left, right


def detect_points(mask, state):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if not MIN_AREA <= area <= MAX_AREA:
            continue
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0 or 4*math.pi*area/(perimeter*perimeter) < MIN_CIRCULARITY:
            continue
        (x,y), radius = cv2.minEnclosingCircle(contour)
        if 5 <= radius <= 80:
            candidates.append({'area':area,'point':(int(x),int(y)),'radius':radius})
    candidates.sort(key=lambda c:c['area'], reverse=True)
    candidates = candidates[:MAX_CANDIDATES]
    best=None;best_score=-1e9
    for three in combinations(candidates,3):
        result=identify_triangle(three)
        if result is None: continue
        quality,angle,apex,left,right=result
        cx=sum(c['point'][0] for c in three)/3
        cy=sum(c['point'][1] for c in three)/3
        size=sum(distance(three[i]['point'],three[j]['point']) for i,j in ((0,1),(0,2),(1,2)))/3
        score=quality
        if state['smooth_x'] is not None:
            jump=math.hypot(cx-state['smooth_x'],cy-state['smooth_y'])
            score-=min(jump/75,5)
            if state['active'] and jump>MAX_TRACK_JUMP: continue
            score-=min(abs(size-state['smooth_size'])/90,2)
        if score>best_score:
            best_score=score;best=(apex,left,right,cx,cy,size,angle)
    return best


def smooth(old,new,alpha=SMOOTHING):
    return new if old is None else old*(1-alpha)+new*alpha


def update_state(state, result, now):
    if result is not None:
        apex,left,right,x,y,size,angle=result
        state['points']=[apex,left,right]
        state['smooth_x']=smooth(state['smooth_x'],x,0.25)
        state['smooth_y']=smooth(state['smooth_y'],y,0.25)
        state['smooth_size']=smooth(state['smooth_size'],size)
        state['smooth_angle']=smooth(state['smooth_angle'],angle,0.20)
        state['last_seen']=now
        state['valid_streak']+=1
        if state['valid_streak']>=CONFIRM_FRAMES:state['active']=True
    else:
        state['points']=[]
        state['valid_streak']=0
        # 已啟用的傘容許短暫遮擋，但遊戲開場絕不能靠殘留單點啟動。
        if now-state['last_seen']>LOST_TIMEOUT:
            state['active']=False
            state['smooth_x']=state['smooth_y']=state['smooth_size']=state['smooth_angle']=None


def make_payload(width,height):
    data={'camera':{'width':width,'height':height}}
    for key,state in states.items():
        data[key]={
            'visible':state['active'],
            'valid_points':len(state['points']),
            'x':state['smooth_x'] if state['smooth_x'] is not None else 0,
            'y':state['smooth_y'] if state['smooth_y'] is not None else 0,
            'size':state['smooth_size'] if state['smooth_size'] is not None else 60,
            'angle':state['smooth_angle'] if state['smooth_angle'] is not None else 0,
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
                    state=states[key]
                    result=detect_points(mask,state)
                    update_state(state,result,now)
                    if result is not None:
                        apex,left,right=state['points']
                        cv2.polylines(frame,[np.array([apex,left,right],dtype=np.int32)],True,BGR_DRAW[key],2)
                        for i,pt in enumerate((apex,left,right)):
                            cv2.circle(frame,pt,8,BGR_DRAW[key],-1)
                            cv2.putText(frame,f'{key[:1].upper()}{i+1}',(pt[0]+8,pt[1]),
                                        cv2.FONT_HERSHEY_SIMPLEX,.5,BGR_DRAW[key],2)
                data = make_payload(width, height)
                if clients:
                    message = json.dumps(data)
                    await asyncio.gather(*(ws.send(message) for ws in tuple(clients)), return_exceptions=True)
                cv2.putText(frame, f'CAMERA: {width} x {height}', (10, 26), cv2.FONT_HERSHEY_SIMPLEX, .65, (255,255,255), 2)
                for i, (key, state) in enumerate(states.items()):
                    pcount = len(state['points'])
                    suffix = f' X:{state["smooth_x"]:.0f} Y:{state["smooth_y"]:.0f} A:{state["smooth_angle"]:.0f}' if state['smooth_x'] is not None else ''
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
