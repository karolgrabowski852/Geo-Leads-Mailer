from django.contrib import admin
from django import forms
from .models import User, SearchQuery, Company
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

class SearchQueryForm(forms.ModelForm):
    class Meta:
        model = SearchQuery
        fields = ['accuracy', 'location', 'query', 'companies']
        widgets = {
            'companies': forms.CheckboxSelectMultiple(),
            'query': forms.TextInput(attrs={'size': 50}),
            'location': forms.TextInput(attrs={'size': 50}),
        }

@admin.register(SearchQuery)
class SearchQueryAdmin(admin.ModelAdmin):
    form = SearchQueryForm
    list_display = ('location', 'query', 'get_users', 'grid_size_display', 'id')
    list_filter = ('location', 'accuracy')
    search_fields = ('query', 'location')

    def grid_size_display(self, obj):
        return f"{obj.accuracy} km (grid)"
    grid_size_display.short_description = 'Grid Size'

    def get_users(self, obj):
        return ", ".join([u.username for u in obj.user.all()])
    get_users.short_description = 'Users'

class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = (
            'username', 'email', 'password', 'language', 'country',
            'results', 'credentials', 'token', 'is_active', 'is_staff',
            'is_superuser', 'groups', 'user_permissions',
        )
        widgets = {
            'password': forms.PasswordInput(),
            'results': forms.CheckboxSelectMultiple(),
            'credentials': forms.FileInput(),
            'token': forms.FileInput(),
        }

@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = UserForm
    list_display = (
        'username', 'email', 'language', 'country', 'is_staff',
        'is_superuser', 'results_count', 'has_credentials', 'token',
    )
    search_fields = ('username', 'email')
    filter_horizontal = ('results', 'groups', 'user_permissions')

    fieldsets = DjangoUserAdmin.fieldsets + (
        ('Geo Leads', {'fields': ('language', 'country', 'results', 'credentials', 'token')}),
    )

    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ('Geo Leads', {'fields': ('language', 'country', 'results', 'credentials', 'token')}),
    )

    def results_count(self, obj):
        return obj.results.count()

    def has_credentials(self, obj):
        return True if obj.credentials else False


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'website', 'email', 'phones', 'get_queries')

    def get_queries(self, obj):
        return ", ".join([q.query for q in obj.search_queries.all()])
    get_queries.short_description = 'Queries'


