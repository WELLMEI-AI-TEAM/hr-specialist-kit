import contextlib
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import hr_query as query
import hr_connect as connect
from hr_security import mask_data, safe_link


def fixture():
    return json.loads((ROOT / 'examples/queries/demo.json').read_text(encoding='utf-8'))


def identity():
    return fixture()['identity']


def config(scenario='attendance.balance'):
    return dict(enabled=True, base_url='https://hr.example.invalid', allowed_host='hr.example.invalid',
                identity_path='/identity', api_key_env='TEST_HR_QUERY_KEY',
                routes={scenario: '/query'}, navigation_hosts=['hr.example.invalid'])


def response(scenario='attendance.balance'):
    return fixture()['responses'][scenario]


def run_live(scenario='attendance.balance', params=None, who=None, result=None):
    with patch.object(query, 'request_json', side_effect=[who or identity(), result or response(scenario)]) as request:
        out = query.execute(scenario, params, config=config(scenario), api_key='fake-query-key')
        return out, request


class CatalogTests(unittest.TestCase):
    def test_all_13_skills_and_102_scenarios(self):
        suite = json.loads((ROOT / 'suite.json').read_text(encoding='utf-8'))
        catalog = query.catalog()['scenarios']
        self.assertEqual(suite['business_skill_count'], 13)
        self.assertEqual(len(suite['skills']), 13)
        self.assertEqual(len(catalog), 102)
        self.assertEqual(len({s['id'] for s in catalog}), 102)
        self.assertEqual({s['skill'] for s in catalog} | {'hr-data-query'}, {s['name'] for s in suite['skills']})
        self.assertFalse(suite['internal_rules_registered'])
        self.assertTrue((ROOT / suite['internal_rules']).is_file())
        self.assertNotIn('hr-shared-rules', {s['name'] for s in suite['skills']})
        for s in suite['skills']:
            self.assertTrue((ROOT / 'skills' / s['name'] / 'SKILL.md').is_file())

    def test_writes_are_only_guides(self):
        guide = {'talent.start_entry', 'talent.cancel_entry', 'insight.interview_quality_entry', 'insight.competitor_analysis_entry'}
        for s in query.catalog()['scenarios']:
            self.assertIn(s['mode'], {'query', 'guide'})
            if s['id'] in guide or s['skill'] == 'hr-service-entry':
                self.assertEqual(s['mode'], 'guide')

    def test_every_registered_scene_has_valid_contract(self):
        for spec in query.catalog()['scenarios']:
            with self.subTest(scene=spec['id']):
                self.assertTrue(set(spec['required']) <= set(spec['parameters']))
                self.assertTrue(spec['fields'])
                params = {k: 'management' if k == 'purpose' else 'DEMO-ID' for k in spec['required']}
                query.params_for(spec, params)
                who = identity()
                row = {'tenant_id': 'DEMO-TENANT', spec['fields'][0]: 'DEMO-VALUE'}
                if spec['scope'] == 'self': row['owner_employee_id'] = 'DEMO001'
                if spec['scope'] in {'team', 'organization'}: row['department_id'] = 'DEMO-DEPT'
                if spec['skill'] == 'hr-recruiting-todos': row['owner_subject_id'] = 'DEMO-SUBJECT'
                result = {'status': 'ok', 'records': [row], 'page': {'has_more': False, 'next_cursor': None},
                          'authorization': {'subject_id': 'DEMO-SUBJECT', 'tenant_id': 'DEMO-TENANT',
                                            'scope': spec['scope'], 'permission': spec['permission'], 'enforced': True}}
                with patch.object(query, 'request_json', side_effect=[who, result]):
                    output = query.execute(spec['id'], params, config=config(spec['id']), api_key='fake-query-key')
                self.assertEqual(output['status'], 'ok', output)


