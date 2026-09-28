# Stage 3 (F-R2/F-R3): driver_analysis.ranked_drivers carries a statistical
# contribution/explained_share per driver (kpi_engine/attribution.py).
# Stage 8-lite: that contribution is now read into expected_impact under
# ATTRIBUTION_CONTRIBUTION_PRO_RATA_7D -- a declared arithmetic projection of
# the driver's attributed contribution over a fixed 7-day horizon, with the
# regression's beta interval carried through as a range. It is shown for every
# card with AC >= 0.35 and is labelled "not validated" unless AC >= 0.6 and
# the driver has conditional causal support. A contextual driver is advisory
# and is never given a number, because the engine cannot change the weather.
"""Deterministic, evidence-limited action recommendations."""

from dataclasses import asdict, dataclass
from typing import Any

from kpi_engine.narrative import lever_family
from kpi_engine.personas import PersonaConfig, load_persona

# Stage 8-lite: at most three cards, strongest Attribution Confidence first.
MAX_CARDS = 3
# A driver at or above AC_PROPOSE may be acted on (after a causal test in the
# strongest case); between AC_CHECK and AC_PROPOSE it earns a next check only.
AC_PROPOSE = 0.6
AC_CHECK = 0.35
# The impact projection horizon. Fixed and declared, not tuned per KPI.
IMPACT_HORIZON_DAYS = 7
IMPACT_METHOD = "ATTRIBUTION_CONTRIBUTION_PRO_RATA_7D"
# Overall confidence states in which no driver may be turned into an action,
# whatever its own Attribution Confidence says. A driver can be locally
# confident inside a run the engine as a whole does not stand behind.
WEAK_OVERALL_STATUSES = frozenset({"LOW", "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"})
# Card kinds that ask for a change, i.e. the ones that need someone's approval.
ACTION_KINDS = frozenset({"ACTION_PROPOSAL", "VERIFY_THEN_ACT"})
KIND_STRENGTH = {"ADVISORY": 0, "NEXT_CHECK": 1, "VERIFY_THEN_ACT": 2, "ACTION_PROPOSAL": 3}


@dataclass(frozen=True)
class DecisionCard:
    action_id: str
    kind: str
    status: str
    driver_id: str | None
    driver_rank: int | None
    driver_relationship: str
    controllability: str
    lever: str
    recommendation: str
    owner: str
    owner_source: str
    decision_right: str
    approval_required: bool
    expected_impact: float | None = None
    expected_impact_unit: str | None = None
    impact_method: str = "NOT_ESTIMATED"
    impact_explanation: str = "Impact is not estimated: no validated deterministic method is configured, and correlation is not converted into business impact."
    evidence_status: str = "NOT_ASSESSED"
    confidence_status: str = "NOT_ASSESSED"
    evidence_references: tuple[dict[str, Any], ...] = ()
    constraints: tuple[str, ...] = ()
    monitoring_plan: str = ""
    success_metric: str = ""
    review_window: str = ""
    stop_conditions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    evidence_paths: tuple[str, ...] = ()
    # Stage 8-lite: who is reading this card, how confident the engine is in
    # the driver behind it, and the projected impact. The range is the beta
    # confidence interval of the same projection; both bounds are None when the
    # fit produced no interval (the ridge path does not).
    persona: str = "default"
    attribution_confidence: float | None = None
    attribution_band: str | None = None
    attribution_label: str | None = None
    expected_impact_low: float | None = None
    expected_impact_high: float | None = None
    approval_threshold: float | None = None


