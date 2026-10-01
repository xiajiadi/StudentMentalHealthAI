from __future__ import annotations

from types import SimpleNamespace

import pytest

from harness.controlled_product_eval.safety_service_bootstrap import start_safety_service


def test_safety_bootstrap_loads_local_guard_before_serving():
    events = []
    bundle = SimpleNamespace(
        service=SimpleNamespace(
            qwen=SimpleNamespace(
                load=lambda: (events.append("qwen-load") or SimpleNamespace(ready=True))
            )
        )
    )

    start_safety_service(
        build_bundle=lambda: (events.append("build") or bundle),
        create_app=lambda **kwargs: (events.append(("create-app", kwargs["bundle"])) or "app"),
        run_server=lambda app, **kwargs: events.append(("serve", app, kwargs)),
    )

    assert events == [
        "build",
        "qwen-load",
        ("create-app", bundle),
        (
            "serve",
            "app",
            {"host": "127.0.0.1", "port": 8190, "log_level": "info"},
        ),
    ]


def test_safety_bootstrap_fails_closed_when_offline_guard_does_not_load():
    events = []
    bundle = SimpleNamespace(
        service=SimpleNamespace(
            qwen=SimpleNamespace(
                load=lambda: (events.append("qwen-load") or SimpleNamespace(ready=False))
            )
        )
    )

    with pytest.raises(RuntimeError, match="fixed offline Qwen3Guard preload failed"):
        start_safety_service(
            build_bundle=lambda: bundle,
            create_app=lambda **_kwargs: pytest.fail("unready guard must not start the server"),
            run_server=lambda *_args, **_kwargs: pytest.fail("unready guard must not start the server"),
        )

    assert events == ["qwen-load"]
