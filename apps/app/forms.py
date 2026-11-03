from django import forms

from apps.web.web_search import CATEGORY_CHOICES

class SearchForm(forms.Form):
	category = forms.ChoiceField(choices=CATEGORY_CHOICES)
	custom_category = forms.CharField(max_length=100, required=False)
	polygon_coords = forms.CharField(max_length=16000)

	def clean(self):
		cleaned_data = super().clean()
		if (
			cleaned_data.get("category") == "custom"
			and not cleaned_data.get("custom_category", "").strip()
		):
			self.add_error("custom_category", "Enter a custom category.")
		return cleaned_data


class SendEmailForm(forms.Form):
	location = forms.CharField(max_length=255)
	subject = forms.CharField(max_length=255)
	text = forms.CharField(widget=forms.Textarea)
	delay_min = forms.IntegerField(min_value=0, required=False)

	def clean_delay_min(self):
		val = self.cleaned_data.get('delay_min')
		if val is None:
			return 1
		return val


class LoginForm(forms.Form):
	username = forms.CharField(max_length=150)
	password = forms.CharField(widget=forms.PasswordInput)


class RegisterForm(forms.Form):
	username = forms.CharField(max_length=150)
	email = forms.EmailField()
	password = forms.CharField(widget=forms.PasswordInput, min_length=6)
	language = forms.CharField(max_length=8, initial='pl')
	country = forms.CharField(max_length=8, initial='PL')
