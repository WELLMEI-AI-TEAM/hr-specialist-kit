"""Deterministic local HR calculations. Python standard library only."""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import json
import re
import sys
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

EMPLOYEE_FIELDS = ('employee_id', 'employee_name', 'department', 'position',
                   'employment_type', 'status', 'hire_date', 'probation_end',
                   'contract_end', 'leave_date')
PAY_FIELDS = ('employee_id', 'base_salary', 'payable_days', 'paid_days',
              'ot_weekday_hours', 'ot_restday_hours', 'ot_holiday_hours',
              'bonus', 'allowance', 'employee_social', 'employee_housing',
              'tax', 'other_deduction')
PERF_FIELDS = ('employee_id', 'indicator', 'weight', 'target', 'actual', 'direction', 'evidence')
MONEY = Decimal('0.01')


def number(value, field):
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f'{field}: 必须为非负有限数值') from None
    if not n.is_finite() or n < 0 or n > Decimal('1000000000000'):
        raise ValueError(f'{field}: 数值超出允许范围')
    return n


def money(n):
    return n.quantize(MONEY, rounding=ROUND_HALF_UP)


def iso(value, field):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError(f'{field}: 需要 YYYY-MM-DD')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f'{field}: 无效日期') from None


def period(value):
    if not re.fullmatch(r'\d{4}-\d{2}', value):
        raise ValueError('month: 需要 YYYY-MM')
    start = iso(value + '-01', 'month')
    return start, start.replace(day=calendar.monthrange(start.year, start.month)[1])


def read_csv(path, required):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or set(required) - set(fields):
            raise ValueError('CSV 表头重复或缺少字段: ' + ', '.join(sorted(set(required) - set(fields))))
        rows = []
        for line, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f'CSV 第 {line} 行列数不匹配')
            rows.append({k: v.strip() for k, v in row.items()})
        return rows


def employee_rows(rows):
    seen = set()
    parsed = []
    for line, r in enumerate(rows, 2):
        eid = r['employee_id']
        if not eid or eid in seen:
            raise ValueError(f'第 {line} 行员工编号为空或重复；返聘需使用任职事件表')
        seen.add(eid)
        if r['status'] not in {'active', 'probation', 'left'}:
            raise ValueError(f'第 {line} 行 status 仅支持 active/probation/left')
        hire = iso(r['hire_date'], f'第 {line} 行 hire_date')
        dates = {k: iso(r[k], f'第 {line} 行 {k}') if r[k] else None
                 for k in ('probation_end', 'contract_end', 'leave_date')}
        if (r['status'] == 'left') != bool(dates['leave_date']):
            raise ValueError(f'第 {line} 行离职状态与离职日期不一致')
        if any(d and d < hire for d in dates.values()):
            raise ValueError(f'第 {line} 行结束日期早于入职日期')
        parsed.append((r, hire, dates))
    return parsed


def audit(rows, as_of, days=30):
    if days < 0 or days > 3660:
        raise ValueError('days 必须在 0 到 3660 之间')
    details = []
    for r, hire, dates in employee_rows(rows):
        if hire > as_of or (dates['leave_date'] and dates['leave_date'] <= as_of):
            continue
        for k in ('employee_name', 'department', 'position', 'employment_type', 'contract_end'):
            if not r[k]:
                details.append(dict(employee_id=r['employee_id'], item=k, level='missing', due_date='', days_left=''))
        if r['status'] == 'probation' and not r['probation_end']:
            details.append(dict(employee_id=r['employee_id'], item='probation_end', level='missing', due_date='', days_left=''))
        keys = ['contract_end'] + (['probation_end'] if r['status'] == 'probation' else [])
        for k in keys:
            due = dates[k]
            if due and due <= as_of + timedelta(days=days):
                left = (due - as_of).days
                details.append(dict(employee_id=r['employee_id'], item=k,
                                    level='overdue' if left < 0 else 'due',
                                    due_date=due.isoformat(), days_left=left))
    return dict(status='no_data' if not rows else ('needs_review' if details else 'ready'),
                summary={'input_rows': len(rows), 'alerts': len(details)}, details=details,
                notes=['到期提醒不是自动转正、续签或解除。contract_end 留空需人工确认是否为无固定期限或缺失。'])


