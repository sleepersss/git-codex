import tempfile,unittest
from pathlib import Path
from source_controls import load_control_program


class SourceControlTests(unittest.TestCase):
    def test_immutable_constant_cannot_be_expanded_from_comparison(self):
        p=self.load('[Constants]\nglobal $fixed=0\n[TextureOverrideBody]\nif $fixed==1\nendif\n')
        self.assertEqual(p.domains_for({'fixed'}),{'fixed':[0]})
        with self.assertRaises(ValueError):p.resolve({'fixed':1})
    def test_key_selector_mutated_by_present_is_still_enumerated(self):
        p=self.load('[Constants]\nglobal persist $v=0\n[KeyV]\ntype=cycle\n$v=0,1,2\n'
            '[Present]\nif $v==2\n$v=0\nendif\n')
        self.assertEqual(p.domains_for({'v'}),{'v':[0,1,2]})
        self.assertEqual(p.resolve({'v':1})['v'],1)
        self.assertEqual(p.resolve({'v':2})['v'],0)
    def load(self,text):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        p=Path(t.name)/'mod.ini';p.write_text(text,encoding='utf-8')
        return load_control_program(p)

    def test_present_branch_is_frozen_when_it_changes_control(self):
        p=self.load('[Constants]\nglobal persist $v=0\nglobal $base=0\n'
            '[Present]\nif $v==0\n$v=1\n$base=2\nelse\n$base=3\nendif\n')
        self.assertEqual(p.resolve({})['base'],2)

    def test_unknown_present_does_not_keep_declared_default(self):
        p=self.load('[Constants]\nglobal $base=1\n[Present]\nif $runtime\n$base=0\nendif\n')
        self.assertNotIn('base',p.resolve({}))

    def test_key_cycle_domain_excludes_invented_values(self):
        p=self.load('[Constants]\nglobal persist $v=2\n[KeyV]\ntype=cycle\n$v=2,4\n')
        self.assertEqual(p.domains_for({'v'}),{'v':[2,4]})
        with self.assertRaises(ValueError):p.resolve({'v':3})

    def test_undeclared_runtime_selector_has_no_search_domain(self):
        p=self.load('[Present]\nif $runtime==1\n$base=1\nendif\n')
        self.assertEqual(p.domains_for({'runtime'}),{})
        with self.assertRaises(ValueError):p.resolve({'runtime':1})

    def test_derived_search_does_not_include_unrelated_present_sliders(self):
        p=self.load('[Constants]\nglobal persist $dress=1\nglobal persist $slider=0\nglobal $base=0\n'
            '[KeyDress]\ntype=cycle\n$dress=0,1\n[KeySlider]\ntype=cycle\n$slider=0,1\n'
            '[Present]\n$base=1-$dress\n$unused=$slider\n')
        self.assertEqual(p.domains_for({'base'}),{'dress':[0,1]})
        self.assertNotIn('slider',p.domains_for({'base'}))

    def test_persist_menu_writes_do_not_drop_present_defaults(self):
        p=self.load('[Constants]\nglobal persist $siwa=0\nglobal persist $xiashen0=0\n'
            '[Present]\nif $siwa == 0\n$xiashen0 = 1\nelif $siwa == 1\n$xiashen0 = 0\nendif\n'
            '[CommandListMenu]\n$siwa = 1\n$xiashen0 = 0\n')
        self.assertEqual(p.resolve({})['xiashen0'],1)
        self.assertEqual(p.domains_for({'siwa'}),{'siwa':[0,1]})

    def test_missing_framework_shader_does_not_abort_present(self):
        p=self.load('[Constants]\nglobal $base=0\n[Present]\nrun=CommandListInit\n'
            '[CommandListInit]\nrun=CustomShader\\WWMIv1\\BlendRemapper\n'
            'run=BuiltinCommandListUnbindAllRenderTargets\n$base=1\n')
        self.assertEqual(p.resolve({})['base'],1)

    def test_called_present_is_evaluated_without_executing_source(self):
        p=self.load('[Constants]\nglobal persist $v=0\nglobal $base=0\n'
            '[Present]\nrun=CommandListSet\n[CommandListSet]\n$base=2+$v\n')
        self.assertEqual(p.resolve({})['base'],2)

    def test_unknown_guarded_call_invalidates_target(self):
        p=self.load('[Constants]\nglobal $base=1\n[Present]\nif $runtime\nrun=CommandListSet\nendif\n'
            '[CommandListSet]\n$base=0\n')
        self.assertNotIn('base',p.resolve({}))

