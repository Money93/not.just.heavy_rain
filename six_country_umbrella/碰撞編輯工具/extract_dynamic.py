#!/usr/bin/env python3
"""Generate per-frame alpha silhouette collision profiles for transparent WebM.
Requires ffmpeg compiled with libvpx-vp9, ffprobe, numpy and opencv-python.
"""
import argparse, json, math, shutil, subprocess
from pathlib import Path
import cv2
import numpy as np

KINDS=('cat','dog','chair','knife','frog','rope','snake','lizard')

def run(*args):
    p=subprocess.run(args,capture_output=True,check=True)
    return p.stdout

def main():
    a=argparse.ArgumentParser()
    a.add_argument('--input', required=True)
    a.add_argument('--type', required=True, choices=KINDS)
    a.add_argument('--output', default='collision_data.js')
    a.add_argument('--fps', type=int, default=12)
    a.add_argument('--width', type=int, default=320)
    a.add_argument('--threshold', type=int, default=75)
    a.add_argument('--points', type=int, default=20)
    a.add_argument('--pad', type=float, default=.05)
    a.add_argument('--preview',default='')
    args=a.parse_args()
    for tool in ('ffmpeg','ffprobe'):
        if not shutil.which(tool):raise SystemExit(f'Missing {tool}; install FFmpeg.')
    src=Path(args.input)
    probe=json.loads(run('ffprobe','-v','error','-show_entries','stream=width,height:format=duration','-of','json',str(src)))
    sw=int(probe['streams'][0]['width']);sh=int(probe['streams'][0]['height'])
    duration=float(probe['format']['duration'])
    width=args.width; height=max(2,round(sh*width/sw/2)*2)
    # One FFmpeg pass; native VP9 decoder can lose transparency so explicitly use libvpx-vp9.
    raw=run('ffmpeg','-v','error','-c:v','libvpx-vp9','-i',str(src),'-an', '-vf',f'fps={args.fps},scale={width}:{height}', '-pix_fmt','rgba','-f','rawvideo','pipe:1')
    stride=width*height*4
    count=len(raw)//stride
    if count<1:raise SystemExit('No frames decoded')
    array=np.frombuffer(raw[:count*stride],dtype=np.uint8).reshape(count,height,width,4)
    masks=[]; bounds=[]
    kernel=np.ones((3,3),np.uint8)
    for frame in array:
        alpha=(frame[:,:,3]>=args.threshold).astype(np.uint8)*255
        alpha=cv2.morphologyEx(alpha,cv2.MORPH_CLOSE,kernel)
        n, labels, stats, _=cv2.connectedComponentsWithStats(alpha)
        mask=np.zeros_like(alpha)
        if n>1:
            k=1+np.argmax(stats[1:,cv2.CC_STAT_AREA]);mask[labels==k]=255
            # Include substantial disconnected fragments close to largest body.
            x,y,w,h,area=stats[k]
            for i in range(1,n):
                if i==k:continue
                xi,yi,wi,hi,ai=stats[i]
                dx=max(x-(xi+wi),xi-(x+w),0);dy=max(y-(yi+hi),yi-(y+h),0)
                if ai>max(25,area*.006) and math.hypot(dx,dy)<max(w,h)*.10:mask[labels==i]=255
        masks.append(mask)
        ys,xs=np.where(mask>0)
        if len(xs):bounds.append((xs.min(),ys.min(),xs.max()+1,ys.max()+1))
    if not bounds:raise SystemExit('No visible alpha foreground. Verify transparent WebM and FFmpeg decoder.')
    l=min(b[0] for b in bounds);t=min(b[1] for b in bounds);r=max(b[2] for b in bounds);b=max(b[3] for b in bounds)
    px=max(3,round((r-l)*args.pad));py=max(3,round((b-t)*args.pad))
    l=max(0,l-px);t=max(0,t-py);r=min(width,r+px);b=min(height,b+py)
    frames=[];old=None
    for mask in masks:
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            frames.append(old if old else []);continue
        contour=max(contours,key=cv2.contourArea)
        arc=cv2.arcLength(contour,True)
        pts=contour[:,0,:]
        for eps in np.linspace(.002,.075,160):
            approx=cv2.approxPolyDP(contour,float(eps)*arc,True)[:,0,:]
            if 3<=len(approx)<=args.points:
                pts=approx;break
        if len(pts)>args.points:pts=pts[np.linspace(0,len(pts)-1,args.points).astype(int)]
        if len(pts)<3:frames.append(old if old else []);continue
        old=[[round((float(x)-l)/(r-l),5),round((float(y)-t)/(b-t),5)] for x,y in pts]
        frames.append(old)
    for i,f in enumerate(frames):
        if not f:frames[i]=next((z for z in frames if z),[])
    if not any(frames):raise SystemExit('No polygon generated.')
    crop=[round(l*sw/width),round(t*sh/height),round((r-l)*sw/width),round((b-t)*sh/height)]
    out=Path(args.output);data={}
    if out.exists():
        content=out.read_text(encoding='utf-8').strip()
        if content.startswith('window.COLLISION_DATA'):content=content.split('=',1)[1].strip().removesuffix(';')
        try:data=json.loads(content)
        except ValueError:pass
    # frames are sampled regularly at fps; master video time maps to the corresponding index.
    data[args.type]={'source':src.name,'crop':crop,'fps':args.fps,'duration':duration,'frames':frames,'points':frames[0]}
    out.write_text('window.COLLISION_DATA = '+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')
    # Contact sheet: first, middle, last selected samples, overlaid with contours.
    tiles=[]
    for idx in sorted(set([0,len(frames)//4,len(frames)//2,3*len(frames)//4,len(frames)-1])):
        tile=np.full((height,width,3),40,np.uint8);tile[masks[idx]>0]=(220,220,220)
        poly=np.array([[(round(u*(r-l)+l),round(v*(b-t)+t)) for u,v in frames[idx]]],dtype=np.int32)
        cv2.polylines(tile,poly,True,(0,180,255),2)
        cv2.putText(tile,f'{idx/args.fps:.2f}s', (8,24),cv2.FONT_HERSHEY_SIMPLEX,.65,(75,235,75),2)
        tiles.append(tile)
    preview=Path(args.preview) if args.preview else out.parent/(args.type+'_dynamic_preview.png')
    cv2.imwrite(str(preview),np.concatenate(tiles,axis=1))
    print(f'Generated {len(frames)} shapes / {args.fps}fps; crop={crop}; {out}; {preview}')

if __name__=='__main__':main()
