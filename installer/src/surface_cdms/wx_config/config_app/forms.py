from django import forms
from surface_app.models import InstallType

class InstallTypeForm(forms.ModelForm):
    class Meta:
        model = InstallType
        fields = ['install_type']
        widgets = {
            'install_type': forms.RadioSelect
        }