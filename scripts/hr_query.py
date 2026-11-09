"""Scenario-based, principal-bound, read-only HR queries. Python 3.10+."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from uuid import uuid4

from hr_connect import ServiceError, request_json, validate_config
from hr_security import mask_data, safe_link

ROOT = Path(__file__).resolve().parents[1]
STATUSES = {
    'not_connected': '尚未配置连接器；请查看 CONNECTORS.md 配置入口，不猜测数据。',
    'not_authorized': '缺少 API Key 或用户授权，请在宿主连接器设置中完成授权。',
    'auth_expired': '授权已失效，请重新授权后重试；本次不自动轮询。',
    'permission_denied': '当前身份无权查询该范围，不代表没有数据。',
    'module_unavailable': '该模块未开通或未配置映射，不代表没有数据。',
    'service_error': '服务异常，请稍后重试，并保留 request_id/client_request_id 报障。',
    'invalid_request': '请求参数或连接配置不符合约定，请检查后重试。',
    'contract_error': '服务响应缺少有效身份、权限或分页信息，已阻止展示。',
    'empty': '查询成功，在当前授权范围及筛选条件下没有记录。',
    'ok': '查询成功；仅展示授权范围内已脱敏的记录。',
    'partial': '只取得当前页，尚有后续记录；不能当作全部数据。',
}


class QueryError(ValueError):
    def __init__(self, status, message=None, request_id=None):
        super().__init__(message or STATUSES[status])
        self.status, self.request_id = status, request_id


def catalog():
    return json.loads((ROOT / 'assets/catalog/scenarios.json').read_text(encoding='utf-8'))


def safe_id(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value) else None


def params_for(spec, params):
    if not isinstance(params, dict) or set(params) - set(spec['parameters']):
        raise QueryError('invalid_request', '存在未知参数；本人身份、租户及权限不可由请求参数指定。')
    result = {}
    for key, value in params.items():
        kind = spec['parameters'][key]
        if kind == 'integer':
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                raise QueryError('invalid_request', f'{key} 必须为0到100之间的整数。')
            if key == 'page_size' and value == 0:
                raise QueryError('invalid_request', 'page_size 必须大于0。')
        elif not isinstance(value, str) or not value.strip() or len(value) > 1000 or any(ord(c) < 32 for c in value):
            raise QueryError('invalid_request', f'{key} 需要非空短文本。')
        if kind == 'date':
            from datetime import date
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value): raise ValueError()
                date.fromisoformat(value)
            except ValueError:
                raise QueryError('invalid_request', f'{key} 需要有效 YYYY-MM-DD 日期。') from None
        result[key] = value
    for key in spec.get('required', []):
        if key not in result:
            raise QueryError('invalid_request', f'缺少必需参数：{key}')
    if 'start_date' in result and 'end_date' in result and result['start_date'] > result['end_date']:
        raise QueryError('invalid_request', '开始日期不能晚于结束日期。')
    if result.get('experience_min', 0) > result.get('experience_max', 100):
        raise QueryError('invalid_request', '经验下限不能超过经验上限。')
    return result


def query_config(config):
    if not isinstance(config, dict) or config.get('enabled') is not True:
        raise QueryError('not_connected')
    allowed = {'enabled', 'base_url', 'allowed_host', 'api_key_env', 'identity_path', 'routes',
               'auth_header', 'auth_scheme', 'navigation_hosts'}
    if set(config) - allowed:
        raise QueryError('invalid_request', '未知连接字段；不能在配置中指定用户身份、权限或明文密钥。')
    transport = {k: v for k, v in config.items() if k in {'enabled', 'base_url', 'allowed_host', 'api_key_env', 'auth_header', 'auth_scheme'}}
    transport.update(kind='generic', path=config.get('identity_path', ''))
    try:
        _, base, identity_path, _, env = validate_config(transport)
        routes = config.get('routes', {})
        if not isinstance(routes, dict): raise ValueError()
        known = {s['id'] for s in catalog()['scenarios']}
        for scenario, path in routes.items():
            if scenario not in known: raise ValueError()
            validate_config(dict(transport, path=path))
        hosts = config.get('navigation_hosts', [])
        if not isinstance(hosts, list) or any(not isinstance(h, str) or not re.fullmatch(r'[A-Za-z0-9.-]+', h) for h in hosts):
            raise ValueError()
    except (ValueError, TypeError):
        raise QueryError('invalid_request', '需要合法 HTTPS 主机、身份端点、场景映射和导航主机白名单。') from None
    return base, identity_path, env


def envelope(response):
    if not isinstance(response, dict): raise QueryError('contract_error')
    status = response.get('status')
    if status != 'ok':
        if status not in {'not_authorized', 'auth_expired', 'permission_denied', 'module_unavailable', 'service_error'}:
            raise QueryError('contract_error')
        message = response.get('message')
        raise QueryError(status, message[:500] if isinstance(message, str) else None, safe_id(response.get('request_id')))
    return response


def principal(response):
    data = envelope(response).get('data')
    if not isinstance(data, dict): raise QueryError('contract_error')
    if any(not safe_id(data.get(k)) for k in ('subject_id', 'tenant_id', 'employee_id')):
        raise QueryError('contract_error')
    for k in ('roles', 'permissions', 'managed_department_ids', 'managed_position_ids'):
        if not isinstance(data.get(k), list) or any(not safe_id(v) for v in data[k]):
            raise QueryError('contract_error')
    return data


def authorize(identity, spec, params):
    if spec['permission'] not in identity['permissions']:
        raise QueryError('permission_denied')
    scope = spec['scope']
    roles = set(identity['roles'])
    if scope in {'team', 'organization'}:
        if params.get('purpose') != 'management' or not roles.intersection({'manager', 'hr', 'hrbp'}):
            raise QueryError('permission_denied', '团队数据仅限具备权限的管理用途，请明确查询团队管理事项。')
        dept = params.get('department_id')
        if dept and dept not in identity['managed_department_ids']:
            raise QueryError('permission_denied')
    if scope == 'recruitment':
        if not roles.intersection({'hr', 'hrbp', 'manager'}): raise QueryError('permission_denied')
        if not roles.intersection({'hr', 'hrbp'}) and params.get('position_id') and params['position_id'] not in identity['managed_position_ids']:
            raise QueryError('permission_denied')


def normalize(response, identity, spec, params, navigation_hosts):
    data = envelope(response)
    authz = data.get('authorization', {})
    expected = dict(subject_id=identity['subject_id'], tenant_id=identity['tenant_id'],
                    scope=spec['scope'], permission=spec['permission'], enforced=True)
    if not isinstance(authz, dict) or authz.get('enforced') is not True or any(authz.get(k) != v for k, v in expected.items()):
        raise QueryError('contract_error', '服务未证明按当前身份和场景范围执行权限过滤。')
    rows, page = data.get('records'), data.get('page')
    if not isinstance(rows, list) or len(rows) > params.get('page_size', 100) or not isinstance(page, dict):
        raise QueryError('contract_error')
    if not isinstance(page.get('has_more'), bool): raise QueryError('contract_error')
    cursor = page.get('next_cursor')
    if page['has_more'] and (not isinstance(cursor, str) or not cursor or len(cursor) > 1000):
        raise QueryError('contract_error')
    if not page['has_more'] and cursor not in (None, ''):
        raise QueryError('contract_error')
    details = []
    for row in rows:
        if not isinstance(row, dict):
            raise QueryError('contract_error')
        if row.get('tenant_id') != identity['tenant_id']:
            raise QueryError('permission_denied', '服务返回跨租户或无法识别归属的数据，已整页阻断。')
        if spec['scope'] == 'self' and row.get('owner_employee_id') != identity['employee_id']:
            raise QueryError('permission_denied', '服务返回其他员工自助数据，已整页阻断。')
        if spec['skill'] == 'hr-recruiting-todos' and row.get('owner_subject_id') != identity['subject_id']:
            raise QueryError('permission_denied', '招聘待办不属于当前用户，已整页阻断。')
        if spec['scope'] in {'team', 'organization'} and row.get('department_id') not in identity['managed_department_ids']:
            raise QueryError('permission_denied')
        if spec['scope'] == 'recruitment' and not set(identity['roles']).intersection({'hr', 'hrbp'}):
            if row.get('position_id') not in identity['managed_position_ids']:
                raise QueryError('permission_denied')
        item = {k: row[k] for k in spec['fields'] if k in row}
        if not item:
            raise QueryError('contract_error', '记录没有本场景可展示字段，请检查厂商字段映射。')
        for key in list(item):
            if key.endswith('_url') or key == 'url':
                clean = safe_link(item[key], navigation_hosts)
                item[key] = clean if clean else '[LINK_BLOCKED]'
        details.append(mask_data(item))
    status = 'partial' if page['has_more'] else ('ok' if rows else 'empty')
    return dict(status=status, message=STATUSES[status], request_id=safe_id(data.get('request_id')),
                records=details, page={'has_more': page['has_more'], 'next_cursor': cursor},
                coverage='current_page_of_authorized_filtered_query',
                scope=spec['scope'], mode=spec['mode'],
                data_classification='masked',
                untrusted_content=True)


def execute(scenario, params=None, *, config=None, api_key='', demo=False):
    """No caller-supplied identity is accepted in the live path."""
    request_id = 'hr-' + uuid4().hex
    try:
        spec = next((s for s in catalog()['scenarios'] if s['id'] == scenario), None)
        if not spec: raise QueryError('invalid_request', '场景不存在，请先查看 catalog。')
        params = params_for(spec, params if params is not None else {})
        if demo:
            # Synthetic fixture only; never infer live identity from local files.
            fixture = json.loads((ROOT / 'examples/queries/demo.json').read_text(encoding='utf-8'))
            if scenario not in fixture['responses']:
                raise QueryError('module_unavailable', '该场景没有内置演示数据。')
            identity = principal(fixture['identity'])
            authorize(identity, spec, params)
            result = normalize(fixture['responses'][scenario], identity, spec, params, ['hr.example.invalid'])
        else:
            base, identity_path, _ = query_config(config)
            if not isinstance(api_key, str) or not api_key or any(ord(c) < 33 or ord(c) > 126 for c in api_key):
                raise QueryError('not_authorized')
            route = config.get('routes', {}).get(scenario)
            if not route: raise QueryError('module_unavailable')
            auth = ('Bearer ' if config.get('auth_scheme', 'Bearer') == 'Bearer' else '') + api_key
            headers = {config.get('auth_header', 'Authorization'): auth, 'X-Client-Request-Id': request_id}
            identity = principal(request_json(base + identity_path, headers=headers))
            authorize(identity, spec, params)
            wire = dict(params, scenario=scenario, subject_id=identity['subject_id'],
                        tenant_id=identity['tenant_id'], scope=spec['scope'])
            # Identity and permission must be re-enforced server-side, never trusted from these query params.
            response = request_json(base + route + '?' + urlencode(wire), headers=headers)
            result = normalize(response, identity, spec, params, config.get('navigation_hosts', []))
        result['scenario'] = scenario
        result['filters'] = params
        result['source_host'] = 'hr.example.invalid' if demo else config['allowed_host']
        result['retrieved_at'] = datetime.now(timezone.utc).isoformat()
        result['client_request_id'] = request_id
        result['demo'] = demo
        if demo:
            result['message'] = '【虚构演示，非真实人事数据】' + result['message']
        return mask_data(result, (api_key,))
    except ServiceError as exc:
        result = dict(status=exc.status, message=STATUSES.get(exc.status, STATUSES['service_error']), request_id=exc.request_id)
    except QueryError as exc:
        result = dict(status=exc.status, message=str(exc), request_id=exc.request_id)
    except (ValueError, TypeError, OSError, AttributeError):
        result = dict(status='service_error', message=STATUSES['service_error'], request_id=None)
    result.update(scenario=scenario, client_request_id=request_id, demo=demo, records=[], untrusted_content=True)
    return mask_data(result, (api_key,))


def poll_job(params, *, config=None, api_key='', demo=False, max_attempts=3, interval=5):
    """Explicit bounded read-only polling; stop immediately on errors or terminal state."""
    if (isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 10
            or isinstance(interval, bool) or not isinstance(interval, int) or not 1 <= interval <= 30):
        return dict(status='invalid_request', message='轮询最多1到10次，间隔1到30秒。', records=[])
    for attempt in range(1, max_attempts + 1):
        result = execute('talent.job_status', params, config=config, api_key=api_key, demo=demo)
        result['poll_attempts'] = attempt
        if result['status'] != 'ok': return result
        records = result.get('records', [])
        if len(records) != 1 or records[0].get('job_id') != params.get('job_id'):
            result.update(status='contract_error', message='任务状态响应必须唯一匹配当前任务。', records=[])
            return result
        state = records[0].get('job_status')
        if state not in {'queued', 'running', 'succeeded', 'failed', 'cancelled'}:
            result.update(status='contract_error', message='未识别的任务状态，停止轮询。', records=[])
            return result
        if state in {'succeeded', 'failed', 'cancelled'}: return result
        if attempt < max_attempts: time.sleep(interval)
    result['poll_limit_reached'] = True
    result['message'] += ' 已达到本次轮询上限，任务仍未结束；没有取消后台任务。'
    return result


def render(result):
    def safe_json(data):
        return json.dumps(data, ensure_ascii=False, indent=2).replace('<', '\\u003c').replace('`', '\\u0060')
    lines = ['# HR 查询结果', '', f"状态：{result['status']}", '', '```json', safe_json({'说明': result['message']}), '```', '',
             f"追踪：{result.get('request_id') or result.get('client_request_id')}", '',
             '```json', safe_json({'scope': result.get('scope'), 'filters': result.get('filters'), 'source_host': result.get('source_host')}), '```', '']
    if result.get('demo'): lines += ['**虚构演示，不代表已连接企业系统。**', '']
    for row in result.get('records', []):
        # JSON preserves hostile document text as data instead of embedding raw HTML/Markdown links.
        text = safe_json(row)
        lines += ['```json', text, '```', '']
        for k, v in row.items():
            if (k.endswith('_url') or k == 'url') and isinstance(v, str) and v.startswith('https://'):
                from urllib.parse import quote
                lines += [f'[打开授权业务入口](<{quote(v, safe=":/?=&%.-_~")}>)', '']
    if result.get('page', {}).get('has_more'):
        lines += ['仍有下一页，当前记录不足以代表全部数据。', '']
    if result.get('mode') == 'guide':
        lines += ['仅提供入口引导，未发起任务、提交申请或改变业务记录。', '']
    return '\n'.join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    c = sub.add_parser('catalog'); c.add_argument('--skill')
    for command in ('query', 'poll'):
        q = sub.add_parser(command)
        if command == 'query': q.add_argument('--scenario', required=True)
        else:
            q.set_defaults(scenario='talent.job_status')
            q.add_argument('--max-attempts', type=int, default=3); q.add_argument('--interval', type=int, default=5)
        q.add_argument('--params', default='{}'); q.add_argument('--config'); q.add_argument('--demo', action='store_true')
        q.add_argument('--prompt-key', action='store_true'); q.add_argument('--output')
    args = p.parse_args(argv)
    if args.command == 'catalog':
        data = catalog()
        print(json.dumps([s for s in data['scenarios'] if not args.skill or s['skill'] == args.skill], ensure_ascii=False, indent=2))
        return 0
    try:
        if args.demo and (args.config or args.prompt_key):
            raise QueryError('invalid_request', '演示与在线配置不可混用。')
        if args.output and Path(args.output).exists():
            raise QueryError('invalid_request', '输出目录已存在，拒绝覆盖。')
        config = json.loads(Path(args.config).read_text(encoding='utf-8-sig')) if args.config else None
        key = ''
        if not args.demo and isinstance(config, dict) and config.get('enabled') is True:
            _, _, env = query_config(config)
            if args.prompt_key:
                if not sys.stdin.isatty(): raise QueryError('invalid_request', '隐藏输入需要交互终端。')
                key = getpass.getpass('HR API Key（隐藏输入）: ')
            else:
                key = os.environ.get(env, '')
        params = json.loads(args.params)
        if args.command == 'poll':
            result = poll_job(params, config=config, api_key=key, demo=args.demo,
                              max_attempts=args.max_attempts, interval=args.interval)
        else:
            result = execute(args.scenario, params, config=config, api_key=key, demo=args.demo)
        if args.output:
            out = Path(args.output); out.mkdir(parents=True, exist_ok=False)
            (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            (out / 'report.md').write_text(render(result), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] in ('ok', 'empty', 'partial') else 2
    except (ValueError, OSError, TypeError) as exc:
        status = exc.status if isinstance(exc, QueryError) else 'invalid_request'
        print(json.dumps({'status': status, 'message': STATUSES[status], 'records': []}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
