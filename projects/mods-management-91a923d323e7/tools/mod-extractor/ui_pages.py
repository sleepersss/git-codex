"""Qt pages with live text, opaque panels and independent result states."""
import json
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QUrl
from PySide6.QtGui import QDesktopServices,QPixmap
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QLineEdit,QComboBox,QStackedWidget,QListWidget,QTableWidget,QTableWidgetItem,QHeaderView,
    QFileDialog,QMessageBox,QFormLayout,QGroupBox,QTextEdit)
from app_paths import check_dependencies,default_config_path,APP_VERSION
from library_service import list_assets,import_result,display_warning
from discovery import discover_mod
from manual_body import ManualBodyService
from record_deletion import DeletionService

SAMPLES={'denia':('达妮娅 · 已核对来源',r'E:\1_Game\Wuthering Waves\WWMI\Mods\denia\达妮娅-原版 女仆 束缚v1.0full(？)by VeloriaLab'),
         'iuno':('尤诺 · 已核对来源',r'E:\1_Game\Wuthering Waves\WWMI\Mods\iuno\尤诺 半果.zip')}
STYLE='''
QWidget { background: #F8FAFC; color: #0F172A; }
QGroupBox { background: white; border: 1px solid #CBD5E1; border-radius: 8px; margin-top: 12px; padding: 16px; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; }
QLineEdit,QComboBox,QTextEdit,QTableWidget,QListWidget { background: white; border: 1px solid #CBD5E1; border-radius: 5px; padding: 7px; }
QPushButton { background: white; border: 1px solid #94A3B8; border-radius: 5px; padding: 9px 16px; }
QPushButton:hover { background: #EFF6FF; border-color: #2563EB; }
QPushButton:focus,QLineEdit:focus,QComboBox:focus { border: 2px solid #2563EB; }
QPushButton#primary { background: #2563EB; color: white; border: 1px solid #2563EB; }
QPushButton:disabled { background: #E2E8F0; color: #475569; border-color: #CBD5E1; }
QListWidget::item { padding: 12px; }
QListWidget::item:selected,QTableWidget::item:selected { background: #DBEAFE; color: #1E40AF; }
QHeaderView::section { background: #F1F5F9; border: 0; padding: 9px; font-weight: 600; }
QLabel#muted { color: #475569; }
'''
def label(text,muted=False):
    w=QLabel(text);w.setWordWrap(True);w.setTextInteractionFlags(Qt.TextSelectableByMouse)
    if muted:w.setObjectName('muted')
    return w
def table(headers):
    w=QTableWidget(0,len(headers));w.setHorizontalHeaderLabels(headers);w.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    w.verticalHeader().hide();w.setEditTriggers(QTableWidget.NoEditTriggers);w.setSelectionBehavior(QTableWidget.SelectRows);return w

