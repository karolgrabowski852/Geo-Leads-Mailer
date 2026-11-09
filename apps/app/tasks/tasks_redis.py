import logging

from apps.celery import celery_redis
from apps.web.email_crawler import email_crawler
from apps.web.email_validation import extract_valid_emails

logger = logging.getLogger(__name__)

@celery_redis.task(name='apps.app.crawl_email_addresses', queue='redis_tasks')
def crawl_email_addresses(url: str, company_id: int | None = None):
    from apps.app.models import Company

    try:
        email_addresses = extract_valid_emails(
            ", ".join(email_crawler.crawl_sync(url))
        )
        if company_id is not None:
            company = Company.objects.get(pk=company_id)
            if company.website == url:
                emails_joined = ", ".join(sorted(set(email_addresses)))
                company.email = emails_joined
                company.email_crawl_status = Company.CrawlStatus.COMPLETED
                company.save(update_fields=["email", "email_crawl_status"])
        return {"emails": email_addresses}
    except Exception:
        if company_id is not None:
            Company.objects.filter(
                pk=company_id,
                website=url,
                email_crawl_status=Company.CrawlStatus.PENDING,
            ).update(email_crawl_status=Company.CrawlStatus.FAILED)
        logger.exception("Website email extraction failed for %s", url)
        raise
