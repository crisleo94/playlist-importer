from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from apps.accounts.forms import RegisterForm

User = get_user_model()


class AccountsTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_register_get_renders_custom_form(self):
        response = self.client.get(reverse('accounts:register'))
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context['form'], RegisterForm)
        self.assertContains(response, 'Crear Cuenta')
        self.assertContains(response, 'placeholder="Ej. usuario"')

    def test_register_post_success(self):
        response = self.client.post(reverse('accounts:register'), {
            'username': 'newuser',
            'password1': 'StrongP@ssw0rd123',
            'password2': 'StrongP@ssw0rd123',
        })
        self.assertRedirects(response, reverse('importer:dashboard'))
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_register_post_password_mismatch(self):
        response = self.client.post(reverse('accounts:register'), {
            'username': 'mismatchuser',
            'password1': 'StrongP@ssw0rd123',
            'password2': 'DifferentPassword123',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='mismatchuser').exists())
        self.assertTrue(bool(response.context['form'].errors.get('password2')))

    def test_login_and_logout(self):
        User.objects.create_user(username='loginuser', password='Password123!')
        response = self.client.post(reverse('accounts:login'), {
            'username': 'loginuser',
            'password': 'Password123!',
        })
        self.assertRedirects(response, reverse('importer:dashboard'))

        logout_response = self.client.post(reverse('accounts:logout'))
        self.assertRedirects(logout_response, reverse('accounts:login'))
