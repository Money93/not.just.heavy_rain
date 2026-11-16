from pathlib import Path
import json
import hashlib
import numpy as np
from PIL import Image
from scipy.ndimage import label

ROOT=Path(__file__).resolve().parent
SOURCES={'A':ROOT.parent/'參考圖'/'黑色青蛙躍動剪影.png','B':ROOT.parent/'參考圖'/'幾何感黑色青蛙剪影.png'}

def main():
    for name,path in SOURCES.items():
        image=Image.open(path); rgba=image.convert('RGBA'); a=np.array(rgba)
        directory=ROOT/f'frog_{name}'; directory.mkdir(exist_ok=True)
        report=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),mode=image.mode,size=image.size,
                    alpha_extrema=rgba.getchannel('A').getextrema(),bbox=rgba.getbbox(),components=label(a[:,:,3]>127)[1],
                    visible_rgb_min=a[:,:,:3][a[:,:,3]>0].min(axis=0).tolist(),visible_rgb_max=a[:,:,:3][a[:,:,3]>0].max(axis=0).tolist())
        (directory/'source_analysis.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        rgba.thumbnail((800,800)); bg=Image.new('RGBA',rgba.size,'#d3dae2'); bg.alpha_composite(rgba)
        bg.convert('RGB').save(directory/'source_inspection.jpg')
        print(name,json.dumps(report,ensure_ascii=True))

if __name__=='__main__': main()
