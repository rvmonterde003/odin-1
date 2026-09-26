from odin_pi.watchdog import PostWatchdog


def test_heartbeat_every_200ms_holds_hover_past_two_seconds():
    dog = PostWatchdog()
    dog.notify_post()
    t = dog._last_post_at
    assert t is not None
    for _ in range(10):
        t += 0.2
        dog._last_post_at = t
        assert dog.should_disarm(t + 0.1) is False
    assert dog.should_disarm(t + 0.9) is False
    assert dog.should_disarm(t + 1.0) is True


def test_silence_past_1s_disarms():
    dog = PostWatchdog()
    dog.notify_post()
    t0 = dog._last_post_at
    assert dog.should_disarm(t0 + 0.5) is False
    assert dog.should_disarm(t0 + 1.0) is True
