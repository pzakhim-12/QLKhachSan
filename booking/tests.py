from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from .models import Room, RoomCategory, Booking
from django.contrib.auth.models import User

class DatetimeImportFixTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='test', password='123')
        self.category = RoomCategory.objects.create(name='Deluxe', price_per_night=500000)
        self.room = Room.objects.create(room_number='P101', category=self.category)

    def test_calculate_price_api_accepts_valid_dates(self):
        """Đảm bảo calculate_price_api không lỗi do import datetime sai"""
        self.client.login(username='test', password='123')
        response = self.client.post('/api/calculate-price/', data={
            'room_id': self.room.id,
            'check_in': '2026-08-10',
            'check_out': '2026-08-12',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get('success'))