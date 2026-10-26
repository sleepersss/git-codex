"""Non-destructive virtual seam analysis. Source meshes are never welded or filled."""
from collections import Counter,defaultdict
import math

def analyze_body(points,faces,boundary_support=None,include_connected_indices=False,reference_bounds=None):
    if not points or not faces:return {'status':'unverified','reason':'没有身体网格','gaps':[]}
    active=sorted({i for f in faces for i in f});remap={old:new for new,old in enumerate(active)}
    points=[points[i] for i in active];faces=[[remap[i] for i in f] for f in faces]
    bounds=[(min(p[i] for p in points),max(p[i] for p in points)) for i in range(3)]
    up=2 if bounds[2][1]-bounds[2][0]>=bounds[1][1]-bounds[1][0] else 1
    height=bounds[up][1]-bounds[up][0]
    if height<=0:return {'status':'unverified','reason':'身体高度为零','gaps':[]}
    center=0 if bounds[0][0]<0<bounds[0][1] else (bounds[0][0]+bounds[0][1])/2
    zs=[(p[up]-bounds[up][0])/height for p in points];xs=[(p[0]-center)/height for p in points]
    regions={};region_points={}
    if reference_bounds:
        low,high=reference_bounds[up];source_height=high-low
        regions['source_vertical_coverage']='verified' if source_height>0 and height>=source_height*.70 and bounds[up][0]<=low+source_height*.10 else 'gap'
    def present(name,predicate):
        region_points[name]=[i for i,(x,z) in enumerate(zip(xs,zs)) if predicate(x,z)]
        regions[name]='verified' if len(region_points[name])>=3 else 'gap'
    present('torso',lambda x,z:abs(x)<.15 and .64<z<.90)
    present('hips',lambda x,z:abs(x)<.16 and .48<z<.64)
    for side,sign in (('left',-1),('right',1)):
        present(side+'_foot',lambda x,z:sign*x>.01 and z<.08)
        present(side+'_calf',lambda x,z:sign*x>.01 and .10<z<.30)
        present(side+'_thigh',lambda x,z:sign*x>.01 and .34<z<.50)
        present(side+'_upper_arm',lambda x,z:.105<sign*x<.185 and .45<z<.95)
        present(side+'_forearm',lambda x,z:.185<sign*x<.245 and .40<z<.95)
        present(side+'_hand',lambda x,z:sign*x>.245 and .35<z<.95)
    # Quantized coordinate identity accounts for UV splits and touching mesh seams.
    tolerance=height*1e-5;keys={};weld=[];coords=[]
    for p in points:
        key=tuple(round(v/tolerance) for v in p)
        if key not in keys:keys[key]=len(coords);coords.append(p)
        weld.append(keys[key])
    parent=list(range(len(coords)))
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def join(a,b):parent[root(a)]=root(b)
    edges=Counter();seen=set()
    for face in faces:
        f=[weld[i] for i in face]
        if len(set(f))<3:continue
        identity=tuple(sorted(f))
        if identity in seen:continue
        seen.add(identity)
        for v in f[1:]:join(f[0],v)
        edges.update(tuple(sorted((a,b))) for a,b in zip(f,f[1:]+f[:1]))
    adjacency=defaultdict(set)
    for (a,b),n in edges.items():
        if n==1:adjacency[a].add(b);adjacency[b].add(a)
    remaining=set(adjacency);loops=[];gaps=[]
    while remaining:
        seed=remaining.pop();component={seed};stack=[seed]
        while stack:
            for v in adjacency[stack.pop()]:
                if v in remaining:remaining.remove(v);component.add(v);stack.append(v)
        ps=[coords[i] for i in component]
        lower=[min(p[i] for p in ps) for i in range(3)];upper=[max(p[i] for p in ps) for i in range(3)]
        diameter=math.dist(lower,upper);z=((lower[up]+upper[up])/2-bounds[up][0])/height
        x=((lower[0]+upper[0])/2-center)/height
        perimeter=sum(math.dist(coords[a],coords[b]) for a in component for b in adjacency[a] if a<b)
        neck=z>.92 and abs(x)<.12
        anatomical_small=abs(x)<.08 and .48<z<.72 and diameter<height*.05
        # Small central source detail openings do not remove an arm or a leg.
        # Preserve them verbatim and record them; this is not a watertight-mesh claim.
        torso_detail=abs(x)<.08 and .72<z<.92 and diameter<height*.06 and perimeter<height*.12
        substantial=diameter>height*.04 and perimeter>height*.08
        loop={'vertices':len(component),'min':lower,'max':upper,'perimeter':perimeter,'diameter':diameter,'allowed_interface':neck or anatomical_small or torso_detail,
            'interface_reason':'head_omitted' if neck else 'small_pelvic_source_detail' if anatomical_small else 'small_central_torso_source_detail' if torso_detail else None}
        loop['_points']=ps;loop['_ids']=list(component);loop['_substantial']=substantial
        loops.append(loop)
    # Independently exported touching rings may have slightly different vertex counts.
    for i,a in enumerate(loops):
        if not a['_substantial'] or a['allowed_interface']:continue
        support=boundary_support(a['_points'],height*.002) if boundary_support else None
        if support and (not isinstance(support,dict) or support.get('supported')):
            if isinstance(support,dict):
                for p,q in support.get('links',[]):
                    kp=tuple(round(v/tolerance) for v in p);kq=tuple(round(v/tolerance) for v in q)
                    if kp in keys and kq in keys:join(keys[kp],keys[kq])
            a['allowed_interface']=True;a['covered_by_source_surface']=True;continue
        for b in loops[i+1:]:
            if not b['_substantial'] or not .7<a['perimeter']/max(b['perimeter'],1e-20)<1.3:continue
            if math.dist(a['min'],b['min'])>height*.005 or math.dist(a['max'],b['max'])>height*.005:continue
            distance=max(max(min(math.dist(p,q) for q in b['_points']) for p in a['_points']),max(min(math.dist(p,q) for q in a['_points']) for p in b['_points']))
            if distance<=height*.002:
                join(a['_ids'][0],b['_ids'][0])
                a['allowed_interface']=b['allowed_interface']=True;a['matched_source_seam']=b['matched_source_seam']=True
        if not a['allowed_interface']:gaps.append(a)
    components=Counter(root(v) for v in weld)
    primary=components.most_common(1)[0][0]
    disconnected=[name for name,ids in region_points.items() if sum(root(weld[i])==primary for i in ids)<3]
    for loop in loops:loop.pop('_points');loop.pop('_ids');loop.pop('_substantial')
    regions['limb_connections']='gap' if gaps or disconnected else 'verified'
    missing=[name for name,value in regions.items() if value=='gap']
    result={'status':'gaps' if missing else 'complete','regions':regions,'gaps':gaps,'missing_parts':missing,'boundaries':loops,
        'height':height,'up_axis':up,'virtual_weld_tolerance':tolerance,'connected_components':len(components),'disconnected_regions':disconnected,
        'scope':'headless_body','method':'source-labelled geometry / connected limb coverage / verified source seam graph; no geometry alteration'}
    if include_connected_indices:result['connected_vertex_indices']=[active[i] for i,v in enumerate(weld) if root(v)==primary]
    return result
