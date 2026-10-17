import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from mikroclear.bot.settings import BotSettings
from mikroclear.settings import Settings
from mikroclear.web.app import create_app
from mikroclear.web.config import WebSettings


class WebAuditTests(unittest.TestCase):
    def attempt(self, kind, scenario):
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / 'audit.jsonl'
            core = Settings(monitor_only=scenario == 'monitor', mangle_control_enable=scenario != 'disabled')
            with patch('mikroclear.web.app.BotSettings.from_env', return_value=BotSettings(audit_log=str(audit))), patch('mikroclear.web.app.RouterWebGateway') as factory:
                gateway = factory.return_value
                gateway.block_entries.return_value = [{'address': '192.0.2.1'}]
                gateway.managed_mangle.return_value = [{'id': '*1', 'name': 'managed'}]
                if scenario == 'missing':
                    gateway.block_entries.return_value = []
                    gateway.managed_mangle.return_value = []
                if scenario == 'inventory':
                    gateway.block_entries.side_effect = RuntimeError('PRIVATE gateway error')
                    gateway.managed_mangle.side_effect = RuntimeError('PRIVATE gateway error')
                app = create_app(core_settings=core, web_settings=WebSettings(admin_password='test-password', session_secret='test-secret-at-least-32-characters', secure_cookie=False, static_dir=directory))
                with TestClient(app) as client:
                    login = client.post('/api/auth/login', json={'username': 'admin', 'password': 'test-password'}).json()
                    headers = {'X-CSRF-Token': login['csrf']}
                    route = '/api/router/mangle/*1/request' if kind == 'mangle' else '/api/router/unblock/request'
                    payload = {'disabled': True} if kind == 'mangle' else {'address': '192.0.2.1'}
                    if scenario in ('invalid', 'expired', 'replayed'):
                        if scenario == 'invalid':
                            token = 'PRIVATE-invalid-token'
                        else:
                            token = client.post(route, json=payload, headers=headers).json()['token']
                        route = f'/api/router/{kind}/confirm'
                        if scenario == 'replayed':
                            self.assertEqual(client.post(route, json={'token': token}, headers=headers).status_code, 200)
                            gateway.reset_mock()
                        if scenario == 'expired':
                            with patch('mikroclear.web.actions.time', return_value=10**12):
                                response = client.post(route, json={'token': token}, headers=headers)
                        else:
                            response = client.post(route, json={'token': token}, headers=headers)
                        expected, outcome, detail = 409, 'denied', 'ConfirmationError'
                    else:
                        response = client.post(route, json=payload, headers=headers)
                        expected, outcome, detail = {
                            'monitor': (409, 'denied', 'monitor_only'),
                            'disabled': (403, 'denied', 'mangle_disabled'),
                            'missing': (404, 'denied', 'target_not_found'),
                            'inventory': (503, 'error', 'inventory_unavailable'),
                        }[scenario]
                    self.assertEqual(response.status_code, expected)
                    row = json.loads(audit.read_text().splitlines()[-1])
                    stage = 'confirm' if scenario in ('invalid', 'expired', 'replayed') else 'request'
                    self.assertEqual((row['action'], row['outcome'], row['detail']), (f'web.{kind}.{stage}', outcome, detail))
                    self.assertEqual(row['target'], 'mangle' if kind == 'mangle' else 'address-list')
                    self.assertNotIn('PRIVATE', audit.read_text())
                    gateway.set_mangle_disabled.assert_not_called()
                    gateway.unblock.assert_not_called()

    def test_denied_requests_are_audited_without_mutation(self):
        for kind in ('mangle', 'unblock'):
            for scenario in ('monitor', 'missing', 'inventory', 'invalid', 'expired', 'replayed'):
                with self.subTest(kind=kind, scenario=scenario):
                    self.attempt(kind, scenario)
        self.attempt('mangle', 'disabled')
