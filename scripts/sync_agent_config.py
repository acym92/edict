#!/usr/bin/env python3
"""
同步 openclaw.json 中的 agent 配置 → data/agent_config.json
支持自动发现 agent workspace 下的 Skills 目录
"""
import json, pathlib, datetime, logging, shutil
from file_lock import atomic_json_write

log = logging.getLogger('sync_agent_config')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')

# Auto-detect project root (parent of scripts/)
BASE = pathlib.Path(__file__).parent.parent
DATA = BASE / 'data'
OPENCLAW_CFG = pathlib.Path.home() / '.openclaw' / 'openclaw.json'

ID_LABEL = {
    'taizi':    {'label': '太子',   'role': '太子',     'duty': '飞书消息分拣与回奏',  'emoji': '🤴'},
    'main':     {'label': '太子',   'role': '太子',     'duty': '飞书消息分拣与回奏',  'emoji': '🤴'},  # 兼容旧配置
    'zhongshu': {'label': '中书省', 'role': '中书令',   'duty': '起草任务令与优先级',  'emoji': '📜'},
    'menxia':   {'label': '门下省', 'role': '侍中',     'duty': '审议与退回机制',      'emoji': '🔍'},
    'shangshu': {'label': '尚书省', 'role': '尚书令',   'duty': '派单与升级裁决',      'emoji': '📮'},
    'libu':     {'label': '礼部',   'role': '礼部尚书', 'duty': '文档/汇报/规范',      'emoji': '📝'},
    'hubu':     {'label': '户部',   'role': '户部尚书', 'duty': '资源/预算/成本',      'emoji': '💰'},
    'bingbu':   {'label': '兵部',   'role': '兵部尚书', 'duty': '应急与巡检',          'emoji': '⚔️'},
    'xingbu':   {'label': '刑部',   'role': '刑部尚书', 'duty': '合规/审计/红线',      'emoji': '⚖️'},
    'gongbu':   {'label': '工部',   'role': '工部尚书', 'duty': '工程交付与自动化',    'emoji': '🔧'},
    'libu_hr':  {'label': '吏部',   'role': '吏部尚书', 'duty': '人事/培训/Agent管理',  'emoji': '👔'},
    'zaochao':  {'label': '钦天监', 'role': '朝报官',   'duty': '每日新闻采集与简报',  'emoji': '📰'},
    'hanlinyuan': {'label': '翰林院', 'role': '翰林院学士', 'duty': '论文研究与评审改进', 'emoji': '🧪'},
    'dalisi': {'label': '大理寺', 'role': '大理寺卿', 'duty': '论文监督与审稿裁定', 'emoji': '⚖️'},
}


def normalize_model(model_value, fallback='unknown'):
    if isinstance(model_value, str) and model_value:
        return model_value
    if isinstance(model_value, dict):
        return model_value.get('primary') or model_value.get('id') or fallback
    return fallback


def get_skills(workspace: str):
    skills_dir = pathlib.Path(workspace) / 'skills'
    skills = []
    try:
        if skills_dir.exists():
            for d in sorted(skills_dir.iterdir()):
                if d.is_dir():
                    md = d / 'SKILL.md'
                    desc = ''
                    if md.exists():
                        try:
                            for line in md.read_text(encoding='utf-8', errors='ignore').splitlines():
                                line = line.strip()
                                if line and not line.startswith('#') and not line.startswith('---'):
                                    desc = line[:100]
                                    break
                        except Exception:
                            desc = '(读取失败)'
                    skills.append({'name': d.name, 'path': str(md), 'exists': md.exists(), 'description': desc})
    except PermissionError as e:
        log.warning(f'Skills 目录访问受限: {e}')
    return skills


def _collect_openclaw_models(cfg):
    """从 openclaw.json 中收集所有已配置的 model id（不注入任何预设模型）。"""
    known_ids = set()
    extra = []
    agents_cfg = cfg.get('agents', {})
    # 收集 defaults.model
    dm = normalize_model(agents_cfg.get('defaults', {}).get('model', {}), '')
    if dm and dm not in known_ids:
        extra.append({'id': dm, 'label': dm, 'provider': 'OpenClaw'})
        known_ids.add(dm)
    # 收集每个 agent 的 model
    for ag in agents_cfg.get('list', []):
        m = normalize_model(ag.get('model', ''), '')
        if m and m not in known_ids:
            extra.append({'id': m, 'label': m, 'provider': 'OpenClaw'})
            known_ids.add(m)
    # 收集 providers 中的 model id（如 copilot-proxy、anthropic 等）
    for pname, pcfg in cfg.get('providers', {}).items():
        for mid in (pcfg.get('models') or []):
            mid_str = mid if isinstance(mid, str) else (mid.get('id') or mid.get('name') or '')
            if mid_str and mid_str not in known_ids:
                extra.append({'id': mid_str, 'label': mid_str, 'provider': pname})
                known_ids.add(mid_str)
    return extra


