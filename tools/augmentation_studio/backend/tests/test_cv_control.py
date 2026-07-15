import sys
import types

import numpy as np

from donkeycar.config import Config

from app import cv_config, cv_replay, export


def test_import_myconfig_reads_literals_without_executing(tmp_path):
    marker = tmp_path / 'executed'
    config_path = tmp_path / 'myconfig.py'
    config_path.write_text(
        "\n".join([
            "CV_PREPROCESS = ['CROP']",
            "ROI_CROP_TOP = 37",
            "CANNY_LOW_THRESHOLD = 42",
            f"open({str(marker)!r}, 'w').write('bad')",
        ]),
        encoding='utf-8',
    )

    result = cv_config.load_myconfig(str(config_path))

    assert result['cv_preprocess'] == ['CROP']
    assert result['roi']['ROI_CROP_TOP'] == 37
    assert result['cv_params']['CANNY_LOW_THRESHOLD'] == 42
    assert not marker.exists()


def test_cv_control_export_uses_cv_keys_not_training_keys():
    snippet = export.export_full_snippet(
        profile='cv_control',
        cv_preprocess=['TRAPEZE_EDGE'],
        cv_debug_transformations=['RGB2GRAY', 'BLUR', 'CANNY'],
        cv_params={
            'CANNY_LOW_THRESHOLD': 45,
            'CANNY_HIGH_THRESHOLD': 120,
        },
        roi={'ROI_CROP_TOP': 40},
    )

    assert "CV_PREPROCESS = ['TRAPEZE_EDGE']" in snippet
    assert "CV_DEBUG_TRANSFORMATIONS = ['RGB2GRAY', 'BLUR', 'CANNY']" in snippet
    assert 'CANNY_LOW_THRESHOLD = 45' in snippet
    assert 'ROI_CROP_TOP = 40' in snippet
    assert '\nTRANSFORMATIONS =' not in snippet
    assert '\nAUGMENTATIONS =' not in snippet


def test_cv_replay_runs_cv_control_interface(monkeypatch):
    cfg = Config()
    cfg.CV_CONTROLLER_MODULE = 'test_lok_controller'
    cfg.CV_CONTROLLER_CLASS = 'FakeController'
    cfg.CV_PREPROCESS = []
    cfg.PID_P = -0.01
    cfg.PID_I = 0.0
    cfg.PID_D = 0.0

    class FakeController:
        def __init__(self, pid, config):
            self.pid = pid
            self.config = config

        def run(self, image):
            assert image.shape == (4, 5, 3)
            return 0.25, 0.15, image

    module = types.ModuleType('test_lok_controller')
    module.FakeController = FakeController
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(cv_replay, '_load_config', lambda path: cfg)

    session = types.SimpleNamespace(
        path='/tmp/test-tub',
        image_key='cam/image_array',
        records=[{
            '_index': 7,
            'cam/image_array': '7.jpg',
            'user/angle': 0.1,
            'user/throttle': 0.2,
        }],
    )
    monkeypatch.setattr(cv_replay.tub_loader, 'open_tub', lambda path: session)
    monkeypatch.setattr(
        cv_replay.tub_loader,
        'load_image_array',
        lambda path, index: np.zeros((4, 5, 3), dtype=np.uint8),
    )

    result = cv_replay.run_replay('/tmp/test-tub')

    assert result['model_label'].endswith('.FakeController')
    assert result['records'][0]['actual_angle'] == 0.1
    assert result['records'][0]['pred_angle'] == 0.25
