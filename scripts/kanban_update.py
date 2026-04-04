#!/usr/bin/env python3
"""
看板任务更新工具 - 供各省部 Agent 调用

本工具操作 data/tasks_source.json（JSON 看板模式）。
如果您已部署 edict/backend（Postgres + Redis 事件总线模式），
请使用 edict/backend API 端点代替本脚本，或运行迁移脚本：
  python3 edict/migration/migrate_json_to_pg.py

两种模式互相独立，数据不会自动同步。

用法:
  # 新建任务（收旨时）
  python3 kanban_update.py create JJC-20260223-012 "任务标题" Zhongshu 中书省 中书令

  # 更新状态
  python3 kanban_update.py state JJC-20260223-012 Menxia "规划方案已提交门下省"

  # 添加流转记录
  python3 kanban_update.py flow JJC-20260223-012 "中书省" "门下省" "规划方案提交审核"

  # 完成任务
  python3 kanban_update.py done JJC-20260223-012 "/path/to/output" "任务完成摘要"

  # 添加/更新子任务 todo
  python3 kanban_update.py todo JJC-20260223-012 1 "实现API接口" in-progress
  python3 kanban_update.py todo JJC-20260223-012 1 "" completed

  # 🔥 实时进展汇报（Agent 主动调用，频率不限）
  python3 kanban_update.py progress JJC-20260223-012 "正在分析需求，拟定3个子方案" "1.调研技术选型|2.撰写设计文档|3.实现原型"
"""
import json, pathlib, sys, subprocess, logging, os, re


def _resolve_project_base() -> pathlib.Path:
    """
    解析看板数据根目录。
    兼容 agent workspace（~/.openclaw/workspace-*/scripts）场景，避免把任务写进各自隔离目录。
    """
    # 1) 显式环境变量（最高优先级）
    for key in ('EDICT_PROJECT_DIR', 'OPENCLAW_PROJECT_DIR'):
        val = (os.environ.get(key) or '').strip()
        if not val:
            continue
        p = pathlib.Path(val).expanduser().resolve()
        if (p / 'dashboard' / 'server.py').exists():
            return p

    # 2) 常见开发目录（Codex 容器默认）
    default_repo = pathlib.Path('/workspace/edict')
    if (default_repo / 'dashboard' / 'server.py').exists():
        return default_repo

    # 3) 当前脚本所在仓库（兜底）
    return pathlib.Path(__file__).resolve().parent.parent


_BASE = _resolve_project_base()
TASKS_FILE = _BASE / 'data' / 'tasks_source.json'
REFRESH_SCRIPT = _BASE / 'scripts' / 'refresh_live_data.py'

log = logging.getLogger('kanban')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')

# 文件锁 —— 防止多 Agent 同时读写 tasks_source.json
from file_lock import atomic_json_read, atomic_json_update  # noqa: E402
from utils import now_iso  # noqa: E402

STATE_ORG_MAP = {
    'Taizi': '太子', 'Zhongshu': '中书省', 'Menxia': '门下省', 'Assigned': '尚书省',
    'Hanlinyuan': '翰林院',
    'Dalisi': '大理寺',
    'Doing': '执行中', 'Review': '尚书省', 'Done': '完成', 'Blocked': '阻塞',
}

_STATE_AGENT_MAP = {
    'Taizi': 'taizi',
    'Zhongshu': 'zhongshu',
    'Menxia': 'menxia',
    'Assigned': 'shangshu',
    'Hanlinyuan': 'hanlinyuan',
    'Dalisi': 'dalisi',
    'Review': 'shangshu',
    'Pending': 'zhongshu',
}

_ORG_AGENT_MAP = {
    '礼部': 'libu', '户部': 'hubu', '兵部': 'bingbu',
    '刑部': 'xingbu', '工部': 'gongbu', '吏部': 'libu_hr',
    '中书省': 'zhongshu', '门下省': 'menxia', '尚书省': 'shangshu', '翰林院': 'hanlinyuan', '大理寺': 'dalisi',
}

_AGENT_LABELS = {
    'main': '太子', 'taizi': '太子',
    'zhongshu': '中书省', 'menxia': '门下省', 'shangshu': '尚书省',
    'libu': '礼部', 'hubu': '户部', 'bingbu': '兵部', 'xingbu': '刑部',
    'gongbu': '工部', 'libu_hr': '吏部', 'zaochao': '钦天监',
    'hanlinyuan': '翰林院',
    'dalisi': '大理寺',
}