class AuthorizationTests(unittest.TestCase):
    def test_no_connection_or_key_no_network(self):
        with patch.object(query, 'request_json') as request:
            for cfg, key, state in [(None, '', 'not_connected'), ({'enabled': False}, 'fake-query-key', 'not_connected'),
                                     (config(), '', 'not_authorized')]:
                self.assertEqual(query.execute('attendance.balance', config=cfg, api_key=key)['status'], state)
            request.assert_not_called()

    def test_unknown_and_identity_override_params_no_network(self):
        with patch.object(query, 'request_json') as request:
            for params in ({'employee_id': 'OTHER'}, {'tenant_id': 'OTHER'}, {'role': 'hr'}, {'scope': 'all'}, []):
                r = query.execute('attendance.balance', params, config=config(), api_key='fake-query-key')
                self.assertEqual(r['status'], 'invalid_request')
            request.assert_not_called()

    def test_identity_cannot_be_declared_in_config(self):
        for field in ('principal', 'roles', 'subject_id', 'api_key', 'employee_id'):
            c = config(); c[field] = 'forged'
            with patch.object(query, 'request_json') as request:
                self.assertEqual(query.execute('attendance.balance', config=c, api_key='fake-query-key')['status'], 'invalid_request')
                request.assert_not_called()

    def test_missing_permission_stops_before_business_read(self):
        who = identity(); who['data']['permissions'] = []
        r, req = run_live(who=who)
        self.assertEqual(r['status'], 'permission_denied'); self.assertEqual(req.call_count, 1)

    def test_self_cross_employee_whole_page_blocked(self):
        result = response(); result['records'][1]['owner_employee_id'] = 'OTHER'
        r, _ = run_live(result=result)
        self.assertEqual(r['status'], 'permission_denied'); self.assertEqual(r['records'], [])

    def test_cross_tenant_blocked(self):
        result = response(); result['records'][0]['tenant_id'] = 'OTHER-TENANT'
        r, _ = run_live(result=result)
        self.assertEqual(r['status'], 'permission_denied'); self.assertEqual(r['records'], [])

    def test_team_requires_explicit_management_purpose(self):
        r, req = run_live('organization.headcount', {'purpose': 'curiosity'})
        self.assertEqual(r['status'], 'permission_denied'); self.assertEqual(req.call_count, 1)
        good, _ = run_live('organization.headcount', {'purpose': 'management'})
        self.assertEqual(good['status'], 'ok')

    def test_team_requires_role_and_managed_department(self):
        who = identity(); who['data']['roles'] = ['employee']
        r, req = run_live('organization.headcount', {'purpose': 'management'}, who=who)
        self.assertEqual(r['status'], 'permission_denied'); self.assertEqual(req.call_count, 1)
        r, _ = run_live('organization.headcount', {'purpose': 'management', 'department_id': 'OTHER'})
        self.assertEqual(r['status'], 'permission_denied')
        result = response('organization.headcount'); result['records'][0]['department_id'] = 'OTHER'
        r, _ = run_live('organization.headcount', {'purpose': 'management'}, result=result)
        self.assertEqual(r['status'], 'permission_denied')

    def test_employee_cannot_query_recruitment(self):
        who = identity(); who['data']['roles'] = ['employee']
        r, req = run_live('position.search', who=who)
        self.assertEqual(r['status'], 'permission_denied'); self.assertEqual(req.call_count, 1)

    def test_manager_only_managed_positions(self):
        who = identity(); who['data']['roles'] = ['manager']
        r, _ = run_live('position.search', who=who)
        self.assertEqual(r['status'], 'ok')
        result = response('position.search'); result['records'][0]['position_id'] = 'OTHER'
        r, _ = run_live('position.search', who=who, result=result)
        self.assertEqual(r['status'], 'permission_denied')
        r, req = run_live('position.detail', {'position_id': 'OTHER'}, who=who)
        self.assertEqual(r['status'], 'permission_denied'); self.assertEqual(req.call_count, 1)

    def test_recruiting_todos_only_current_subject(self):
        result = response('todo.today_interviews'); result['records'][0]['owner_subject_id'] = 'OTHER'
        r, _ = run_live('todo.today_interviews', result=result)
        self.assertEqual(r['status'], 'permission_denied')

    def test_organization_also_requires_management_purpose(self):
        with patch.object(query, 'request_json', return_value=identity()) as req:
            r = query.execute('organization.department', {'purpose': 'curiosity'}, config=config('organization.department'), api_key='fake-query-key')
        self.assertEqual(r['status'], 'permission_denied'); self.assertEqual(req.call_count, 1)

    def test_gateway_must_confirm_scope_enforcement(self):
        for update in ({'enforced': False}, {'enforced': 1}, {'scope': 'all'}, {'subject_id': 'OTHER'}, {'permission': 'admin'}):
            result = response(); result['authorization'].update(update)
            r, _ = run_live(result=result)
            self.assertEqual(r['status'], 'contract_error')

    def test_missing_or_invalid_identity_is_not_empty(self):
        for who in ({'status': 'ok', 'data': {}}, {'status': 'ok', 'data': []}, {'status': 'ok', 'data': {'subject_id': 'X'}}):
            r, req = run_live(who=who)
            self.assertEqual(r['status'], 'contract_error'); self.assertEqual(req.call_count, 1)

    def test_unconfigured_scene_not_requested(self):
        c = config(); c['routes'] = {}
        with patch.object(query, 'request_json') as req:
            r = query.execute('attendance.balance', config=c, api_key='fake-query-key')
        self.assertEqual(r['status'], 'module_unavailable'); req.assert_not_called()


