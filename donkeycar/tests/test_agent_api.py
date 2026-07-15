# -*- coding: utf-8 -*-
import json
import time

import numpy as np
import pytest
from tornado.testing import AsyncHTTPTestCase

from donkeycar.parts.agent_api import AgentApiController


@pytest.fixture
def agent():
    return AgentApiController(
        port=18991,
        command_timeout_secs=0.5,
        token='',
        stream_hz=5,
    )


def test_inactive_passthrough(agent):
    steering, throttle, mode, recording = agent.run_threaded(
        None, 0.3, 0.4, 'user', False)
    assert agent.agent_active is False
    assert steering == pytest.approx(0.3)
    assert throttle == pytest.approx(0.4)
    assert mode == 'user'
    assert recording is False


def test_active_applies_agent_commands(agent):
    agent.apply_control({'steering': -0.5, 'throttle': 0.2})
    assert agent.agent_active is True
    steering, throttle, mode, recording = agent.run_threaded(
        None, 0.9, 0.9, 'user', False)
    assert steering == pytest.approx(-0.5)
    assert throttle == pytest.approx(0.2)
    assert mode == 'user'


def test_set_active_false_releases_and_zeros_throttle(agent):
    agent.apply_control({'steering': 0.1, 'throttle': 0.5})
    agent.set_active(False)
    assert agent.agent_active is False
    assert agent.throttle == pytest.approx(0.0)
    steering, throttle, mode, recording = agent.run_threaded(
        None, 0.2, 0.3, 'user', True)
    assert steering == pytest.approx(0.2)
    assert throttle == pytest.approx(0.3)
    assert recording is True


def test_command_timeout_deactivates(agent):
    agent.command_timeout_secs = 0.05
    agent.apply_control({'steering': 0.1, 'throttle': 0.6})
    time.sleep(0.08)
    steering, throttle, mode, recording = agent.run_threaded(
        None, 0.25, 0.35, 'user', False)
    assert agent.agent_active is False
    assert throttle == pytest.approx(0.0)
    # After timeout, subsequent frames pass through human again.
    steering, throttle, mode, recording = agent.run_threaded(
        None, 0.25, 0.35, 'user', False)
    assert steering == pytest.approx(0.25)
    assert throttle == pytest.approx(0.35)


def test_build_state_includes_imu(agent):
    agent.imu_accel = (1.0, 2.0, 3.0)
    agent.imu_gyro = (0.1, 0.2, 0.3)
    agent.enc_speed = 1.5
    state = agent.build_state()
    assert state['imu']['accel'] == [1.0, 2.0, 3.0]
    assert state['imu']['gyro'] == [0.1, 0.2, 0.3]
    assert state['enc_speed'] == pytest.approx(1.5)
    assert state['agent_active'] is False


def test_angle_alias_in_control(agent):
    agent.apply_control({'angle': 0.7, 'throttle': 0.1})
    assert agent.angle == pytest.approx(0.7)


class TestAgentApiHTTP(AsyncHTTPTestCase):
    def get_app(self):
        self.agent = AgentApiController(
            port=0,
            command_timeout_secs=1.0,
            token='',
            stream_hz=2,
        )
        self.agent.img_arr = np.zeros((8, 8, 3), dtype=np.uint8)
        self.agent.human_angle = 0.1
        self.agent.human_throttle = 0.0
        return self.agent

    def test_health(self):
        resp = self.fetch('/api/v1/health')
        assert resp.code == 200
        data = json.loads(resp.body)
        assert data['ok'] is True
        assert data['agent_active'] is False

    def test_state_and_control_roundtrip(self):
        resp = self.fetch('/api/v1/state')
        assert resp.code == 200
        before = json.loads(resp.body)
        assert before['agent_active'] is False

        resp = self.fetch(
            '/api/v1/control',
            method='POST',
            body=json.dumps({'steering': -0.2, 'throttle': 0.15}),
            headers={'Content-Type': 'application/json'},
        )
        assert resp.code == 200
        after = json.loads(resp.body)
        assert after['agent_active'] is True
        assert after['steering'] == pytest.approx(-0.2)
        assert after['throttle'] == pytest.approx(0.15)

    def test_active_endpoint(self):
        resp = self.fetch(
            '/api/v1/active',
            method='POST',
            body=json.dumps({'active': True}),
            headers={'Content-Type': 'application/json'},
        )
        assert resp.code == 200
        assert json.loads(resp.body)['agent_active'] is True

        resp = self.fetch(
            '/api/v1/active',
            method='POST',
            body=json.dumps({'active': False}),
            headers={'Content-Type': 'application/json'},
        )
        assert resp.code == 200
        assert json.loads(resp.body)['agent_active'] is False

    def test_camera_jpg(self):
        resp = self.fetch('/api/v1/camera.jpg')
        assert resp.code == 200
        assert resp.headers['Content-Type'] == 'image/jpeg'
        assert len(resp.body) > 0

    def test_auth_required_when_token_set(self):
        self.agent.token = 'secret'
        resp = self.fetch('/api/v1/health')
        assert resp.code == 401

        resp = self.fetch(
            '/api/v1/health',
            headers={'Authorization': 'Bearer secret'},
        )
        assert resp.code == 200
