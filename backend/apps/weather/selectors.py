from datetime import timedelta

from django.utils import timezone


SUMMARIES = ["Freezing", "Bracing", "Chilly", "Cool", "Mild", "Warm", "Hot"]


def list_weather_forecast(*, days=5):
    today = timezone.localdate()
    forecast = []

    for index in range(days):
        temperature_c = 8 + (index * 3)
        forecast.append(
            {
                "date": today + timedelta(days=index),
                "temperature_c": temperature_c,
                "temperature_f": 32 + int(temperature_c / 0.5556),
                "summary": SUMMARIES[index % len(SUMMARIES)],
            }
        )

    return forecast