class MainWindow(QMainWindow):
    def __init__(self,task_service,library_root,config):
        super().__init__();self.service=task_service;self.library_root=Path(library_root);self.config=dict(config)
        self.run=None;self.active_task=None;self.docs=[];self.task_rows={};self.manual_body=ManualBodyService();self.deletion=DeletionService()
        self.setWindowTitle('Mod 素材提取工具 v'+APP_VERSION);self.resize(1180,760);self.setMinimumSize(820,580);self.setStyleSheet(STYLE)
        central=QWidget();self.setCentralWidget(central);outer=QVBoxLayout(central);outer.setContentsMargins(22,18,22,18);outer.setSpacing(16)
        header=QHBoxLayout();title=label('Mod 素材提取工具');title.setStyleSheet('font-size: 22px; font-weight: 600;');header.addWidget(title);header.addStretch()
        self.environment=label('检测环境');header.addWidget(self.environment);outer.addLayout(header)
        content=QHBoxLayout();outer.addLayout(content,1);self.nav=QListWidget();self.nav.addItems(['提取任务','素材库','设置']);self.nav.setFixedWidth(154);content.addWidget(self.nav)
        self.pages=QStackedWidget();content.addWidget(self.pages,1)
        for page in (self.make_tasks(),self.make_library(),self.make_settings()):self.pages.addWidget(page)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex);self.nav.setCurrentRow(0)
        outer.addWidget(label('本地运行 · 原 Mod 只读 · 不完整裸模直接放弃',True))
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(150)
        self.check_ready();self.load_library();self.load_tasks()
    def make_tasks(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);box=QGroupBox('新建提取任务');form=QFormLayout(box)
        choices=QHBoxLayout();self.game_choice=QComboBox();self.game_choice.addItems(['自动识别','鸣潮','崩坏：星穹铁道','绝区零']);self.profile_choice=QComboBox()
        choices.addWidget(self.game_choice);choices.addWidget(self.profile_choice,1);form.addRow('游戏 / 来源适配',choices)
        row=QHBoxLayout();self.source=QLineEdit();self.source.setPlaceholderText('选择任意人物的 Mod 文件夹');self.source.setClearButtonEnabled(True);row.addWidget(self.source,1)
        self.source.setCursorPosition(0)
        browse=QPushButton('选择文件夹');browse.clicked.connect(self.browse_source);row.addWidget(browse);form.addRow('来源文件夹',row)
        self.work_label=label(str(self.config['work_root']),True);form.addRow('任务保存位置',self.work_label)
        form.addRow(label('无法得到完整裸模时，放弃裸模生成；保留从 Mod 提取出的模型和原因记录。'))
        actions=QHBoxLayout();self.start_button=QPushButton('开始提取');self.start_button.setObjectName('primary');self.start_button.clicked.connect(self.start)
        self.cancel_button=QPushButton('取消任务');self.cancel_button.setEnabled(False);self.cancel_button.clicked.connect(self.cancel)
        actions.addWidget(self.start_button);actions.addWidget(self.cancel_button);actions.addStretch();form.addRow(actions)
        self.ready_label=label('',True);form.addRow(self.ready_label);layout.addWidget(box)
        self.tasks=table(['来源','当前阶段','处理结果']);self.tasks.itemSelectionChanged.connect(self.select_task);layout.addWidget(self.tasks,1)
        detail=QGroupBox('任务结果');details=QVBoxLayout(detail);self.result_label=label('选择来源，开始一次新任务。');self.run_label=label('',True)
        details.addWidget(self.result_label);details.addWidget(self.run_label);buttons=QHBoxLayout()
        self.open_button=QPushButton('打开 Mod 模型目录');self.report_button=QPushButton('查看任务报告 / 日志');self.import_button=QPushButton('保存到素材库');self.open_body_button=QPushButton('打开裸模')
        self.open_body_button.clicked.connect(lambda:self.open_path(self.run/'models/body.blend' if self.run else None))
        self.open_button.clicked.connect(lambda:self.open_path(self.run/'models' if self.run else None))
        self.report_button.clicked.connect(self.open_report);self.import_button.clicked.connect(self.import_current)
        for b in (self.open_button,self.open_body_button,self.report_button,self.import_button):b.setEnabled(False);buttons.addWidget(b)
        buttons.addStretch();details.addLayout(buttons);layout.addWidget(detail)
        self.manual_body_button=QPushButton('打开 full.blend 手动删减');self.manual_body_button.setEnabled(False)
        self.manual_body_button.setToolTip('删除多余模型并保存后退出 Blender，自动生成 body.blend；未保存或模型未删减则不生成。')
        self.manual_body_button.clicked.connect(self.edit_manual_body)
        more=QHBoxLayout();more.addWidget(self.manual_body_button)
        self.delete_task_button=QPushButton('删除处理记录和工作文件');self.delete_task_button.setEnabled(False)
        self.delete_task_button.clicked.connect(self.delete_current_task);more.addWidget(self.delete_task_button);more.addStretch();details.addLayout(more)
        self.game_choice.currentIndexChanged.connect(self.check_ready);self.source.textChanged.connect(self.check_ready);return page
    def browse_source(self):
        p=QFileDialog.getExistingDirectory(self,'选择本地 Mod 文件夹',self.source.text())
        if p:self.source.setText(p)
    def choose_profile(self):
        self.source.setText(SAMPLES[self.profile_choice.currentData()][1]);self.source.setCursorPosition(0);self.check_ready()
    def check_ready(self):
        missing=[r['name'] for r in check_dependencies(self.config) if not r['ok']]
        key=(self.source.text(),self.game_choice.currentIndex())
        if getattr(self,'discovery_key',None)!=key:
            self.discovery_key=key
            self.detected=discover_mod(self.source.text(),[None,'WW','HSR','ZZZ'][self.game_choice.currentIndex()]) if self.source.text() else {'supported':False,'message':'请选择 Mod 文件夹。','candidates':[]}
            self.profile_choice.clear()
            for c in self.detected['candidates']:
                if c['valid']:self.profile_choice.addItem(c['ini'],c['ini'])
            self.profile_choice.setCurrentIndex(self.profile_choice.findData(self.detected.get('selected_ini')))
        supported=self.detected['supported'];exists=bool(self.source.text()) and Path(self.source.text()).is_dir()
        self.environment.setText('本机环境：待配置' if missing else '本机环境：已就绪');self.start_button.setEnabled(not missing and supported and exists and not self.service.busy and not self.manual_body.busy and not self.deletion.busy)
        game={'WW':'鸣潮','HSR':'崩坏：星穹铁道','ZZZ':'绝区零'}.get(self.detected.get('game'),'游戏未识别')
        self.ready_label.setText('请在设置中配置：'+ '、'.join(missing) if missing else self.detected['message']+' · '+game+' · 静态模型包含切换变体。')
    def start(self):
        try:
            if self.deletion.busy:raise ValueError('删除操作结束后再开始新任务')
            choice={'ini':self.profile_choice.currentData(),'game':self.detected['game']}
            self.active_task=self.service.start(choice,Path(self.source.text()),dict(self.config));self.run=None
            for b in (self.open_button,self.open_body_button,self.report_button,self.import_button):b.setEnabled(False)
            self.cancel_button.setEnabled(True);self.check_ready()
        except Exception as e:QMessageBox.warning(self,'无法开始',str(e))
    def cancel(self):self.service.cancel(self.active_task)
    def poll(self):
        for e in self.service.drain():self.handle_event(e)
        for e in self.manual_body.drain():
            if self.run and self.run.resolve()==Path(e['run']).resolve():
                self.select_task();self.result_label.setText(e['message'])
            if e['status']=='passed':
                for row in range(self.tasks.rowCount()):
                    data=self.tasks.item(row,0).data(Qt.UserRole) or {}
                    if data.get('run') and Path(data['run']).resolve()==Path(e['run']).resolve():
                        self.tasks.item(row,1).setText('手动删减已保存并核对');self.tasks.item(row,2).setText('Mod 与裸模已保存')
        for e in self.deletion.drain():
            if not e['ok']:
                QMessageBox.warning(self,'删除未完成',e['error']);self.select_task();self.load_library();continue
            if e['kind']=='task':
                self.tasks.blockSignals(True);self.tasks.setRowCount(0);self.task_rows.clear();self.tasks.blockSignals(False)
                self.run=None;self.current_log=None;self.load_tasks();self.clear_task_result()
            else:self.load_library()
            message='处理记录及对应工作文件已删除。' if e['kind']=='task' else '所选素材已删除，索引已同步；原 Mod 和来源备份保留。'
            message+='恢复归档：'+e['archive']
            if e['status']=='deleted_cleanup_pending':message+=' 部分占用文件待清理：'+e['pending']
            if e['kind']=='task':self.result_label.setText(message)
            else:self.asset_details.setPlainText(message)
        self.update_manual_controls()
        self.cancel_button.setEnabled(self.service.busy);self.check_ready()
    def handle_event(self,e):
        task=e['task_id'];row=self.task_rows.get(task)
        if row is None:
            row=self.tasks.rowCount();self.tasks.insertRow(row);self.task_rows[task]=row
            for c in range(3):self.tasks.setItem(row,c,QTableWidgetItem(''))
            self.tasks.item(row,0).setText(Path(self.source.text()).name)
        saved=self.tasks.item(row,0).data(Qt.UserRole) or {};saved.update(e.get('artifacts',{}));self.tasks.item(row,0).setData(Qt.UserRole,saved)
        self.tasks.item(row,1).setText(e.get('message',''));status=e['status']
        body_status=saved.get('body_status','unverified')
        self.tasks.item(row,2).setText({'running':'处理中','passed':{'available':'Mod 与裸模已保存','abandoned':'Mod 已保存 · 裸模已放弃','unverified':'Mod 已保存 · 身体待核对'}[body_status],'failed':'处理失败','cancelled':'已取消'}.get(status,status))
        if status=='passed' and saved.get('full_status')=='partial':self.tasks.item(row,2).setText('基础网格已保存 · 动态未还原')
        self.result_label.setText(e.get('message',''))
        if saved.get('run'):self.run=Path(saved['run']);self.run_label.setText(str(self.run))
        if status=='passed':
            self.result_label.setText({'available':'Mod 模型与源裸模均已保存并核对。','abandoned':'Mod 模型已保存；源身体存在肢体缺口，裸模已放弃。','unverified':'Mod 模型已保存；身体分组或完整性待核对，请查看任务报告。'}[body_status])
            for b in (self.open_button,self.report_button,self.import_button):b.setEnabled(True)
            if saved.get('full_status')=='partial':
                self.import_button.setEnabled(False)
                self.result_label.setText('源基础网格已保存；动态形态尚未还原，不能作为完整 Mod 入库。')
            self.open_body_button.setEnabled(body_status=='available')
        elif status in ('failed','cancelled'):
            self.open_button.setEnabled(False);self.open_body_button.setEnabled(False);self.import_button.setEnabled(False)
            self.report_button.setEnabled(bool(saved.get('log')))
        self.tasks.selectRow(row)
        self.tasks.scrollToItem(self.tasks.item(row,0))
        self.update_manual_controls()
    def select_task(self):
        row=self.tasks.currentRow()
        if row<0:self.clear_task_result();return
        self.clear_task_result()
        data=self.tasks.item(row,0).data(Qt.UserRole) or {};self.run=Path(data['run']) if data.get('run') else None
        self.open_button.setEnabled(bool(self.run and self.run.is_dir()))
        self.current_log=data.get('log');self.report_button.setEnabled(bool(self.current_log))
        self.open_body_button.setEnabled(False)
        self.manual_body_button.setEnabled(False)
        self.run_label.setText(str(self.run) if self.run else '')
        if self.run and (self.run/'pipeline-result.json').exists():
            r=json.loads((self.run/'pipeline-result.json').read_text(encoding='utf-8'));passed=r['status']=='passed'
            self.open_button.setEnabled(passed);self.import_button.setEnabled(passed and r.get('full_status','verified')=='verified' and 'body_status' in r);self.report_button.setEnabled(True)
            self.open_body_button.setEnabled(passed and r.get('body_status')=='available')
            prefix='源基础网格已保存。' if r.get('full_status')=='partial' else 'Mod 模型已核对。'
            self.result_label.setText(prefix+r.get('body_reason',{}).get('message','旧规则结果，仅供历史查阅。') if passed else r.get('error','处理中或未完成，不能入库。'))
            if passed and display_warning(r):self.result_label.setText(self.result_label.text()+display_warning(r))
        self.update_manual_controls()
    def update_manual_controls(self):
        eligible=False;deletable=False
        if self.run and (self.run/'pipeline-result.json').is_file():
            try:
                r=json.loads((self.run/'pipeline-result.json').read_text(encoding='utf-8'))
                eligible=r.get('status')=='passed' and r.get('full_status')=='verified' and (self.run/'models/full.blend').is_file()
                deletable=r.get('status') in ('passed','failed','cancelled')
            except (OSError,ValueError):pass
        idle=not self.service.busy and not self.manual_body.busy and not self.deletion.busy
        self.manual_body_button.setEnabled(eligible and idle and Path(self.config.get('blender','')).is_file())
        self.delete_task_button.setEnabled(deletable and idle)
        if hasattr(self,'delete_asset_button'):self.delete_asset_button.setEnabled(idle and 0<=self.assets.currentRow()<len(self.docs))
        if self.manual_body.busy or self.deletion.busy:self.import_button.setEnabled(False)
    def clear_task_result(self):
        for button in (self.open_button,self.open_body_button,self.report_button,self.import_button,self.manual_body_button,self.delete_task_button):button.setEnabled(False)
        self.run_label.setText('')
    def confirm_delete(self,title,message):
        box=QMessageBox(QMessageBox.Warning,title,message,QMessageBox.NoButton,self)
        confirm=box.addButton('确认删除',QMessageBox.DestructiveRole);cancel=box.addButton('取消',QMessageBox.RejectRole)
        box.setDefaultButton(cancel);box.setEscapeButton(cancel);box.exec()
        return box.clickedButton() is confirm
    def delete_current_task(self):
        if self.service.busy or self.manual_body.busy or self.deletion.busy:return
        if not self.run:return
        selected=self.run
        if not self.confirm_delete('删除处理记录','将删除本条处理记录及对应 work 文件夹内的全部文件。已归档素材保留。\n\n'+str(selected)+'\n\n删除前会核验恢复归档。'):return
        self.deletion.start('task',run=selected,work_root=Path(self.config['work_root']),library_root=self.library_root)
        self.result_label.setText('正在归档并删除所选处理记录和工作文件……');self.update_manual_controls();self.check_ready()
    def delete_current_asset(self):
        if self.service.busy or self.manual_body.busy or self.deletion.busy:return
        row=self.assets.currentRow()
        if not 0<=row<len(self.docs):return
        doc=self.docs[row];ident=doc['id']
        if not self.confirm_delete('删除所选素材','将删除所选素材的模型、预览、测量及核验资料，并移除素材库记录。原 Mod、来源备份和其他素材保留。\n\n'+ident+' / '+doc['target_character']+'\n\n删除前会核验恢复归档。'):return
        self.deletion.start('asset',library_root=self.library_root,asset_id=ident)
        self.asset_details.setPlainText('正在归档并删除所选素材……');self.update_manual_controls();self.check_ready()
    def edit_manual_body(self):
        try:
            if self.service.busy or self.deletion.busy:raise ValueError('当前任务结束后再手动删减')
            self.manual_body.start(self.run,self.config['blender'])
            self.result_label.setText('已打开 full.blend 副本：删除多余模型，按 Ctrl+S 保存并退出 Blender。退出后自动测量并生成 body.blend；不保存或没有删减则不生成。')
            self.update_manual_controls();self.check_ready()
        except Exception as e:QMessageBox.warning(self,'无法打开手动删减',str(e))
    def open_report(self):
        if self.run and (self.run/'manual-body.html').is_file():
            self.open_path(self.run/'manual-body.html');return
        if self.run and (self.run/'body-review.html').is_file():
            self.open_path(self.run/'body-review.html');return
        path=self.run/'pipeline-result.json' if self.run else None
        self.open_path(path if path and path.exists() else getattr(self,'current_log',None))
    def load_tasks(self):
        root=Path(self.config['work_root'])
        for p in sorted(root.glob('mod-extraction-*/pipeline-result.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:25]:
            try:
                d=json.loads(p.read_text(encoding='utf-8'));row=self.tasks.rowCount();self.tasks.insertRow(row)
                for c,t in enumerate((d.get('title') or d.get('profile','历史任务'),'历史记录','旧规则记录' if 'body_status' not in d else {'available':'裸模可用','abandoned':'裸模已放弃','unverified':'身体待核对'}.get(d.get('body_status'),'未完成') if d['status']=='passed' else d['status'])):self.tasks.setItem(row,c,QTableWidgetItem(t))
                self.tasks.item(row,0).setData(Qt.UserRole,{'run':str(p.parent)})
            except (OSError,ValueError):continue
    def import_current(self):
        try:
            if self.manual_body.busy or self.deletion.busy:raise ValueError('请先等待当前手动删减或删除操作结束')
            d=import_result(self.library_root,self.run);self.result_label.setText('素材库记录：'+d['id']+'；原来源与永久编号保留。');self.load_library()
        except Exception as e:QMessageBox.warning(self,'入库未完成',str(e))
    @staticmethod
    def open_path(path):
        if path and Path(path).exists():QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))
    def make_library(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);row=QHBoxLayout()
        self.search=QLineEdit();self.search.setPlaceholderText('搜索人物、游戏、作者或编号');row.addWidget(self.search,1)
        self.filter=QComboBox();self.filter.addItems(['全部素材','裸模可用','裸模已放弃','裸模未确认']);row.addWidget(self.filter)
        b=QPushButton('刷新');b.clicked.connect(self.load_library);row.addWidget(b);layout.addLayout(row)
        self.assets=table(['编号 / 人物','游戏','Mod 模型','裸模状态']);layout.addWidget(self.assets,1)
        self.asset_details=QTextEdit();self.asset_details.setReadOnly(True);self.asset_details.setMaximumHeight(150);layout.addWidget(self.asset_details)
        previews=QHBoxLayout();self.preview_labels=[]
        for title in ('正面','背面','侧面','斜侧面'):
            w=QLabel(title);w.setAlignment(Qt.AlignCenter);w.setMinimumSize(100,100);w.setMaximumHeight(140);previews.addWidget(w);self.preview_labels.append(w)
        layout.addLayout(previews);actions=QHBoxLayout();b=QPushButton('打开所选素材目录');b.clicked.connect(self.open_asset);actions.addWidget(b)
        self.delete_asset_button=QPushButton('删除所选素材');self.delete_asset_button.setEnabled(False);self.delete_asset_button.clicked.connect(self.delete_current_asset)
        actions.addWidget(self.delete_asset_button);actions.addStretch();layout.addLayout(actions)
        self.search.textChanged.connect(self.load_library);self.filter.currentIndexChanged.connect(self.load_library);self.assets.itemSelectionChanged.connect(self.select_asset);return page
    def load_library(self):
        try:self.docs=list_assets(self.library_root,self.search.text(),[None,'available','abandoned','unverified'][self.filter.currentIndex()])
        except Exception as e:self.asset_details.setPlainText('素材库读取失败：'+str(e));return
        self.assets.setRowCount(0)
        self.delete_asset_button.setEnabled(False);self.asset_details.clear()
        for preview in self.preview_labels:preview.clear();preview.setText('暂无有效预览')
        for d in self.docs:
            row=self.assets.rowCount();self.assets.insertRow(row)
            values=[d['id']+' / '+d['target_character'],d['game'],'已保存' if 'full' in d['files'] else '未入库',{'available':'可用','abandoned':'已放弃','unverified':'未确认'}.get(d['display_body_status'],'未确认')]
            for c,t in enumerate(values):self.assets.setItem(row,c,QTableWidgetItem(t))
    def select_asset(self):
        row=self.assets.currentRow()
        self.delete_asset_button.setEnabled(0<=row<len(self.docs) and not self.service.busy and not self.manual_body.busy and not self.deletion.busy)
        if not 0<=row<len(self.docs):return
        d=self.docs[row];self.asset_details.setPlainText(d['id']+' · '+d['target_character']+'\n来源：'+d.get('mod_name','')+'\n'+d['extraction'].get('body_reason',{}).get('message','裸模完整性尚未确认。')+'\n缺失说明：'+'；'.join(d.get('body',{}).get('missing_parts',[])))
        if display_warning(d['extraction']):self.asset_details.append(display_warning(d['extraction']))
        for v,w in zip(('front','back','side','three_quarter'),self.preview_labels):
            f=(d['files'].get('preview_'+v) or d['files'].get('full_preview_'+v)) if d['display_body_status']=='available' else d['files'].get('full_preview_'+v)
            if not f:w.clear();w.setText('暂无有效预览');continue
            p=QPixmap(str(self.library_root/f['path']));ratio=w.devicePixelRatioF();target=w.size()*ratio
            if p.width()>target.width() or p.height()>target.height():p=p.scaled(target,Qt.KeepAspectRatio,Qt.SmoothTransformation)
            p.setDevicePixelRatio(ratio);w.setPixmap(p)
    def open_asset(self):
        row=self.assets.currentRow()
        if 0<=row<len(self.docs) and 'full' in self.docs[row]['files']:self.open_path((self.library_root/self.docs[row]['files']['full']['path']).parent)
    def make_settings(self):
        page=QWidget();layout=QVBoxLayout(page);box=QGroupBox('本机工具与保存位置');form=QFormLayout(box);self.settings_fields={}
        for key,title,directory in [('blender','Blender 程序',False),('sword_root','Sword 文件夹',True),('herta_parent','Herta 所在父文件夹',True),('work_root','任务保存目录',True),('library_root','素材库目录',True)]:
            row=QHBoxLayout();f=QLineEdit(self.config.get(key,''));self.settings_fields[key]=f;row.addWidget(f,1)
            b=QPushButton('选择');b.clicked.connect(lambda checked=False,k=key,isdir=directory:self.pick_setting(k,isdir));row.addWidget(b);form.addRow(title,row)
        self.config_status=label('',True);form.addRow(self.config_status);b=QPushButton('保存并检测');b.clicked.connect(self.save_settings);form.addRow(b)
        form.addRow(label('使用本机已有第三方工具；不修改其原设置。无需联网或打开 Codex。',True));layout.addWidget(box);layout.addStretch();return page
    def pick_setting(self,key,directory):
        p=QFileDialog.getExistingDirectory(self,'选择目录') if directory else QFileDialog.getOpenFileName(self,'选择 Blender 程序',filter='程序 (*.exe)')[0]
        if p:self.settings_fields[key].setText(p)
    def save_settings(self):
        if self.service.busy or self.manual_body.busy or self.deletion.busy:QMessageBox.information(self,'任务正在运行','当前任务结束后可修改设置。');return
        cfg={k:f.text().strip() for k,f in self.settings_fields.items()}
        if not cfg['work_root'] or not cfg['library_root']:self.config_status.setText('请设置任务与素材库目录。');return
        try:
            path=Path(self.config.get('config_path',str(default_config_path())));path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
            self.config={**cfg,'config_path':str(path)};self.library_root=Path(cfg['library_root']);self.work_label.setText(cfg['work_root'])
            self.config_status.setText('；'.join(r['name']+('：已找到' if r['ok'] else '：未找到') for r in check_dependencies(cfg)));self.check_ready();self.load_library()
        except Exception as e:self.config_status.setText('保存失败：'+str(e))
    def closeEvent(self,event):
        if self.deletion.busy:
            QMessageBox.information(self,'删除尚未结束','请等待恢复归档核验与删除操作结束后再关闭工具。');event.ignore();return
        if self.manual_body.busy:
            QMessageBox.information(self,'手动删减尚未结束','请先退出本次 Blender 窗口，并等待身体处理结束后再关闭提取工具。');event.ignore();return
        if self.service.busy:
            if QMessageBox.question(self,'任务仍在运行','取消本次任务并关闭窗口？',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:event.ignore();return
            self.service.cancel(self.service.task_id)
        event.accept()
