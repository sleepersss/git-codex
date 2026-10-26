"""Portable Mod asset registry. Metadata is authoritative; SQLite is disposable."""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from contextlib import closing

ROOT = Path(__file__).resolve().parent
GAMES = {'WW': '鸣潮', 'HSR': '崩坏：星穹铁道', 'ZZZ': '绝区零'}
COMPLETENESS = ('unverified', 'partial', 'complete', 'none')

def now():
    return datetime.now(timezone.utc).isoformat()

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     suffix='.tmp', delete=False) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
        temp = Path(f.name)
    os.replace(temp, path)

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def locate_models(root=ROOT, game=None, character=None, role='all', model_id=None):
    """Read-only daily lookup. JSON wins over a missing/stale SQLite index.

    A callable body is an existing, hash-checked stored source subset with
    recorded verification. This does not certify anatomy, rig or game fit.
    """
    root = Path(root).resolve(strict=True)
    if game is not None and game not in GAMES:
        raise ValueError('游戏必须是 HSR、WW 或 ZZZ')
    if role not in ('all', 'full', 'body'):
        raise ValueError('模型类型必须是 all、full 或 body')
    def inside(relative):
        if Path(relative).is_absolute():
            raise ValueError('素材文件必须使用库内相对路径')
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError('素材路径超出模型库')
        return path
    paths = sorted((root / 'models').glob('*/*/*/metadata.json'))
    documents = [(p, read_json(p)) for p in paths]
    index = {'status': 'unavailable', 'reason': '没有现有 SQLite；直接读取权威 JSON'}
    dbpath = root / 'database/models.sqlite'
    if dbpath.is_file():
        try:
            with closing(sqlite3.connect('file:' + dbpath.as_posix() + '?mode=ro', uri=True)) as db:
                indexed = {r[0] for r in db.execute('SELECT id FROM models')}
            index = {'status': 'present', 'ids_match_json': indexed == {d['id'] for _,d in documents},
                     'reason': '只读检查现有索引；筛选与路径仍以 JSON 为准，不重建数据库'}
        except sqlite3.Error as e:
            index = {'status': 'unavailable', 'reason': str(e)}
    models, excluded = [], []
    for metadata, doc in documents:
        if game and doc.get('game') != game: continue
        if model_id and doc.get('id') != model_id: continue
        if character and str(doc.get('target_character', '')).casefold() != character.casefold(): continue
        files = doc.get('files', {}); errors = []
        def asset(key, hashed=True):
            f = files.get(key)
            if not f: return None
            try:
                p = inside(f['path'])
                if not p.is_file(): raise ValueError('文件不存在')
                if p.stat().st_size != f['size']: raise ValueError('文件大小不匹配')
                if hashed and sha256(p) != f['sha256']: raise ValueError('SHA-256 不匹配')
                return str(p)
            except (OSError, KeyError, ValueError) as e:
                errors.append({'role': key, 'reason': str(e)})
                return None
        full = asset('full')
        extraction = doc.get('extraction', {}); reason = extraction.get('body_reason') or {}
        body_technical = doc.get('technical', {}).get('body') or {}
        evidence = reason.get('evidence') or {}
        scope = body_technical.get('scope') or evidence.get('scope')
        verified = (extraction.get('body_status') == 'available'
                    and extraction.get('body_completeness') == 'verified_scope'
                    and reason.get('reason_code') == 'body_verified' and bool(scope))
        claimed_verified = verified
        proof = None
        if verified:
            for key in ('validation_source_body_source_verification', 'validation_body_source_verification'):
                if key in files:
                    proof = asset(key)
                    if proof and read_json(proof).get('status') != 'passed': proof = None
                    break
            verified = bool(proof)
        body = asset('body') if verified else None
        status = 'available' if body else ('failed' if verified else 'unverified')
        body_reason = ('已核验的源身体子集；解剖完整度、骨架与游戏适配不因此得到确认' if body else
                       reason.get('message') or reason.get('reason_code') or '身体尚未通过可调用验证')
        if claimed_verified and not proof: body_reason = '身体源网格核验文件缺失、校验不一致或未通过，不能调用'
        if verified and not body: body_reason = '身体文件缺失或校验失败，不能调用'
        preview = None
        for key in (('preview_front', 'full_preview_front') if role=='body' and body else ('full_preview_front', 'preview_front')):
            if key in files:
                preview = asset(key)
                if preview: break
        source_metadata = root / 'sources' / doc['game'] / doc['source_id'] / 'metadata.json'
        source_path = None
        if source_metadata.is_file():
            source = read_json(source_metadata)
            if source.get('payload'):
                candidate = inside(source['payload'])
                if candidate.exists(): source_path = str(candidate)
            if not source_path and source.get('original_path'):
                candidate = Path(source['original_path'])
                if candidate.exists(): source_path = str(candidate.resolve())
        row = {'model_id': doc['id'], 'game': doc['game'], 'character': doc.get('target_character'),
               'mod_name': doc.get('mod_name'), 'full_path': full, 'body_path': body,
               'body_status': status, 'body_scope': scope if body else None, 'body_reason': body_reason,
               'preview_path': preview, 'source_path': source_path, 'metadata_path': str(metadata),
               'errors': errors}
        if (role=='body' and not body) or (role=='full' and not full): excluded.append(row)
        else: models.append(row)
    return {'matches': len(models), 'models': models, 'not_callable_models': excluded,
            'sqlite_index': index, 'read_only': True}

