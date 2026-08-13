from server.run_worker import lazy_handler


def test_lazy_handler_creates_the_expensive_handler_only_once_on_first_job() -> None:
    created: list[bool] = []

    def factory():
        created.append(True)
        return lambda payload: {"value": payload["value"]}

    handler = lazy_handler(factory)
    assert created == []
    assert handler({"value": "first"}) == {"value": "first"}
    assert handler({"value": "second"}) == {"value": "second"}
    assert created == [True]
