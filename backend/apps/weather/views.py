from rest_framework.response import Response
from rest_framework.views import APIView

from apps.weather.selectors import list_weather_forecast
from apps.weather.serializers import WeatherForecastListSerializer


class WeatherForecastAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        forecast = list_weather_forecast()
        serializer = WeatherForecastListSerializer(forecast, many=True)

        return Response(serializer.data)
