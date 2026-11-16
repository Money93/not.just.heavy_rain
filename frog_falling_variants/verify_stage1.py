"""Check source identity, pure-black RGBA, mesh integrity and stage-one scope."""
import hashlib
import numpy as np
from PIL import Image
from generate import ROOT, SOURCES, VariantAnimator, read, topology

def main():
    for v in 'AB':
        folder=ROOT/f'frog_{v}'; report=read(folder/'validation.json')
        assert hashlib.sha256(SOURCES[v].read_bytes()).hexdigest()==report['source_sha256']
        animator=VariantAnimator(v)
        # Pose A is the normalized original, with no local deformation or offset.
        expected=(animator.vertices-animator.center)*animator.scale+256
        assert np.allclose(animator.pose(0),expected)
        baseline=topology(animator.original)
        for i in range(6):
            image=Image.open(folder/'keyposes'/f'pose_{chr(65+i)}.png')
            a=np.array(image)
            assert image.mode=='RGBA' and image.size==(512,512)
            assert not a[:,:,:3].any()
            assert not a[[0,-1],:,3].any() and not a[:,[0,-1],3].any()
            assert topology(image)==baseline
            src=animator.vertices[animator.triangles]; dst=animator.pose(i)[animator.triangles]
            def area(tri):
                a,b=tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]
                return a[:,0]*b[:,1]-a[:,1]*b[:,0]
            assert (area(src)*area(dst)>0).all()
        assert len(list((folder/'keyposes').glob('pose_?.png')))==6
        assert not (folder/'spritesheet.png').exists()
        assert not (folder/'frames').exists(), 'Stage 2 must await approval'
        quiet=read(folder/'keyposes.json'); quiet['gains']['body']=0; quiet['gains']['rotation']=0
        local=VariantAnimator(v,settings=quiet)
        assert np.max(np.linalg.norm(local.pose(2)-local.pose(0),axis=1))>1
        print(f'PASS {v}: source unchanged, six RGBA poses, original Pose A, no folds/cuts/extra components/holes, independent limbs, no full-animation outputs.')

if __name__=='__main__': main()
