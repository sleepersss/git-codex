"""Explicit user-run installer; no administrator privileges needed."""
import json
from pathlib import Path
import re
import sys
import winreg

HOST='com.sleepersss.game_download'
KEY=rf'Software\Microsoft\Edge\NativeMessagingHosts\{HOST}'
HERE=Path(__file__).resolve().parent

def install(extension_id):
    if not re.fullmatch('[a-p]{32}',extension_id):
        raise ValueError('插件 ID 必须是32位 a-p 字母，请从插件设置页复制')
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY) as key:
            previous=winreg.QueryValueEx(key,'')[0]
            if Path(previous).resolve()!= (HERE/'host-manifest.json').resolve():
                raise ValueError('此助手名称已有其他注册路径，请先核实旧注册；未覆盖')
    except FileNotFoundError: pass
    launcher=HERE/'host.cmd'
    launcher.write_text(f'@echo off\r\n"{sys.executable}" -u "{HERE / "archive_helper.py"}" %*\r\n',encoding='utf-8')
    manifest=HERE/'host-manifest.json'
    manifest.write_text(json.dumps({'name':HOST,'description':'Game download archive helper','path':str(launcher),'type':'stdio','allowed_origins':[f'chrome-extension://{extension_id}/']},indent=2),encoding='utf-8')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,KEY) as key:
        winreg.SetValueEx(key,'',0,winreg.REG_SZ,str(manifest))
    print('助手已注册。请回到插件设置页点击“检查助手连接”。')

def uninstall():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY) as key:
            previous=winreg.QueryValueEx(key,'')[0]
            if Path(previous).resolve()!=(HERE/'host-manifest.json').resolve():
                raise ValueError('注册指向其他项目，未移除')
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER,KEY)
    except FileNotFoundError: pass
    print('助手注册已移除。项目文件和已归档游戏均保留。')

if __name__=='__main__':
    try:
        if '--uninstall' in sys.argv: uninstall()
        else: install(input('请输入 Edge 插件 ID：').strip())
    except Exception as error:
        print('未完成：'+str(error));sys.exit(1)
