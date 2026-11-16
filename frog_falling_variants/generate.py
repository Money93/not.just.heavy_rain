"""Stage 1 only: original-pixel six-keypose design, reusing the existing renderer."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import label, binary_fill_holes, gaussian_filter, distance_transform_edt

ROOT=Path(__file__).resolve().parent
from mesh_renderer import Animator
from inspect_sources import SOURCES

def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path,value): Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def rotation(degrees):
    a=math.radians(degrees)
    return np.array([[math.cos(a),-math.sin(a)],[math.sin(a),math.cos(a)]])

class VariantAnimator(Animator):
    def __init__(self,variant,rig=None,settings=None):
        self.variant=variant
        directory=ROOT/f'frog_{variant}'
        rig=rig or read(directory/'skeleton.json')
        self.settings=settings or read(directory/'keyposes.json')
        super().__init__(rig,size=512,source=SOURCES[variant])
        # Constant scale for all poses, with clearance for both rotation directions.
        self.scale=512*.68/max(self.original.size)
        self.weights=[]; self.bend_weights=[]
        protected=Image.new('L',self.original.size)
        ImageDraw.Draw(protected).polygon([tuple(p) for p in rig['torso']],fill=255)
        clearance=distance_transform_edt(np.array(protected)==0)
        u=np.clip(clearance/60,0,1)
        torso_fade=u*u*(3-2*u)
        for limb in rig['limbs']:
            mask=Image.new('L',self.original.size)
            ImageDraw.Draw(mask).polygon([tuple(p) for p in limb['region']],fill=255)
            xy=np.rint(self.vertices).astype(int)
            soft=gaussian_filter(np.array(mask,dtype=float)/255,sigma=20)*torso_fade
            member=soft[xy[:,1],xy[:,0]]
            root,joint,tip=np.array([limb[k] for k in ('root','joint','tip')])
            distance=np.linalg.norm(self.vertices-root,axis=1)
            u=np.clip(distance/limb['blend_length'],0,1)
            weight=member*u*u*(3-2*u)
            self.weights.append(weight)
            axis=tip-joint
            u=np.clip((self.vertices-joint)@axis/max(axis@axis,1)*3,0,1)
            self.bend_weights.append(u*u*(3-2*u))

    def pose(self,t,params=None):
        settings=self.settings; pose=settings['poses'][int(t)]; gains=settings['gains']
        src=self.vertices; dst=src.copy()
        for i,(limb,weight,bend_weight) in enumerate(zip(self.rig['limbs'],self.weights,self.bend_weights)):
            values=pose['limbs'][i]; gain=gains[limb['kind']]
            root,joint=np.array(limb['root']),np.array(limb['joint'])
            # Extension is an angular opening at the existing joint; never length scaling.
            bend=(values['joint_deg']+values['extension']*limb['extension_direction']*5)*gain
            local=src+bend_weight[:,None]*((src-joint)@rotation(bend).T+joint-src)
            local=(local-root)@rotation(values['root_deg']*gain).T+root
            dst+=weight[:,None]*(local-src)
        result=(dst-self.center)@rotation(pose['body_deg']*gains['body']+pose['rotation_deg']*gains['rotation']).T
        return result*self.scale+256+np.array(pose['offset_px'])*gains['body']

def topology(image):
    a=np.array(image.getchannel('A'))>127
    labels,n=label(a)
    counts=np.bincount(labels.ravel())[1:]
    return dict(components=int((counts>=5).sum()),holes=int((binary_fill_holes(a)&~a).sum()))

def generate(variant,rig=None,settings=None):
    animator=VariantAnimator(variant,rig,settings)
    source_hash=hashlib.sha256(SOURCES[variant].read_bytes()).hexdigest()
    images=[animator.frame(i) for i in range(6)]
    # Validate everything before replacing this variant's review outputs.
    source_topology=topology(animator.original)
    checks=[]
    for i,image in enumerate(images):
        box=image.getbbox(); top=topology(image)
        if not box or min(box[:2])<8 or max(box[2:])>504:
            raise ValueError(f'{variant} Pose {i}: insufficient canvas margin')
        if top['components']!=source_topology['components'] or top['holes']!=source_topology['holes']:
            raise ValueError(f'{variant} Pose {i}: topology changed: {top}')
        checks.append(dict(pose=chr(65+i),bbox=box,topology=top))
    if hashlib.sha256(SOURCES[variant].read_bytes()).hexdigest()!=source_hash:
        raise ValueError('Source changed during render')
    directory=ROOT/f'frog_{variant}'; (directory/'keyposes').mkdir(exist_ok=True)
    overlay=Image.new('RGBA',animator.original.size,'#e2e8f0'); overlay.alpha_composite(animator.original)
    annotation=ImageDraw.Draw(overlay)
    annotation.polygon([tuple(p) for p in animator.rig['torso']],outline='#eab308',width=3)
    for index,limb in enumerate(animator.rig['limbs']):
        color=['#e11d48','#2563eb','#059669','#9333ea'][index]
        annotation.line([tuple(limb[k]) for k in ('root','joint','tip')],fill=color,width=4)
        for key in ('root','joint','tip'):
            x,y=limb[key]; annotation.ellipse((x-8,y-8,x+8,y+8),fill=color,outline='white',width=2)
            annotation.text((x+12,y-15),f'{index+1}:{key}',fill=color)
    overlay.thumbnail((900,900)); overlay.save(directory/'skeleton_overlay.png')
    transparent=Image.new('RGBA',(1536,1024))
    contact=Image.new('RGB',(1536,1104),'#e2e8f0'); draw=ImageDraw.Draw(contact)
    for i,image in enumerate(images):
        image.save(directory/'keyposes'/f'pose_{chr(65+i)}.png')
        x,y=(i%3)*512,(i//3)*552
        contact.paste(image,(x,y+30),image); draw.text((x+22,y+14),f'Pose {chr(65+i)}',fill='black')
        transparent.paste(image,(x,(i//3)*512))
    contact.save(directory/'pose_comparison.png')
    transparent.save(directory/'keypose_sheet.png')
    write(directory/'validation.json',dict(stage=1,source_sha256=source_hash,source_topology=source_topology,
          checks=checks,source_unchanged=True,full_animation_generated=False))
    return images

def main():
    parser=argparse.ArgumentParser(description='Stage 1 keyposes only; full animation awaits design approval.')
    parser.add_argument('--variant',choices=['A','B','both'],default='both')
    parser.add_argument('--editor',action='store_true')
    args=parser.parse_args()
    if args.editor:
        from editor import main as editor
        editor(); return
    for variant in (['A','B'] if args.variant=='both' else [args.variant]):
        generate(variant); print(f'{variant}: six transparent keyposes and review sheets exported.')

if __name__=='__main__': main()
