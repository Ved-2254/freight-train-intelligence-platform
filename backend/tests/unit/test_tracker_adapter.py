import numpy as np

from app.pipeline.config import TrackConfig, TrackerConfig
from app.pipeline.models import Detection, FrameSample
from tests.conftest import requires_ultralytics

pytestmark = requires_ultralytics


def _adapter(fps=10.0, **cfg):
    from app.pipeline.tracker import ByteTrackAdapter

    return ByteTrackAdapter(TrackerConfig(**cfg), TrackConfig(), frame_rate=fps)


def _sample(i, fps=10.0):
    return FrameSample(np.zeros((360, 640, 3), np.uint8), frame_index=i, timestamp=i / fps, sample_index=i)


def _det(x, i, cls="BOXN", conf=0.9, fps=10.0):
    return Detection((x, 100.0, x + 150.0, 220.0), 1, cls, conf, i, i / fps)


def test_empty_frames_are_handled():
    trk = _adapter()
    for i in range(5):
        assert trk.update([], _sample(i)) == []


def test_consistent_ids_and_class_passthrough():
    trk = _adapter()
    ids = set()
    for i in range(10):
        dets = [_det(20 + 10 * i, i), _det(220 + 10 * i, i, cls="BCN")]
        obs = trk.update(dets, _sample(i))
        if i >= 2:
            assert len(obs) == 2
            ids |= {o.track_id for o in obs}
            assert {o.class_name for o in obs} == {"BOXN", "BCN"}
            assert all(o.frame_index == i and o.timestamp == i / 10 for o in obs)
    assert len(ids) == 2


def test_brief_miss_keeps_track_id():
    trk = _adapter(track_buffer_seconds=1.0)
    seen = []
    for i in range(14):
        dets = [] if i in (6, 7) else [_det(20 + 10 * i, i)]
        seen += [o.track_id for o in trk.update(dets, _sample(i))]
    assert len(set(seen)) == 1
