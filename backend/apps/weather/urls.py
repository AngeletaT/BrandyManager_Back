from django.urls import path

from apps.weather.views import WeatherForecastAPIView


urlpatterns = [
    path("", WeatherForecastAPIView.as_view(), name="weather-forecast"),
]
