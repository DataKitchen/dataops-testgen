"""Unit tests for run_keyed_worker_pool / WorkerOutcome."""
import threading
import time

import pytest

from testgen.common.database.database_service import WorkerOutcome, run_keyed_worker_pool

pytestmark = pytest.mark.unit


def test_yields_one_outcome_per_item_with_key_preserved():
    items = [("k1", 1), ("k2", 2), ("k3", 3)]
    outcomes = list(run_keyed_worker_pool(items, lambda arg: arg * 10, max_threads=2))

    assert len(outcomes) == 3
    by_key = {o.key: o for o in outcomes}
    assert set(by_key) == {"k1", "k2", "k3"}
    assert by_key["k2"].result == 20
    assert by_key["k2"].error is None


def test_success_carries_result_and_failure_carries_message():
    def process(arg):
        if arg == 0:
            raise ValueError("boom")
        return arg

    by_key = {o.key: o for o in run_keyed_worker_pool([("ok", 5), ("bad", 0)], process, max_threads=2)}

    assert by_key["ok"].result == 5
    assert by_key["ok"].error is None
    assert by_key["bad"].result is None
    assert "boom" in by_key["bad"].error


def test_never_yields_ambiguous_outcome():
    # Exactly one of result / error is set on every outcome — never both-None (a phantom
    # success the consumer can't distinguish from a real result) and never both-set.
    def process(arg):
        if arg % 2 == 0:
            raise ValueError(f"e{arg}")
        return arg

    outcomes = list(run_keyed_worker_pool([(i, i) for i in range(10)], process, max_threads=4))

    assert len(outcomes) == 10
    for outcome in outcomes:
        assert (outcome.result is None) != (outcome.error is None)


def test_empty_input_yields_nothing():
    assert list(run_keyed_worker_pool([], lambda arg: arg)) == []


def test_every_item_is_processed():
    items = [(i, i) for i in range(50)]
    outcomes = list(run_keyed_worker_pool(items, lambda arg: arg, max_threads=8))
    assert sorted(o.key for o in outcomes) == list(range(50))


def test_process_runs_off_the_caller_thread():
    caller = threading.get_ident()
    worker_threads: set[int] = set()

    def process(arg):
        worker_threads.add(threading.get_ident())
        return arg

    list(run_keyed_worker_pool([(i, i) for i in range(20)], process, max_threads=4))

    assert caller not in worker_threads
    assert worker_threads


def test_key_is_returned_untouched_and_process_sees_only_the_arg():
    seen_args = []

    def process(arg):
        seen_args.append(arg)
        return arg

    outcomes = list(run_keyed_worker_pool([("KEY", "ARG")], process))

    assert outcomes[0] == WorkerOutcome(key="KEY", result="ARG", error=None)
    assert seen_args == ["ARG"]


def test_stop_predicate_halts_dispatch():
    stop = threading.Event()
    items = [(key, key) for key in "abcdef"]

    def process(arg):
        time.sleep(0.05)
        return arg.upper()

    outcomes = []
    for outcome in run_keyed_worker_pool(items, process, max_threads=1, stop=stop.is_set):
        outcomes.append(outcome)
        if len(outcomes) == 2:
            stop.set()

    assert 2 <= len(outcomes) < len(items)
    assert len({outcome.key for outcome in outcomes}) == len(outcomes)


def test_stop_predicate_yields_only_whole_outcomes():
    stop = threading.Event()
    items = [(key, key) for key in "abcdef"]

    outcomes = []
    for outcome in run_keyed_worker_pool(items, lambda a: a, max_threads=2, stop=stop.is_set):
        outcomes.append(outcome)
        stop.set()

    assert outcomes
    for outcome in outcomes:
        assert (outcome.result is None) != (outcome.error is None)


def test_stop_true_from_the_start_yields_nothing():
    items = [(key, key) for key in "abc"]

    assert list(run_keyed_worker_pool(items, lambda a: a, stop=lambda: True)) == []


def test_default_run_still_yields_every_item():
    items = [(key, key) for key in "abcdef"]

    outcomes = list(run_keyed_worker_pool(items, lambda a: a.upper(), max_threads=3))

    assert {outcome.key for outcome in outcomes} == set("abcdef")


def test_pool_terminates_when_a_worker_dies_from_a_base_exception():
    """A BaseException escapes the per-item guard; the pool must end rather than hang."""
    def process(arg):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        list(run_keyed_worker_pool([("a", "a")], process, max_threads=1))


def test_a_caller_that_stops_consuming_stops_the_pool():
    """Abandoning the results must not first pay for producing them."""
    processed = []
    lock = threading.Lock()

    def process(arg):
        with lock:
            processed.append(arg)
        # Slow enough that the pool cannot drain the list before the caller gives up, which
        # is the real shape too: a work item is a query against the target database.
        time.sleep(0.01)
        return arg

    items = [(index, index) for index in range(200)]
    with pytest.raises(RuntimeError):
        for _ in run_keyed_worker_pool(items, process, max_threads=2):
            raise RuntimeError("the caller gave up")

    # A couple may already be in flight; the rest must never be picked up.
    assert len(processed) < len(items) / 2


def test_closing_the_iterator_stops_the_pool():
    processed = []
    lock = threading.Lock()

    def process(arg):
        with lock:
            processed.append(arg)
        time.sleep(0.01)
        return arg

    items = [(index, index) for index in range(200)]
    outcomes = run_keyed_worker_pool(items, process, max_threads=2)
    next(outcomes)
    outcomes.close()

    assert len(processed) < len(items) / 2
