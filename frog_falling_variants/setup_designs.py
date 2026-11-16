"""Initialize independently marked rigs. Does not alter source images."""
from generate import ROOT, SOURCES, write
from PIL import Image

def limb(name,kind,root,joint,tip,region,direction):
    return dict(name=name,kind=kind,root=root,joint=joint,tip=tip,region=region,
                radius=60,blend_length=110,phase=0,extension_direction=direction)

def main():
    designs={
      'A':dict(center=[367,411],torso=[[294,250],[360,180],[450,140],[520,180],[525,300],[485,350],[480,455],[416,515],[322,560],[241,530],[205,462],[247,346]],limbs=[
        limb('front_left','front',[280,285],[182,265],[182,140],[[300,245],[225,248],[210,205],[275,205],[280,120],[250,45],[140,45],[85,105],[85,160],[150,205],[150,255],[170,295],[258,327]],-1),
        limb('front_right','front',[480,340],[555,396],[650,320],[[480,320],[546,370],[610,330],[615,260],[650,230],[715,250],[750,340],[695,365],[610,410],[560,435],[490,395]],1),
        limb('rear_left','rear',[250,440],[152,395],[140,570],[[240,410],[195,330],[140,325],[95,355],[80,445],[120,510],[135,555],[95,540],[75,500],[30,505],[10,590],[100,630],[140,675],[190,670],[210,580],[185,540],[195,475],[235,490]],1),
        limb('rear_right','rear',[380,530],[510,525],[475,715],[[365,505],[460,500],[525,465],[565,490],[590,550],[540,615],[450,670],[460,692],[510,700],[530,645],[565,655],[600,700],[585,780],[525,795],[415,790],[425,735],[360,695],[355,650],[415,590],[365,585]],-1)]),
      'B':dict(center=[390,445],torso=[[291,333],[325,300],[365,304],[420,283],[470,330],[492,418],[515,490],[530,550],[492,591],[480,630],[450,646],[400,610],[365,578],[340,548],[303,500],[270,465],[255,410],[259,370]],limbs=[
        limb('rear_left','rear',[298,375],[155,355],[206,152],[[302,335],[225,325],[200,330],[235,235],[225,207],[190,180],[250,147],[285,155],[300,120],[292,55],[230,35],[220,0],[180,0],[165,95],[135,135],[140,200],[180,235],[130,325],[115,370],[160,405],[255,420],[290,410]],-1),
        limb('rear_right','rear',[404,335],[457,306],[454,215],[[378,300],[424,280],[400,235],[389,188],[410,170],[525,205],[570,205],[590,195],[612,220],[610,260],[616,313],[570,328],[530,310],[500,320],[474,346],[446,365]],1),
        limb('front_left','front',[350,526],[270,564],[300,681],[[337,493],[270,525],[235,550],[231,595],[270,650],[270,707],[257,748],[305,767],[340,751],[380,764],[397,722],[389,672],[335,647],[315,628],[306,600],[310,580],[371,560]],1),
        limb('front_right','front',[490,510],[554,489],[623,569],[[485,480],[525,460],[565,458],[585,485],[615,525],[650,550],[690,565],[706,600],[685,649],[665,667],[615,670],[582,658],[543,623],[540,591],[580,570],[582,552],[555,524],[520,537],[498,555]],-1)])}
    for name,d in designs.items():
        factor=Image.open(SOURCES[name]).width/800
        def point(p): return [round(v*factor,2) for v in p]
        rig=dict(source=str(SOURCES[name].relative_to(ROOT.parent)),coordinate_system='original PNG pixels',
                 status='Design draft: visible joint positions; confirm hidden attachment points in editor.',
                 body_center=point(d['center']),torso=[point(p) for p in d['torso']],limbs=[])
        for l in d['limbs']:
            for k in ('root','joint','tip'): l[k]=point(l[k])
            l['region']=[point(p) for p in l['region']]
            for k in ('radius','blend_length'): l[k]*=factor
            rig['limbs'].append(l)
        directory=ROOT/f'frog_{name}'
        if not (directory/'skeleton.json').exists(): write(directory/'skeleton.json',rig)
        # Uneven phase spacing and asymmetric angular changes; no sine oscillator.
        roots=([[0,0,0,0],[-2,3,3,-2],[-5,4,5,-4],[2,-2,1,-2],[3,-3,-3,2],[1,-1,-1,1]] if name=='A' else
               [[0,0,0,0],[2,-2,-1,2],[4,-3,-3,4],[-1,1,2,-1],[-3,2,2,-2],[-1,1,1,0]])
        bodies=[0,2,4,1,-3,-1] if name=='A' else [0,-2,-3,-1,2,.7]
        rotations=[0,2,5,2,-2,-.5] if name=='A' else [0,-1,-3,1,3,1]
        offsets=[[0,0],[1,-1],[3,0],[1,1],[-2,0],[-1,0]]
        poses=[]
        for i in range(6):
            poses.append(dict(name=f'Pose {chr(65+i)}',time=[0,.14,.34,.53,.73,.9][i],body_deg=bodies[i],rotation_deg=rotations[i],offset_px=offsets[i],
               limbs=[dict(root_deg=roots[i][j],joint_deg=roots[i][j]*.4,extension=[0,.2,.45,.2,-.1,-.05][i],time_offset_seconds=([0,.055,.025,.085] if name=='A' else [0,.09,.045,.12])[j]) for j in range(4)]))
        settings=dict(stage=1,duration_seconds=2,fps=12,supported_fps=[12,16,24],gains=dict(front=1,rear=1,body=1,rotation=1),
                      preview_speed=1 if name=='A' else .8,interpolation_plan='Periodic cubic interpolation of six nonuniform poses; no length scaling. Apply limb delays with baseline subtraction to preserve Pose A.',poses=poses)
        if not (directory/'keyposes.json').exists(): write(directory/'keyposes.json',settings)

if __name__=='__main__': main()