def main():
    cfg = {}
    try:
        cfg = json.loads(OPENCLAW_CFG.read_text())
    except Exception as e:
        log.warning(f'cannot read openclaw.json: {e}')
        return

    agents_cfg = cfg.get('agents', {})
    default_model = normalize_model(agents_cfg.get('defaults', {}).get('model', {}), 'unknown')
    agents_list = agents_cfg.get('list', [])
    merged_models = _collect_openclaw_models(cfg)

    result = []
    seen_ids = set()
    for ag in agents_list:
        ag_id = ag.get('id', '')
        if ag_id not in ID_LABEL:
            continue
        meta = ID_LABEL[ag_id]
        workspace = ag.get('workspace', str(pathlib.Path.home() / f'.openclaw/workspace-{ag_id}'))
        result.append({
            'id': ag_id,
            'label': meta['label'], 'role': meta['role'], 'duty': meta['duty'], 'emoji': meta['emoji'],
            'model': normalize_model(ag.get('model', default_model), default_model),
            'defaultModel': default_model,
            'workspace': workspace,
            'skills': get_skills(workspace),
            'allowAgents': ag.get('subagents', {}).get('allowAgents', []),
        })
        seen_ids.add(ag_id)

    # 补充不在 openclaw.json agents list 中的 agent（兼容旧版 main）
    EXTRA_AGENTS = {
        'taizi':   {'model': default_model, 'workspace': str(pathlib.Path.home() / '.openclaw/workspace-taizi'),
                    'allowAgents': ['zhongshu', 'hanlinyuan', 'dalisi']},
        'main':    {'model': default_model, 'workspace': str(pathlib.Path.home() / '.openclaw/workspace-main'),
                    'allowAgents': ['zhongshu','menxia','shangshu','hubu','libu','bingbu','xingbu','gongbu','libu_hr']},
        'zaochao': {'model': default_model, 'workspace': str(pathlib.Path.home() / '.openclaw/workspace-zaochao'),
                    'allowAgents': []},
        'libu_hr': {'model': default_model, 'workspace': str(pathlib.Path.home() / '.openclaw/workspace-libu_hr'),
                    'allowAgents': ['shangshu']},
        'hanlinyuan': {'model': default_model, 'workspace': str(pathlib.Path.home() / '.openclaw/workspace-hanlinyuan'),
                   'allowAgents': ['taizi', 'dalisi']},
        'dalisi': {'model': default_model, 'workspace': str(pathlib.Path.home() / '.openclaw/workspace-dalisi'),
                    'allowAgents': ['taizi', 'hanlinyuan']},
    }
    for ag_id, extra in EXTRA_AGENTS.items():
        if ag_id in seen_ids or ag_id not in ID_LABEL:
            continue
        meta = ID_LABEL[ag_id]
        result.append({
            'id': ag_id,
            'label': meta['label'], 'role': meta['role'], 'duty': meta['duty'], 'emoji': meta['emoji'],
            'model': extra['model'],
            'defaultModel': default_model,
            'workspace': extra['workspace'],
            'skills': get_skills(extra['workspace']),
            'allowAgents': extra['allowAgents'],
            'isDefaultModel': True,
        })

    # 保留已有的 dispatchChannel 配置 (Fix #139)
    existing_cfg = {}
    cfg_path = DATA / 'agent_config.json'
    if cfg_path.exists():
        try:
            existing_cfg = json.loads(cfg_path.read_text())
        except Exception:
            pass

    payload = {
        'generatedAt': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'defaultModel': default_model,
        'knownModels': merged_models,
        'dispatchChannel': existing_cfg.get('dispatchChannel', 'feishu'),
        'dispatchPolicy': existing_cfg.get('dispatchPolicy', {
            'timeoutSec': 300,
            'maxRetries': 2,
            'retryDelaySec': 5,
            'agentOverrides': {
                'hubu': {'timeoutSec': 420, 'maxRetries': 3},
                'xingbu': {'timeoutSec': 420, 'maxRetries': 3},
            },
        }),
        'agents': result,
    }
    DATA.mkdir(exist_ok=True)
    atomic_json_write(DATA / 'agent_config.json', payload)
    log.info(f'{len(result)} agents synced')

    # 自动部署 SOUL.md 到 workspace（如果项目里有更新）
    deploy_soul_files()
    # 同步 scripts/ 到各 workspace（保持 kanban_update.py 等最新）
    sync_scripts_to_workspaces()
    # 同步完整 research 资料到论文专线 workspace（翰林院/大理寺）
    sync_research_to_paper_workspaces()


