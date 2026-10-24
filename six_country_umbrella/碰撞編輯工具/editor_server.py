"""本機動態輪廓編輯器；只有 localhost 可以連線。"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import json, subprocess, sys, threading, webbrowser

ROOT=Path(__file__).resolve().parent
KINDS={'cat','dog','chair','knife','frog','rope','snake','lizard'}
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
    def reply(self,code,data):
        raw=json.dumps(data,ensure_ascii=False).encode('utf-8');self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)))
        self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if urlparse(self.path).path=='/api/profiles':
            p=ROOT/'collision_data.js';s=p.read_text('utf-8') if p.exists() else ''
            try:data=json.loads(s.split('=',1)[1].strip().rstrip(';')) if s else {}
            except Exception:data={}
            return self.reply(200,data)
        return super().do_GET()
    def do_POST(self):
        path=urlparse(self.path).path
        n=int(self.headers.get('Content-Length','0'))
        if n>50_000_000:return self.reply(413,{'error':'資料太大'})
        try:body=json.loads(self.rfile.read(n))
        except Exception:return self.reply(400,{'error':'無效的資料'})
        kind=body.get('type')
        if kind not in KINDS:return self.reply(400,{'error':'未知物件種類'})
        try:
            if path=='/api/process':
                src=ROOT/(kind+'.webm')
                if not src.exists():return self.reply(404,{'error':f'找不到 {kind}.webm，請把影片放進資料夾'})
                fps=int(body.get('fps',12));fps=max(4,min(24,fps))
                args=[sys.executable,str(ROOT/'extract_dynamic.py'),'--input',src.name,'--type',kind,'--fps',str(fps),'--output','collision_data.js','--preview',kind+'_dynamic_preview.png']
                p=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=180)
                if p.returncode:return self.reply(500,{'error':(p.stderr or p.stdout)[-2000:]})
                return self.reply(200,{'message':p.stdout.strip()})
            if path=='/api/save':
                poly=body.get('frames');crop=body.get('crop')
                if not isinstance(poly,list) or len(poly)>2000:return self.reply(400,{'error':'影格數量不正確'})
                for frame in poly:
                    if not isinstance(frame,list) or not 3<=len(frame)<=60:return self.reply(400,{'error':'每格須有 3–60 點'})
                    for pair in frame:
                        if not isinstance(pair,list) or len(pair)!=2 or any(not isinstance(v,(float,int)) or not -0.2<=v<=1.2 for v in pair):return self.reply(400,{'error':'頂點資料不正確'})
                f=ROOT/'collision_data.js';s=f.read_text('utf-8')
                data=json.loads(s.split('=',1)[1].strip().rstrip(';'));data[kind]['frames']=poly;data[kind]['points']=poly[0]
                f.write_text('window.COLLISION_DATA = '+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n','utf-8')
                return self.reply(200,{'message':f'{kind}: 已儲存 {len(poly)} 格的碰撞輪廓'})
            return self.reply(404,{'error':'API 不存在'})
        except Exception as e:return self.reply(500,{'error':str(e)})

if __name__=='__main__':
    httpd=ThreadingHTTPServer(('127.0.0.1',8766),Handler)
    url='http://127.0.0.1:8766/dynamic_editor.html'
    print('動態碰撞編輯器：'+url,flush=True)
    threading.Timer(1,lambda:webbrowser.open(url)).start()
    try:httpd.serve_forever()
    except KeyboardInterrupt:pass
