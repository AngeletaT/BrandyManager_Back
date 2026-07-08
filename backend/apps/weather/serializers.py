from rest_framework import serializers


class WeatherForecastListSerializer(serializers.Serializer):
    date = serializers.DateField()
    temperature_c = serializers.IntegerField()
    temperature_f = serializers.IntegerField()
    summary = serializers.CharField()
