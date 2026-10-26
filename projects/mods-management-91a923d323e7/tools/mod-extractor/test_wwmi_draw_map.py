import tempfile,unittest
from pathlib import Path
from wwmi_draw_map import parse_component_draws,expected_fmt_count,select_reverse_layout,static_draw_conditions
from body_selection import classify_label
from body_candidates import regions,select_body_candidates


class WWMIDrawMapTests(unittest.TestCase):
    def test_every_labelled_draw_is_kept_not_first_per_component(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini=Path(tmp)/'mod.ini'
            ini.write_text('[TextureOverrideComponent0]\ndrawindexed = 3, 0, 0\n'
                '[TextureOverrideComponent3]\nif $xiashen0 == 1\n'
                '; Draw Component 3.下身\ndrawindexed = 9, 10, 0\nendif\n'
                'if $shenti0 == 1\n; Draw Component 3.身体\ndrawindexed = 6, 20, 0\nendif\n'
                'if $jiao0 == 1\n; Draw Component 3.脚\ndrawindexed = 12, 30, 0\nendif\n',encoding='utf-8')
            components=parse_component_draws(ini)
            self.assertEqual(expected_fmt_count(components),4)
            labels=[row['label'] for row in components['3']]
            self.assertEqual(labels,['Draw Component 3.下身','Draw Component 3.身体','Draw Component 3.脚'])
            self.assertEqual([row['index'] for row in components['3']],[0,1,2])
            self.assertEqual(components['3'][0]['conditions'],['$xiashen0 == 1'])

    def test_first_draw_only_map_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini=Path(tmp)/'mod.ini'
            ini.write_text('[TextureOverrideComponent3]\n; Draw Component 3.下身\ndrawindexed = 9, 10, 0\n'
                '; Draw Component 3.身体\ndrawindexed = 6, 20, 0\n',encoding='utf-8')
            self.assertGreater(expected_fmt_count(parse_component_draws(ini)),1)

    def test_layout_matching_draw_count_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            good=root/'CPU_P12_TA4_N4_T4_T1-4_T2-4_T3-4_4';good.mkdir()
            other=root/'CPU_P12_TA4_N4_T4_T1-4_T2-4_T3-4_3';other.mkdir()
            for folder,count in ((good,2),(other,1)):
                for index in range(count):
                    fmt=folder/('Component 3.%s.fmt'%index)
                    fmt.write_text('stride: 40\n',encoding='utf-8')
                    fmt.with_suffix('.ib').write_bytes(b'\0\0\0\0')
                    fmt.with_suffix('.vb').write_bytes(b'\0'*12)
            chosen=select_reverse_layout(root,2)
            self.assertEqual(chosen,good)
            with self.assertRaisesRegex(ValueError,'不一致'):select_reverse_layout(root,3)

    def test_texture_format_conditions_are_not_static_draw_tests(self):
        self.assertEqual(static_draw_conditions(['ps-t0->format == 98','$xiashen0 == 1']),['$xiashen0 == 1'])

    def test_format_probe_does_not_block_labelled_skin(self):
        from body_selection import variant_conditions
        rows=[{'name':'hips','label':'Draw Component 3.下身',
               'conditions':['ps-t0->format == 98 && ps-t1->format == 77','$xiashen0 == 1']}]
        self.assertEqual(variant_conditions(rows[0]['conditions']),['$xiashen0 == 1'])
        result=select_body_candidates(rows)
        self.assertEqual(result['status'],'selected')
        self.assertEqual(result['selected'],['hips'])

    def test_chinese_body_parts_are_skin_candidates(self):
        for label in ('Draw Component 3.下身','Draw Component 3.脚','Draw Component 3.身体手臂',
                      'Draw Component 3.身体乳突','Draw Component 3.原脖子'):
            self.assertEqual(classify_label(label),'skin',label)
        self.assertEqual(classify_label('Draw Component 3.原鞋子'),'clothes')
        self.assertEqual(classify_label('Draw Component 3.膝袜脚'),'clothes')
        self.assertIn('lower',regions('Draw Component 3.下身'))
        self.assertIn('feet',regions('Draw Component 3.脚'))

    def test_equal_region_variants_prefer_clothing_off_controls(self):
        from source_controls import load_control_program
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            ini=Path(tmp)/'mod.ini'
            ini.write_text('[Constants]\nglobal persist $yifu=1\nglobal persist $bishi=1\n'
                '[KeyYifu]\ntype=cycle\n$yifu=0,1\n[KeyBishi]\ntype=cycle\n$bishi=0,1\n'
                '[Present]\nif $yifu == 0\n$shenti1 = 1\n$shenti0 = 0\nelse\n$shenti1 = 0\n$shenti0 = 1\nendif\n'
                'if $bishi == 0\n$shoubi = 1\nelse\n$shoubi = 0\nendif\n',encoding='utf-8')
            rows=[{'name':'a','label':'Draw Component 3.身体','conditions':['$shenti0 == 1']},
                  {'name':'b','label':'Draw Component 3.身体乳突','conditions':['$shenti1 == 1']},
                  {'name':'c','label':'Draw Component 3.身体手臂','conditions':['$shoubi == 1']}]
            r=select_body_candidates(rows,load_control_program(ini))
            self.assertEqual(r['status'],'selected')
            self.assertEqual(set(r['selected']),{'b','c'})
            self.assertEqual(r['controls']['yifu'],0)

    def test_complementary_nude_parts_are_selected_together(self):
        rows=[{'name':'body','label':'Draw Component 3.身体乳突','conditions':['$shenti1 == 1']},
              {'name':'arms','label':'Draw Component 3.身体手臂','conditions':['$shoubi == 1']},
              {'name':'hips','label':'Draw Component 3.下身','conditions':['$xiashen0 == 1']},
              {'name':'legs','label':'Draw Component 3.大腿','conditions':['$datui0 == 1']},
              {'name':'feet','label':'Draw Component 3.脚','conditions':['$jiao0 == 1']},
              {'name':'neck','label':'Draw Component 3.原脖子','conditions':[]},
              {'name':'shoes','label':'Draw Component 3.原鞋子','conditions':['$xiezi == 1']}]
        result=select_body_candidates(rows)
        self.assertEqual(result['status'],'selected')
        self.assertEqual(set(result['selected']),{'body','arms','hips','legs','feet','neck'})
