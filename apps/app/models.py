from django.db import models, transaction
from django.db.models import Q
from django.contrib.auth.models import AbstractUser
from rest_framework import serializers
from pathlib import Path
import uuid
from django.core.exceptions import ValidationError
from apps.app.fields import EncryptedTextField


def save_file(instance, filename: str) -> str:
    path = Path(filename)
    if path.suffix.lower() != '.json':
        raise ValidationError("Only JSON files are allowed (.json)")
    name = uuid.uuid4().hex
    enddir = 'token' if filename.startswith('token') else 'credentials'
    return f"uploads/{enddir}/{name}.json"


class User(AbstractUser):
    email = models.EmailField(unique=True)
    language = models.CharField(max_length=8, default='pl')
    country = models.CharField(max_length=8, default='PL')
    results = models.ManyToManyField(
        'SearchQuery',
        related_name='user_queries',
        blank=True)
    token = EncryptedTextField(blank=True, null=True)

    def __str__(self):
        return self.username


class SearchQuery(models.Model):
    user = models.ManyToManyField(User, related_name='search_queries')
    accuracy = models.FloatField(null=True, blank=True)
    location = models.CharField(max_length=255)
    query = models.CharField(max_length=255)
    result = models.JSONField(default=dict)
    companies = models.ManyToManyField(
        'Company',
        related_name='search_queries',
        blank=True
    )

    @staticmethod
    def save_result(user: User, location: str, query: str, accuracy: float, result: dict) -> 'SearchQuery':
        with transaction.atomic():
            search_query, _created = SearchQuery.objects.update_or_create(
                location=location,
                query=query,
                defaults={
                    'accuracy': accuracy,
                    'result': result,
                }
            )
            search_query.user.add(user)
            Company.save_results(result, search_query)
            user.results.add(search_query)
        return search_query

    def __str__(self):
        return f"{self.query}-{self.location}"


class Company(models.Model):
    EMAIL_CRAWL_STATUS_CHOICES = (
        ("not_started", "Not started"),
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    )

    query = models.ManyToManyField(SearchQuery, related_name='company_queries')
    name = models.CharField(max_length=255)
    website = models.URLField(blank=True, null=True, unique=True)
    email = models.TextField(blank=True)
    osm_email = models.TextField(blank=True)
    phones = models.TextField(blank=True)
    address = models.TextField(blank=True)
    osm_id = models.BigIntegerField(blank=True, null=True)
    osm_type = models.CharField(max_length=10, blank=True)
    source = models.CharField(max_length=16, blank=True, default="")
    category = models.CharField(max_length=128, blank=True)
    osm_tags = models.JSONField(blank=True, null=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    email_crawl_status = models.CharField(
        choices=EMAIL_CRAWL_STATUS_CHOICES,
        default="not_started",
        max_length=16,
    )

    @staticmethod
    def save_results(result: dict, search_query: 'SearchQuery') -> None:
        places_dict = next(
            (
                value
                for key, value in result.items()
                if key.startswith("polygon_search_") and isinstance(value, dict)
            ),
            {},
        )

        for place_data in places_dict.values():
            if not isinstance(place_data, dict):
                continue

            osm_type = place_data.get("osm_type", "")
            osm_id = place_data.get("osm_id")
            if osm_type not in {"node", "way", "relation"} or not isinstance(
                osm_id, int
            ):
                continue

            website = place_data.get("website") or None
            defaults = {
                "name": place_data.get("name") or "Firma bez nazwy",
                "website": website,
                "osm_email": place_data.get("osm_email", ""),
                "phones": place_data.get("phone", ""),
                "address": place_data.get("address", ""),
                "osm_id": osm_id,
                "osm_type": osm_type,
                "source": "osm",
                "category": place_data.get("category", ""),
                "osm_tags": place_data.get("osm_tags", {}),
                "latitude": place_data.get("latitude"),
                "longitude": place_data.get("longitude"),
            }

            with transaction.atomic():
                company = Company.objects.filter(
                    osm_type=osm_type,
                    osm_id=osm_id,
                ).first()
                if company is None and website:
                    company = Company.objects.filter(website=website).first()

                if company is None:
                    company = Company.objects.create(**defaults)
                else:
                    website_conflict = (
                        Company.objects.filter(website=website)
                        .exclude(pk=company.pk)
                        .first()
                        if website
                        else None
                    )
                    if website_conflict is not None:
                        company = website_conflict
                    else:
                        old_website = company.website
                        for field, value in defaults.items():
                            if field in {"osm_type", "osm_id"} and getattr(
                                company, field
                            ):
                                continue
                            setattr(company, field, value)
                        if old_website != website:
                            company.email = ""
                            company.email_crawl_status = "not_started"
                        company.save()

                search_query.companies.add(company)

    def save_mail(self) -> bool:
        if not self.pk or not self.website:
            return False

        can_queue = Company.objects.filter(
            pk=self.pk,
            email="",
            email_crawl_status__in=("not_started", "failed"),
        ).update(email_crawl_status="pending")
        if not can_queue:
            return False

        self.email_crawl_status = "pending"
        from apps.app.tasks import crawl_email_addresses

        try:
            crawl_email_addresses.apply_async(
                kwargs={"url": self.website, "company_id": self.pk},
                queue="redis_tasks",
            )
        except Exception:
            Company.objects.filter(
                pk=self.pk,
                email_crawl_status="pending",
            ).update(email_crawl_status="failed")
            self.email_crawl_status = "failed"
            logger.exception(
                "Could not queue website email extraction for company %s",
                self.pk,
            )
            raise
        return True

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Companies"
        constraints = [
            models.UniqueConstraint(
                condition=Q(osm_id__isnull=False),
                fields=("osm_type", "osm_id"),
                name="unique_company_osm_object",
            )
        ]


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = '__all__'