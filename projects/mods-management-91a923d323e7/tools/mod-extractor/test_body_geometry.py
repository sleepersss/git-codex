import unittest
from body_geometry import analyze_body

def cube(points,faces,center,size):
    start=len(points)
    points.extend(tuple(center[i]+sign[i]*size[i] for i in range(3)) for sign in
        ((-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)))
    for f in ((0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)):
        faces.extend((start+f[0],start+f[i],start+f[i+1]) for i in (1,2))

class BodyGeometryTests(unittest.TestCase):
    def test_partial_torso_cannot_define_its_own_full_body_height(self):
        points=[];faces=[];cube(points,faces,(0,0,1.1),(.3,.1,.3))
        result=analyze_body(points,faces,reference_bounds=[(-.4,.4),(-.2,.2),(0,1.7)])
        self.assertEqual(result['regions']['source_vertical_coverage'],'gap')
    def test_closed_detached_limbs_are_not_complete(self):
        points=[];faces=[]
        cube(points,faces,(0,0,.80),(.04,.03,.20))
        cube(points,faces,(0,0,.56),(.04,.03,.03))
        for side in (-1,1):
            for x,z,s in ((.065,.025,.025),(.065,.20,.02),(.065,.42,.02),(.145,.76,.015),(.215,.7,.015),(.30,.65,.015)):
                cube(points,faces,(side*x,0,z),(s,.02,s))
        result=analyze_body(points,faces)
        self.assertEqual(result['status'],'gaps')
        self.assertEqual(result['regions']['limb_connections'],'gap')