def metrics(rows, month):
    start, end = period(month)
    parsed = employee_rows(rows)
    opening = sum(hire < start and (not ds['leave_date'] or ds['leave_date'] >= start)
                  for _, hire, ds in parsed)
    closing = sum(hire <= end and (not ds['leave_date'] or ds['leave_date'] > end)
                  for _, hire, ds in parsed)
    hires = sum(start <= hire <= end for _, hire, _ in parsed)
    leaves = sum(bool(ds['leave_date'] and start <= ds['leave_date'] <= end) for _, _, ds in parsed)
    average = Decimal(opening + closing) / 2
    rate = money(Decimal(leaves) / average * 100) if average else None
    return dict(status='no_data' if not rows else 'ready',
                summary=dict(opening=opening, hires=hires, leaves=leaves, closing=closing,
                             turnover_percent=rate),
                details=[dict(metric=k, value=v if v is not None else '') for k, v in
                         dict(opening=opening, hires=hires, leaves=leaves, closing=closing,
                              turnover_percent=rate).items()],
                notes=['期初为月初事件发生前；离职日不计在职；月内入离职均计流量。',
                       '离职率=离职人数/((期初+期末)/2)×100%；分母为零时不适用。',
                       '源表必须覆盖期间全部任职记录，包括已离职人员；当前在职名单不足以还原历史。'])


def payroll(rows, rules, month):
    start, end = period(month)
    if rules.get('mode') not in {'simulation', 'confirmed'}:
        raise ValueError('rules.mode 必须为 simulation 或 confirmed')
    if rules.get('confirmed') is not True or not isinstance(rules.get('source'), str) or not rules['source'].strip():
        raise ValueError('规则必须显式确认并注明来源；示例也必须标注 simulation')
    if not (iso(rules.get('effective_start', ''), 'effective_start') <= start
            and iso(rules.get('effective_end', ''), 'effective_end') >= end):
        raise ValueError('规则有效期必须覆盖完整核算月')
    if rules.get('proration') != 'base_times_paid_over_payable':
        raise ValueError('仅支持明确约定的 base_times_paid_over_payable 折算口径')
    divisor = number(rules.get('hourly_divisor'), 'hourly_divisor')
    if not divisor:
        raise ValueError('hourly_divisor 必须大于零')
    multipliers = {k: number(rules.get('overtime_multipliers', {}).get(k), k)
                   for k in ('weekday', 'restday', 'holiday')}
    details, seen = [], set()
    for line, r in enumerate(rows, 2):
        eid = r['employee_id']
        if not eid or eid in seen:
            raise ValueError(f'第 {line} 行员工编号为空或重复')
        seen.add(eid)
        n = {k: number(r[k], f'第 {line} 行 {k}') for k in PAY_FIELDS[1:]}
        if not n['payable_days'] or n['paid_days'] > n['payable_days']:
            raise ValueError(f'第 {line} 行计薪天数为零或实际计薪天数超过约定天数')
        base = money(n['base_salary'] * n['paid_days'] / n['payable_days'])
        ot = money(sum(n[f'ot_{k}_hours'] * n['base_salary'] / divisor * m for k, m in multipliers.items()))
        gross = base + ot + money(n['bonus']) + money(n['allowance'])
        deductions = sum(money(n[k]) for k in ('employee_social', 'employee_housing', 'tax', 'other_deduction'))
        net = gross - deductions
        details.append(dict(employee_id=eid, prorated_base=base, overtime=ot, gross=gross,
                            deductions=deductions, net=net,
                            review='negative_net' if net < 0 else 'pending_payroll_review'))
    total = lambda key: sum((r[key] for r in details), Decimal(0))
    return dict(status='no_data' if not rows else ('simulation' if rules['mode'] == 'simulation' else 'needs_review'),
                summary=dict(employees=len(rows), gross=total('gross'), deductions=total('deductions'), net=total('net')),
                details=details, notes=['工资复核草稿；加班工资基数由输入 base_salary 指定，不自动判断合法性。',
                    '各金额分项按分四舍五入后汇总；个税、社保、公积金仅使用输入核定金额。',
                    '规则来源：' + rules['source'], '不自动发薪，不自动应用当地最低工资、社保或个税政策。'])


