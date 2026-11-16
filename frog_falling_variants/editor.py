"""Stage-one editor, following the existing Tk control-point/worker workflow."""
import copy
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from generate import ROOT, SOURCES, read, write, generate

def main():
    app=tk.Tk(); app.title('俚雨｜雙視角關鍵姿勢審閱・第一階段')
    rigs={v:read(ROOT/f'frog_{v}'/'skeleton.json') for v in 'AB'}
    settings={v:read(ROOT/f'frog_{v}'/'keyposes.json') for v in 'AB'}
    images={v:[Image.open(ROOT/f'frog_{v}'/'keyposes'/f'pose_{chr(65+i)}.png').copy() for i in range(6)] for v in 'AB'}
    selected=tk.StringVar(value='A'); pose=tk.IntVar(value=0); limb_index=tk.IntVar(value=0)
    playing=tk.BooleanVar(value=False); advanced=tk.BooleanVar(value=False)
    status=tk.StringVar(value='第一階段：只產生六個關鍵姿勢。選擇姿勢、拖曳控制點或調整參數後重新產生。')
    top=ttk.Frame(app,padding=8); top.pack(fill='x')
    ttk.Label(top,text='編輯視角').pack(side='left')
    selector=ttk.Combobox(top,textvariable=selected,values=['A','B'],state='readonly',width=4); selector.pack(side='left',padx=5)
    ttk.Checkbutton(top,text='逐姿勢播放（非正式補間動畫）',variable=playing).pack(side='left',padx=10)
    ttk.Checkbutton(top,text='顯示可拖曳保護區／影響區頂點',variable=advanced).pack(side='left')
    area=ttk.Frame(app); area.pack()
    source_canvas=tk.Canvas(area,width=420,height=420,bg='#d9e0e8',highlightthickness=0)
    source_canvas.grid(row=1,column=0,padx=5)
    ttk.Label(area,text='原圖控制點｜root 根部、joint 關節、tip 末端').grid(row=0,column=0)
    canvases={}; photos={}; points=[]; dragging=[None]; busy=[False]; output=queue.Queue()
    for column,v in enumerate('AB',1):
        ttk.Label(area,text=f'動畫 {v}｜'+('空中失衡' if v=='A' else '漂浮翻動')).grid(row=0,column=column)
        canvases[v]=tk.Canvas(area,width=350,height=350,bg='white',highlightthickness=1,highlightbackground='#ccd4df')
        canvases[v].grid(row=1,column=column,padx=5)
    source_images={v:Image.open(SOURCES[v]).convert('RGBA') for v in 'AB'}
    zoom={v:min(400/source_images[v].width,400/source_images[v].height) for v in 'AB'}
    source_photos={v:ImageTk.PhotoImage(im.resize((round(im.width*zoom[v]),round(im.height*zoom[v])),Image.Resampling.LANCZOS)) for v,im in source_images.items()}
    colors=['#e11d48','#2563eb','#059669','#9333ea']
    def screen(p): return [p[0]*zoom[selected.get()]+10,p[1]*zoom[selected.get()]+10]
    def draw_rig():
        v=selected.get(); rig=rigs[v]; c=source_canvas; c.delete('all'); points.clear()
        c.create_image(10,10,image=source_photos[v],anchor='nw')
        def point(obj,key,color,label):
            p=screen(obj[key]); c.create_oval(p[0]-5,p[1]-5,p[0]+5,p[1]+5,fill=color,outline='white')
            c.create_text(p[0]+7,p[1]-9,text=label,fill=color,anchor='w'); points.append((obj,key))
        for i,l in enumerate(rig['limbs']):
            c.create_line(*[x for k in ('root','joint','tip') for x in screen(l[k])],fill=colors[i],width=2)
            for k in ('root','joint','tip'): point(l,k,colors[i],f'{i+1}:{k}')
        point(rig,'body_center','#ca8a04','中心')
        if advanced.get():
            for polygon,color in ((rig['torso'],'#eab308'),(rig['limbs'][limb_index.get()]['region'],'#f97316')):
                c.create_polygon(*[x for p in polygon for x in screen(p)],fill='',outline=color,width=2)
                for j in range(len(polygon)): point(polygon,j,color,str(j))
    def press(e):
        dragging[0]=None
        candidates=[]
        for obj,key in points:
            x,y=screen(obj[key]); dist=(x-e.x)**2+(y-e.y)**2
            if dist<100: candidates.append((dist,obj,key))
        if candidates:
            _,obj,key=min(candidates,key=lambda item:item[0]); dragging[0]=(obj,key)
    def drag(e):
        if dragging[0] and not busy[0]:
            obj,key=dragging[0]; v=selected.get(); im=source_images[v]
            obj[key]=[round(max(0,min(im.width-1,(e.x-10)/zoom[v])),2),round(max(0,min(im.height-1,(e.y-10)/zoom[v])),2)]
            draw_rig(); status.set('控制點已修改，請重新產生並儲存此視角。')
    source_canvas.bind('<Button-1>',press); source_canvas.bind('<B1-Motion>',drag)
    source_canvas.bind('<ButtonRelease-1>',lambda e: dragging.__setitem__(0,None))
    def preview():
        for v,c in canvases.items():
            photos[v]=ImageTk.PhotoImage(images[v][pose.get()].resize((350,350),Image.Resampling.LANCZOS))
            c.delete('all'); c.create_image(0,0,image=photos[v],anchor='nw')
    row=ttk.Frame(app); row.pack(pady=7)
    for i in range(6): ttk.Radiobutton(row,text=f'Pose {chr(65+i)}',variable=pose,value=i,command=lambda: (playing.set(False),load_fields(),preview())).pack(side='left',padx=12)
    controls=ttk.Frame(app,padding=8); controls.pack(fill='x')
    loading=[False]; fields={}; gains={}
    def update_fields(*_):
        if loading[0]: return
        v=selected.get(); p=settings[v]['poses'][pose.get()]; l=p['limbs'][limb_index.get()]
        for key,var in fields.items():
            value=var.get()
            if key in ('body_deg','rotation_deg'): p[key]=value
            elif key=='offset_x': p['offset_px'][0]=value
            elif key=='offset_y': p['offset_px'][1]=value
            else: l[key]=value
        for key,var in gains.items(): settings[v]['gains'][key]=var.get()
        settings[v]['preview_speed']=speed.get()
        status.set('參數已修改；按「重新產生並儲存此視角」更新圖像。')
    def load_fields(*_):
        loading[0]=True
        v=selected.get(); p=settings[v]['poses'][pose.get()]; l=p['limbs'][limb_index.get()]
        for key,var in fields.items():
            var.set(p[key] if key in ('body_deg','rotation_deg') else p['offset_px'][0 if key=='offset_x' else 1] if key in ('offset_x','offset_y') else l[key])
        for key,var in gains.items(): var.set(settings[v]['gains'][key])
        speed.set(settings[v]['preview_speed'])
        loading[0]=False; draw_rig()
    ttk.Label(controls,text='肢體編號').grid(row=0,column=0)
    for i in range(4): ttk.Radiobutton(controls,text=str(i+1),variable=limb_index,value=i,command=load_fields).grid(row=0,column=i+1)
    specs=[('body_deg','身體傾斜 °',-8,8),('rotation_deg','整體旋轉 °',-10,10),('offset_x','重心 X px',-6,6),('offset_y','重心 Y px',-6,6),('root_deg','選定肢體根部 °',-7,7),('joint_deg','選定肢體彎折 °',-5,5),('extension','選定肢體張開量',-.5,.6),('time_offset_seconds','補間時間差 s（第二階段）',0,.2)]
    for i,(key,title,lo,hi) in enumerate(specs):
        r=1+i//4; col=(i%4)*2
        ttk.Label(controls,text=title).grid(row=r*2-1,column=col,columnspan=2,sticky='w')
        var=tk.DoubleVar(); fields[key]=var
        ttk.Spinbox(controls,from_=lo,to=hi,increment=.1,textvariable=var,width=13).grid(row=r*2,column=col,columnspan=2,sticky='w')
        var.trace_add('write',lambda *_: safe_update())
    def safe_update():
        try: update_fields()
        except (tk.TclError,ValueError): pass
    bottom=ttk.Frame(app,padding=8); bottom.pack(fill='x')
    for key,title in [('front','前腳倍率'),('rear','後腳倍率'),('body','身體倍率'),('rotation','旋轉倍率')]:
        ttk.Label(bottom,text=title).pack(side='left'); var=tk.DoubleVar(value=1); gains[key]=var
        ttk.Spinbox(bottom,from_=0,to=1.3,increment=.1,textvariable=var,width=5).pack(side='left',padx=5)
        var.trace_add('write',lambda *_: safe_update())
    speed=tk.DoubleVar(value=1)
    ttk.Label(bottom,text='姿勢審閱速度').pack(side='left'); ttk.Spinbox(bottom,from_=.25,to=2,increment=.1,textvariable=speed,width=5).pack(side='left')
    speed.trace_add('write',lambda *_: safe_update())
    def build():
        if busy[0]: return
        try: update_fields()
        except (ValueError,tk.TclError): messagebox.showerror('參數錯誤','請輸入有效數值。'); return
        v=selected.get(); rig=copy.deepcopy(rigs[v]); config=copy.deepcopy(settings[v]); busy[0]=True
        status.set(f'正在計算動畫 {v} 的六個原圖關鍵姿勢…')
        def worker():
            try:
                result=generate(v,rig,config)
                write(ROOT/f'frog_{v}'/'skeleton.json',rig); write(ROOT/f'frog_{v}'/'keyposes.json',config)
                output.put((v,result,None))
            except Exception as exc: output.put((v,None,str(exc)))
        threading.Thread(target=worker,daemon=True).start()
    def poll():
        try:
            v,result,error=output.get_nowait(); busy[0]=False
            if error: status.set('未輸出：請校正控制點或減少幅度。'); messagebox.showerror('保形檢查未通過',error)
            else: images[v]=result; preview(); status.set(f'動畫 {v} 已更新六個姿勢、對照圖與 JSON；尚未製作完整影格。')
        except queue.Empty: pass
        app.after(100,poll)
    def tick():
        if playing.get():
            pose.set((pose.get()+1)%6); load_fields(); preview()
        try: delay=max(100,round(2000/6/max(.25,speed.get())))
        except tk.TclError: delay=333
        app.after(delay,tick)
    ttk.Button(app,text='重新產生並儲存此視角（僅六張關鍵姿勢）',command=build).pack(pady=5)
    ttk.Label(app,textvariable=status,wraplength=1080).pack(pady=8)
    selector.bind('<<ComboboxSelected>>',load_fields); advanced.trace_add('write',lambda *_: draw_rig())
    load_fields(); preview(); poll(); tick(); app.mainloop()

if __name__=='__main__': main()
