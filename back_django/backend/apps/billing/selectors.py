from apps.billing.models import Plan, Subscription


def get_plan_by_code(*, code):
    return Plan.objects.filter(code=code).first()


def get_plan_limits(*, plan):
    return plan.features.get("limits", {})


def get_subscription_effective_limits(*, subscription):
    return subscription.effective_limits()


def subscription_has_functional_access(*, subscription, at=None):
    return subscription.has_functional_access(at=at)


def get_subscription_access_block_reason(*, subscription, at=None):
    return subscription.access_block_reason(at=at)


def get_current_subscription_for_company(*, company):
    return (
        Subscription.objects.select_related("plan")
        .filter(company=company)
        .order_by("-started_at", "-created_at")
        .first()
    )