def performance(rows):
    groups, seen = {}, set()
    for line, r in enumerate(rows, 2):
        key = (r['employee_id'], r['indicator'])
        if not all(key) or key in seen:
            raise ValueError(f'第 {line} 行员工/指标为空或指标重复')
        seen.add(key)
        if r['direction'] not in {'higher', 'lower'}:
            raise ValueError(f'第 {line} 行 direction 需为 higher/lower')
        weight, target, actual = [number(r[k], f'第 {line} 行 {k}') for k in ('weight', 'target', 'actual')]
        if not target or not weight or weight > 100:
            raise ValueError(f'第 {line} 行 target/weight 必须大于零且 weight 不超过 100')
        ratio = actual / target if r['direction'] == 'higher' else (target / actual if actual else Decimal('1.2'))
        score = min(ratio * 100, Decimal(120))
        groups.setdefault(r['employee_id'], []).append((weight, score * weight / 100, bool(r['evidence'])))
    details = []
    for eid, values in groups.items():
        if sum(v[0] for v in values) != 100:
            raise ValueError(f'员工 {eid} 权重合计必须为 100，不自动归一化')
        evidence = all(v[2] for v in values)
        details.append(dict(employee_id=eid, score=money(sum(v[1] for v in values)),
                            evidence='provided_not_verified' if evidence else 'missing', review='pending_manager_review'))
    return dict(status='no_data' if not rows else 'needs_review', summary={'employees': len(details)},
                details=details, notes=['高向=实际/目标，低向=目标/实际；低向实际为零时取120分上限；指标均封顶120。',
                     '加权后统一保留两位；证据非空不代表核验通过；结果不是自动定级或人事决策。'])


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=lambda x: str(x) if isinstance(x, Decimal) else x)


def source_info(paths):
    return [dict(file=Path(p).name, sha256=hashlib.sha256(Path(p).read_bytes()).hexdigest()) for p in paths]


def write_result(result, output):
    path = Path(output)
    path.mkdir(parents=True, exist_ok=False)
    (path / 'result.json').write_text(json_text(result) + '\n', encoding='utf-8')
    detail = result['details']
    with (path / 'details.csv').open('w', encoding='utf-8-sig', newline='') as f:
        fields = list(detail[0]) if detail else ['message']
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in detail:
            writer.writerow({k: "'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v
                             for k, v in row.items()})
    lines = ['# 人事工作结果', '', f"状态：{result['status']}", '', '```json', json_text(result['summary']), '```', '',
             '口径及待复核事项：', ''] + ['- ' + n for n in result['notes']]
    lines += ['', '明细见 details.csv；来源、参数和 SHA256 见 result.json。', '']
    (path / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('audit', 'metrics', 'payroll', 'performance'):
        p = sub.add_parser(name)
        p.add_argument('--input', required=True)
        p.add_argument('--output', required=True)
        if name == 'audit':
            p.add_argument('--as-of', required=True)
            p.add_argument('--days', type=int, default=30)
        if name in ('metrics', 'payroll'):
            p.add_argument('--month', required=True)
        if name == 'payroll':
            p.add_argument('--rules', required=True)
    args = parser.parse_args(argv)
    try:
        fields = PAY_FIELDS if args.command == 'payroll' else PERF_FIELDS if args.command == 'performance' else EMPLOYEE_FIELDS
        rows = read_csv(args.input, fields)
        sources = [args.input]
        if args.command == 'audit':
            result = audit(rows, iso(args.as_of, 'as-of'), args.days)
        elif args.command == 'metrics':
            result = metrics(rows, args.month)
        elif args.command == 'payroll':
            rules = json.loads(Path(args.rules).read_text(encoding='utf-8-sig'))
            if not isinstance(rules, dict):
                raise ValueError('rules 必须为 JSON 对象')
            result = payroll(rows, rules, args.month)
            sources.append(args.rules)
        else:
            result = performance(rows)
        result['sources'] = source_info(sources)
        result['parameters'] = {k: v for k, v in vars(args).items() if k not in ('input', 'output', 'rules')}
        result['schema_version'] = '1.0.0'
        write_result(result, args.output)
        print(json_text({'status': result['status'], 'output': str(Path(args.output).resolve())}))
        return 0
    except (ValueError, OSError, TypeError, AttributeError, InvalidOperation) as exc:
        print(json_text({'status': 'error', 'message': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
