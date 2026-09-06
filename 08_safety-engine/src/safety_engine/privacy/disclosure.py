"""Role-aware disclosure matrix with a deliberately small vocabulary."""

from __future__ import annotations

from safety_engine.domain import ActorRole, DisclosurePolicy


class DisclosureMatrix:
    """Resolve what safety metadata may be shown to a role.

    The matrix governs metadata and engineering explanations, not a permission
    to disclose raw student content.  Raw sensitive content remains absent from
    signals and traces in every mode.
    """

    _base = {
        ActorRole.STUDENT: DisclosurePolicy.FULL,
        ActorRole.TEACHER: DisclosurePolicy.SUMMARY,
        ActorRole.PARENT: DisclosurePolicy.SUMMARY,
        ActorRole.REVIEWER: DisclosurePolicy.FULL,
        ActorRole.SYSTEM: DisclosurePolicy.FULL,
    }

    def resolve(
        self,
        actor_role: ActorRole,
        *,
        pii_detected: bool = False,
        restricted: bool = False,
        crisis: bool = False,
    ) -> DisclosurePolicy:
        if restricted or crisis and actor_role in {ActorRole.TEACHER, ActorRole.PARENT}:
            return DisclosurePolicy.HIDDEN
        if pii_detected:
            return DisclosurePolicy.REDACTED
        return self._base[actor_role]