MAX_PROGRESS_LOG = 100  # 单任务最大进展日志条数
_PAPER_LANE_TITLE_RE = re.compile(r'^\s*论文(?:\s*[\\/／:：]|\s+|$)')


def _is_paper_lane_title(title: str) -> bool:
    """识别“论文”开头的专线标题（如：论文/主题、论文 审稿、论文：修改）。"""
    return bool(_PAPER_LANE_TITLE_RE.match((title or '').strip()))

def load():
    return atomic_json_read(TASKS_FILE, [])

def _trigger_refresh():
    """异步触发 live_status 刷新，不阻塞调用方。"""
    try:
        subprocess.Popen(['python3', str(REFRESH_SCRIPT)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def find_task(tasks, task_id):
    return next((t for t in tasks if t.get('id') == task_id), None)


def _remark_key(text: str) -> str:
    txt = re.sub(r'[\u2700-\u27BF\U0001F300-\U0001FAFF]', '', str(text or ''))
    txt = re.sub(r'\s+', '', txt)
    return txt.strip().lower()


def _append_flow_dedup(task: dict, from_dept: str, to_dept: str, remark: str, max_scan: int = 6):
    logs = task.setdefault('flow_log', [])
    rk = _remark_key(remark)
    for prev in reversed(logs[-max_scan:]):
        if (prev.get('from') or '') != (from_dept or ''):
            continue
        if (prev.get('to') or '') != (to_dept or ''):
            continue
        if _remark_key(prev.get('remark', '')) == rk:
            return False
    logs.append({"at": now_iso(), "from": from_dept, "to": to_dept, "remark": remark})
    return True


# 旨意标题最低要求
_MIN_TITLE_LEN = 6
_JUNK_TITLES = {
    '?', '？', '好', '好的', '是', '否', '不', '不是', '对', '了解', '收到',
    '嗯', '哦', '知道了', '开启了么', '可以', '不行', '行', 'ok', 'yes', 'no',
    '你去开启', '测试', '试试', '看看',
}

def _sanitize_text(raw, max_len=80):
    """清洗文本：剥离文件路径、URL、Conversation 元数据、传旨前缀、截断过长内容。"""
    t = (raw or '').strip()
    # 1) 剥离 Conversation info / Conversation 后面的所有内容
    t = re.split(r'\n*Conversation\b', t, maxsplit=1)[0].strip()
    # 2) 剥离 ```json 代码块
    t = re.split(r'\n*```', t, maxsplit=1)[0].strip()
    # 3) 剥离 Unix/Mac 文件路径 (/Users/xxx, /home/xxx, /opt/xxx, ./xxx)
    t = re.sub(r'[/\\.~][A-Za-z0-9_\-./]+(?:\.(?:py|js|ts|json|md|sh|yaml|yml|txt|csv|html|css|log))?', '', t)
    # 4) 剥离 URL
    t = re.sub(r'https?://\S+', '', t)
    # 5) 清理常见前缀: "传旨:" "下旨:" "下旨（xxx）:" 等
    t = re.sub(r'^(传旨|下旨)([（(][^)）]*[)）])?[：:\uff1a]\s*', '', t)
    # 6) 剥离系统元数据关键词
    t = re.sub(r'(message_id|session_id|chat_id|open_id|user_id|tenant_key)\s*[:=]\s*\S+', '', t)
    # 7) 合并多余空白
    t = re.sub(r'\s+', ' ', t).strip()
    # 8) 截断过长内容
    if len(t) > max_len:
        t = t[:max_len] + '…'
    return t


def _sanitize_title(raw):
    """清洗标题（最长 80 字符）。"""
    return _sanitize_text(raw, 80)


def _sanitize_remark(raw):
    """清洗流转备注（最长 120 字符）。"""
    return _sanitize_text(raw, 120)


def _infer_agent_id_from_runtime(task=None):
    """尽量推断当前执行该命令的 Agent。"""
    for k in ('OPENCLAW_AGENT_ID', 'OPENCLAW_AGENT', 'AGENT_ID'):
        v = (os.environ.get(k) or '').strip()
        if v:
            return v

    cwd = str(pathlib.Path.cwd())
    m = re.search(r'workspace-([a-zA-Z0-9_\-]+)', cwd)
    if m:
        return m.group(1)

    # 兼容 `python -c/exec` 场景：此时 __file__ 可能不存在，不能直接引用。
    fpath = globals().get('__file__')
    if fpath:
        try:
            m2 = re.search(r'workspace-([a-zA-Z0-9_\-]+)', str(pathlib.Path(fpath).resolve()))
            if m2:
                return m2.group(1)
        except Exception:
            pass

    if task:
        state = task.get('state', '')
        org = task.get('org', '')
        aid = _STATE_AGENT_MAP.get(state)
        if aid is None and state in ('Doing', 'Next'):
            aid = _ORG_AGENT_MAP.get(org)
        if aid:
            return aid
    return ''


def _is_valid_task_title(title):
    """校验标题是否足够作为一个旨意任务。"""
    t = (title or '').strip()
    if len(t) < _MIN_TITLE_LEN:
        return False, f'标题过短（{len(t)}<{_MIN_TITLE_LEN}字），疑似非旨意'
    if t.lower() in _JUNK_TITLES:
        return False, f'标题 "{t}" 不是有效旨意'
    # 纯标点或问号
    if re.fullmatch(r'[\s?？!！.。,，…·\-—~]+', t):
        return False, '标题只有标点符号'
    # 看起来像文件路径
    if re.match(r'^[/\\~.]', t) or re.search(r'/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+', t):
        return False, f'标题看起来像文件路径，请用中文概括任务'
    # 只剩标点和空白（清洗后可能变空）
    if re.fullmatch(r'[\s\W]*', t):
        return False, '标题清洗后为空'
    return True, ''


def _normalize_state_name(state: str) -> str:
    """统一状态名（当前仅保留 Hanlinyuan）。"""
    return state


def cmd_create(task_id, title, state, org, official, remark=None):
    """新建任务（收旨时立即调用）"""
    # 旨意任务 ID 统一规范：必须为 JJC- 前缀
    if not str(task_id).startswith('JJC-'):
        log.warning(f'⚠️ 拒绝创建 {task_id}：任务ID必须以 JJC- 开头')
        print('[看板] 拒绝创建：任务ID必须以 JJC- 开头（例如 JJC-20260404-001）', flush=True)
        return
    # 清洗标题（剥离元数据）
    title = _sanitize_title(title)
    # 旨意标题校验
    valid, reason = _is_valid_task_title(title)
    if not valid:
        log.warning(f'⚠️ 拒绝创建 {task_id}：{reason}')
        print(f'[看板] 拒绝创建：{reason}', flush=True)
        return
    state = _normalize_state_name(state)
    is_paper_lane = _is_paper_lane_title(title) or state in ('Hanlinyuan', 'Dalisi') or org in ('翰林院', '大理寺')
    # 所有 JJC 旨意（含论文专线）统一从「皇上 -> 太子」开始，避免出现错序首条流转。
    initial_state = state
    actual_org = STATE_ORG_MAP.get(state, org)
    if str(task_id).startswith('JJC-'):
        initial_state = 'Taizi'
        actual_org = '太子'
    clean_remark = _sanitize_remark(remark) if remark else f"下旨：{title}"
    def modifier(tasks):
        existing = next((t for t in tasks if t.get('id') == task_id), None)
        if existing:
            if existing.get('state') in ('Done', 'Cancelled'):
                log.warning(f'⚠️ 任务 {task_id} 已完结 (state={existing["state"]})，不可覆盖')
                return tasks
            if existing.get('state') not in (None, '', 'Inbox', 'Pending'):
                log.warning(f'任务 {task_id} 已存在 (state={existing["state"]})，将被覆盖')
        tasks = [t for t in tasks if t.get('id') != task_id]
        tasks.insert(0, {
            "id": task_id, "title": title, "official": official,
            "org": actual_org, "state": initial_state,
            "now": clean_remark[:60] if remark else ("等待太子接旨分拣" if str(task_id).startswith('JJC-') else f"已下旨，等待{actual_org}接旨"),
            "eta": "-", "block": "无", "output": "", "ac": "",
            "flow_log": [{"at": now_iso(), "from": "皇上", "to": actual_org, "remark": clean_remark}],
            "updatedAt": now_iso()
        })
        if is_paper_lane:
            tasks[0]['pipeline'] = 'paper'
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    log.info(f'✅ 创建 {task_id} | {title[:30]} | state={initial_state}')


def _normalize_progress_text(now_text):
    """把底层协议噪声转成可读的系统事件描述，不隐藏真实流转。"""
    raw = (now_text or '').strip()
    if not raw:
        return raw
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return raw

    mapped = []
    has_protocol = False
    for ln in lines:
        if ln.startswith('execCommand still running '):
            has_protocol = True
            mapped.append('【系统事件】命令仍在执行，已切换为后台会话跟踪（process/poll）')
            continue
        if ln.startswith('subagents{'):
            has_protocol = True
            mapped.append('【系统事件】太子查询子代理列表')
            continue
        if ln.startswith('sessions_spawn{'):
            has_protocol = True
            m = re.search(r'"childSessionKey"\s*:\s*"agent:([a-zA-Z0-9_\-]+)', ln)
            child = m.group(1) if m else '未知子代理'
            label = _AGENT_LABELS.get(child, child)
            mapped.append(f'【系统事件】拉起子代理会话：{label}')
            continue
        mapped.append(ln)

    # 仅在检测到协议噪声时做归一化，避免误改正常进展描述。
    if not has_protocol:
        return raw
    return '；'.join(mapped)


def _extract_spawn_agents(now_text):
    """从原始 progress 文本中提取 sessions_spawn 事件。

    返回: [{'agent_id': 'libu', 'event_key': '...'}]
    event_key 用于在任务级做幂等，避免同一协议事件重复触发 flow 写入。
    """
    raw = (now_text or '').strip()
    if not raw:
        return []
    found = []
    seen_keys = set()
    for ln in [x.strip() for x in raw.splitlines() if x.strip()]:
        # 兼容多种协议/日志格式：
        # 1) sessions_spawn{"childSessionKey":"agent:libu:subagent:..."}
        # 2) dispatch: sessionKey=agent:libu:subagent:...
        # 3) agent:libu:subagent:...（裸字符串）
        candidates = []
        for m in re.finditer(r'childSessionKey"\s*:\s*"agent:([a-zA-Z0-9_\-]+)', ln):
            candidates.append(m.group(1))
        for m in re.finditer(r'sessionKey=agent:([a-zA-Z0-9_\-]+):subagent', ln):
            candidates.append(m.group(1))
        for m in re.finditer(r'agent:([a-zA-Z0-9_\-]+):subagent', ln):
            candidates.append(m.group(1))

        # 兼容“【系统事件】拉起子代理会话：礼部/户部 ...”文案
        label_match = re.search(r'拉起子代理会话[:：]\s*([^\s；,，。]+)', ln)
        if label_match:
            label = label_match.group(1).strip()
            rev_map = {v: k for k, v in _AGENT_LABELS.items()}
            aid_from_label = rev_map.get(label)
            if aid_from_label:
                candidates.append(aid_from_label)

        for aid_raw in candidates:
            aid = (aid_raw or '').strip()
            if not aid:
                continue
            event_key = f'{aid}|{ln}'
            if event_key in seen_keys:
                continue
            seen_keys.add(event_key)
            found.append({'agent_id': aid, 'event_key': event_key})
    return found


# ── 状态流转合法性校验 ──
# 只允许文档定义的状态路径:
# Pending→Taizi→Zhongshu→Menxia→Assigned→Doing→Review→Done
# 额外: Blocked 可双向切换, Cancelled 从任意非终态可达, Next→Doing
_VALID_TRANSITIONS = {
    'Pending':   {'Taizi', 'Cancelled'},
    'Taizi':     {'Zhongshu', 'Hanlinyuan', 'Cancelled'},
    'Hanlinyuan':    {'Done', 'Blocked', 'Cancelled'},
    'Zhongshu':  {'Menxia', 'Cancelled'},
    'Menxia':    {'Assigned', 'Zhongshu', 'Cancelled'},   # 封驳可回中书
    'Assigned':  {'Doing', 'Next', 'Blocked', 'Cancelled'},
    'Next':      {'Doing', 'Blocked', 'Cancelled'},
    'Doing':     {'Review', 'Blocked', 'Cancelled'},
    'Review':    {'Done', 'Menxia', 'Doing', 'Cancelled'},  # 可打回重审/重做
    'Blocked':   {'Doing', 'Next', 'Assigned', 'Review', 'Hanlinyuan', 'Cancelled'},  # 解除后回原位
    'Done':      set(),       # 终态
    'Cancelled': set(),       # 终态
}

_HANLIN_ONLY_TRANSITIONS = {
    'Pending': {'Taizi', 'Cancelled'},
    'Taizi': {'Hanlinyuan', 'Cancelled'},
    'Hanlinyuan': {'Dalisi', 'Blocked', 'Cancelled'},
    'Dalisi': {'Hanlinyuan', 'Done', 'Blocked', 'Cancelled'},
    'Blocked': {'Hanlinyuan', 'Dalisi', 'Cancelled'},
    'Done': set(),
    'Cancelled': set(),
}


def _is_hanlinyuan_task(task: dict) -> bool:
    title = str(task.get('title') or '')
    org = str(task.get('org') or '')
    if _is_paper_lane_title(title) or org == '翰林院':
        return True
    for fl in (task.get('flow_log') or []):
        if fl.get('from') == '翰林院' or fl.get('to') == '翰林院':
            return True
    return False


def _merge_todos_preserve_completed(old_todos, new_todos):
    """合并 todos，避免 completed 被后续 progress 误降级为 in-progress。"""
    old_map = {}
    for td in (old_todos or []):
        key = str(td.get('id'))
        if key:
            old_map[key] = td

    merged = []
    for td in (new_todos or []):
        item = dict(td)
        key = str(item.get('id'))
        prev = old_map.get(key)
        if prev and prev.get('status') == 'completed' and item.get('status') != 'completed':
            item['status'] = 'completed'
        merged.append(item)
    return merged


def _auto_advance_when_todos_done(task: dict):
    """当 todos 全部完成且仍处执行阶段时，自动推进到 Review。"""
    todos = [td for td in (task.get('todos') or []) if isinstance(td, dict)]
    if not todos:
        return False
    all_done = all((td.get('status') == 'completed') for td in todos)
    cur_state = task.get('state')
    if all_done and cur_state in ('Assigned', 'Next', 'Doing'):
        task['state'] = 'Review'
        task['now'] = '✅ 子任务已全部完成，进入审查'
        _append_flow_dedup(task, '六部', '尚书省', '✅ 子任务全部完成，自动进入审查')
        return True
    return False


def _finalize_todos_when_done(task: dict):
    """任务完成时兜底收口 todos，避免 UI 仍显示“进行中”假象。"""
    todos = [td for td in (task.get('todos') or []) if isinstance(td, dict)]
    if not todos:
        return 0
    changed = 0
    for td in todos:
        if td.get('status') != 'completed':
            td['status'] = 'completed'
            changed += 1
    if changed:
        task['todos'] = todos
    return changed


def cmd_state(task_id, new_state, now_text=None):
    """更新任务状态（原子操作，含流转合法性校验）"""
    old_state = [None]
    rejected = [False]
    target_state = _normalize_state_name(new_state)
    def modifier(tasks):
        t = find_task(tasks, task_id)
        if not t:
            log.error(f'任务 {task_id} 不存在')
            return tasks
        old_state[0] = t['state']
        if _is_hanlinyuan_task(t):
            allowed = _HANLIN_ONLY_TRANSITIONS.get(old_state[0], set())
        else:
            allowed = _VALID_TRANSITIONS.get(old_state[0])
        caller = _infer_agent_id_from_runtime(t)
        # 允许太子在任务已实质完成后直接收口为 Done，避免长期停留在执行态。
        if (
            target_state == 'Done'
            and caller in ('taizi', 'main')
            and old_state[0] in ('Assigned', 'Next', 'Doing', 'Review')
        ):
            todos = [td for td in (t.get('todos') or []) if isinstance(td, dict)]
            has_unfinished_todos = any(td.get('status') != 'completed' for td in todos)
            # 若任务还在执行态且已派生过子代理协同，必须先回到 Review 再收口 Done，
            # 避免“子代理仍在跑，主任务先完成”的假完成。
            has_spawned_subagents = bool(t.get('_spawn_event_keys'))
            if has_unfinished_todos or (old_state[0] in ('Assigned', 'Next', 'Doing') and has_spawned_subagents):
                log.warning(f'⚠️ 拒绝提前完成 {task_id}: 子任务未收口（state={old_state[0]}）')
                rejected[0] = True
                return tasks
            allowed = set(allowed or set())
            allowed.add('Done')
        if allowed is not None and target_state not in allowed:
            log.warning(f'⚠️ 非法状态转换 {task_id}: {old_state[0]} → {target_state}（允许: {allowed}）')
            rejected[0] = True
            return tasks
        t['state'] = target_state
        if target_state in STATE_ORG_MAP:
            t['org'] = STATE_ORG_MAP[target_state]
        if target_state in ('Hanlinyuan', 'Dalisi'):
            t['pipeline'] = 'paper'
        if now_text:
            t['now'] = now_text
        if target_state == 'Done':
            _finalize_todos_when_done(t)
        t['updatedAt'] = now_iso()
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    if rejected[0]:
        log.info(f'❌ {task_id} 状态转换被拒: {old_state[0]} → {target_state}')
    else:
        log.info(f'✅ {task_id} 状态更新: {old_state[0]} → {target_state}')


def cmd_flow(task_id, from_dept, to_dept, remark):
    """添加流转记录（原子操作）"""
    clean_remark = _sanitize_remark(remark)
    def modifier(tasks):
        t = find_task(tasks, task_id)
        if not t:
            log.error(f'任务 {task_id} 不存在')
            return tasks
        if _is_hanlinyuan_task(t):
            allowed_depts = {'皇上', '太子', '翰林院'}
            if from_dept not in allowed_depts or to_dept not in allowed_depts:
                log.warning(f'⚠️ Hanlinyuan 专线任务禁止跨入其他部门: {from_dept} -> {to_dept}')
                return tasks
        _append_flow_dedup(t, from_dept, to_dept, clean_remark)
        t['updatedAt'] = now_iso()
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    log.info(f'✅ {task_id} 流转记录: {from_dept} → {to_dept}')


def cmd_done(task_id, output_path='', summary=''):
    """标记任务完成（原子操作）"""
    def modifier(tasks):
        t = find_task(tasks, task_id)
        if not t:
            log.error(f'任务 {task_id} 不存在')
            return tasks
        t['state'] = 'Done'
        _finalize_todos_when_done(t)
        t['output'] = output_path
        t['now'] = summary or '任务已完成'
        done_remark = f"✅ 完成：{summary or '任务已完成'}"
        from_org = t.get('org', '执行部门')
        # 三省六部主流程统一：执行侧先回奏太子，再由太子转报皇上。
        if (not _is_hanlinyuan_task(t)) and from_org not in ('太子', '皇上'):
            _append_flow_dedup(t, from_org, '太子', done_remark)
            _append_flow_dedup(t, '太子', '皇上', '📨 太子转报皇上：任务已完成')
        else:
            _append_flow_dedup(t, from_org, '皇上', done_remark)
        t['updatedAt'] = now_iso()
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    log.info(f'✅ {task_id} 已完成')


def cmd_block(task_id, reason):
    """标记阻塞（原子操作）"""
    def modifier(tasks):
        t = find_task(tasks, task_id)
        if not t:
            log.error(f'任务 {task_id} 不存在')
            return tasks
        t['state'] = 'Blocked'
        t['block'] = reason
        t['updatedAt'] = now_iso()
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    log.warning(f'⚠️ {task_id} 已阻塞: {reason}')


def cmd_progress(task_id, now_text, todos_pipe='', tokens=0, cost=0.0, elapsed=0):
    """🔥 实时进展汇报 — Agent 主动调用，不改变状态，只更新 now + todos

    now_text: 当前正在做什么的一句话描述（必填）
    todos_pipe: 可选，用 | 分隔的 todo 列表，格式：
        "已完成的事项✅|正在做的事项🔄|计划做的事项"
        - 以 ✅ 结尾 → completed
        - 以 🔄 结尾 → in-progress
        - 其他 → not-started
    tokens: 可选，本次消耗的 token 数
    cost: 可选，本次成本（美元）
    elapsed: 可选，本次耗时（秒）
    """
    clean = _sanitize_remark(_normalize_progress_text(now_text))
    spawned_agents = _extract_spawn_agents(now_text)
    # 解析 todos_pipe
    parsed_todos = None
    if todos_pipe:
        new_todos = []
        for i, item in enumerate(todos_pipe.split('|'), 1):
            item = item.strip()
            if not item:
                continue
            if item.endswith('✅'):
                status = 'completed'
                title = item[:-1].strip()
            elif item.endswith('🔄'):
                status = 'in-progress'
                title = item[:-1].strip()
            else:
                status = 'not-started'
                title = item
            new_todos.append({'id': str(i), 'title': title, 'status': status})
        if new_todos:
            parsed_todos = new_todos

    # 解析资源消耗参数
    try:
        tokens = int(tokens) if tokens else 0
    except (ValueError, TypeError):
        tokens = 0
    try:
        cost = float(cost) if cost else 0.0
    except (ValueError, TypeError):
        cost = 0.0
    try:
        elapsed = int(elapsed) if elapsed else 0
    except (ValueError, TypeError):
        elapsed = 0

    done_cnt = [0]
    total_cnt = [0]
    def modifier(tasks):
        t = find_task(tasks, task_id)
        if not t:
            log.error(f'任务 {task_id} 不存在')
            return tasks
        t['now'] = clean
        if parsed_todos is not None:
            t['todos'] = _merge_todos_preserve_completed(t.get('todos', []), parsed_todos)
            _auto_advanced = _auto_advance_when_todos_done(t)
            if _auto_advanced:
                log.info(f'🧭 {task_id} todos 全部完成，自动推进到 Review')
        # 多 Agent 并行进展日志
        at = now_iso()
        agent_id = _infer_agent_id_from_runtime(t)
        agent_label = _AGENT_LABELS.get(agent_id, agent_id)
        if spawned_agents:
            seen = t.setdefault('_spawn_event_keys', [])
            if not isinstance(seen, list):
                seen = []
            from_dept = agent_label or t.get('org', '')
            changed = False
            for sp in spawned_agents:
                child_aid = sp.get('agent_id', '')
                event_key = sp.get('event_key', '')
                if not child_aid or not event_key or event_key in seen:
                    continue
                child_label = _AGENT_LABELS.get(child_aid, child_aid)
                if not child_label:
                    continue
                _append_flow_dedup(
                    t,
                    from_dept,
                    child_label,
                    f'🤝 子代理协同：{from_dept} 拉起 {child_label}',
                )
                seen.append(event_key)
                changed = True
            if changed:
                # 防止字段无限增长，只保留最近 120 条事件 key。
                t['_spawn_event_keys'] = seen[-120:]
        log_todos = parsed_todos if parsed_todos is not None else t.get('todos', [])
        log_entry = {
            'at': at, 'agent': agent_id, 'agentLabel': agent_label,
            'text': clean, 'todos': log_todos,
            'state': t.get('state', ''), 'org': t.get('org', ''),
        }
        # 资源消耗（可选字段，有值才写入）
        if tokens > 0:
            log_entry['tokens'] = tokens
        if cost > 0:
            log_entry['cost'] = cost
        if elapsed > 0:
            log_entry['elapsed'] = elapsed
        t.setdefault('progress_log', []).append(log_entry)
        # 限制 progress_log 大小，防止无限增长
        if len(t['progress_log']) > MAX_PROGRESS_LOG:
            t['progress_log'] = t['progress_log'][-MAX_PROGRESS_LOG:]
        t['updatedAt'] = at
        done_cnt[0] = sum(1 for td in t.get('todos', []) if td.get('status') == 'completed')
        total_cnt[0] = len(t.get('todos', []))
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    res_info = ''
    if tokens or cost or elapsed:
        res_info = f' [res: {tokens}tok/${cost:.4f}/{elapsed}s]'
    log.info(f'📡 {task_id} 进展: {clean[:40]}... [{done_cnt[0]}/{total_cnt[0]}]{res_info}')

def cmd_todo(task_id, todo_id, title, status='not-started', detail=''):
    """添加或更新子任务 todo（原子操作）

    status: not-started / in-progress / completed
    detail: 可选，该子任务的详细产出/说明（Markdown 格式）
    """
    # 校验 status 值
    if status not in ('not-started', 'in-progress', 'completed'):
        status = 'not-started'
    result_info = [0, 0]
    def modifier(tasks):
        t = find_task(tasks, task_id)
        if not t:
            log.error(f'任务 {task_id} 不存在')
            return tasks
        if 'todos' not in t:
            t['todos'] = []
        existing = next((td for td in t['todos'] if str(td.get('id')) == str(todo_id)), None)
        if existing:
            existing['status'] = status
            if title:
                existing['title'] = title
            if detail:
                existing['detail'] = detail
        else:
            item = {'id': todo_id, 'title': title, 'status': status}
            if detail:
                item['detail'] = detail
            t['todos'].append(item)
        t['updatedAt'] = now_iso()
        _auto_advance_when_todos_done(t)
        result_info[0] = sum(1 for td in t['todos'] if td.get('status') == 'completed')
        result_info[1] = len(t['todos'])
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    log.info(f'✅ {task_id} todo [{result_info[0]}/{result_info[1]}]: {todo_id} → {status}')

_CMD_MIN_ARGS = {
    'create': 6, 'state': 2, 'flow': 5, 'done': 2, 'block': 3, 'todo': 4, 'progress': 3,
}

_SHORT_USAGE = (
    "用法: python3 scripts/kanban_update.py <cmd> [...]\n"
    "常用: create/state/flow/done/todo/progress\n"
    "查看完整帮助: python3 scripts/kanban_update.py help"
)

if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print(_SHORT_USAGE)
        sys.exit(0)
    cmd = args[0]
    if cmd in ('help', '--help', '-h'):
        print(__doc__)
        sys.exit(0)
    if cmd in _CMD_MIN_ARGS and len(args) < _CMD_MIN_ARGS[cmd]:
        print(f'错误："{cmd}" 命令至少需要 {_CMD_MIN_ARGS[cmd]} 个参数，实际 {len(args)} 个')
        print(_SHORT_USAGE)
        sys.exit(1)
    if cmd == 'create':
        cmd_create(args[1], args[2], args[3], args[4], args[5], args[6] if len(args)>6 else None)
    elif cmd == 'state':
        # 兼容 agent 偶发误调用：`state <task_id>`（缺 state 参数）
        # 若 dispatch worker 通过环境变量提供了 EDICT_DISPATCH_STATE，则自动兜底。
        fallback_state = (os.environ.get('EDICT_DISPATCH_STATE') or '').strip()
        if len(args) == 2 and fallback_state:
            cmd_state(args[1], fallback_state, f'自动兜底状态：{fallback_state}')
        elif len(args) == 2 and not fallback_state:
            print('错误："state" 缺少状态参数（例如 Doing / Menxia / Done）')
            print('示例: python3 scripts/kanban_update.py state <task_id> <state> "<说明>"')
            sys.exit(1)
        else:
            cmd_state(args[1], args[2], args[3] if len(args)>3 else None)
    elif cmd == 'flow':
        cmd_flow(args[1], args[2], args[3], args[4])
    elif cmd == 'done':
        cmd_done(args[1], args[2] if len(args)>2 else '', args[3] if len(args)>3 else '')
    elif cmd == 'block':
        cmd_block(args[1], args[2])
    elif cmd == 'todo':
        # 解析可选 --detail 参数
        todo_pos = []
        todo_detail = ''
        ti = 1
        while ti < len(args):
            if args[ti] == '--detail' and ti + 1 < len(args):
                todo_detail = args[ti + 1]; ti += 2
            else:
                todo_pos.append(args[ti]); ti += 1
        cmd_todo(
            todo_pos[0] if len(todo_pos) > 0 else '',
            todo_pos[1] if len(todo_pos) > 1 else '',
            todo_pos[2] if len(todo_pos) > 2 else '',
            todo_pos[3] if len(todo_pos) > 3 else 'not-started',
            detail=todo_detail,
        )
    elif cmd == 'progress':
        # 解析可选 --tokens/--cost/--elapsed 参数
        pos_args = []
        kw = {}
        i = 1
        while i < len(args):
            if args[i] == '--tokens' and i + 1 < len(args):
                kw['tokens'] = args[i + 1]; i += 2
            elif args[i] == '--cost' and i + 1 < len(args):
                kw['cost'] = args[i + 1]; i += 2
            elif args[i] == '--elapsed' and i + 1 < len(args):
                kw['elapsed'] = args[i + 1]; i += 2
            else:
                pos_args.append(args[i]); i += 1
        cmd_progress(
            pos_args[0] if len(pos_args) > 0 else '',
            pos_args[1] if len(pos_args) > 1 else '',
            pos_args[2] if len(pos_args) > 2 else '',
            tokens=kw.get('tokens', 0),
            cost=kw.get('cost', 0.0),
            elapsed=kw.get('elapsed', 0),
        )
    else:
        print(__doc__)
        sys.exit(1)
