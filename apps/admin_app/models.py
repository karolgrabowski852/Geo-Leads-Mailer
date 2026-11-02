from django.db import models
from django.contrib.auth.models import AbstractUser
from rest_framework import serializers
from pathlib import Path
import logging
import uuid
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

def save_file(instance, filename: str) -> str:
    path = Path(filename)
    if path.suffix.lower() != '.json':
        raise ValidationError("Only JSON files are allowed (.json)")
    name = uuid.uuid4().hex
    logger.info(f'filename {filename}')
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
    credentials = models.FileField(upload_to=save_file, blank=True, null=True)
    token = models.FileField(upload_to=save_file, blank=True, null=True)

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
        try:
            search_query, created = SearchQuery.objects.update_or_create(
                location=location,
                query=query,
                defaults={
                    'result': result
                }
            )
            if created or user not in search_query.user.all():
                search_query.user.add(user)

            Company.save_results(result, search_query)
            
            user.results.add(search_query)
            user.save()
            
            return search_query
        except Exception as e:
            logger.error(f"Error saving search query: {e}")
        
    def __str__(self):
        return f"{self.query}-{self.location}"


class Company(models.Model):
    query = models.ManyToManyField(SearchQuery, related_name='company_queries')
    name = models.CharField(max_length=255)
    website = models.URLField(blank=True, null=True, unique=True)
    email = models.TextField(blank=True)
    phones = models.TextField(blank=True)
    address = models.TextField(blank=True)

    @staticmethod
    def save_results(result: dict, search_query: 'SearchQuery') -> None:
        fullquery = list(result.keys())[0]
        places_dict = result.get(fullquery, {})
        
        for place_name, place_data in places_dict.items():
            display_name = place_data.get('displayName', {}).get('text', place_name)
            website = place_data.get('websiteUri', '')
            phone = place_data.get('nationalPhoneNumber', '')
            address = place_data.get('formattedAddress', '')
            if website in Company.objects.values_list('website', flat=True) or len(website) >= 200:
                continue
            company, created = Company.objects.update_or_create(
                name=display_name,
                defaults={
                    'website': website,
                    'phones': phone,
                    'email': '',
                    'address': address
                }
            )

            search_query.companies.add(company)

    def save_mail(self):
        if not self.website:
            return
        from apps.app.tasks import crawl_email_addresses 
        result = crawl_email_addresses.apply_async(kwargs={"url": self.website}, queue='redis_tasks').get()
        emails = result.get('emails', [])
        if isinstance(emails, list) and emails:
            emails_joined = ", ".join(map(str, emails))
            if len(emails_joined) >= 500:
                return
            self.email = emails_joined
            self.save(update_fields=["email"])

    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name_plural = "Companies"


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = '__all__'