import unittest,tempfile,os
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from desktop import MainWindow
from task_service import TaskService

class DesktopTests(unittest.TestCase):
    def test_task_delete_waits_for_second_confirmation(self):
        from unittest.mock import patch
        self.window.run=Path(self.t.name)
        with patch.object(self.window,'confirm_delete',return_value=False),patch.object(self.window.deletion,'start') as start:
            self.window.delete_current_task();start.assert_not_called()
        with patch.object(self.window,'confirm_delete',return_value=True),patch.object(self.window.deletion,'start') as start:
            self.window.delete_current_task()
            self.assertEqual(start.call_args.args,('task',));self.assertEqual(start.call_args.kwargs['run'],Path(self.t.name))
    def test_asset_delete_waits_for_second_confirmation_and_uses_selected_id(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QTableWidgetItem
        self.window.docs=[{'id':'WW-000032','target_character':'Fixture'}]
        self.window.assets.blockSignals(True);self.window.assets.setRowCount(1)
        self.window.assets.setItem(0,0,QTableWidgetItem('WW-000032'));self.window.assets.selectRow(0);self.window.assets.blockSignals(False)
        with patch.object(self.window,'confirm_delete',return_value=False),patch.object(self.window.deletion,'start') as start:
            self.window.delete_current_asset();start.assert_not_called()
        with patch.object(self.window,'confirm_delete',return_value=True),patch.object(self.window.deletion,'start') as start:
            self.window.delete_current_asset();self.assertEqual(start.call_args.kwargs['asset_id'],'WW-000032')
    def test_confirmation_dialog_defaults_to_cancel_and_requires_explicit_delete(self):
        from PySide6.QtCore import QTimer
        def click(text):
            box=QApplication.activeModalWidget();self.assertEqual(box.defaultButton().text(),'取消')
            next(button for button in box.buttons() if button.text()==text).click()
        QTimer.singleShot(0,lambda:click('取消'))
        self.assertFalse(self.window.confirm_delete('test','cancel case'))
        QTimer.singleShot(0,lambda:click('确认删除'))
        self.assertTrue(self.window.confirm_delete('test','delete case'))
    def test_manual_button_requires_verified_full_and_opens_selected_task(self):
        import json
        from unittest.mock import patch
        run=Path(self.t.name);(run/'models').mkdir();(run/'models/full.blend').write_bytes(b'BLENDER')
        blender=run/'blender.exe';blender.touch();self.window.config['blender']=str(blender)
        (run/'pipeline-result.json').write_text(json.dumps({'status':'passed','full_status':'verified',
            'body_status':'unverified','body_reason':{}}),encoding='utf-8')
        self.window.handle_event({'task_id':'manual','stage':'task','status':'passed','message':'已保存',
            'artifacts':{'run':str(run),'body_status':'unverified','full_status':'verified'}})
        self.assertTrue(self.window.manual_body_button.isEnabled())
        with patch.object(self.window.manual_body,'start') as started:
            self.window.manual_body_button.click()
        started.assert_called_once_with(run,str(blender))
        self.assertIn('Ctrl+S',self.window.result_label.text())
    def test_manual_report_is_opened_when_present(self):
        from unittest.mock import patch
        self.window.run=Path(self.t.name)
        report=self.window.run/'manual-body.html';report.write_text('manual',encoding='utf-8')
        with patch.object(self.window,'open_path') as opened:self.window.open_report()
        self.assertEqual(opened.call_args.args[0],report)
    def test_partial_full_never_enables_manual_button(self):
        import json
        run=Path(self.t.name);(run/'models').mkdir();(run/'models/full.blend').write_bytes(b'BLENDER')
        blender=run/'blender.exe';blender.touch();self.window.config['blender']=str(blender)
        (run/'pipeline-result.json').write_text(json.dumps({'status':'passed','full_status':'partial',
            'body_status':'unverified','body_reason':{}}),encoding='utf-8')
        self.window.run=run;self.window.update_manual_controls()
        self.assertFalse(self.window.manual_body_button.isEnabled())
    def test_running_to_partial_on_selected_row_keeps_partial_message(self):
        self.window.handle_event({'task_id':'partial-running','stage':'import','status':'running','message':'保存中',
            'artifacts':{}})
        self.window.handle_event({'task_id':'partial-running','stage':'task','status':'passed','message':'源基础网格已保存；动态未还原',
            'artifacts':{'body_status':'unverified','full_status':'partial'}})
        self.assertIn('动态',self.window.result_label.text())
        self.assertFalse(self.window.import_button.isEnabled())
    def test_runtime_partial_result_disables_import(self):
        import json
        self.window.run=Path(self.t.name)
        (self.window.run/'pipeline-result.json').write_text(json.dumps({'status':'passed','full_status':'partial',
            'body_status':'unverified','body_reason':{'message':'动态尚未还原'}}),encoding='utf-8')
        self.window.handle_event({'task_id':'partial','stage':'task','status':'passed','message':'基础网格已保存',
            'artifacts':{'run':self.t.name,'body_status':'unverified','full_status':'partial'}})
        self.assertFalse(self.window.import_button.isEnabled())
        self.assertIn('动态',self.window.tasks.item(0,2).text())
        self.assertNotIn('Mod 模型已核对',self.window.result_label.text())
    def test_result_report_opens_readable_body_review(self):
        from unittest.mock import patch
        self.window.run=Path(self.t.name)
        report=self.window.run/'body-review.html';report.write_text('review',encoding='utf-8')
        with patch.object(self.window,'open_path') as opened:
            self.window.open_report()
        self.assertEqual(opened.call_args.args[0],report)
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();p=Path(self.t.name)
        self.window=MainWindow(TaskService(),p/'library',{'work_root':str(p/'work'),'library_root':str(p/'library')})
    def tearDown(self):self.window.close();self.t.cleanup()
    def test_missing_dependencies_disable_start(self):self.assertFalse(self.window.start_button.isEnabled())
    def test_abandoned_has_full_result_only(self):
        self.window.handle_event({'task_id':'test','stage':'task','status':'passed','message':'已完成',
            'artifacts':{'run':self.t.name,'body_status':'abandoned'}})
        self.assertTrue(self.window.open_button.isEnabled())
        self.assertFalse(self.window.open_body_button.isEnabled())
        self.assertIn('裸模',self.window.result_label.text())
    def test_unknown_game_disables_start(self):
        self.window.game_choice.setCurrentIndex(2)
        self.assertFalse(self.window.start_button.isEnabled())
    def test_available_body_does_not_show_abandoned(self):
        import json
        (Path(self.t.name)/'pipeline-result.json').write_text(json.dumps({'status':'passed','body_status':'available','body_reason':{'message':'源裸模已保存并核对。'}}))
        self.window.handle_event({'task_id':'test','stage':'task','status':'passed','message':'已完成',
            'artifacts':{'run':self.t.name,'body_status':'available'}})
        self.assertTrue(self.window.open_body_button.isEnabled())
        self.assertNotIn('放弃',self.window.result_label.text())
        self.assertIn('裸模',self.window.tasks.item(0,2).text())
