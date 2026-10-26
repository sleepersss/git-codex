import unittest
from body_selection import classify_label,select_parts,draw_metadata
import tempfile
from pathlib import Path

class BodySelectionTests(unittest.TestCase):
    def test_old_inferred_clothing_off_tag_cannot_outlive_its_evidence(self):
        from body_selection import body_draw_metadata
        row=body_draw_metadata({'metadata_exact':True,'label':'base1 [source clothing-off body]',
            'conditions':['$base1==1']},{},None,{})
        self.assertEqual(classify_label(row['label']),'unknown')

    def test_inferred_clothing_off_tag_carries_actual_control_constraint(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini=Path(tmp)/'mod.ini'
            ini.write_text('[Constants]\nglobal persist $dress=0\nglobal $base1=0\n'
                '[KeyDress]\ntype=cycle\n$dress=0,1\n[Present]\nif $dress==0\n$base1=1\nelse\n$base1=1\nendif\n'
                '[TextureOverrideBody]\nif $base1==1\n; Draw base1\ndrawindexed=3,0,0\nendif',encoding='utf-8')
            row=list(draw_metadata(ini).values())[0]
            self.assertEqual(row.get('clothing_off_controls'),{'dress':0})
    def test_user_corrected_labels_are_skin_candidates(self):
        for label in ('Draw Component 3.Nipple','Draw Component 3.bodyup','Draw Component 3.bodydown',
                      'Draw Component 3.原脖子','Draw Component 2.手','Draw Component 2.腿平',
                      'Draw Component 3.下身','Draw Component 3.脚','Draw Component 3.身体手臂'):
            self.assertEqual(classify_label(label),'skin',label)
    def test_source_folder_requires_four_explicit_clothing_off_controls(self):
        from body_selection import source_state_hint
        self.assertTrue(source_state_hint('01 normal nocloth noglove noshoes nobra+nobelt'))
        for name in ('Character nude&halfnude toggle V1.3','normal nocloth glove shoes bra','normal nude','normal nocloth noglove noshoes bra'):
            self.assertFalse(source_state_hint(name),name)
    def test_bare_labels_and_clothes_are_distinguished(self):
        for label in ('Draw Component 3 Body','Body_Hands','Body_Feet','手臂','丝袜无','内裤无'):
            self.assertEqual(classify_label(label),'skin',label)
        for label in ('Body_Stockings','High Heels','脖环','鞋子','裙子','Underwear','膝袜脚','原鞋子'):
            self.assertEqual(classify_label(label),'clothes',label)
    def test_unconditional_body_ex_variants_require_review(self):
        rows=[{'name':x,'label':x} for x in ('Body','Body_EX1','Body_EX2','Body_Hands','Body_Feet','Shoes')]
        self.assertEqual(select_parts(rows),[])
    def test_geometry_only_does_not_assume_clothing_is_skin(self):
        self.assertEqual(select_parts([{'name':'Component 3','label':''}]),[])
    def test_else_assignment_cannot_be_treated_as_clothing_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini=Path(tmp)/'mod.ini'
            ini.write_text('[Present]\nif $dress == 0\n$base1=0\nelse\n$base1=1\nendif\n[TextureOverrideBody]\nif $base1==1\n; Draw Component 3 base1\ndrawindexed=300,0,0\nendif',encoding='utf-8')
            rows=list(draw_metadata(ini).values())
            self.assertEqual(classify_label(rows[0]['label']),'unknown')
    def test_clothing_off_positive_branch_and_else_are_distinguished(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini=Path(tmp)/'mod.ini'
            ini.write_text('[Present]\nif $dress == 0\n$base1=1\nelse\n$base1=0\nendif\n[TextureOverrideBody]\nif $base1==1\n; Draw Component 3 base1\ndrawindexed=300,0,0\nelse\n; Draw Component 3 base2\ndrawindexed=300,300,0\nendif',encoding='utf-8')
            rows=list(draw_metadata(ini).values())
            self.assertEqual(classify_label(rows[0]['label']),'skin')
            self.assertEqual(classify_label(rows[1]['label']),'unknown')
    def test_neutral_toggle_state_resolves_unlabelled_skin_and_elif(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini=Path(tmp)/'mod.ini'
            ini.write_text('[Constants]\nglobal persist $dress=1\nglobal persist $bra=1\nglobal persist $pants=1\nglobal persist $glove=1\n[TextureOverrideA]\nif $glove==0\ndrawindexed=300,0,0\nelif $glove==1\ndrawindexed=300,300,0\nendif\nif $dress!=0\ndrawindexed=300,600,0\nendif',encoding='utf-8')
            rows=list(draw_metadata(ini).values())
            self.assertTrue(rows[0].get('neutral_body_state'))
            self.assertFalse(rows[1].get('neutral_body_state'))
            self.assertFalse(rows[2].get('neutral_body_state'))
    def test_mutually_exclusive_labelled_variants_are_not_combined(self):
        rows=[{'name':'a','label':'Body','conditions':['$variant == 0']},{'name':'b','label':'Body','conditions':['$variant == 1']}]
        self.assertEqual(select_parts(rows),[])
    def test_else_variant_is_not_combined_with_first_branch(self):
        rows=[{'name':'a','label':'Body','conditions':['$variant == 0']},{'name':'b','label':'Body','conditions':['not ($variant == 0)']}]
        self.assertEqual(select_parts(rows),[])
    def test_same_draw_with_different_branch_labels_is_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini=Path(tmp)/'mod.ini'
            ini.write_text('[TextureOverrideA]\nif $v==0\nvb0=ResourceNude\n; Draw Body\ndrawindexed=300,0,0\nelse\nvb0=ResourceClothed\n; Draw Stockings\ndrawindexed=300,0,0\nendif',encoding='utf-8')
            row=list(draw_metadata(ini).values())[0]
            self.assertEqual(classify_label(row['label']),'unknown')
    def test_neutral_state_does_not_use_stale_derived_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini=Path(tmp)/'mod.ini'
            ini.write_text('[Constants]\nglobal persist $dress=1\nglobal persist $bra=1\nglobal persist $pants=1\nglobal persist $glove=1\nglobal $body=1\n[Present]\nif $dress==0\n$body=0\nendif\n[TextureOverrideA]\nif $body==1\ndrawindexed=300,0,0\nendif',encoding='utf-8')
            self.assertFalse(list(draw_metadata(ini).values())[0].get('neutral_body_state'))
    def test_multivalue_and_or_opposing_branches_choose_one_state(self):
        for condition in ('$variant == 2','$a == 0 || $b == 0'):
            rows=[{'name':'first','label':'Body','conditions':[condition]},
                {'name':'else','label':'Body','conditions':['not ('+condition+')']}]
            self.assertEqual(select_parts(rows),[])
    def test_static_wwmi_skin_does_not_require_live_skeleton_resource(self):
        rows=[{'name':'skin','label':'Draw Body','conditions':['$mod_enabled','ResourceMergedSkeleton !== null','$base1==1']}]
        self.assertEqual(select_parts(rows),['skin'])
