import json
import os
from pathlib import Path

import pytest

from app import replay


@pytest.fixture
def replay_registry(tmp_path, monkeypatch):
    model_path = tmp_path / 'pilot.h5'
    config_path = tmp_path / 'config.py'
    myconfig_path = tmp_path / 'myconfig.py'
    tub_path = tmp_path / 'tub'
    tub_path.mkdir()
    (tub_path / 'manifest.json').write_text('{}', encoding='utf-8')
    model_path.write_bytes(b'model-v1')
    config_path.write_text('IMAGE_H = 120\nIMAGE_W = 160\n', encoding='utf-8')
    myconfig_path.write_text('ROI_CROP_TOP = 45\n', encoding='utf-8')

    models_path = tmp_path / 'models.json'
    tubs_path = tmp_path / 'tubs.json'
    cache_path = tmp_path / 'cache'
    models_path.write_text(json.dumps({
        'models': [{
            'id': 'pilot',
            'label': 'Test pilot',
            'path': str(model_path),
            'type': 'linear',
            'config_path': str(config_path),
            'myconfig_path': str(myconfig_path),
        }]
    }), encoding='utf-8')
    tubs_path.write_text(json.dumps({
        'tubs': {
            'training-tub': {
                'label': 'Training tub',
                'path': str(tub_path),
                'tag': 'train',
            }
        }
    }), encoding='utf-8')

    monkeypatch.setenv('LOK_REPLAY_MODELS_PATH', str(models_path))
    monkeypatch.setenv('LOK_REPLAY_TUBS_PATH', str(tubs_path))
    monkeypatch.setenv('LOK_REPLAY_CACHE_DIR', str(cache_path))
    return {'model': model_path, 'cache': cache_path}


def test_options_hide_model_config_details(replay_registry):
    options = replay.list_options()
    assert options['models'] == [{
        'id': 'pilot',
        'label': 'Test pilot',
        'path': str(replay_registry['model']),
    }]
    assert options['tubs'][0]['tag'] == 'train'


def test_replay_caches_records_and_sets_training_warning(
    replay_registry, monkeypatch
):
    calls = []
    records = [{
        'frame_id': 7,
        'actual_angle': 0.1,
        'actual_throttle': 0.2,
        'pred_angle': 0.15,
        'pred_throttle': 0.25,
        'image_path': '7_cam-image_array_.jpg',
    }]

    def fake_inference(model_entry, tub_entry):
        calls.append((model_entry, tub_entry))
        return records

    monkeypatch.setattr(replay, '_run_inference', fake_inference)
    first = replay.get_replay('training-tub', 'pilot')
    second = replay.get_replay('training-tub', str(replay_registry['model']))

    assert first['cache_hit'] is False
    assert second['cache_hit'] is True
    assert second['training_warning'] is True
    assert second['records'] == records
    assert len(calls) == 1
    cache_files = list(replay_registry['cache'].glob('replay_training-tub_*.json'))
    assert len(cache_files) == 1
    assert json.loads(cache_files[0].read_text(encoding='utf-8')) == records


def test_model_change_invalidates_cache(replay_registry, monkeypatch):
    calls = []
    monkeypatch.setattr(
        replay,
        '_run_inference',
        lambda model_entry, tub_entry: calls.append(1) or [],
    )

    replay.get_replay('training-tub', 'pilot')
    replay_registry['model'].write_bytes(b'model-v2-with-new-size')
    os.utime(replay_registry['model'], None)
    replay.get_replay('training-tub', 'pilot')

    assert len(calls) == 2
    assert len(list(replay_registry['cache'].glob('replay_*.json'))) == 2


def test_unknown_model_is_rejected(replay_registry):
    with pytest.raises(KeyError, match='Unknown or unregistered'):
        replay.get_replay('training-tub', '/tmp/unregistered.h5')


def test_registry_rejects_unsafe_tub_id(tmp_path, monkeypatch):
    models = tmp_path / 'models.json'
    tubs = tmp_path / 'tubs.json'
    models.write_text('{"models": []}', encoding='utf-8')
    tubs.write_text(json.dumps({
        'tubs': {'../bad': {'path': str(Path('/tmp/tub')), 'tag': 'holdout'}}
    }), encoding='utf-8')
    monkeypatch.setenv('LOK_REPLAY_MODELS_PATH', str(models))
    monkeypatch.setenv('LOK_REPLAY_TUBS_PATH', str(tubs))

    with pytest.raises(ValueError, match='Invalid replay tub'):
        replay.list_options()