def safe_files(path):
    """No symlinks/junctions, including Windows reparse directories."""
    path = Path(path)
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise ValueError(f'不接受链接或联接目录：{path}')
    if path.is_file():
        return [path]
    files = []
    for base, dirs, names in os.walk(path, followlinks=False):
        for name in dirs + names:
            p = Path(base) / name
            if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
                raise ValueError(f'来源含链接或联接目录：{p}')
        files.extend(Path(base) / n for n in sorted(names))
    return sorted(files)

def inventory(path):
    path = Path(path).resolve(strict=True)
    files = safe_files(path)
    rows = [{'path': p.relative_to(path).as_posix() if path.is_dir() else p.name,
             'size': p.stat().st_size, 'sha256': sha256(p)} for p in files]
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False,
                                      separators=(',', ':')).encode()).hexdigest()
    return rows, digest

class Library:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        for folder in ('models', 'sources', 'database', 'cache', 'reports'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        for game in GAMES:
            (self.root / 'models' / game).mkdir(exist_ok=True)
            (self.root / 'sources' / game).mkdir(exist_ok=True)

    def inside(self, relative):
        p = (self.root / relative).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError('路径超出素材库')
        return p

    def documents(self):
        models = [(p, read_json(p)) for p in sorted((self.root / 'models').glob('*/*/*/metadata.json'))]
        sources = [(p, read_json(p)) for p in sorted((self.root / 'sources').glob('*/*/metadata.json'))]
        return models, sources

    def allocate(self, game, source=False):
        if game not in GAMES:
            raise ValueError('游戏必须是 WW、HSR 或 ZZZ')
        prefix = ('SRC-' if source else '') + game + '-'
        documents = self.documents()[1 if source else 0]
        numbers = [int(d['id'].removeprefix(prefix)) for _, d in documents if d['id'].startswith(prefix)]
        if not source:
            # Deleted model IDs remain reserved; existing references must never
            # silently identify a newly registered, unrelated model.
            for path in (self.root / 'history/deleted-assets').glob('*.json'):
                ident = read_json(path).get('id', '')
                if re.fullmatch(re.escape(prefix) + r'\d{6}', ident):
                    numbers.append(int(ident.removeprefix(prefix)))
        return prefix + f'{max(numbers, default=0) + 1:06d}'

    def find(self, ident, source=False):
        for path, doc in self.documents()[1 if source else 0]:
            if doc['id'] == ident:
                return path, doc
        raise ValueError(f'找不到记录：{ident}')

    def source(self, path, game, author=None, url=None, license_note=None):
        path = Path(path).resolve(strict=True)
        if path == self.root or self.root.is_relative_to(path) or path.is_relative_to(self.root):
            raise ValueError('来源不能是素材库自身、其子目录或包含素材库的父目录')
        if not path.is_file() and not path.is_dir():
            raise ValueError('来源必须是普通文件或文件夹')
        manifest, digest = inventory(path)
        if not manifest:
            raise ValueError('来源为空')
        for _, doc in self.documents()[1]:
            if doc['game'] == game and doc['manifest_sha256'] == digest:
                self.verify_source(doc)
                return doc
        ident = self.allocate(game, source=True)
        target = self.root / 'sources' / game / ident
        staging = Path(tempfile.mkdtemp(prefix='source-', dir=self.root / 'cache'))
        try:
            payload = staging / 'payload'
            if path.is_dir():
                shutil.copytree(path, payload)
            else:
                payload.mkdir()
                shutil.copy2(path, payload / path.name)
            copied, copied_digest = inventory(payload)
            if copied != manifest or copied_digest != digest:
                raise ValueError('来源复制校验失败；未入库')
            doc = {'id': ident, 'schema_version': 1, 'game': game,
                   'original_name': path.name, 'original_path': str(path),
                   'author': author, 'source_url': url, 'license': license_note,
                   'acquired_at': now(), 'manifest_sha256': digest, 'manifest': manifest,
                   'payload': f'sources/{game}/{ident}/payload', 'backup_verified': True,
                   'history': [{'at': now(), 'action': 'source_copy_hash_verified'}]}
            write_json(staging / 'metadata.json', doc)
            staging.rename(target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        self.rebuild()
        return doc

    def verify_source(self, doc):
        rows, digest = inventory(self.inside(doc['payload']))
        if rows != doc['manifest'] or digest != doc['manifest_sha256']:
            raise ValueError(f"来源备份哈希不一致：{doc['id']}")

    def register(self, game, character, source_id, full=None, body=None, variant=None):
        if not re.fullmatch(r'[^<>:"/\\|?*\x00-\x1f]{1,80}', character) or character in ('.', '..') or character.endswith((' ', '.')):
            raise ValueError('角色名称含无效路径字符')
        if character.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(1,10)], *[f'LPT{i}' for i in range(1,10)]}:
            raise ValueError('角色名称是 Windows 保留名称')
        _, source = self.find(source_id, source=True)
        if source['game'] != game:
            raise ValueError('来源和模型游戏不一致')
        ident = self.allocate(game)
        target = self.root / 'models' / game / character / ident
        doc = {'id': ident, 'schema_version': 1, 'asset_kind': 'mod', 'game': game,
               'target_character': character, 'variant': variant,
               'mod_name': source['original_name'], 'source_id': source_id,
               'files': {}, 'extraction': {'status': 'pending', 'method': None,
                 'tool_version': None, 'body_completeness': 'unverified',
                 'scope_note': '本系统不执行提取，仅接收已有模型'},
               'body': {'source_character': None, 'type': '未分类', 'tags': [],
                 'body_regions': {k: 'unverified' for k in ('chest','abdomen','back','hips','legs')},
                 'missing_parts': [], 'pose': None, 'coordinate_system': None},
               'technical': {}, 'measurements': [], 'compatibility': [],
               'validation': {'full_model': 'pending', 'body_model': 'pending',
                 'save_reload': 'pending', 'game_compatibility': 'not_tested'},
               'storage': {'location': 'local', 'archive_id': None, 'archive_verified': False},
               'notes': '', 'created_at': now(), 'history': [{'at': now(), 'action': 'registered'}]}
        # Check inputs before reserving an ID or writing permanent records.
        prepared = self.prepare_assets(full, body)
        target.mkdir(parents=True)
        (target / 'previews').mkdir()
        try:
            self.copy_assets(target, doc, prepared)
            write_json(target / 'metadata.json', doc)
        except Exception:
            # Remove only this newly created record; never touch the supplied assets.
            shutil.rmtree(target)
            raise
        self.rebuild()
        return doc

    def prepare_assets(self, full, body):
        assets = {}
        for role, value in (('full', full), ('body', body)):
            if value:
                p = Path(value).resolve(strict=True)
                if p.suffix.lower() != '.blend' or p.stat().st_size < 12:
                    raise ValueError('模型须为已有的非空 .blend 文件')
                with p.open('rb') as f:
                    header = f.read(7)
                if not (header == b'BLENDER' or header[:2] == b'\x1f\x8b' or header[:4] == b'\x28\xb5\x2f\xfd'):
                    raise ValueError(f'无法识别 Blender 文件头：{p}')
                assets[role] = (p, sha256(p))
        if len(assets) == 2 and assets['full'][1] == assets['body'][1]:
            raise ValueError('完整模型和身体模型是同一份文件；不能冒充两份独立模型')
        return assets

    def copy_assets(self, target, doc, assets):
        for role, (p, digest) in assets.items():
            destination = target / f'{role}.blend'
            if destination.exists():
                raise ValueError(f'已有 {role}.blend；不覆盖已保存的基线')
            shutil.copy2(p, destination)
            if sha256(destination) != digest:
                raise ValueError('模型复制后哈希不一致')
            doc['files'][role] = {'path': destination.relative_to(self.root).as_posix(),
                                 'sha256': digest, 'size': destination.stat().st_size,
                                 'original_name': p.name}
            doc['validation'][f'{role}_model'] = 'copied_hash_verified'
        if {'full', 'body'}.issubset(doc['files']):
            doc['extraction']['status'] = 'files_received'
        elif doc['files']:
            doc['extraction']['status'] = 'awaiting_pair'

    def attach(self, ident, full=None, body=None, previews=None):
        path, doc = self.find(ident)
        assets = self.prepare_assets(full, body)
        target = path.parent
        for role, (_, digest) in assets.items():
            if role in doc['files'] or (target / f'{role}.blend').exists():
                raise ValueError(f'已有 {role}.blend；请为新变体建立新记录')
            other = 'body' if role == 'full' else 'full'
            if doc['files'].get(other, {}).get('sha256') == digest:
                raise ValueError('两个模型不能使用同一份文件')
        preview_inputs = []
        for view, value in (previews or {}).items():
            if view not in ('front', 'side', 'back', 'three_quarter'):
                raise ValueError('预览视角无效')
            p = Path(value).resolve(strict=True)
            if p.suffix.lower() != '.png' or p.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
                raise ValueError('预览须为 PNG 图片')
            if (target / 'previews' / f'{view}.png').exists():
                raise ValueError('已有同角度预览；不覆盖基线')
            preview_inputs.append((view, p, sha256(p)))
        # Stage copies and hashes before publishing any of the new assets.
        staging = Path(tempfile.mkdtemp(prefix='attach-', dir=self.root / 'cache'))
        published = []
        try:
            for role, (p, digest) in assets.items():
                shutil.copy2(p, staging / f'{role}.blend')
                if sha256(staging / f'{role}.blend') != digest:
                    raise ValueError('模型复制后哈希不一致')
            for view, p, digest in preview_inputs:
                shutil.copy2(p, staging / f'{view}.png')
                if sha256(staging / f'{view}.png') != digest:
                    raise ValueError('预览复制后哈希不一致')
            for role, (p, digest) in assets.items():
                dest = target / f'{role}.blend'
                (staging / f'{role}.blend').rename(dest)
                published.append(dest)
                doc['files'][role] = {'path': dest.relative_to(self.root).as_posix(),
                                     'sha256': digest, 'size': dest.stat().st_size,
                                     'original_name': p.name}
                doc['validation'][f'{role}_model'] = 'copied_hash_verified'
            for view, p, digest in preview_inputs:
                dest = target / 'previews' / f'{view}.png'
                (staging / f'{view}.png').rename(dest)
                published.append(dest)
                doc['files'][f'preview_{view}'] = {'path': dest.relative_to(self.root).as_posix(),
                                                 'sha256': digest, 'size': dest.stat().st_size}
            doc['extraction']['status'] = ('files_received' if {'full','body'}.issubset(doc['files'])
                                            else 'awaiting_pair' if doc['files'] else 'pending')
            doc['history'].append({'at': now(), 'action': 'assets_attached'})
            write_json(path, doc)
        except Exception:
            for p in published:
                p.unlink()
            raise
        finally:
            shutil.rmtree(staging)
        self.rebuild()
        return doc

    def annotate(self, ident, **values):
        path, doc = self.find(ident)
        completeness = values.get('completeness')
        if completeness is not None:
            if completeness not in COMPLETENESS:
                raise ValueError('完整度状态无效')
            if completeness in ('partial','complete') and 'body' not in doc['files']:
                raise ValueError('没有 body.blend，不能确认身体完整度')
            if completeness != 'unverified' and completeness != doc['extraction']['body_completeness'] and not values.get('evidence'):
                raise ValueError('人工确认完整度必须填写检查依据')
            doc['extraction']['body_completeness'] = completeness
        for key in ('type', 'source_character', 'tags', 'missing_parts'):
            if values.get(key) is not None:
                doc['body'][key] = values[key]
        if values.get('notes') is not None:
            doc['notes'] = values['notes']
        doc['history'].append({'at': now(), 'action': 'annotated', 'changes': values})
        write_json(path, doc)
        self.rebuild()
        return doc

    def rebuild(self):
        models, sources = self.documents()
        dbpath = self.root / 'database' / 'models.sqlite'
        staging = self.root / 'cache' / 'index-building.sqlite'
        if staging.exists():
            staging.unlink()
        try:
            with closing(sqlite3.connect(staging)) as db, db:
                db.executescript('''
                    CREATE TABLE sources(id TEXT PRIMARY KEY, game TEXT, name TEXT, hash TEXT, metadata TEXT);
                    CREATE TABLE models(id TEXT PRIMARY KEY, source_id TEXT, game TEXT, character TEXT,
                                        variant TEXT, status TEXT, metadata_path TEXT, metadata TEXT);
                    CREATE TABLE bodies(model_id TEXT PRIMARY KEY, type TEXT, completeness TEXT, tags TEXT);
                    CREATE TABLE measurements(model_id TEXT, name TEXT, value REAL, unit TEXT, confidence TEXT, metadata TEXT);
                    CREATE TABLE files(model_id TEXT, role TEXT, path TEXT, sha256 TEXT, size INTEGER);
                    CREATE INDEX file_hash ON files(sha256);
                    CREATE TABLE compatibility(model_id TEXT, target TEXT, result TEXT, metadata TEXT);
                    CREATE TABLE history(record_id TEXT, at TEXT, action TEXT, metadata TEXT);
                ''')
                ids = set()
                for path, d in sources:
                    ids.add(d['id'])
                    db.execute('INSERT INTO sources VALUES(?,?,?,?,?)',
                               (d['id'],d['game'],d['original_name'],d['manifest_sha256'],json.dumps(d,ensure_ascii=False)))
                    for h in d['history']:
                        db.execute('INSERT INTO history VALUES(?,?,?,?)', (d['id'],h['at'],h['action'],json.dumps(h,ensure_ascii=False)))
                for path, d in models:
                    if d['source_id'] not in ids or d.get('asset_kind') != 'mod':
                        raise ValueError(f"模型来源丢失或不是 Mod 资产：{d['id']}")
                    db.execute('INSERT INTO models VALUES(?,?,?,?,?,?,?,?)',
                               (d['id'],d['source_id'],d['game'],d['target_character'],d['variant'],d['extraction']['status'],
                                path.relative_to(self.root).as_posix(),json.dumps(d,ensure_ascii=False)))
                    db.execute('INSERT INTO bodies VALUES(?,?,?,?)',
                               (d['id'],d['body']['type'],d['extraction']['body_completeness'],json.dumps(d['body']['tags'],ensure_ascii=False)))
                    for role, f in d['files'].items():
                        self.inside(f['path'])
                        db.execute('INSERT INTO files VALUES(?,?,?,?,?)', (d['id'],role,f['path'],f['sha256'],f['size']))
                    for m in d['measurements']:
                        db.execute('INSERT INTO measurements VALUES(?,?,?,?,?,?)',
                                   (d['id'],m['name'],m.get('value'),m.get('unit'),m.get('confidence'),json.dumps(m,ensure_ascii=False)))
                    for c in d['compatibility']:
                        db.execute('INSERT INTO compatibility VALUES(?,?,?,?)',
                                   (d['id'],c['target'],c['result'],json.dumps(c,ensure_ascii=False)))
                    for h in d['history']:
                        db.execute('INSERT INTO history VALUES(?,?,?,?)', (d['id'],h['at'],h['action'],json.dumps(h,ensure_ascii=False)))
            os.replace(staging, dbpath)
        finally:
            if staging.exists():
                staging.unlink()
        return {'models': len(models), 'sources': len(sources)}

    def search(self, query='', game=None, completeness=None, status=None):
        # Rebuild intentionally: edits to authoritative JSON are immediately searchable.
        self.rebuild()
        with closing(sqlite3.connect(self.root / 'database' / 'models.sqlite')) as db:
            sql = 'SELECT m.metadata FROM models m JOIN bodies b ON b.model_id=m.id WHERE 1=1'
            params = []
            if game:
                sql += ' AND m.game=?'; params.append(game)
            if completeness:
                sql += ' AND b.completeness=?'; params.append(completeness)
            if status:
                sql += ' AND m.status=?'; params.append(status)
            docs = [json.loads(row[0]) for row in db.execute(sql + ' ORDER BY m.id', params)]
        words = query.casefold().split()
        return [d for d in docs if all(w in json.dumps(d,ensure_ascii=False).casefold() for w in words)]

    def audit(self):
        errors = []
        models, sources = self.documents()
        duplicates = collections.defaultdict(list)
        geometry = collections.defaultdict(list)
        for _, source in sources:
            try:
                self.verify_source(source)
            except (OSError, ValueError) as e:
                errors.append(str(e))
        for _, model in models:
            fingerprint = model.get('technical',{}).get('body',{}).get('mesh_fingerprint')
            if fingerprint:
                geometry[fingerprint].append(model['id'])
            for role, f in model['files'].items():
                try:
                    p = self.inside(f['path'])
                    if p.stat().st_size != f['size'] or sha256(p) != f['sha256']:
                        raise ValueError('大小或哈希不匹配')
                    if role == 'body':
                        duplicates[f['sha256']].append(model['id'])
                except (OSError, ValueError) as e:
                    errors.append(f"{model['id']}/{role}: {e}")
        result = {'at': now(), 'models': len(models), 'sources': len(sources), 'errors': errors,
                  'identical_body_files': [v for v in duplicates.values() if len(v)>1],
                  'identical_indexed_body_geometry': [v for v in geometry.values() if len(v)>1],
                  'geometry_fingerprint': 'only_for_inspected_models', 'save_reload': 'not_performed_by_audit'}
        write_json(self.root / 'reports' / 'integrity.json', result)
        return result

    def open_model(self, ident, role):
        _, d = self.find(ident)
        f = d['files'].get(role)
        if not f:
            raise ValueError('该模型文件尚未入库')
        p = self.inside(f['path'])
        if sha256(p) != f['sha256']:
            raise ValueError('文件哈希改变；请先核查')
        config = read_json(self.root / 'config.json') if (self.root / 'config.json').exists() else {}
        blender = config.get('blender')
        if blender and Path(blender).is_file():
            subprocess.Popen([blender, str(p)])
        elif os.name == 'nt':
            os.startfile(str(p))
        else:
            raise ValueError('请在 config.json 配置 Blender 路径')

    def inspect(self, ident, previews=False):
        """Read saved assets in isolated Blender; no extraction or blend rewriting."""
        path, doc = self.find(ident)
        if previews and 'body' not in doc['files']:
            raise ValueError('尚无 body.blend，不能生成身体预览；可以选择仅检查已有完整模型')
        config = read_json(self.root / 'config.json')
        blender = Path(config['blender'])
        if not blender.is_file():
            raise ValueError('配置的 Blender 不存在')
        script = ROOT / 'inspect_blend.py'
        staging = Path(tempfile.mkdtemp(prefix='inspect-', dir=self.root/'cache'))
        results = {}
        try:
            for role in ('full', 'body'):
                f = doc['files'].get(role)
                if not f:
                    continue
                asset = self.inside(f['path'])
                if sha256(asset) != f['sha256']:
                    raise ValueError('模型哈希已改变；停止检查')
                output = staging / role
                output.mkdir()
                command = [str(blender),'--factory-startup','--disable-autoexec','--background',str(asset),
                           '--python-exit-code','1','--python',str(script),'--',str(output)]
                if role == 'body' and previews:
                    command.append('--previews')
                process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240)
                log = process.stdout.decode('utf-8',errors='replace')
                (self.root/'reports'/f'{ident}-{role}-inspection.log').write_text(log,encoding='utf-8')
                if process.returncode or not (output/'inspection.json').exists():
                    raise ValueError(f'{role} 检查失败；详见 reports 中日志')
                if sha256(asset) != f['sha256']:
                    raise ValueError('检查后模型哈希改变')
                results[role] = read_json(output/'inspection.json')
            if not results:
                raise ValueError('尚无 Blender 模型可检查')
            if previews and 'body' in results:
                self.attach(ident,previews={v: staging/'body'/f'{v}.png' for v in ('front','side','back','three_quarter')})
                path, doc = self.find(ident)
            doc['technical'].update(results)
            for role in results:
                doc['validation'][role+'_model'] = 'blender_read_verified'
            doc['validation']['save_reload'] = 'read_existing_files_verified'
            doc['history'].append({'at':now(),'action':'existing_blend_read_inspected',
                                   'previews':previews,'note':'只打开已保存文件；未执行提取、另存或完整度推断'})
            write_json(path,doc)
            self.rebuild()
            return results
        finally:
            shutil.rmtree(staging)

