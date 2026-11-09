import contextlib
import copy
import csv
from datetime import date
from decimal import Decimal
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import hr_local as hr
import hr_connect as connect
import package_skill as release


def employees():
    return hr.read_csv(ROOT / 'examples/local/employees.csv', hr.EMPLOYEE_FIELDS)


def pay_data():
    return hr.read_csv(ROOT / 'examples/local/payroll.csv', hr.PAY_FIELDS)


def rules():
    return json.loads((ROOT / 'examples/local/payroll-rules.json').read_text(encoding='utf-8'))


def config(kind='generic'):
    c = dict(enabled=True, kind=kind, api_key_env='TEST_HR_KEY', query={})
    if kind == 'generic':
        c.update(base_url='https://hr.example.invalid', allowed_host='hr.example.invalid', path='/api/employees')
    else:
        c.update(client_id='public-client-id', path={
            'dingtalk': '/v1.0/contact/users/union123',
            'feishu': '/open-apis/contact/v3/users',
            'wecom': '/cgi-bin/user/list'}[kind])
    return c


class LocalTests(unittest.TestCase):
    def test_metrics_balance_and_turnover(self):
        s = hr.metrics(employees(), '2026-10')['summary']
        self.assertEqual(s, dict(opening=2, hires=2, leaves=2, closing=2, turnover_percent=Decimal('100.00')))
        self.assertEqual(s['opening'] + s['hires'] - s['leaves'], s['closing'])

    def test_month_first_and_last_day_leavers(self):
        rows = employees()[:1]
        rows[0].update(status='left', leave_date='2026-10-01')
        for leave in ('2026-10-01', '2026-10-31'):
            rows[0]['leave_date'] = leave
            s = hr.metrics(rows, '2026-10')['summary']
            self.assertEqual((s['opening'], s['closing'], s['leaves']), (1, 0, 1))

    def test_same_day_hire_leave_zero_denominator(self):
        rows = employees()[:1]
        rows[0].update(status='left', hire_date='2026-10-01', probation_end='', contract_end='', leave_date='2026-10-01')
        s = hr.metrics(rows, '2026-10')['summary']
        self.assertEqual((s['opening'], s['hires'], s['leaves'], s['closing']), (0, 1, 1, 0))
        self.assertIsNone(s['turnover_percent'])

    def test_leap_month(self):
        self.assertEqual(hr.period('2024-02')[1], date(2024, 2, 29))

    def test_empty_data_not_pass(self):
        for result in (hr.audit([], date(2026, 11, 1)), hr.metrics([], '2026-10'),
                       hr.payroll([], rules(), '2026-10'), hr.performance([])):
            self.assertEqual(result['status'], 'no_data')

    def test_audit_expected_due(self):
        r = hr.audit(employees(), date(2026, 11, 1))
        self.assertEqual(r['status'], 'needs_review')
        self.assertEqual({(v['employee_id'], v['item'], v['days_left']) for v in r['details']},
                         {('DEMO001', 'contract_end', 14), ('DEMO002', 'probation_end', 19)})

    def test_audit_boundaries_and_missing(self):
        rows = employees()[:1]
        for ending, level in [('2026-10-31', 'overdue'), ('2026-11-01', 'due'), ('2026-12-01', 'due')]:
            rows[0]['contract_end'] = ending
            self.assertEqual(hr.audit(rows, date(2026, 11, 1))['details'][0]['level'], level)
        rows[0].update(contract_end='', department='')
        self.assertEqual(len(hr.audit(rows, date(2026, 11, 1))['details']), 2)

    def test_duplicate_ids_block(self):
        rows = employees()
        with self.assertRaises(ValueError):
            hr.metrics(rows + rows[:1], '2026-10')

    def test_date_and_status_inconsistency_block(self):
        for update in ({'leave_date': '2026-10-01'}, {'status': 'left'},
                       {'hire_date': '2026-02-30'}, {'contract_end': '2024-12-31'}):
            rows = employees()[:1]
            rows[0].update(update)
            with self.assertRaises(ValueError):
                hr.metrics(rows, '2026-10')

    def test_payroll_exact(self):
        r = hr.payroll(pay_data(), rules(), '2026-10')
        self.assertEqual(r['status'], 'simulation')
        self.assertEqual(r['summary']['gross'], Decimal('14987.50'))
        self.assertEqual(r['summary']['deductions'], Decimal('2800.00'))
        self.assertEqual(r['summary']['net'], Decimal('12187.50'))
        self.assertEqual(r['details'][0]['overtime'], Decimal('187.50'))

    def test_confirmed_is_still_review(self):
        r = rules(); r['mode'] = 'confirmed'
        self.assertEqual(hr.payroll(pay_data(), r, '2026-10')['status'], 'needs_review')

    def test_unconfirmed_missing_and_expired_rules(self):
        for update in ({'confirmed': False}, {'source': ''}, {'effective_start': '2026-10-02'},
                       {'effective_end': '2026-10-30'}, {'hourly_divisor': '0'}, {'mode': 'auto'}):
            r = rules(); r.update(update)
            with self.assertRaises(ValueError):
                hr.payroll(pay_data(), r, '2026-10')

    def test_numbers_reject_nonfinite_negative_and_blank(self):
        for value in ('NaN', 'Infinity', '-1', '', None, True, '1e500'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    hr.number(value, 'amount')

    def test_pay_days_invalid(self):
        for update in ({'payable_days': '0'}, {'paid_days': '21'}, {'tax': ''}):
            rows = pay_data(); rows[0].update(update)
            with self.assertRaises(ValueError):
                hr.payroll(rows, rules(), '2026-10')

    def test_negative_net_retained(self):
        rows = pay_data()[:1]; rows[0]['tax'] = '99999'
        row = hr.payroll(rows, rules(), '2026-10')['details'][0]
        self.assertLess(row['net'], 0)
        self.assertEqual(row['review'], 'negative_net')

    def test_round_half_up(self):
        self.assertEqual(hr.money(Decimal('1.005')), Decimal('1.01'))

    def test_performance_evidence_and_score(self):
        rows = hr.read_csv(ROOT / 'examples/local/performance.csv', hr.PERF_FIELDS)
        r = hr.performance(rows)
        self.assertEqual(r['details'][0]['score'], Decimal('92.00'))
        self.assertEqual(r['details'][1]['score'], Decimal('75.00'))
        self.assertEqual(r['details'][1]['evidence'], 'missing')
        self.assertEqual(r['status'], 'needs_review')

    def test_weights_and_duplicates(self):
        rows = hr.read_csv(ROOT / 'examples/local/performance.csv', hr.PERF_FIELDS)
        with self.assertRaises(ValueError):
            hr.performance(rows[:1])
        with self.assertRaises(ValueError):
            hr.performance(rows + rows[:1])

    def test_lower_zero_caps(self):
        r = dict(employee_id='A', indicator='bugs', weight='100', target='5', actual='0', direction='lower', evidence='proof')
        self.assertEqual(hr.performance([r])['details'][0]['score'], Decimal('120.00'))

    def test_csv_bad_shapes_and_duplicate_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'bad.csv'
            for text in ('a,a\n1,2\n', 'a,b\n1,2,3\n', 'a,b\n1\n'):
                p.write_text(text, encoding='utf-8')
                with self.assertRaises(ValueError):
                    hr.read_csv(p, ('a', 'b'))

    def test_output_no_overwrite_and_formula_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'result'
            r = hr.audit(employees(), date(2026, 11, 1))
            r['details'][0]['employee_id'] = ' =HYPERLINK("bad")'
            hr.write_result(r, out)
            with (out / 'details.csv').open(encoding='utf-8-sig', newline='') as f:
                first = next(csv.DictReader(f))
            self.assertTrue(first['employee_id'].startswith("'"))
            self.assertEqual(json.loads((out / 'result.json').read_text(encoding='utf-8'))['details'][0]['employee_id'], ' =HYPERLINK("bad")')
            with self.assertRaises(FileExistsError):
                hr.write_result(r, out)

    def test_cli_all_four_commands_and_traceability(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, filename, extra in (
                ('audit', 'employees.csv', ['--as-of', '2026-11-01']),
                ('metrics', 'employees.csv', ['--month', '2026-10']),
                ('payroll', 'payroll.csv', ['--month', '2026-10', '--rules', str(ROOT / 'examples/local/payroll-rules.json')]),
                ('performance', 'performance.csv', [])):
                out = Path(tmp) / name
                run = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/hr_local.py'), name,
                    '--input', str(ROOT / 'examples/local' / filename), '--output', str(out)] + extra, capture_output=True)
                self.assertEqual(run.returncode, 0, run.stderr)
                result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
                self.assertEqual(len(result['sources'][0]['sha256']), 64)
                self.assertTrue((out / 'report.md').is_file())


