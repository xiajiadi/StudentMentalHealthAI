"""Adapter for the verified Round 1 `adaptivetesting` API."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any

from ..domain.config import CATConfig
from ..domain.enums import ResponseStatus, StopReason
from ..domain.errors import ProviderError, ProviderUnavailableError
from ..domain.item import Item, ResponseValue
from ..domain.item_bank import ItemBank
from .base import (
    CATProvider,
    ItemSelection,
    ProviderResultSnapshot,
    ProviderSession,
    ProviderUpdate,
    StopDecision,
)


@dataclass
class _AdaptiveTestingState:
    """Private adapter state; no adaptivetesting object leaves this module."""

    item_bank: ItemBank
    config: CATConfig
    engine: Any
    engine_items: dict[str, Any]
    domain_items: dict[str, Item]
    theta: float
    se: float
    pending_item_id: str | None = None
    items_administered: int = 0
    items_answered: int = 0


class AdaptiveTestingProvider(CATProvider):
    """Use `adaptivetesting` for GRM estimation, MFI selection, and simulation."""

    provider_name = "adaptivetesting"
    provider_version = "adaptivetesting-1.2.1"

    def __init__(self) -> None:
        """Import the dependency lazily and fail explicitly when unavailable."""

        try:
            import adaptivetesting as adaptivetesting_module
        except Exception as exc:  # the stable error retains the real cause
            raise ProviderUnavailableError(
                f"adaptivetesting cannot be imported in this Python environment: {exc}"
            ) from exc
        self._adt = adaptivetesting_module

    def start_session(self, session_id: str, item_bank: ItemBank, config: CATConfig) -> ProviderSession:
        """Create a non-simulation TestAssembler over an immutable item bank."""

        item_bank.assert_runtime_ready()
        config.validate()
        if item_bank.measurement_model != config.model:
            raise ProviderError("CAT config model does not match item bank measurement_model")
        if config.selection_method != "MFI":
            raise ProviderError("AdaptiveTestingProvider only supports selection_method=MFI")
        if config.estimator not in {"EAP", "BM"}:
            raise ProviderError(f"unsupported estimator: {config.estimator}")
        if config.max_items > len(item_bank.items):
            raise ProviderError("max_items cannot exceed the available item bank size")

        engine_items: dict[str, Any] = {}
        for index, item in enumerate(item_bank.items):
            engine_item = self._adt.TestItem()
            engine_item.id = index
            engine_item.a = float(item.parameters["a"])
            engine_item.b = [float(value) for value in item.parameters["thresholds"]]
            engine_item.additional_properties = {"item_id": item.item_id}
            engine_items[item.item_id] = engine_item

        item_pool = self._adt.ItemPool(list(engine_items.values()))
        estimator = (
            self._adt.ExpectedAPosteriori
            if config.estimator == "EAP"
            else self._adt.BayesModal
        )
        prior = self._adt.NormalPrior(config.prior_mean, config.prior_sd)
        engine = self._adt.TestAssembler(
            item_pool=item_pool,
            simulation_id=session_id,
            participant_id=session_id,
            ability_estimator=estimator,
            estimator_args={
                "prior": prior,
                "optimization_interval": config.optimization_interval,
                "model": config.model,
            },
            item_selector=self._adt.maximum_information_criterion,
            item_selector_args={"model": config.model},
            model_type=config.model,
            initial_ability_level=config.initial_theta,
            simulation=False,
            debug=False,
        )
        # TestAssembler deep-copies its ItemPool. Re-index the owned copies so
        # response submission and deletion address the exact engine objects.
        engine_items = {
            str(engine_item.additional_properties["item_id"]): engine_item
            for engine_item in engine.item_pool.test_items
        }
        state = _AdaptiveTestingState(
            item_bank=item_bank,
            config=config,
            engine=engine,
            engine_items=engine_items,
            domain_items={item.item_id: item for item in item_bank.items},
            theta=float(config.initial_theta),
            se=float(config.prior_sd),
        )
        return ProviderSession(
            session_id=session_id,
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            item_bank_version=item_bank.version,
            config_version=config.config_version,
            _opaque_state=state,
        )

    def select_next_item(self, session: ProviderSession) -> ItemSelection:
        """Delegate MFI selection to the package and expose only stable fields."""

        state = self._state(session)
        self._require_no_pending(state)
        if not state.engine.item_pool.test_items:
            raise ProviderError("no unadministered items remain")
        engine_item = state.engine.get_next_item()
        item_id = str(engine_item.additional_properties["item_id"])
        information = self._adt.item_information_function(
            ability=state.theta,
            item=engine_item,
            model=state.config.model,
        )
        state.pending_item_id = item_id
        return ItemSelection(
            item_id=item_id,
            criterion=state.config.selection_method,
            score=float(information),
        )

    def submit_response(self, session: ProviderSession, item_id: str, response_score: int) -> ProviderUpdate:
        """Update the package estimator with one validated GRM category index."""

        state = self._state(session)
        engine_item = self._require_pending_item(state, item_id)
        item = state.domain_items[item_id]
        if response_score not in range(len(item.response_options)):
            raise ProviderError(f"response score is invalid for item {item_id}")
        state.engine.response_pattern.append(response_score)
        state.engine.answered_items.append(engine_item)
        try:
            estimation, standard_error = state.engine.estimate_ability_level()
        except Exception as exc:
            raise ProviderError(f"adaptivetesting failed to estimate ability for {item_id}: {exc}") from exc
        state.theta = float(estimation)
        state.se = float(standard_error)
        state.engine.ability_level = state.theta
        state.engine.standard_error = state.se
        state.engine.item_pool.delete_item(engine_item)
        state.pending_item_id = None
        state.items_administered += 1
        state.items_answered += 1
        return ProviderUpdate(state.theta, state.se, response_score)

    def record_non_answer(
        self,
        session: ProviderSession,
        item_id: str,
        status: ResponseStatus,
    ) -> ProviderUpdate:
        """Remove a presented missing-response item without scoring it."""

        if status is ResponseStatus.ANSWERED:
            raise ProviderError("answered status must use submit_response")
        state = self._state(session)
        engine_item = self._require_pending_item(state, item_id)
        state.engine.item_pool.delete_item(engine_item)
        state.pending_item_id = None
        state.items_administered += 1
        return ProviderUpdate(state.theta, state.se, None)

    def estimate_ability(self, session: ProviderSession) -> float:
        """Return the adapter's latest provider estimate."""

        return self._state(session).theta

    def get_uncertainty(self, session: ProviderSession) -> float:
        """Return the adapter's latest provider standard error."""

        return self._state(session).se

    def should_stop(self, session: ProviderSession) -> StopDecision:
        """Apply configured minimum, SE, maximum, then bank-exhaustion rules."""

        state = self._state(session)
        if state.items_administered < state.config.min_items:
            return StopDecision(False, StopReason.NOT_STOPPED)
        if state.config.se_threshold is not None and state.se <= state.config.se_threshold:
            return StopDecision(True, StopReason.SE_THRESHOLD_REACHED)
        if state.items_administered >= state.config.max_items:
            return StopDecision(True, StopReason.MAX_ITEMS_REACHED)
        if not state.engine.item_pool.test_items:
            return StopDecision(True, StopReason.ITEM_BANK_EXHAUSTED)
        return StopDecision(False, StopReason.NOT_STOPPED)

    def get_result(
        self,
        session: ProviderSession,
        stop_decision: StopDecision | None = None,
    ) -> ProviderResultSnapshot:
        """Return a provider-neutral snapshot without exposing package objects."""

        state = self._state(session)
        return ProviderResultSnapshot(
            theta=state.theta,
            se=state.se,
            items_administered=state.items_administered,
            items_answered=state.items_answered,
        )

    def sample_response(
        self,
        session: ProviderSession,
        item_id: str,
        true_theta: float,
        rng: Random,
    ) -> ResponseValue:
        """Use the package's public response generator for an authentic GRM draw."""

        state = self._state(session)
        engine_item = self._require_pending_item(state, item_id)
        seed = rng.randrange(0, 2**32)
        response_score = self._adt.generate_response_pattern(
            ability=float(true_theta),
            items=[engine_item],
            model=state.config.model,
            seed=seed,
        )[0]
        return state.domain_items[item_id].option_for_score(int(response_score))

    @staticmethod
    def _state(session: ProviderSession) -> _AdaptiveTestingState:
        """Retrieve adapter-owned state and reject a foreign provider handle."""

        if not isinstance(session.opaque_state(), _AdaptiveTestingState):
            raise ProviderError("provider session does not belong to AdaptiveTestingProvider")
        return session.opaque_state()  # type: ignore[return-value]

    @staticmethod
    def _require_no_pending(state: _AdaptiveTestingState) -> None:
        if state.pending_item_id is not None:
            raise ProviderError("the previously selected item still awaits a response")

    @staticmethod
    def _require_pending_item(state: _AdaptiveTestingState, item_id: str) -> Any:
        if state.pending_item_id != item_id:
            raise ProviderError(f"item {item_id} is not the currently presented item")
        engine_item = state.engine_items.get(item_id)
        if engine_item is None or engine_item not in state.engine.item_pool.test_items:
            raise ProviderError(f"item {item_id} is no longer available")
        return engine_item