class ResultTests(unittest.TestCase):
    def test_empty_different_from_permission_failure(self):
        result = response(); result['records'] = []
        r, _ = run_live(result=result)
        self.assertEqual(r['status'], 'empty')
        r, _ = run_live(result={'status': 'permission_denied', 'message': '无当前部门权限', 'request_id': 'upstream-403'})
        self.assertEqual(r['status'], 'permission_denied'); self.assertEqual(r['request_id'], 'upstream-403')
        self.assertIn('无当前部门权限', r['message'])

    def test_all_failure_states_preserved(self):
        for state in ('not_authorized', 'auth_expired', 'permission_denied', 'module_unavailable', 'service_error'):
            r, req = run_live(result={'status': state, 'request_id': 'upstream-'+state})
            self.assertEqual(r['status'], state); self.assertEqual(r['records'], [])
            self.assertEqual(req.call_count, 2)

    def test_auth_expired_identity_never_polls(self):
        with patch.object(query, 'request_json', return_value={'status': 'auth_expired'}) as req:
            r = query.execute('attendance.balance', config=config(), api_key='fake-query-key')
        self.assertEqual(r['status'], 'auth_expired'); self.assertEqual(req.call_count, 1)

    def test_http_error_and_request_id(self):
        from urllib.error import HTTPError
        for code, state in ((401, 'auth_expired'), (403, 'permission_denied'), (503, 'service_error')):
            error = HTTPError('https://example.invalid?token=do-not-echo', code, 'private', {'X-Request-Id': 'transport-id'}, None)
            with patch('urllib.request.OpenerDirector.open', side_effect=error):
                r = query.execute('attendance.balance', config=config(), api_key='fake-query-key')
            self.assertEqual(r['status'], state); self.assertEqual(r['request_id'], 'transport-id')
            self.assertNotIn('do-not-echo', json.dumps(r))

    def test_timeout_has_client_trace_no_retry(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=TimeoutError('private')) as req:
            r = query.execute('attendance.balance', config=config(), api_key='fake-query-key')
        self.assertEqual(r['status'], 'service_error'); self.assertTrue(r['client_request_id'].startswith('hr-'))
        self.assertEqual(req.call_count, 1)

    def test_pagination_and_empty_page_with_next(self):
        for rows in (response()['records'], []):
            result = response(); result['records'] = rows
            result['page'] = {'has_more': True, 'next_cursor': 'NEXT-1'}
            r, req = run_live(result=result)
            self.assertEqual(r['status'], 'partial'); self.assertEqual(req.call_count, 2)
            self.assertEqual(r['page']['next_cursor'], 'NEXT-1')
            self.assertIn('下一页', query.render(r))

    def test_bad_paging_and_non_records_fail_closed(self):
        for page in ({}, {'has_more': True, 'next_cursor': None}, {'has_more': 1},
                     {'has_more': False, 'next_cursor': 'not-empty'}):
            result = response(); result['page'] = page
            r, _ = run_live(result=result); self.assertEqual(r['status'], 'contract_error')
        for rows in (None, {}, ['bad-row']):
            result = response(); result['records'] = rows
            r, _ = run_live(result=result); self.assertEqual(r['status'], 'contract_error')

    def test_field_projection_and_sensitive_data_masked(self):
        result = response('profile.basic')
        result['records'][0].update(email='private@example.com', salary='32000', name='虚构员工甲', secret_debug='never-show')
        r, _ = run_live('profile.basic', result=result)
        encoded = json.dumps(r, ensure_ascii=False)
        for forbidden in ('32000', '13800138000', 'private@example.com', 'never-show'):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(r['records'][0]['salary'], '[REDACTED]')
        self.assertNotIn('secret_debug', r['records'][0])

    def test_nested_and_chinese_masking(self):
        raw = {'薪酬': 12345, '身份证': '110101199001011234', 'phone_number': '13800138000',
               'nested': [{'email': 'a@b.com', 'notes': '联系a@b.com，13800138000，工资: 50000元'}]}
        encoded = json.dumps(mask_data(raw), ensure_ascii=False)
        for forbidden in ('12345', '110101199001011234', '13800138000', 'a@b.com', '50000'):
            self.assertNotIn(forbidden, encoded)

    def test_errors_cannot_echo_keys(self):
        r, _ = run_live(result={'status': 'service_error', 'message': 'echo fake-query-key contact a@b.com'})
        self.assertNotIn('fake-query-key', json.dumps(r)); self.assertNotIn('a@b.com', json.dumps(r))

    def test_navigation_whitelist_and_credential_urls(self):
        for url in ('javascript:alert(1)', 'https://evil.invalid/form', 'http://hr.example.invalid/x',
                    'https://hr.example.invalid/x?access_token=secret', 'https://user:pass@hr.example.invalid/',
                    'https://hr.example.invalid/x#token=secret'):
            result = response('service.leave'); result['records'][0]['entry_url'] = url
            r, _ = run_live('service.leave', result=result)
            self.assertEqual(r['records'][0]['entry_url'], '[LINK_BLOCKED]')
            self.assertNotIn('打开授权业务入口', query.render(r))
        r, _ = run_live('service.leave')
        self.assertIn('打开授权业务入口', query.render(r)); self.assertIn('未发起任务', query.render(r))

    def test_prompt_payload_remains_inert_in_report(self):
        result = response('knowledge.search')
        result['records'][0]['content'] = '```\n<script>fetch("secrets")</script>\n![x](https://evil.invalid)'
        r, _ = run_live('knowledge.search', result=result)
        text = query.render(r)
        self.assertTrue(r['untrusted_content'])
        self.assertNotIn('<script>', text)
        self.assertNotIn('```\n<script>', text)

    def test_parameters_types_dates_and_required_ids(self):
        cases = [('attendance.exceptions', {'start_date': '2026-02-30'}),
                 ('attendance.exceptions', {'start_date': '2026-11-02', 'end_date': '2026-11-01'}),
                 ('attendance.balance', {'page_size': 0}), ('attendance.balance', {'page_size': True}),
                 ('attendance.balance', {'page_size': 101}), ('approval.detail', {}),
                 ('talent.search', {'experience_min': 5, 'experience_max': 3})]
        with patch.object(query, 'request_json') as req:
            for scene, params in cases:
                r = query.execute(scene, params, config=config(scene), api_key='fake-query-key')
                self.assertEqual(r['status'], 'invalid_request')
            req.assert_not_called()

    def test_cursor_and_identity_wired_without_key_in_url(self):
        r, req = run_live(params={'cursor': 'NEXT-1', 'page_size': 20})
        url = req.call_args.args[0]
        parsed = parse_qs(urlsplit(url).query)
        self.assertEqual(parsed['subject_id'], ['DEMO-SUBJECT']); self.assertEqual(parsed['cursor'], ['NEXT-1'])
        self.assertNotIn('fake-query-key', url)
        self.assertEqual(req.call_args.kwargs['headers']['Authorization'], 'Bearer fake-query-key')

    def test_async_running_not_success_claim_or_mutation(self):
        r, req = run_live('talent.job_status', {'job_id': 'DEMO-JOB'})
        self.assertEqual(r['records'][0]['job_status'], 'running')
        self.assertEqual(req.call_count, 2)
        for call in req.call_args_list: self.assertNotIn('payload', call.kwargs)
        for scene, params in [('talent.start_entry', {}), ('talent.cancel_entry', {'job_id': 'DEMO-JOB'})]:
            r, req = run_live(scene, params)
            self.assertEqual(r['mode'], 'guide')
            for call in req.call_args_list: self.assertNotIn('payload', call.kwargs)


