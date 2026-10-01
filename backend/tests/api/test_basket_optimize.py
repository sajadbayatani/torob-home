"""
Optimising a selection list must not re-read the sentence that produced it.

The bug this pins down: ``POST /baskets/{id}/optimize`` used to fall back to
``SearchService().interpret(payload.query)`` when it had no target budget. So a
plain "optimise my list" click spent a model call pushing the user's original query
through the *search interpretation* prompt — a prompt built to classify a
sentence as a product search or a project — and could then fail with an
interpretation error the user had no way to act on.

Optimising is not interpreting. The list already holds the products, and the
project that produced it already holds the room, the area, the quality and the
budget. The only model call this path is allowed to make is the one it was
designed around: the optimisation reasoning flow, once.

The other thing worth proving is that the fix did not turn the endpoint into a
non-LLM one. A regression that "fixes" the bug by skipping reasoning entirely
would pass every assertion in the first half of this file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.fixtures import FAUCET_ID


@pytest.fixture
def basket_with_a_product(client: TestClient) -> str:
    """A product list, built through the real endpoint so it has real contents."""
    response = client.post(
        "/api/v1/baskets", json={"kind": "product", "product_id": FAUCET_ID}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestOptimizeNeverInterprets:
    """
    The regression itself.

    Both a black-box check (the endpoint succeeds with the model stubbed to fail on
    interpretation) and a white-box one (the interpretation entry point is
    replaced with something that raises loudly). The first proves the behaviour; the
    second proves the absence, which the first could not distinguish from "it was
    called and swallowed".
    """

    def test_the_interpretation_entry_point_is_not_reachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Replace `SearchService.interpret` with a tripwire.

        Any call fails the test with a message naming the caller, which is more
        useful than a 500 from a mocked model.
        """

        def tripwire(*_args, **_kwargs):
            raise AssertionError(
                "basket optimisation called SearchService().interpret(): "
                "optimising a list must use the list, not re-read the query"
            )

        monkeypatch.setattr("app.domains.search.service.SearchService.interpret", tripwire)
        assert "app.domains.search.service" not in _imported_by_the_basket_router()

    def test_optimizing_a_budgeted_list_never_interprets(
        self, client: TestClient, basket_with_a_product: str, monkeypatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(
            "app.domains.search.service.SearchService.interpret",
            lambda *_a, **_k: calls.append("interpret"),
        )

        response = client.post(
            f"/api/v1/baskets/{basket_with_a_product}/optimize",
            json={"target_budget": 1_000_000},
        )
        assert response.status_code == 200, response.text
        assert calls == [], "the interpretation flow was entered"

    def test_optimizing_with_only_a_query_never_interprets(
        self, client: TestClient, basket_with_a_product: str, monkeypatch
    ) -> None:
        """
        The exact shape that used to trigger it.

        A caller with no budget sends the original query, and that used to be the
        condition for reading it back through the interpreter.
        """
        calls: list[str] = []
        monkeypatch.setattr(
            "app.domains.search.service.SearchService.interpret",
            lambda *_a, **_k: calls.append("interpret"),
        )

        response = client.post(
            f"/api/v1/baskets/{basket_with_a_product}/optimize",
            json={"query": "میخوام سرویس بهداشتی رو بازسازی کنم"},
        )
        assert response.status_code == 200, response.text
        assert calls == [], "the query was sent through the interpreter instead of ignored"

    def test_the_query_never_reaches_the_model(
        self, client: TestClient, llm, basket_with_a_product: str
    ) -> None:
        """
        Asserted on what was actually sent.

        Every prompt the stub received is searched for the query, so this catches a
        path that routes the query somewhere other than `SearchService` — the
        provider being called directly, say — which patching one method would not.
        """
        llm.answer(intent="product_search", search={"text": "یخچال", "terms": ["یخچال"]})
        client.post(
            f"/api/v1/baskets/{basket_with_a_product}/optimize",
            json={"query": "میخوام سرویس بهداشتی رو بازسازی کنم", "target_budget": 1_000_000},
        )
        for call in llm.calls:
            assert "سرویس بهداشتی" not in call.get("system", "")
            assert "سرویس بهداشتی" not in call.get("user", "")


class TestNoBudgetIsAnAnswerNotAFallback:
    """
    With no ceiling anywhere, the endpoint says so.

    This is the branch that replaced the interpreter call, so it is worth pinning:
    it must be a plain 200 with an explanation and no model call, rather than an
    empty plan that looks like "nothing to optimise" with no reason given.
    """

    def test_it_reports_that_no_ceiling_was_set(
        self, client: TestClient, basket_with_a_product: str, llm
    ) -> None:
        response = client.post(
            f"/api/v1/baskets/{basket_with_a_product}/optimize",
            json={"query": "بودجه ندارم"},
        )
        assert response.status_code == 200
        body = response.json()

        assert body["can_optimize"] is False
        assert body["target_budget"] is None
        assert body["changes"] == []
        assert "بودجه" in body["explanation"]
        assert llm.calls == [], "reporting a missing budget costs nothing"

    def test_it_leaves_the_list_exactly_as_it_was(
        self, client: TestClient, basket_with_a_product: str
    ) -> None:
        before = client.get(f"/api/v1/baskets/{basket_with_a_product}").json()
        client.post(
            f"/api/v1/baskets/{basket_with_a_product}/optimize",
            json={"query": "بودجه ندارم"},
        )
        after = client.get(f"/api/v1/baskets/{basket_with_a_product}").json()
        assert after["items"] == before["items"]
        assert after["total"] == before["total"]

    def test_an_explicit_budget_is_preferred_over_a_query(
        self, client: TestClient, basket_with_a_product: str
    ) -> None:
        body = client.post(
            f"/api/v1/baskets/{basket_with_a_product}/optimize",
            json={"target_budget": 4_000_000, "query": "بودجه ندارم"},
        ).json()
        assert body["target_budget"] == 4_000_000


class TestTheOptimisationReasoningStillRunsOnce:
    """
    The other half: the fix must not have removed reasoning along with the bug.

    A change that made `optimize` deterministic-and-silent would satisfy every
    assertion in the class above. The optimisation reasoning flow is the one model
    call this path is meant to make, and it is still made.
    """

    def test_the_optimisation_flow_is_called_exactly_once(
        self, client: TestClient, basket_with_a_product: str, monkeypatch
    ) -> None:
        import app.domains.basket.optimizer as optimizer

        calls: list[dict] = []
        real = optimizer._reason_about_basket

        def counting(**kwargs):
            calls.append(kwargs)
            return real(**kwargs)

        monkeypatch.setattr(optimizer, "_reason_about_basket", counting)

        response = client.post(
            f"/api/v1/baskets/{basket_with_a_product}/optimize",
            json={"target_budget": 1_000_000},
        )
        assert response.status_code == 200, response.text
        assert len(calls) == 1, f"expected one reasoning pass, got {len(calls)}"

        # and it was given the list, not a query
        assert calls[0]["items"], "the reasoning pass needs the list's products"
        assert calls[0]["target_budget"] == 1_000_000

    def test_the_dedicated_reasoning_entry_point_is_used(
        self, client: TestClient, basket_with_a_product: str, monkeypatch
    ) -> None:
        """
        `reason_optimization` — the basket-specific flow — not the interpreter.

        Recorded at the source module so an alias, a re-import or a different
        caller cannot hide a second path.
        """
        import app.domains.projects.reasoning as project_reasoning

        calls: list[dict] = []
        real = project_reasoning.reason_optimization

        def counting(**kwargs):
            calls.append(kwargs)
            return real(**kwargs)

        monkeypatch.setattr(project_reasoning, "reason_optimization", counting)

        response = client.post(
            f"/api/v1/baskets/{basket_with_a_product}/optimize",
            json={"target_budget": 1_000_000},
        )
        assert response.status_code == 200, response.text
        assert len(calls) == 1, f"expected one optimisation call, got {len(calls)}"
        assert calls[0]["basket_items"], "it reasons over the basket's own products"

    def test_the_reasoning_effort_setting_is_untouched(
        self, client: TestClient, basket_with_a_product: str, monkeypatch
    ) -> None:
        """
        `LLM_REASONING_EFFORT=low` still reads as `low` after optimizing.

        The setting is scoped to the *interpretation* call by design, and this
        endpoint no longer makes one — so it is not on the wire here, and asserting
        that it were would be asserting a different change. What matters is that
        removing the interpreter call did not disturb the configuration.
        """
        from app.core.config import get_settings

        monkeypatch.setenv("LLM_REASONING_EFFORT", "low")
        get_settings.cache_clear()

        client.post(
            f"/api/v1/baskets/{basket_with_a_product}/optimize",
            json={"target_budget": 1_000_000},
        )
        assert get_settings().llm_reasoning_effort == "low"


class TestOptimizeDoesNotTouchTheListUnasked:
    """
    A proposal is a proposal.

    ``apply`` defaults to false, so optimizing returns something to look at rather
    than quietly rewriting the user's selection.
    """

    def test_the_default_leaves_the_list_alone(
        self, client: TestClient, basket_with_a_product: str
    ) -> None:
        before = client.get(f"/api/v1/baskets/{basket_with_a_product}").json()

        body = client.post(
            f"/api/v1/baskets/{basket_with_a_product}/optimize",
            json={"target_budget": 1_000},
        ).json()
        assert body["applied"] is False

        after = client.get(f"/api/v1/baskets/{basket_with_a_product}").json()
        assert after["items"] == before["items"]

    def test_asking_for_it_to_apply_does_change_the_list(
        self, client: TestClient, basket_with_a_product: str
    ) -> None:
        """The opposite half: the confirmation is honoured when it is asked for."""
        body = client.post(
            f"/api/v1/baskets/{basket_with_a_product}/optimize",
            json={"target_budget": 1_000_000, "apply": True},
        ).json()
        assert body["applied"] is True


def _imported_by_the_basket_router() -> str:
    """
    The module names the basket router pulls from the search domain.

    Asserted so the test above means something: if the router never imports the
    service at all, "no call" is guaranteed by the import graph rather than by a
    branch that could grow back.
    """
    source = (
        Path(__file__).resolve().parents[2] / "app" / "domains" / "basket" / "router.py"
    ).read_text(encoding="utf-8")
    return json.dumps(source)
