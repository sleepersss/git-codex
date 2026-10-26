"""Isolated Blender regression, using a synthetic connected surface, not a real person."""
import unittest,tempfile,struct,json,subprocess,hashlib
from pathlib import Path
from app_paths import resolve_paths
from runner import write_json,sha256
from generic_extract import plan_meshes
from body_pipeline import extract_source_body


def make_source(root,ambiguous=False):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    cells=set()
    def block(x0,x1,y0,y1,z0,z1):
        cells.update((x,y,z) for x in range(x0,x1) for y in range(y0,y1) for z in range(z0,z1))
    block(-4,4,-2,2,16,33);block(-5,5,-2,2,15,20)
    for side in (-1,1):
        block(-4,-1,-2,2,0,18) if side<0 else block(1,4,-2,2,0,18)
        block(-4,-1,-4,2,0,2) if side<0 else block(1,4,-4,2,0,2)
    block(-14,14,-2,2,24,28)
    vertices=[];lookup={};lower=[];upper=[]
    sides=[((-1,0,0),((0,0,0),(0,0,1),(0,1,1),(0,1,0))),
        ((1,0,0),((1,0,0),(1,1,0),(1,1,1),(1,0,1))),
        ((0,-1,0),((0,0,0),(1,0,0),(1,0,1),(0,0,1))),
        ((0,1,0),((0,1,0),(0,1,1),(1,1,1),(1,1,0))),
        ((0,0,-1),((0,0,0),(0,1,0),(1,1,0),(1,0,0))),
        ((0,0,1),((0,0,1),(1,0,1),(1,1,1),(0,1,1)))]
    for cell in sorted(cells):
        for direction,corners in sides:
            if tuple(cell[i]+direction[i] for i in range(3)) in cells:continue
            face=[]
            for corner in corners:
                key=tuple(cell[i]+corner[i] for i in range(3))
                if key not in lookup:lookup[key]=len(vertices);vertices.append(tuple(v*.05 for v in key))
                face.append(lookup[key])
            target=upper if sum(vertices[v][2] for v in face)/4>=1 else lower
            target.extend((face[0],face[i],face[i+1]) for i in (1,2))
    start=len(vertices)
    vertices.extend([(.10,-.101,1.30),(.12,-.101,1.30),(.12,-.101,1.32),(.10,-.101,1.32)])
    detail=[(start,start+1,start+2),(start,start+2,start+3)]
    groups=[('bodydown',lower),('bodyup',upper),('Nipple',detail)]
    data=[n for _,faces in groups for face in faces for n in face]
    (root/'Position.buf').write_bytes(struct.pack('<'+'f'*(len(vertices)*3),*(c for p in vertices for c in p)))
    (root/'Index.buf').write_bytes(struct.pack('<'+'I'*len(data),*data))
    (root/'Texcoord.buf').write_bytes(struct.pack('<4f',.1,.2,.3,.4)*len(vertices))
    text='; WWMI synthetic regression surface\n[Constants]\nglobal persist $dress=0\nglobal persist $bra=0\nglobal persist $pants=0\nglobal persist $glove=0\n'
    if ambiguous:text+='global persist $variant=0\n[KeyVariant]\ntype=cycle\n$variant=0,1\n'
    text+='[ResourcePosition]\ntype=Buffer\nstride=12\nfilename=Position.buf\n[ResourceIndex]\ntype=Buffer\nformat=R32_UINT\nfilename=Index.buf\n'
    text+='[ResourceTexcoord]\ntype=Buffer\nstride=16\nfilename=Texcoord.buf\n[TextureOverrideBody]\nhash=abcdef12\nvb0=ResourcePosition\nvb1=ResourceTexcoord\nib=ResourceIndex\n'
    if ambiguous:
        for v in (0,1):text+=f'if $variant=={v}\n; Draw Body\ndrawindexed={len(data)},0,0\nendif\n'
    else:
        offset=0
        for label,faces in groups:
            text+=f'; Draw Component 3.{label}\ndrawindexed={len(faces)*3},{offset},0\n';offset+=len(faces)*3
    (root/'mod.ini').write_text(text,encoding='utf-8')
    return root


class BodyBlenderIntegrationTests(unittest.TestCase):
    def check(self,ambiguous):
        blender=Path(resolve_paths()['blender'])
        if not blender.is_file():self.skipTest('Blender unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);root=make_source(run/'input',ambiguous)
            plans=plan_meshes(root,root/'mod.ini');write_json(run/'mesh-plan.json',plans)
            write_json(run/'job.json',{'blender':str(blender),'main_ini':str(root/'mod.ini'),'name':'regression','source':str(root)})
            command=[str(blender),'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(Path(__file__).with_name('import_generic.py')),'--',str(run)]
            p=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90)
            self.assertEqual(p.returncode,0,p.stdout.decode(errors='replace'))
            # Add independently checked shape data and eight weight channels.
            script=run/'attributes.py'
            script.write_text("import bpy\nbpy.ops.wm.open_mainfile(filepath="+repr(str(run/'models/full.blend'))+")\n"
                "for o in bpy.data.objects:\n if o.type!='MESH':continue\n o.shape_key_add(name='Basis')\n key=o.shape_key_add(name='SourceTarget')\n"
                " for v in key.data:v.co.y+=.001\n"
                " for i in range(8):\n  g=o.vertex_groups.new(name=str(i))\n  g.add(list(range(len(o.data.vertices))),.125,'REPLACE')\n"
                "bpy.context.preferences.filepaths.save_version=0\nbpy.ops.wm.save_as_mainfile(filepath="+repr(str(run/'models/full.blend'))+")\n",encoding='utf-8')
            p=subprocess.run([str(blender),'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(script)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90)
            self.assertEqual(p.returncode,0,p.stdout.decode(errors='replace'))
            original=sha256(run/'models/full.blend');result=extract_source_body(run)
            if ambiguous:
                self.assertEqual(result['body_status'],'unverified',result)
                self.assertFalse((run/'models/body.blend').exists())
                self.assertEqual(json.loads((run/'body-candidates.json').read_text(encoding='utf-8'))['status'],'ambiguous')
            else:
                log=(run/'body-analysis.log').read_text(encoding='utf-8',errors='replace')
                self.assertEqual(result['body_status'],'available',str(result)+'\n'+log)
                saved=json.loads((run/'body-selection.json').read_text(encoding='utf-8'))
                candidates=json.loads((run/'body-candidates.json').read_text(encoding='utf-8'))
                details=[r['name'] for r in candidates['parts'] if 'Nipple' in r['label']]
                self.assertEqual(len(details),1)
                self.assertIn(details[0],saved['meshes'])
                checks=json.loads((run/'body-source-verification.json').read_text(encoding='utf-8'))
                self.assertEqual(checks['status'],'passed')
                self.assertTrue(all(r['weights_exact'] and r['shape_targets_exact'] and r['uv_exact'] for r in checks['checks']))
            self.assertEqual(sha256(run/'models/full.blend'),original)
            self.assertTrue((run/'body-review.html').is_file())

    def test_split_body_and_independent_detail_preserve_all_attributes(self):self.check(False)
    def test_ambiguous_source_variants_do_not_publish_body(self):self.check(True)