def scan(path):
    path = Path(path).resolve(strict=True)
    files = safe_files(path)
    counts = collections.Counter(p.suffix.lower() for p in files)
    hints = set()
    ini_resources, switches = [], []
    for p in files:
        if p.suffix.lower() != '.ini':
            continue
        text = p.read_text(encoding='utf-8-sig', errors='replace')
        for game, token in [('WW','WWMI'),('HSR','SRMI'),('ZZZ','ZZMI')]:
            if token.casefold() in text.casefold():
                hints.add(game)
        ini_resources.extend({'ini': p.name, 'reference': m} for m in re.findall(r'^\s*filename\s*=\s*(.+)$', text, re.M|re.I))
        switches.extend({'ini': p.name, 'key': m} for m in re.findall(r'^\s*(?:key|back)\s*=\s*(.+)$', text, re.M|re.I))
    return {'path': str(path), 'file_count': len(files), 'extensions': dict(counts),
            'game_hints': sorted(hints), 'game_confirmed': False, 'character': None,
            'resources': ini_resources, 'switch_keys': switches,
            'mesh_resources_present': any(counts[s] for s in ('.vb','.ib','.buf','.fmt','.blend','.fbx')),
            'extraction': 'skipped_by_scope',
            'note': '扫描只报告文件和 INI 引用。压缩包原样备份，不展开；游戏和角色由用户确认。'}

