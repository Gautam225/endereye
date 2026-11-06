from app.llm.failures import (
    BAD_REQUEST,
    INVALID_KEY,
    NO_CREDITS,
    RATE_LIMITED,
    SERVER_ERROR,
    Failure,
)
from app.llm.key_pool import KeyPool, mask_key


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_pool(keys: int = 3, cooldown: float = 60) -> tuple[KeyPool, FakeClock]:
    clock = FakeClock()
    secrets = [f"secret-key-number-{i}" for i in range(keys)]
    return KeyPool(secrets, rate_limit_cooldown=cooldown, clock=clock), clock


def test_rotation_starts_one_key_further_each_time() -> None:
    pool, _ = make_pool(3)
    orders = [[key.index for key in pool.rotation()] for _ in range(4)]
    assert orders == [[1, 2, 3], [2, 3, 1], [3, 1, 2], [1, 2, 3]]


def test_rate_limit_rests_only_that_model_for_retry_after() -> None:
    pool, clock = make_pool()
    key = pool.keys[0]

    pool.record_failure(key, "m1", Failure(RATE_LIMITED, "slow down", 429, retry_after=30))

    assert not pool.is_available(key, "m1")
    assert pool.is_available(key, "m2")
    clock.now += 30
    assert pool.is_available(key, "m1")


def test_rate_limit_without_retry_after_doubles_until_a_success() -> None:
    pool, clock = make_pool(cooldown=60)
    key = pool.keys[0]

    pool.record_failure(key, "m", Failure(RATE_LIMITED, "x"))
    assert pool.seconds_left(key.model_rest_until["m"]) == 60
    clock.now += 60
    pool.record_failure(key, "m", Failure(RATE_LIMITED, "x"))
    assert pool.seconds_left(key.model_rest_until["m"]) == 120

    clock.now += 120
    pool.record_success(key, "m")
    pool.record_failure(key, "m", Failure(RATE_LIMITED, "x"))
    assert pool.seconds_left(key.model_rest_until["m"]) == 60


def test_invalid_key_is_disabled_for_good() -> None:
    pool, clock = make_pool()
    key = pool.keys[1]

    pool.record_failure(key, "m", Failure(INVALID_KEY, "bad key", 401))
    clock.now += 10**7

    assert not pool.is_available(key, "m")
    assert key.disabled_reason is not None


def test_no_credits_rests_the_whole_key_for_an_hour() -> None:
    pool, clock = make_pool()
    key = pool.keys[0]

    pool.record_failure(key, "m1", Failure(NO_CREDITS, "add credits", 402))

    assert not pool.is_available(key, "m2")
    clock.now += 3600
    assert pool.is_available(key, "m2")


def test_server_errors_rest_the_key_only_briefly() -> None:
    pool, clock = make_pool()
    key = pool.keys[0]
    pool.record_failure(key, "m", Failure(SERVER_ERROR, "oops", 502))
    assert not pool.is_available(key, "m")
    clock.now += 10
    assert pool.is_available(key, "m")


def test_request_problems_do_not_count_against_the_key() -> None:
    pool, _ = make_pool()
    key = pool.keys[0]
    pool.record_failure(key, "m", Failure(BAD_REQUEST, "prompt too long", 400))
    assert key.failures == 0
    assert pool.is_available(key, "m")


def test_seconds_until_available_is_the_shortest_wait() -> None:
    pool, _ = make_pool(2)
    pool.record_failure(pool.keys[0], "m", Failure(RATE_LIMITED, "", retry_after=50))
    pool.record_failure(pool.keys[1], "m", Failure(RATE_LIMITED, "", retry_after=20))
    assert pool.seconds_until_available(["m"]) == 20

    for key in pool.keys:
        pool.record_failure(key, "m", Failure(INVALID_KEY, ""))
    assert pool.seconds_until_available(["m"]) is None


def test_mask_key_keeps_only_the_ends() -> None:
    assert mask_key("sk-or-v1-1234567890abcdef") == "sk-or-...cdef"
    assert mask_key("short") == "****"
