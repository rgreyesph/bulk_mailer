# mailer_app/tests.py
from django.test import TestCase
from django.urls import reverse
from .models import ContactList

class ContactListModelTests(TestCase):
    def test_contact_list_creation(self):
        """Test that a ContactList can be created."""
        list_name = "Test Subscribers"
        cl = ContactList.objects.create(name=list_name)
        self.assertEqual(cl.name, list_name)
        self.assertTrue(isinstance(cl.name, str))

class DashboardViewTests(TestCase):
    def test_dashboard_unauthenticated(self):
        """Test dashboard redirects if user is not logged in."""
        response = self.client.get(reverse('mailer_app:dashboard'))
        self.assertEqual(response.status_code, 302) # 302 is redirect
        self.assertRedirects(response, '/login/?next=/')