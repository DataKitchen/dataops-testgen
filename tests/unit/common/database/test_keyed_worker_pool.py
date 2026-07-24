"""Unit tests for run_keyed_worker_pool / WorkerOutcome."""
import threading

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