def main():
    # Stable machine-readable Chinese paths through Windows redirected pipes.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description='三游戏 Mod 模型素材库：登记已有模型，不执行提取')
    p.add_argument('--root', type=Path, default=ROOT)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('init'); sub.add_parser('rebuild'); sub.add_parser('audit'); sub.add_parser('ui')
    s = sub.add_parser('scan'); s.add_argument('path')
    s = sub.add_parser('source'); s.add_argument('path'); s.add_argument('--game', choices=GAMES, required=True)
    s.add_argument('--author'); s.add_argument('--url'); s.add_argument('--license-note')
    s = sub.add_parser('register'); s.add_argument('--game',choices=GAMES,required=True)
    s.add_argument('--character',required=True); s.add_argument('--source-id',required=True)
    s.add_argument('--full'); s.add_argument('--body'); s.add_argument('--variant')
    s = sub.add_parser('attach'); s.add_argument('id'); s.add_argument('--full'); s.add_argument('--body')
    for view in ('front','side','back','three-quarter'):
        s.add_argument('--'+view)
    s = sub.add_parser('search'); s.add_argument('query',nargs='?',default='')
    s.add_argument('--game',choices=GAMES); s.add_argument('--completeness',choices=COMPLETENESS+('verified_scope',)); s.add_argument('--status')
    s = sub.add_parser('locate', help='只读查找实际模型路径，不重建索引、不打开正式文件')
    s.add_argument('--game',choices=GAMES); s.add_argument('--character')
    s.add_argument('--role',choices=('all','full','body'),default='all'); s.add_argument('--id',dest='model_id')
    s = sub.add_parser('annotate'); s.add_argument('id'); s.add_argument('--type'); s.add_argument('--tags', nargs='*')
    s.add_argument('--notes'); s.add_argument('--source-character'); s.add_argument('--missing-parts',nargs='*')
    s.add_argument('--completeness', choices=COMPLETENESS); s.add_argument('--evidence')
    s = sub.add_parser('open'); s.add_argument('id'); s.add_argument('role',choices=('full','body'))
    s = sub.add_parser('inspect'); s.add_argument('id'); s.add_argument('--previews',action='store_true')
    args = vars(p.parse_args()); root = args.pop('root'); command = args.pop('command')
    if command == 'locate':
        try:
            print(json.dumps(locate_models(root, **args),ensure_ascii=False,indent=2))
        except (OSError, ValueError, KeyError) as e:
            p.exit(2, str(e)+'\n')
        return
    # A process-wide write lock protects IDs, metadata and index rebuilds.
    root.mkdir(parents=True,exist_ok=True)
    lock = root / 'cache' / 'writer.lock'; lock.parent.mkdir(exist_ok=True)
    if command == 'ui':
        from manager import launch
        launch(Library(root)); return
    fd = None
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        lib = Library(root)
        if command in ('init','rebuild'):
            result = lib.rebuild()
        elif command == 'scan':
            result = scan(args['path']); write_json(root/'reports'/'last-scan.json',result)
        elif command == 'source':
            result = lib.source(args.pop('path'),**args)
        elif command == 'register':
            result = lib.register(**args)
        elif command == 'attach':
            ident = args.pop('id')
            previews = {v: args.pop(v) for v in ('front','side','back','three_quarter')}
            result = lib.attach(ident,previews={k:v for k,v in previews.items() if v},**args)
        elif command == 'search':
            result = lib.search(**args)
        elif command == 'annotate':
            result = lib.annotate(args.pop('id'),**{k:v for k,v in args.items() if v is not None})
        elif command == 'audit':
            result = lib.audit()
        elif command == 'open':
            lib.open_model(args['id'],args['role']); result = {'opened': args['id'], 'role':args['role']}
        elif command == 'inspect':
            result = lib.inspect(args['id'], args['previews'])
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if command == 'audit' and result['errors']:
            raise SystemExit(1)
    except FileExistsError:
        p.exit(2,'素材库正被其他进程使用；若此前异常退出，请核对 writer.lock 中进程已结束再删除锁。\n')
    except (ValueError, OSError, sqlite3.Error, KeyError) as e:
        p.exit(2, str(e)+'\n')
    finally:
        if fd is not None:
            os.close(fd); lock.unlink(missing_ok=True)

if __name__ == '__main__':
    main()
