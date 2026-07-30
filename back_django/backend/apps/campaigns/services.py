def campaign_is_active_at(*, campaign, at):
    return campaign.status == campaign.Status.ACTIVE and campaign.starts_at <= at <= campaign.ends_at