class ActionRecommendationEngine:
    """Create review artifacts only; never execute or estimate an action."""

    # Keyed by the current driver id (plan §1.3 rename); LEGACY_DRIVER_IDS in
    # kpi_engine/contracts/registry.py is the single place the old spelling
    # resolves to these. traffic_drop is gone: traffic is a KPI/bridge
    # component (Stage 3), never an actionable driver (F-R2).
    LEVERS = {
        "checkout_latency": (
            "Checkout performance", "engineering_lead",
            "Review checkout latency traces and recent releases before proposing a remediation.",
            "Assess a checkout performance remediation plan and rollback criteria.",
            "Engineering change review",
        ),
        "competitor_price_index": (
            "Pricing", "pricing_lead",
            "Validate the competitor-price observation and compare affected products.",
            "Assess a targeted pricing response and its margin implications.",
            "Pricing and margin approval",
        ),
        "marketing_spend": (
            "Marketing", "marketing_lead",
            "Check weekly spend publication and campaign changes for the affected slice.",
            "Assess a campaign-budget adjustment and its guardrails.",
            "Marketing budget approval",
        ),
        "stock_availability": (
            "Availability", "operations_lead",
            "Check inventory and lost-unit records for the affected slice.",
            "Assess a replenishment response and operational capacity.",
            "Operations capacity approval",
        ),
        "price_discount": (
            "Pricing/Promotions", "pricing_lead",
            "Validate the discount depth observation and compare against the promo calendar.",
            "Assess a targeted discount adjustment and its margin implications.",
            "Pricing and margin approval",
        ),
        "promo_flag": (
            "Pricing/Promotions", "pricing_lead",
            "Validate the promotion window observation and compare against the promo calendar.",
            "Assess a promotion timing or scope adjustment.",
            "Pricing and margin approval",
        ),
        "weather_temp": (
            "Contextual", "merchandising_lead",
            "Review the weather observation and its expected category-level effect.",
            "Assess inventory and merchandising plan adjustments; weather is not controllable.",
            "Merchandising plan review",
        ),
    }

    @classmethod
    def _driver_specs(cls, result: dict[str, Any]) -> dict[str, dict[str, Any]]:
        drivers = ((result.get("contract_snapshot") or {}).get("drivers") or {}).get("candidate_drivers") or []
        return {item.get("driver_id"): item for item in drivers if item.get("driver_id")}

    @classmethod
    def _confidence_status(cls, result: dict[str, Any]) -> str:
        overall = ((result.get("confidence_profile") or {}).get("overall") or {})
        return overall.get("status") or (result.get("confidence") or {}).get("status", "NOT_ASSESSED")

    @classmethod
    def _evidence_status(cls, result: dict[str, Any]) -> str:
        source = ((result.get("confidence_profile") or {}).get("source") or {})
        return source.get("status") or ((result.get("reconciliation_verdict") or {}).get("status", "NOT_ASSESSED"))

    @classmethod
    def _blocked(cls, result: dict[str, Any]) -> bool:
        profile = result.get("confidence_profile") or {}
        source = profile.get("source") or {}
        overall = profile.get("overall") or {}
        reconciliation = result.get("reconciliation_verdict") or {}
        return (
            result.get("verdict") == "CONTRADICTED"
            or reconciliation.get("status") == "CONTRADICTED"
            or reconciliation.get("blocking") is True
            or source.get("status") == "CONFLICTING_EVIDENCE"
            or source.get("blocking") is True
            or overall.get("status") == "CONFLICTING_EVIDENCE"
        )

    @classmethod
    def _ranked_drivers(cls, result: dict[str, Any]) -> list[dict[str, Any]]:
        analysis = result.get("driver_analysis")
        return list(analysis.get("ranked_drivers") or []) if isinstance(analysis, dict) else list(result.get("correlational_candidates") or [])

    # ------------------------------------------------------------------
    # Stage 8-lite helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _attribution_confidence(driver: dict[str, Any]) -> float | None:
        """The driver's Stage 7 Attribution Confidence, or None if unassessed."""
        value = driver.get("attribution_confidence")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        return float(value)

    @staticmethod
    def _kpi_unit(result: dict[str, Any]) -> str | None:
        thresholds = ((result.get("contract_snapshot") or {}).get("materiality") or {}).get("business_thresholds") or {}
        unit = thresholds.get("unit")
        return unit if isinstance(unit, str) and unit.strip() else None

    @classmethod
    def _impact_estimate(cls, result: dict[str, Any], driver: dict[str, Any]) -> dict[str, Any]:
        """Project the driver's attributed contribution over the fixed horizon.

        ``-contribution * 7`` in the KPI's declared unit: reversing a driver
        that moved the KPI by `contribution` is taken to move it back by the
        same amount for one horizon of days. The bounds are the regression's own
        beta interval carried through the identical arithmetic, so the range can
        only ever be as wide as the fit is uncertain. A driver with no numeric
        contribution gets no estimate at all rather than a guessed one.
        """
        contribution = driver.get("contribution")
        if not isinstance(contribution, (int, float)) or isinstance(contribution, bool):
            return {
                "expected_impact": None, "expected_impact_unit": None,
                "impact_method": "NOT_ESTIMATED",
                "impact_explanation": (
                    "Impact is not estimated: this driver carries no regression contribution, "
                    "and an association is never converted into business impact."
                ),
                "expected_impact_low": None, "expected_impact_high": None,
            }
        interval = driver.get("contribution_interval") or []
        bounds = [
            float(value) for value in interval[:2]
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        low = round(-bounds[1] * IMPACT_HORIZON_DAYS, 2) if len(bounds) == 2 else None
        high = round(-bounds[0] * IMPACT_HORIZON_DAYS, 2) if len(bounds) == 2 else None
        if low is not None and high is not None and low > high:
            low, high = high, low
        unit = cls._kpi_unit(result)
        explanation = (
            f"Projected, not measured: the driver's attributed contribution for the target day "
            f"({contribution}) reversed over {IMPACT_HORIZON_DAYS} days, in {unit or 'the KPI unit'}. "
            f"Method {IMPACT_METHOD}: a fixed pro-rata extension of one day's statistical "
            "attribution, not a measured outcome and not a guaranteed return."
        )
        if low is None or high is None:
            explanation += " No range is shown because the regression produced no beta confidence interval for this driver."
        return {
            "expected_impact": round(-float(contribution) * IMPACT_HORIZON_DAYS, 2),
            "expected_impact_unit": unit,
            "impact_method": IMPACT_METHOD,
            "impact_explanation": explanation,
            "expected_impact_low": low,
            "expected_impact_high": high,
        }

    @classmethod
    def _card_kind(
        cls, result: dict[str, Any], driver: dict[str, Any], confidence: float | None,
    ) -> str:
        """Pick the card kind from the driver's AC, its lever and the run's state.

        ACTION_PROPOSAL needs both gates at once: the driver's own AC at or above
        AC_PROPOSE and a causal test on *this* driver that came back
        SUPPORTED_CONDITIONAL. A contextual driver is always ADVISORY, because
        the engine cannot propose changing the weather. Finally, a run the engine
        as a whole rates weak cannot produce an action however confident the
        driver looks, so anything stronger than NEXT_CHECK is downgraded.
        """
        if lever_family(driver.get("driver_id")) == "contextual" or (
            driver.get("controllability") or ""
        ) == "not_controllable":
            return "ADVISORY"
        if confidence is None or confidence < AC_CHECK:
            return "NEXT_CHECK"
        if confidence < AC_PROPOSE:
            return "NEXT_CHECK"
        verification = result.get("causal_verification") or {}
        # A design supplied for a different driver cannot advance this
        # driver's card beyond a next check, even when its own AC is high.
        if verification.get("driver_id") and verification.get("driver_id") != driver.get("driver_id"):
            return "NEXT_CHECK"
        kind = "ACTION_PROPOSAL" if (
            verification.get("verdict") == "SUPPORTED_CONDITIONAL"
            and verification.get("driver_id") == driver.get("driver_id")
        ) else "VERIFY_THEN_ACT"
        if cls._confidence_status(result) in WEAK_OVERALL_STATUSES:
            return "NEXT_CHECK"
        return kind

    @classmethod
    def _recommendation_text(cls, kind: str, lever_entry: tuple[str, ...]) -> str:
        lever, _owner, check, proposal, _right = lever_entry
        return proposal if kind in ACTION_KINDS else check

    # ------------------------------------------------------------------
    # Card construction
    # ------------------------------------------------------------------

    @classmethod
    def _build_card(
        cls, result: dict[str, Any], *, kind: str, driver: dict[str, Any] | None,
        lever: str, recommendation: str, fallback_owner: str, owner_source: str,
        decision_right: str, approval_required: bool, evidence_paths: tuple[str, ...],
        limitations: tuple[str, ...] = (), persona: PersonaConfig | None = None,
        confidence: float | None = None,
    ) -> dict[str, Any]:
        driver_id = driver.get("driver_id") if driver else None
        spec = cls._driver_specs(result).get(driver_id, {})
        # Owner precedence: the governed KPI contract first, then the persona's
        # owner for this lever family, then the action catalog's fallback. The
        # persona never overrides a governed owner; it only fills a gap.
        family = lever_family(driver_id)
        persona = persona or load_persona(result.get("persona"))
        persona_owner = persona.owner_for(family)
        owner = spec.get("owner") or persona_owner or fallback_owner
        if spec.get("owner"):
            resolved_owner_source = "contract.candidate_drivers.owner"
        elif persona_owner and persona_owner != fallback_owner:
            resolved_owner_source = "persona.lever_owners"
        else:
            resolved_owner_source = owner_source
        rank = driver.get("rank") if driver else None
        source_id = (driver or {}).get("source_id") or spec.get("source_id") or spec.get("source")
        period = result.get("target_date") or result.get("as_of")
        references = tuple({
            "evidence_type": "ranked_driver" if driver else "source_verification",
            "path": path,
            "driver_id": driver_id,
            "driver_rank": rank,
            "source_id": source_id,
            "period": period,
            "method": driver.get("alignment_method", "governed association") if driver else "source reconciliation",
        } for path in evidence_paths)
        monitor = f"Monitor {spec.get('display_name') or lever} ({driver_id or 'source verification'}) and the declared KPI at the governed native grain."
        stops = (
            "Stop the review if the driver is excluded, source coverage falls below its governed minimum, or reconciliation becomes contradictory.",
            "Do not roll out a change without independent verification and approval.",
        )
        limits = (*limitations, "Expected impact is not estimated without a validated deterministic method.")
        if kind == "ACTION_PROPOSAL":
            limits = (*limits, "Conditional observational support is not proof of causality.")
        # A sufficiently ranked driver can carry a transparent projection even
        # when the card is only a check. The validation label keeps that number
        # distinct from an approved, causally supported impact.
        impact = (
            cls._impact_estimate(result, driver)
            if driver is not None and confidence is not None and confidence >= AC_CHECK
            else {
                "expected_impact": None, "expected_impact_unit": None,
                "impact_method": "NOT_ESTIMATED",
                "impact_explanation": (
                    "Impact is not estimated: this card does not propose a change, and the "
                    "driver's attribution has not cleared the threshold for a projection."
                ),
                "expected_impact_low": None, "expected_impact_high": None,
            }
        )
        if impact["expected_impact"] is not None:
            causal = result.get("causal_verification") or {}
            impact_validated = confidence is not None and confidence >= AC_PROPOSE and (
                causal.get("verdict") == "SUPPORTED_CONDITIONAL"
                and causal.get("driver_id") == driver_id
            )
            if not impact_validated:
                impact["impact_explanation"] = "Not validated. " + impact["impact_explanation"]
            limits = tuple(
                limitation for limitation in limits
                if limitation != "Expected impact is not estimated without a validated deterministic method."
            ) + (
                f"Expected impact is a {IMPACT_HORIZON_DAYS}-day pro-rata projection of a statistical "
                "attribution, not a measured outcome.",
            )
        # Approval. A card that proposes a change always needs a sign-off; the
        # persona's approval_threshold decides whether this role may give it or
        # whether the proposal is escalated above the role.
        threshold = persona.approval_threshold
        escalation = ""
        if approval_required and confidence is not None and confidence < threshold:
            escalation = (
                f" Attribution Confidence {confidence:.0%} is below this role's approval threshold "
                f"{threshold:.0%}, so the proposal is escalated rather than self-approved."
            )
            limits = (*limits, escalation.strip())
        if kind == "ADVISORY":
            limits = (*limits, "Contextual drivers are not controllable; this card informs planning and proposes no change.")
        return asdict(DecisionCard(
            action_id=f"ACTION_{driver_id or 'EVIDENCE_COLLECTION'}_{kind}", kind=kind,
            status="AWAITING_APPROVAL" if approval_required else "AWAITING_REVIEW",
            driver_id=driver_id, driver_rank=rank,
            driver_relationship="CONDITIONAL_CAUSAL_SUPPORT" if kind == "ACTION_PROPOSAL" else "ASSOCIATION" if driver else "EVIDENCE_GATHERING",
            controllability=(driver or {}).get("controllability") or spec.get("controllability", "contextual"),
            lever=lever, recommendation=recommendation, owner=owner, owner_source=resolved_owner_source,
            decision_right=decision_right, approval_required=approval_required,
            expected_impact=impact["expected_impact"],
            expected_impact_unit=impact["expected_impact_unit"],
            impact_method=impact["impact_method"],
            impact_explanation=impact["impact_explanation"],
            evidence_status=cls._evidence_status(result), confidence_status=cls._confidence_status(result),
            evidence_references=references, constraints=("Association is diagnostic only; no causal or monetary impact is established.",),
            monitoring_plan=monitor, success_metric=f"Verify the declared {spec.get('display_name') or lever} signal before any rollout.",
            review_window="Review after the next governed observation window and source validation.",
            stop_conditions=stops, limitations=limits, evidence_paths=evidence_paths,
            persona=persona.persona_id,
            attribution_confidence=confidence,
            attribution_band=(driver or {}).get("band"),
            attribution_label=(driver or {}).get("label"),
            expected_impact_low=impact["expected_impact_low"],
            expected_impact_high=impact["expected_impact_high"],
            approval_threshold=threshold,
        ))

    @classmethod
    def _persona_cards(
        cls, result: dict[str, Any], ranked: list[dict[str, Any]],
        persona: PersonaConfig, verification: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Up to MAX_CARDS cards, strongest Attribution Confidence first.

        A lever family the persona may not act on is dropped, not reworded: the
        persona config decides which levers this role is offered, and dropping a
        card changes no number or driver in it. If that leaves nothing, the
        reviewer still gets the evidence-collection check, which is honest about
        there being no lever for this role yet.
        """
        scored = [
            (cls._attribution_confidence(driver) or 0.0, driver)
            for driver in ranked
            if driver.get("driver_id") in cls.LEVERS
            and lever_family(driver.get("driver_id")) in persona.allowed_action_levers
            and not (
                verification.get("verdict") == "REJECTED"
                and driver.get("driver_id") == verification.get("driver_id")
            )
        ]
        if not scored:
            return [cls._evidence_collection_card(result, persona)]
        scored.sort(key=lambda entry: (
            -entry[0],
            entry[1].get("rank") if isinstance(entry[1].get("rank"), int) else 10 ** 6,
        ))
        cards = []
        for confidence, driver in scored[:MAX_CARDS]:
            kind = cls._card_kind(result, driver, confidence)
            lever_entry = cls.LEVERS[driver["driver_id"]]
            family = lever_family(driver.get("driver_id"))
            cards.append(cls._build_card(
                result, kind=kind, driver=driver,
                lever=lever_entry[0], recommendation=cls._recommendation_text(kind, lever_entry),
                fallback_owner=lever_entry[1], owner_source="validated_action_catalog",
                decision_right=lever_entry[4] if kind in ACTION_KINDS else "Driver verification review",
                approval_required=kind in ACTION_KINDS,
                evidence_paths=("driver_analysis.ranked_drivers",),
                limitations=("The driver ranking is statistical; each card still needs its own verification before any change.",),
                persona=persona, confidence=confidence,
            ) if family != "contextual" else cls._build_card(
                result, kind=kind, driver=driver,
                lever=lever_entry[0], recommendation=lever_entry[2],
                fallback_owner=lever_entry[1], owner_source="validated_action_catalog",
                decision_right="Merchandising plan review", approval_required=False,
                evidence_paths=("driver_analysis.ranked_drivers",),
                limitations=("Contextual drivers cannot be changed by a decision; this is awareness only.",),
                persona=persona, confidence=confidence,
            ))
        return cards

    @classmethod
    def _evidence_collection_card(
        cls, result: dict[str, Any], persona: PersonaConfig,
    ) -> dict[str, Any]:
        return cls._build_card(result, kind="NEXT_CHECK", driver=None, lever="Evidence collection",
            recommendation="Review the event timeline and identify a valid comparison group before proposing action.",
            fallback_owner=persona.default_owner, owner_source="validated_evidence_collection_rule",
            decision_right=persona.decision_right, approval_required=False,
            evidence_paths=("causal_verification",), persona=persona)

    @classmethod
    def _legacy_cards(
        cls, result: dict[str, Any], ranked: list[dict[str, Any]], persona: PersonaConfig,
        verification: dict[str, Any], verified_driver: str | None,
    ) -> list[dict[str, Any]]:
        """The pre-Stage-8 single card, used when no driver carries an AC.

        A hand-built or projected payload may reach the action engine without
        the Stage 7 Attribution Confidence fields, in which case there is nothing
        to rank or threshold by and the older, more conservative single-card
        rules are used unchanged. The one addition is the persona: the owner
        falls back to the persona config and the approval threshold is recorded.
        """
        confidence_status = cls._confidence_status(result)
        if verified_driver in cls.LEVERS and verified_driver in {item.get("driver_id") for item in ranked}:
            driver = next(item for item in ranked if item.get("driver_id") == verified_driver)
            lever, fallback_owner, check, proposal, decision_right = cls.LEVERS[verified_driver]
            if verification.get("verdict") == "SUPPORTED_CONDITIONAL":
                if confidence_status in WEAK_OVERALL_STATUSES:
                    return [cls._build_card(result, kind="NEXT_CHECK", driver=driver, lever=lever,
                        recommendation=check, fallback_owner=fallback_owner, owner_source="validated_action_catalog",
                        decision_right=decision_right, approval_required=False,
                        evidence_paths=("causal_verification.verdict", "causal_verification.driver_id"),
                        limitations=("Confidence is insufficient for an operational proposal.",), persona=persona)]
                return [cls._build_card(result, kind="ACTION_PROPOSAL", driver=driver, lever=lever,
                    recommendation=proposal, fallback_owner=fallback_owner, owner_source="validated_action_catalog",
                    decision_right=decision_right, approval_required=True,
                    evidence_paths=("causal_verification.verdict", "causal_verification.driver_id"),
                    persona=persona)]
            if verification.get("verdict") in {"INCONCLUSIVE", "UNTESTABLE"}:
                return [cls._build_card(result, kind="NEXT_CHECK", driver=driver, lever=lever,
                    recommendation=check, fallback_owner=fallback_owner, owner_source="validated_action_catalog",
                    decision_right=decision_right, approval_required=False,
                    evidence_paths=("causal_verification.verdict", "causal_verification.driver_id"),
                    persona=persona)]
        if ranked:
            candidate = ranked[0]
            driver_id = candidate.get("driver_id")
            if driver_id in cls.LEVERS and not (verification.get("verdict") == "REJECTED" and driver_id == verified_driver):
                lever, fallback_owner, check, _, decision_right = cls.LEVERS[driver_id]
                return [cls._build_card(result, kind="NEXT_CHECK", driver=candidate, lever=lever,
                    recommendation=check, fallback_owner=fallback_owner, owner_source="validated_action_catalog",
                    decision_right=decision_right, approval_required=False,
                    evidence_paths=("driver_analysis.ranked_drivers", "correlational_candidates"),
                    limitations=("The ranked relationship is associative and requires verification before action.",),
                    persona=persona)]
        return [cls._evidence_collection_card(result, persona)]

    @classmethod
    def recommend(cls, result: dict[str, Any]) -> list[dict[str, Any]]:
        persona = load_persona(result.get("persona"))
        if result.get("verdict") == "ACCESS_DENIED":
            return []
        if cls._blocked(result):
            return [cls._build_card(result, kind="NEXT_CHECK", driver=None, lever="Source integrity",
                recommendation="Reconcile sales and finance postings before investigating drivers.",
                fallback_owner="finance_owner", owner_source="validated_source_integrity_rule",
                decision_right="Source reconciliation review", approval_required=False,
                evidence_paths=("reconciliation_verdict.status",),
                limitations=("Contradictory evidence blocks all operational action proposals.",),
                persona=persona)]
        if result.get("verdict") not in {"MATERIAL_CAUSE_UNVERIFIED", "EVENT_ASSESSED_CAUSE_UNVERIFIED"}:
            return []
        verification = result.get("causal_verification") or {}
        verified_driver = verification.get("driver_id")
        analysis = result.get("driver_analysis")
        if isinstance(analysis, dict) and analysis.get("status") == "BLOCKED":
            return []
        ranked = cls._ranked_drivers(result)
        ranked_ids = {item.get("driver_id") for item in ranked}
        if analysis is None and verification.get("verdict") == "SUPPORTED_CONDITIONAL" and verified_driver in cls.LEVERS:
            ranked.append({"driver_id": verified_driver, "claim_type": "CONDITIONAL_CAUSAL_SUPPORT"})
            ranked_ids.add(verified_driver)
        if not any(cls._attribution_confidence(driver) is not None for driver in ranked):
            return cls._legacy_cards(result, ranked, persona, verification, verified_driver)
        return cls._persona_cards(result, ranked, persona, verification)
