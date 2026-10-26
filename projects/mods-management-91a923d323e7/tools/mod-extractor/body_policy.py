"""Conservative naked-body gate. Importing a Mod is a separate outcome."""
from pathlib import Path
REQUIRED_REGIONS=('torso','hips','left_upper_arm','right_upper_arm','left_forearm',
    'right_forearm','left_hand','right_hand','left_thigh','right_thigh',
    'left_calf','right_calf','left_foot','right_foot','limb_connections')

def evaluate_body(profile: str, evidence: dict) -> dict:
    missing=[r for r,v in evidence.get('regions',{}).items() if v=='gap']
    if missing:
        return dict(status='abandoned',reason_code='body_gaps',missing_parts=missing,
                    message='无法得到完整裸模：腿、脚或肢体连接处存在缺口。只保留 Mod 提取模型。',evidence=evidence)
    if (all(evidence.get('regions',{}).get(r)=='verified' for r in REQUIRED_REGIONS)
        and evidence.get('skin_only') is True and evidence.get('source_manifest_verified') is True
        and evidence.get('scope')=='headless_body'):
        return dict(status='eligible',reason_code='body_verified',missing_parts=[],
                    message='限定无头身体范围的完整性证据已核对。',evidence=evidence)
    return dict(status='unverified',reason_code='body_unconfirmed',missing_parts=[],
                message='身体分组或完整性尚未确认，已保留 Mod 提取模型和检查记录。',evidence=evidence)

def output_roles(run: Path, decision: dict) -> tuple:
    if decision['status']=='eligible':return ('full','body')
    if (Path(run)/'models/body.blend').exists():
        raise ValueError('Unexpected existing body.blend; use a fresh task to avoid stale body output')
    return ('full',)