class ConnectorTests(unittest.TestCase):
    def test_disabled_and_missing_key_make_no_requests(self):
        with patch.object(connect, 'request_json') as request:
            for kind in ('generic', 'dingtalk', 'feishu', 'wecom'):
                c = config(kind); c['enabled'] = False
                with self.assertRaises(ValueError): connect.pull(c, 'fake-key')
                c['enabled'] = True
                with self.assertRaises(ValueError): connect.pull(c, '')
            request.assert_not_called()

    def test_generic_bearer_key_and_raw_header(self):
        for raw in (False, True):
            c = config()
            if raw: c.update(auth_header='X-API-Key', auth_scheme='raw')
            with patch.object(connect, 'request_json', return_value={'employees': []}) as request:
                r = connect.pull(c, 'fake-test-key')
            headers = request.call_args.kwargs['headers']
            self.assertEqual(headers['X-API-Key' if raw else 'Authorization'], 'fake-test-key' if raw else 'Bearer fake-test-key')
            self.assertEqual(r['coverage'], 'single_response_not_complete_sync')

    def test_native_auth_and_resource_hosts(self):
        cases = [('dingtalk', {'accessToken': 'test-token'}),
                 ('feishu', {'code': 0, 'tenant_access_token': 'test-token'}),
                 ('wecom', {'errcode': 0, 'access_token': 'test-token'})]
        for kind, auth in cases:
            with self.subTest(kind=kind), patch.object(connect, 'request_json', side_effect=[auth, {'users': []}]) as request:
                r = connect.pull(config(kind), 'test-key')
                self.assertEqual(request.call_count, 2)
                self.assertEqual(r['kind'], kind)
                self.assertTrue(request.call_args.args[0].startswith('https://' + connect.HOSTS[kind] + '/'))
                self.assertNotIn('test-key', json.dumps(r))
                self.assertNotIn('test-token', json.dumps(r))

    def test_failed_native_auth_never_reads_business_data(self):
        for kind in ('dingtalk', 'feishu', 'wecom'):
            with patch.object(connect, 'request_json', return_value={'errcode': 40013}) as request:
                with self.assertRaises(ValueError): connect.pull(config(kind), 'test-key')
                self.assertEqual(request.call_count, 1)

    def test_platform_business_error(self):
        for data in ({'code': 999}, {'errcode': 400}, {'success': False}):
            with patch.object(connect, 'request_json', return_value=data):
                with self.assertRaises(ValueError): connect.pull(config(), 'test-key')

    def test_bad_config_blocked_before_request(self):
        variants = [dict(base_url='http://hr.example.invalid'), dict(allowed_host='evil.invalid'),
                    dict(base_url='https://a:b@hr.example.invalid'), dict(path='//evil.invalid/x'),
                    dict(path='/api/%2e%2e/secret'), dict(path='/api?key=x'), dict(query={'access_token': 'x'}),
                    dict(api_key='plaintext'), dict(auth_header='Host'), dict(auth_scheme='Basic'),
                    dict(path='/api\r\nHeader:x')]
        with patch.object(connect, 'request_json') as request:
            for update in variants:
                c = config(); c.update(update)
                with self.subTest(update=update), self.assertRaises(ValueError): connect.pull(c, 'test-key')
            request.assert_not_called()

    def test_native_write_paths_rejected(self):
        for kind, path in [('wecom', '/cgi-bin/user/delete'), ('feishu', '/open-apis/contact/v3/users/batch_delete/execute'),
                           ('dingtalk', '/v1.0/contact/users/../delete')]:
            c = config(kind); c['path'] = path
            with self.assertRaises(ValueError): connect.validate_config(c)

    def test_secrets_redacted_even_if_echoed(self):
        value = {'secret-test': 'contains secret-test', 'access_token': 'other', 'list': ['secret-test'], 'api_key': 'x'}
        output = json.dumps(connect.sanitize(value, ['secret-test']))
        self.assertNotIn('secret-test', output)
        self.assertNotIn('other', output)

    def test_redirect_denied(self):
        self.assertIsNone(connect.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.invalid'))

    def test_http_error_does_not_leak_url_or_body(self):
        error = urllib.error.HTTPError('https://x.invalid?access_token=secret-test', 401, 'secret-test', {}, None)
        with patch('urllib.request.OpenerDirector.open', side_effect=error):
            with self.assertRaises(ValueError) as caught:
                connect.request_json('https://example.invalid')
        self.assertNotIn('secret-test', str(caught.exception))
        self.assertIn('401', str(caught.exception))

    def test_cli_missing_key_no_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, out = Path(tmp) / 'config.json', Path(tmp) / 'snapshot.json'
            cfg.write_text(json.dumps(config()), encoding='utf-8')
            with patch.dict('os.environ', {}, clear=True), contextlib.redirect_stderr(io.StringIO()), patch.object(connect, 'request_json') as request:
                self.assertEqual(connect.main(['pull', '--config', str(cfg), '--output', str(out)]), 2)
                request.assert_not_called()
                self.assertFalse(out.exists())

    def test_transport_rejects_large_and_invalid_responses(self):
        from unittest.mock import MagicMock
        for raw in (b'x' * (connect.MAX_BYTES + 1), b'not-json', b'\xff'):
            response = MagicMock()
            response.__enter__.return_value.read.return_value = raw
            with patch('urllib.request.OpenerDirector.open', return_value=response):
                with self.assertRaises(ValueError): connect.request_json('https://example.invalid')

    def test_transport_timeout_is_failure(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=TimeoutError('do-not-echo')):
            with self.assertRaises(ValueError) as caught: connect.request_json('https://example.invalid')
        self.assertNotIn('do-not-echo', str(caught.exception))

    def test_cli_success_persists_redacted_snapshot_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, out = Path(tmp) / 'config.json', Path(tmp) / 'snapshot.json'
            cfg.write_text(json.dumps(config()), encoding='utf-8')
            stdout = io.StringIO()
            with patch.dict('os.environ', {'TEST_HR_KEY': 'fake-secret-for-test'}), contextlib.redirect_stdout(stdout), \
                 patch.object(connect, 'request_json', return_value={'echo': 'fake-secret-for-test', 'users': []}):
                self.assertEqual(connect.main(['pull', '--config', str(cfg), '--output', str(out)]), 0)
            self.assertNotIn('fake-secret-for-test', out.read_text(encoding='utf-8') + stdout.getvalue())
            self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['status'], 'snapshot')

    def test_existing_snapshot_blocks_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, out = Path(tmp) / 'config.json', Path(tmp) / 'snapshot.json'
            cfg.write_text(json.dumps(config()), encoding='utf-8'); out.write_text('preserve')
            with contextlib.redirect_stderr(io.StringIO()), patch.object(connect, 'request_json') as request:
                self.assertEqual(connect.main(['pull', '--config', str(cfg), '--output', str(out)]), 2)
                request.assert_not_called()
            self.assertEqual(out.read_text(), 'preserve')

    def test_hidden_input_cannot_fallback_to_echo(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / 'config.json'; cfg.write_text(json.dumps(config()), encoding='utf-8')
            with patch('sys.stdin.isatty', return_value=False), patch('getpass.getpass') as prompt, \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(connect.main(['pull', '--config', str(cfg), '--prompt-key', '--output', str(Path(tmp) / 'out.json')]), 2)
                prompt.assert_not_called()


class PackagingTests(unittest.TestCase):
    def test_release_allowlist_and_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for name in release.RELEASE_FILES:
                dest = target / name; dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(release.source_path(ROOT, name).read_bytes())
            (target / 'examples' / 'private-keys.json').write_text('{"secret":"never-package"}')
            zip_path, digest = release.package(target)
            self.assertEqual(len(digest), 64)
            suite_version = json.loads((target / 'suite.json').read_text(encoding='utf-8'))['version']
            self.assertEqual(zip_path.name, f'hr-specialist-{suite_version}.zip')
            self.assertEqual(zip_path.parent, (target / 'dist/skillhub').resolve())
            manifest = json.loads((zip_path.parent / f'hr-specialist-{suite_version}.manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['sha256'], digest)
            self.assertEqual({f['path'] for f in manifest['files']}, set(release.RELEASE_FILES))
            with zipfile.ZipFile(zip_path) as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(set(z.namelist()), set(release.RELEASE_FILES))
                self.assertIn('SKILL.md', z.namelist())
                self.assertNotIn('LICENSE', z.namelist())
                self.assertEqual(z.read('LICENSE.txt'), release.source_path(ROOT, 'LICENSE.txt').read_bytes())
                self.assertIn(b'](LICENSE.txt)', z.read('README.md'))
                self.assertTrue(all(Path(n).suffix.lower() in release.RELEASE_SUFFIXES for n in z.namelist()))
                self.assertFalse(z.read('SKILL.md').startswith(b'\xef\xbb\xbf'))
                self.assertTrue(all('..' not in Path(n).parts and not n.startswith('/') for n in z.namelist()))

    def test_relative_markdown_links_resolve(self):
        for name in release.RELEASE_FILES:
            if not name.endswith('.md'): continue
            p = release.source_path(ROOT, name)
            for link in re.findall(r'\]\(([^)]+)\)', p.read_text(encoding='utf-8')):
                if '://' not in link and not link.startswith('#'):
                    self.assertTrue((p.parent / link.split('#')[0]).is_file(), f'{name}: {link}')


if __name__ == '__main__':
    unittest.main()
