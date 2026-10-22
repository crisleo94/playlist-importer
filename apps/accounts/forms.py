from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

INPUT_CLASSES = (
    'w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2.5 '
    'text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500 '
    'focus:ring-1 focus:ring-emerald-500 text-sm'
)


class RegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('username',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': INPUT_CLASSES})
            field.help_text = ''
        self.fields['username'].widget.attrs.update({'autofocus': True, 'placeholder': 'Ej. usuario'})
        self.fields['password1'].widget.attrs.update({'placeholder': 'Mínimo 8 caracteres'})
        self.fields['password2'].widget.attrs.update({'placeholder': 'Repite la contraseña'})