class CliTests(unittest.TestCase):
    def test_demo_is_explicit_and_never_networks(self):
        with patch.object(query, 'request_json') as req:
            r = query.execute('attendance.balance', demo=True)
            self.assertTrue(r['demo']); self.assertIn('虚构演示', r['message']); req.assert_not_called()

    def test_no_demo_fixture_does_not_invent_data(self):
        with patch.object(query, 'request_json') as req:
            r = query.execute('attendance.correction_history', demo=True)
            self.assertEqual(r['status'], 'module_unavailable'); self.assertEqual(r['records'], []); req.assert_not_called()

    def test_cli_actual_demo_report_and_readable_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'balance'
            run = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/hr_query.py'), 'query',
                '--scenario', 'attendance.balance', '--demo', '--output', str(out)], capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            value = json.loads((out / 'result.json').read_text(encoding='utf-8'))
            self.assertTrue(value['demo']); self.assertEqual(value['records'][0]['balance'], 5)
            self.assertIn('虚构演示', (out / 'report.md').read_text(encoding='utf-8'))

    def test_cli_no_config_safe_status(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), patch.object(query, 'request_json') as req:
            self.assertEqual(query.main(['query', '--scenario', 'attendance.balance']), 2)
        self.assertEqual(json.loads(stdout.getvalue())['status'], 'not_connected'); req.assert_not_called()

    def test_cli_no_overwrite_or_demo_live_mixing(self):
        with tempfile.TemporaryDirectory() as tmp:
            for extra in (['--output', tmp], ['--config', 'nonexistent.json']):
                with contextlib.redirect_stdout(io.StringIO()), patch.object(query, 'request_json') as req:
                    self.assertEqual(query.main(['query', '--scenario', 'attendance.balance', '--demo'] + extra), 2)
                    req.assert_not_called()


