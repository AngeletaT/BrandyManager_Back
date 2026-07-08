from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class WeatherForecastAPITests(APITestCase):
    def test_weather_forecast_returns_five_items(self):
        response = self.client.get(reverse("weather-forecast"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 5)
        self.assertEqual(
            set(response.data[0].keys()),
            {"date", "temperature_c", "temperature_f", "summary"},
        )