# 项目 agents/ 目录名 → 运行时 agent_id 映射
_SOUL_DEPLOY_MAP = {
    'taizi': 'taizi',
    'zhongshu': 'zhongshu',
    'menxia': 'menxia',
    'shangshu': 'shangshu',
    'libu': 'libu',
    'hubu': 'hubu',
    'bingbu': 'bingbu',
    'xingbu': 'xingbu',
    'gongbu': 'gongbu',
    'libu_hr': 'libu_hr',
    'zaochao': 'zaochao',
    'hanlinyuan': 'hanlinyuan',
    'dalisi': 'dalisi',
}

def sync_scripts_to_workspaces():
    """将项目 scripts/ 目录同步到各 agent workspace（保持 kanban_update.py 等最新）"""
    scripts_src = BASE / 'scripts'
    if not scripts_src.is_dir():
        return
    synced = 0
    for proj_name, runtime_id in _SOUL_DEPLOY_MAP.items():
        ws_scripts = pathlib.Path.home() / f'.openclaw/workspace-{runtime_id}' / 'scripts'
        ws_scripts.mkdir(parents=True, exist_ok=True)
        for src_file in scripts_src.iterdir():
            if src_file.suffix not in ('.py', '.sh') or src_file.stem.startswith('__'):
                continue
            dst_file = ws_scripts / src_file.name
            try:
                src_text = src_file.read_bytes()
            except Exception:
                continue
            try:
                dst_text = dst_file.read_bytes() if dst_file.exists() else b''
            except Exception:
                dst_text = b''
            if src_text != dst_text:
                dst_file.write_bytes(src_text)
                synced += 1
    # also sync to workspace-main for legacy compatibility
    ws_main_scripts = pathlib.Path.home() / '.openclaw/workspace-main/scripts'
    ws_main_scripts.mkdir(parents=True, exist_ok=True)
    for src_file in scripts_src.iterdir():
        if src_file.suffix not in ('.py', '.sh') or src_file.stem.startswith('__'):
            continue
        dst_file = ws_main_scripts / src_file.name
        try:
            src_text = src_file.read_bytes()
            dst_text = dst_file.read_bytes() if dst_file.exists() else b''
            if src_text != dst_text:
                dst_file.write_bytes(src_text)
                synced += 1
        except Exception:
            pass
    if synced:
        log.info(f'{synced} script files synced to workspaces')


def deploy_soul_files():
    """将项目 agents/xxx/SOUL.md 部署到 ~/.openclaw/workspace-xxx/soul.md"""
    agents_dir = BASE / 'agents'
    deployed = 0
    for proj_name, runtime_id in _SOUL_DEPLOY_MAP.items():
        src = agents_dir / proj_name / 'SOUL.md'
        if not src.exists():
            continue
        ws_dst = pathlib.Path.home() / f'.openclaw/workspace-{runtime_id}' / 'soul.md'
        ws_dst.parent.mkdir(parents=True, exist_ok=True)
        # 只在内容不同时更新（避免不必要的写入）
        src_text = src.read_text(encoding='utf-8', errors='ignore')
        try:
            dst_text = ws_dst.read_text(encoding='utf-8', errors='ignore')
        except FileNotFoundError:
            dst_text = ''
        if src_text != dst_text:
            ws_dst.write_text(src_text, encoding='utf-8')
            deployed += 1
        # 太子兼容：同步一份到 legacy main agent 目录
        if runtime_id == 'taizi':
            ag_dst = pathlib.Path.home() / '.openclaw/agents/main/SOUL.md'
            ag_dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                ag_text = ag_dst.read_text(encoding='utf-8', errors='ignore')
            except FileNotFoundError:
                ag_text = ''
            if src_text != ag_text:
                ag_dst.write_text(src_text, encoding='utf-8')
        # 确保 sessions 目录存在
        sess_dir = pathlib.Path.home() / f'.openclaw/agents/{runtime_id}/sessions'
        sess_dir.mkdir(parents=True, exist_ok=True)
    if deployed:
        log.info(f'{deployed} SOUL.md files deployed')


def sync_research_to_paper_workspaces():
    """同步完整 research/ 到论文专线 workspace（hanlinyuan + dalisi）。"""
    src_root = BASE / 'research'
    if not src_root.is_dir():
        return
    synced = {'hanlinyuan': 0, 'dalisi': 0}
    for runtime_id in ('hanlinyuan', 'dalisi'):
        dst_root = pathlib.Path.home() / f'.openclaw/workspace-{runtime_id}' / 'research'
        for src in src_root.rglob('*'):
            if src.is_dir():
                continue
            rel = src.relative_to(src_root)
            dst = dst_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                if dst.exists() and dst.stat().st_size == src.stat().st_size and int(dst.stat().st_mtime) >= int(src.stat().st_mtime):
                    continue
                shutil.copy2(src, dst)
                synced[runtime_id] += 1
            except Exception:
                continue
    total = synced['hanlinyuan'] + synced['dalisi']
    if total:
        log.info(
            'research files synced (full copy): '
            f'hanlinyuan={synced["hanlinyuan"]}, dalisi={synced["dalisi"]}'
        )


if __name__ == '__main__':
    main()
