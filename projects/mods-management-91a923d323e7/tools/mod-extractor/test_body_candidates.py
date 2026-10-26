import unittest
from body_candidates import select_body_candidates, retain_skin_component


def part(name, label, *conditions):
    return {'name':name, 'label':label, 'conditions':list(conditions)}


class BodyCandidateTests(unittest.TestCase):
    def test_complementary_hands_win_over_first_incomplete_state(self):
        rows=[part('first','Body','$variant == 0'),part('second','Body','$variant == 1'),
              part('hands','Hands','$variant == 1')]
        r=select_body_candidates(rows)
        self.assertEqual(r['status'],'selected')
        self.assertEqual(set(r['selected']),{'second','hands'})
        self.assertEqual(r['controls']['variant'],1)
        self.assertEqual(select_body_candidates(list(reversed(rows)))['selected'],r['selected'])

    def test_equal_mutually_exclusive_variants_require_review(self):
        r=select_body_candidates([part('normal','Body','$v == 0'),part('detail','Body','$v == 1')])
        self.assertEqual(r['status'],'ambiguous')
        self.assertEqual(r['selected'],[])
        self.assertEqual(len(r['alternatives']),2)

    def test_independent_detail_is_kept_with_upper_and_lower_body(self):
        r=select_body_candidates([part('upper','Draw Component 3.bodyup'),
            part('lower','Draw Component 3.bodydown'),part('detail','Draw Component 3.Nipple')])
        self.assertEqual(set(r['selected']),{'upper','lower','detail'})
        self.assertTrue(retain_skin_component(part('detail','Nipple'),False))
        self.assertFalse(retain_skin_component(part('unknown','[source nude toggle state]'),False))

    def test_body_ex2_is_not_silently_dropped(self):
        self.assertEqual(select_body_candidates([part('v2','Body_EX2')])['selected'],['v2'])

    def test_unconditional_ex_variants_are_not_overlaid(self):
        r=select_body_candidates([part('base','Body'),part('extra','Body_EX2')])
        self.assertEqual(r['status'],'ambiguous')
        self.assertFalse(r['selected'])

    def test_unknown_runtime_boolean_is_never_invented(self):
        r=select_body_candidates([part('body','Body','$runtime_ready')])
        self.assertEqual(r['status'],'unresolved')
        self.assertFalse(r['selected'])
        self.assertTrue(r['unresolved'])

    def test_unknown_skin_cannot_be_ignored_beside_known_body(self):
        r=select_body_candidates([part('body','Body'),part('hand','Hands','$runtime_ready')])
        self.assertEqual(r['status'],'unresolved')
        self.assertFalse(r['selected'])

    def test_search_limit_never_yields_a_partial_search_winner(self):
        r=select_body_candidates([part('body','Body','$a == 0','$b == 1')],max_states=2)
        self.assertEqual(r['status'],'search_limited')
        self.assertFalse(r['selected'])

    def test_clothing_exclusion_wins_over_nipple_label(self):
        r=select_body_candidates([part('detail','Nipple ring'),part('body','Body')])
        self.assertEqual(r['selected'],['body'])
        self.assertEqual(r['excluded'][0]['reason'],'clothes')

    def test_inferred_skin_label_is_valid_only_in_its_evidenced_state(self):
        row=part('maybe','[source nude toggle state]','$dress == 1')
        row['neutral_controls']={'dress':0}
        r=select_body_candidates([row])
        self.assertFalse(r['selected'])

    def test_source_program_recomputes_derived_selectors(self):
        import tempfile
        from pathlib import Path
        from source_controls import load_control_program
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'mod.ini'
            p.write_text('[Constants]\nglobal persist $dress=1\nglobal $base=0\n'
                '[KeyDress]\ntype=cycle\n$dress=0,1\n[Present]\n$base=1-$dress\n',encoding='utf-8')
            r=select_body_candidates([part('body','Body','$base == 1')],load_control_program(p))
            self.assertEqual(r['status'],'selected')
            self.assertEqual(r['controls']['dress'],0)
            self.assertEqual(r['resolved_controls']['base'],1)

    def test_immutable_false_branch_cannot_supply_missing_hands(self):
        import tempfile
        from pathlib import Path
        from source_controls import load_control_program
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'mod.ini'
            p.write_text('[Constants]\nglobal $fixed=0\n[TextureOverrideBody]\nif $fixed==1\nendif\n',encoding='utf-8')
            r=select_body_candidates([part('body','Body'),part('hands','Hands','$fixed==1')],load_control_program(p))
            self.assertEqual(r['selected'],['body'])

