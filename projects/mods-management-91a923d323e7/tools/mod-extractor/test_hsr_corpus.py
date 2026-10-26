"""Regressions reproduced from the HSR corpus audit, independent of game paths."""
import unittest,tempfile,struct
from pathlib import Path
from discovery import discover_mod
from generic_extract import plan_meshes
from body_selection import draw_metadata,classify_label,evaluate_condition

class HSRCorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def resource(self,name,kind='position',count=3):
        file=name+'.buf'
        if kind=='index':
            data=struct.pack('<3I',0,1,2);fields='format=R32_UINT'
        else:
            stride={'position':40,'blend':32,'texcoord':8}[kind]
            data=bytes(count*stride);fields='stride='+str(stride)
        (self.root/file).write_bytes(data)
        return f'[Resource{name}]\n{fields}\nfilename={file}\n'
    def ini(self,text):
        p=self.root/'Mod.ini';p.write_text('; HSR\n'+text,encoding='utf-8');return p
    def test_rejoined_binding_preserves_logical_union(self):
        text='[Constants]\nglobal $state=1\n'+self.resource('DemoPosition')+self.resource('DemoAIB','index')+self.resource('DemoBIB','index')
        text+='[TextureOverrideDemo]\nvb0=ResourceDemoPosition\nif $state == 0\nib=ResourceDemoAIB\nelse if $state == 1\nib=ResourceDemoBIB\nelse\nib=ResourceDemoAIB\nendif\ndrawindexed=3,0,0\n'
        plans=plan_meshes(self.root,self.ini(text))
        self.assertEqual([p['bindings']['ib']['file'] for p in plans if p['visible_by_default']],['DemoBIB.buf'])

    def test_unknown_mutually_exclusive_display_is_unresolved(self):
        text=self.resource('DemoPosition')+self.resource('DemoAIB','index')
        text+='[TextureOverrideDemo]\nib=ResourceDemoAIB\nif $runtime == 0\ndrawindexed=3,0,0\nelse\ndrawindexed=3,0,0\nendif\n'
        plans=plan_meshes(self.root,self.ini(text))
        self.assertFalse(any(p['visible_by_default'] for p in plans))
        self.assertTrue(all(p['default_display_status']=='unresolved' for p in plans))

    def test_present_derived_default_controls(self):
        text='[Constants]\nglobal $dress=0\nglobal $base=0\n[Present]\nif $dress == 0\n$base=1\nelse\n$base=0\nendif\n'
        text+=self.resource('DemoPosition')+self.resource('DemoAIB','index')
        text+='[TextureOverrideDemo]\nib=ResourceDemoAIB\nif $base == 1\ndrawindexed=3,0,0\nelse\ndrawindexed=3,0,0\nendif\n'
        plans=plan_meshes(self.root,self.ini(text))
        self.assertEqual(sum(p['visible_by_default'] for p in plans),1)
        self.assertEqual(plans[0]['default_controls']['base'],1)
        self.assertTrue(plans[0]['visible_by_default'])

    def test_condition_known_false_with_unknown_is_false(self):
        self.assertIs(evaluate_condition('$known == 1 && $runtime == 0',{'known':0}),False)
        self.assertIs(evaluate_condition('$runtime == 0 || $known == 1',{'known':1}),True)

    def test_present_arithmetic_selector_uses_declared_controls(self):
        text='[Constants]\nglobal $part=2\nglobal $swapvar=0\n[Present]\n$swapvar=$part + 1\n'
        text+=self.resource('DemoPosition')+self.resource('DemoAIB','index')
        text+='[TextureOverrideDemo]\nib=ResourceDemoAIB\nif $swapvar == 3\ndrawindexed=3,0,0\nendif\n'
        plans=plan_meshes(self.root,self.ini(text))
        self.assertTrue(plans[0]['visible_by_default'])

    def test_present_branch_decision_survives_control_mutation(self):
        text='[Constants]\nglobal $state=0\nglobal $base=0\n[Present]\nif $state == 0\n$state=1\n$base=1\nelse\n$base=2\nendif\n'
        text+=self.resource('DemoPosition')+self.resource('DemoAIB','index')
        text+='[TextureOverrideDemo]\nib=ResourceDemoAIB\nif $base == 1\ndrawindexed=3,0,0\nendif\n'
        plans=plan_meshes(self.root,self.ini(text))
        self.assertTrue(plans[0]['visible_by_default'])
        self.assertEqual(plans[0]['default_controls']['base'],1)

    def test_inferred_nude_label_cannot_outlive_native_condition(self):
        from body_selection import body_draw_metadata
        draw={'metadata_exact':True,'label':' [source nude toggle state]','conditions':['$headdress == 1']}
        row=body_draw_metadata(draw,{}, {'headdress':0,'dress':0}, {})
        self.assertFalse(row['neutral_body_state'])
        self.assertEqual(classify_label(row['label']),'unknown')
        valid=body_draw_metadata({**draw,'conditions':['$headdress == 0']},{},{'headdress':0,'dress':0},{})
        self.assertEqual(classify_label(valid['label']),'skin')

    def test_auto_draw_inherits_per_hash_index_parts(self):
        text=self.resource('DemoPosition')+self.resource('DemoAIB','index')+self.resource('DemoBIB','index')
        p=self.ini(text+'[TextureOverrideDemoPosition]\nvb0=ResourceDemoPosition\ndraw=3,0\n[TextureOverrideDemoIB]\nhash=abcdef12\ndrawindexed=auto\n[TextureOverrideDemoA]\nhash=abcdef12\nmatch_first_index=0\nib=ResourceDemoAIB\n[TextureOverrideDemoB]\nhash=abcdef12\nmatch_first_index=123\nib=ResourceDemoBIB\n')
        self.assertTrue(discover_mod(self.root)['supported'])
        plans=plan_meshes(self.root,p)
        self.assertEqual({p['bindings']['ib']['file'] for p in plans},{'DemoAIB.buf','DemoBIB.buf'})
        self.assertTrue(all((p['count'],p['start'],p['base'])==(3,0,0) for p in plans))
    def test_body_and_hair_bind_their_own_position_and_uv(self):
        text=''
        for prefix in ('DemoBody','DemoHair'):
            text+=self.resource(prefix+'Position')+self.resource(prefix+'Texcoord','texcoord')+self.resource(prefix+'AIB','index')
            text+=f'[TextureOverride{prefix}Position]\nvb0=Resource{prefix}Position\ndraw=3,0\n[TextureOverride{prefix}Texcoord]\nvb1=Resource{prefix}Texcoord\n[TextureOverride{prefix}A]\nib=Resource{prefix}AIB\ndrawindexed=3,0,0\n'
        plans=plan_meshes(self.root,self.ini(text))
        self.assertEqual(len(plans),2)
        for p in plans:
            stem=p['bindings']['ib']['name'].removesuffix('AIB')
            self.assertEqual(p['bindings']['vb0']['name'],stem+'Position')
            self.assertEqual(p['bindings']['vb1']['name'],stem+'Texcoord')
    def test_static_ref_binding_is_resolved_without_running_shader(self):
        text=self.resource('DemoPosition')+self.resource('DemoAIB','index')
        p=self.ini(text+'[TextureOverrideDemo]\nvb0=ref ResourceDemoPosition\nib=ResourceDemoAIB\ndrawindexed=3,0,0\n')
        self.assertEqual(plan_meshes(self.root,p)[0]['bindings']['vb0']['file'],'DemoPosition.buf')
    def test_else_if_is_mutually_exclusive(self):
        p=self.ini('[TextureOverrideDemo]\nif $shoes == 0\n; Draw Shoes\ndrawindexed=3,0,0\nelse if $shoes == 1\n; Draw Bare feet\ndrawindexed=3,3,0\nendif\n')
        metadata=draw_metadata(p)
        self.assertIn('$shoes == 1',metadata[('textureoverridedemo',3,3,0)]['conditions'])
        self.assertTrue(any('not' in x for x in metadata[('textureoverridedemo',3,3,0)]['conditions']))
    def test_exporter_part_comments_are_body_labels(self):
        p=self.ini('[TextureOverrideDemo]\n; Arms (8728)\nif $sleeves == 2\ndrawindexed=3,0,0\nendif\n; DressB (2446)\ndrawindexed=3,3,0\n')
        metadata=draw_metadata(p)
        self.assertIn('Arms',metadata[('textureoverridedemo',3,0,0)]['label'])
        self.assertIn('DressB',metadata[('textureoverridedemo',3,3,0)]['label'])
    def test_same_draw_in_different_states_preserves_all_conditions(self):
        text=self.resource('DemoPosition')+self.resource('DemoAIB','index')
        p=self.ini(text+'[TextureOverrideDemo]\nvb0=ResourceDemoPosition\nib=ResourceDemoAIB\nif $state == 0\n; Draw Body\ndrawindexed=3,0,0\nelse if $state == 1\n; Draw Body\ndrawindexed=3,0,0\nendif\n')
        plans=plan_meshes(self.root,p)
        for state in (0,1):
            self.assertTrue(any(all(evaluate_condition(c,{'state':state}) is True for c in p.get('conditions',[])) for p in plans))
        self.assertFalse(any(not p.get('conditions') for p in plans))
    def test_nude_or_arm_labels_with_positive_clothing_are_not_skin(self):
        for label in ('Nude w/ leotard (lower)','Arms w/ sleeves','Feet w/ left shoes'):
            self.assertEqual(classify_label(label),'clothes',label)

    def test_parent_auto_and_child_explicit_auto_cover_different_states(self):
        text='[Constants]\nglobal persist $swapvar=0\n'
        for i in (0,1):
            text+=self.resource('DemoPosition.'+str(i))+self.resource('DemoCIB.'+str(i),'index')
        text+='[TextureOverrideParent]\nhash=abcdef12\nrun=CommandListParent\n[CommandListParent]\nif $swapvar == 0\ndrawindexed=auto\nendif\n'
        text+='[TextureOverridePart]\nhash=abcdef12\nrun=CommandListPart\n[CommandListPart]\nif $swapvar == 0\nib=ResourceDemoCIB.0\nelse if $swapvar == 1\nib=ResourceDemoCIB.1\ndrawindexed=auto\nendif\n'
        plans=plan_meshes(self.root,self.ini(text))
        self.assertEqual({p['bindings']['ib']['file'] for p in plans},{'DemoCIB.0.buf','DemoCIB.1.buf'})
        self.assertEqual([p['bindings']['ib']['file'] for p in plans if p['visible_by_default']],['DemoCIB.0.buf'])
        self.assertEqual(len(plans),2)

    def test_native_draw_conditions_recover_neutral_body_metadata(self):
        from body_selection import body_draw_metadata
        p=self.ini('[Constants]\nglobal persist $dress=0\nglobal persist $bra=0\nglobal persist $pants=0\nglobal persist $cloth=0\nglobal persist $trans=0\n[TextureOverrideDemo]\nif $trans == 0\ndrawindexed=3,0,0\nelse if $trans == 1\ndrawindexed=3,0,0\nendif\n[CommandListMenu]\n$trans=1-$trans\n')
        metadata,neutral=draw_metadata(p,include_neutral_state=True)
        legacy=metadata[('textureoverridedemo',3,0,0)]
        self.assertTrue(legacy['ambiguous'])
        bare=body_draw_metadata({'metadata_exact':True,'conditions':['$trans == 0']},legacy,neutral,{})
        self.assertTrue(bare['neutral_body_state'])
        self.assertEqual(classify_label(bare['label']),'skin')
        alternative=body_draw_metadata({'metadata_exact':True,'conditions':['$trans == 1']},legacy,neutral,{})
        self.assertFalse(alternative['neutral_body_state'])
        self.assertEqual(classify_label(alternative['label']),'unknown')

if __name__=='__main__':unittest.main()