class PollingTests(unittest.TestCase):
    @staticmethod
    def result(state):
        return {'status': 'ok', 'message': '查询成功', 'records': [{'job_id': 'DEMO-JOB', 'job_status': state}]}

    def test_terminal_states_stop_immediately(self):
        for state in ('succeeded', 'failed', 'cancelled'):
            with patch.object(query, 'execute', return_value=self.result(state)) as run, patch.object(query.time, 'sleep') as sleep:
                r = query.poll_job({'job_id': 'DEMO-JOB'})
            self.assertEqual(r['records'][0]['job_status'], state); self.assertEqual(run.call_count, 1); sleep.assert_not_called()

    def test_running_to_success_bounded(self):
        with patch.object(query, 'execute', side_effect=[self.result('queued'), self.result('running'), self.result('succeeded')]) as run, patch.object(query.time, 'sleep') as sleep:
            r = query.poll_job({'job_id': 'DEMO-JOB'}, max_attempts=3, interval=1)
        self.assertEqual(r['poll_attempts'], 3); self.assertEqual(run.call_count, 3); self.assertEqual(sleep.call_count, 2)

    def test_expiry_stops_without_sleep_or_retry(self):
        with patch.object(query, 'execute', return_value={'status': 'auth_expired', 'message': '过期', 'records': []}) as run, patch.object(query.time, 'sleep') as sleep:
            r = query.poll_job({'job_id': 'DEMO-JOB'})
        self.assertEqual(r['status'], 'auth_expired'); self.assertEqual(run.call_count, 1); sleep.assert_not_called()

    def test_limit_does_not_claim_job_completed(self):
        with patch.object(query, 'execute', side_effect=lambda *a, **kw: self.result('running')) as run, patch.object(query.time, 'sleep'):
            r = query.poll_job({'job_id': 'DEMO-JOB'}, max_attempts=2)
        self.assertTrue(r['poll_limit_reached']); self.assertEqual(r['records'][0]['job_status'], 'running'); self.assertEqual(run.call_count, 2)

    def test_invalid_limits_no_requests(self):
        for kwargs in ({'max_attempts': 0}, {'max_attempts': 11}, {'interval': 0}, {'interval': 31}):
            with patch.object(query, 'execute') as run:
                r = query.poll_job({'job_id': 'DEMO-JOB'}, **kwargs)
            self.assertEqual(r['status'], 'invalid_request'); run.assert_not_called()

    def test_wrong_job_and_unknown_state_stop(self):
        for data in ({'status': 'ok', 'message': 'ok', 'records': [{'job_id': 'OTHER', 'job_status': 'running'}]}, self.result('unknown')):
            with patch.object(query, 'execute', return_value=data), patch.object(query.time, 'sleep') as sleep:
                r = query.poll_job({'job_id': 'DEMO-JOB'})
            self.assertEqual(r['status'], 'contract_error'); sleep.assert_not_called()

    def test_explicit_cli_poll_demo_remains_running(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch.object(query, 'request_json') as req:
            code = query.main(['poll', '--params', '{"job_id":"DEMO-JOB"}', '--demo', '--max-attempts', '1'])
        self.assertEqual(code, 0); req.assert_not_called()
        r = json.loads(out.getvalue()); self.assertTrue(r['demo']); self.assertTrue(r['poll_limit_reached'])


class TransportContractTests(unittest.TestCase):
    def test_real_http_serialization_with_local_fake_gateway(self):
        """Exercise the actual HTTP client on loopback with fake credentials only."""
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append((self.path, self.headers.get('Authorization')))
                body = identity() if self.path == '/identity' else response()
                raw = json.dumps(body).encode('utf-8')
                self.send_response(200); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True); thread.start()
        actual = connect.request_json
        def local_request(url, **kwargs):
            parsed = urlsplit(url)
            local = f'http://127.0.0.1:{server.server_port}' + parsed.path + ('?' + parsed.query if parsed.query else '')
            return actual(local, **kwargs)
        try:
            with patch.object(query, 'request_json', side_effect=local_request):
                result = query.execute('attendance.balance', config=config(), api_key='fake-query-key')
            self.assertEqual(result['status'], 'ok'); self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0], ('/identity', 'Bearer fake-query-key'))
            self.assertNotIn('fake-query-key', calls[1][0])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
