from app.pipeline.class_aggregation import aggregate_class
from app.pipeline.config import ClassConfig
from tests.synthetic import make_track, moving_boxes

CFG = ClassConfig()


def _obs(names, conf=0.9, edge=False):
    return make_track(1, 0, moving_boxes(0, len(names), 5), names, conf=conf, edge=edge).observations


def test_single_noisy_prediction_does_not_flip_the_class():
    d = aggregate_class(_obs(["BOXN", "BOXN", "BCN", "BOXN", "BOXN"]), CFG, 0.5)
    assert d.class_name == "BOXN" and not d.uncertain
    assert d.confidence == 0.8
    assert d.runner_up == "BCN"
    assert d.distribution == {"BOXN": 0.8, "BCN": 0.2}


def test_split_votes_are_marked_unresolved_with_best_guess():
    d = aggregate_class(_obs(["BOXN", "BCN", "BOXN", "BCN", "BTPN"]), CFG, 0.5)
    assert d.uncertain and d.class_name == "Unresolved"
    assert d.best_guess in {"BOXN", "BCN"}


def test_too_few_observations_is_uncertain():
    d = aggregate_class(_obs(["BOXN", "BOXN"]), CFG, 0.5)
    assert d.uncertain


def test_confidence_weights_votes():
    obs = make_track(1, 0, moving_boxes(0, 3, 5), "BOXN", conf=0.95).observations
    obs += make_track(1, 3, moving_boxes(15, 3, 5), "BCN", conf=0.2).observations
    d = aggregate_class(obs, CFG, 0.5)
    assert d.class_name == "BOXN"
    assert d.confidence > 0.8


def test_edge_observations_count_less():
    full = make_track(1, 0, moving_boxes(0, 3, 5), "BCN", conf=0.6).observations
    edge = make_track(1, 3, moving_boxes(15, 4, 5), "BOXN", conf=0.6, edge=True).observations
    d = aggregate_class(full + edge, ClassConfig(min_class_share=0.5), 0.5)
    assert d.best_guess == "BCN"  # 3*0.6 beats 4*0.6*0.5


def test_empty_is_unresolved():
    d = aggregate_class([], CFG, 0.5)
    assert d.uncertain and d.supporting_observations == 0
