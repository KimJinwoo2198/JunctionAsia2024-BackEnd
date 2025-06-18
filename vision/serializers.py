from rest_framework import serializers
from .models import Food, FoodLog, UserPregnancyProfile, FoodRecommendation, FoodRecognitionLog, FoodRating, ResponseStyle

class FoodSerializer(serializers.ModelSerializer):
    class Meta:
        model = Food
        fields = ['id', 'name', 'description', 'image_url', 'nutritional_info']

class FoodLogSerializer(serializers.ModelSerializer):
    food_name = serializers.CharField(source='food.name', read_only=True)

    class Meta:
        model = FoodLog
        fields = ['id', 'food', 'food_name', 'date', 'portion', 'meal_type']
        read_only_fields = ['user']

class UserPregnancyProfileSerializer(serializers.ModelSerializer):
    bmi = serializers.FloatField(read_only=True)
    weight_gain = serializers.FloatField(read_only=True)
    current_week = serializers.IntegerField(read_only=True)

    class Meta:
        model = UserPregnancyProfile
        fields = ['id', 'user', 'due_date', 'current_weight', 'height', 'pre_pregnancy_weight', 'bmi', 'weight_gain', 'current_week']
        read_only_fields = ['user']

class FoodRecommendationSerializer(serializers.ModelSerializer):
    food_name = serializers.CharField(source='food.name', read_only=True)

    class Meta:
        model = FoodRecommendation
        fields = ['id', 'user', 'food', 'food_name', 'reason', 'priority', 'date']
        read_only_fields = ['user', 'date']

class FoodRecognitionLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = FoodRecognitionLog
        fields = ['id', 'user', 'image_url', 'recognized_food', 'confidence_score', 'date']
        read_only_fields = ['user', 'date']

class FoodRatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = FoodRating
        fields = ['id', 'user', 'food', 'rating', 'comment', 'pregnancy_week', 'created_at', 'is_verified']
        read_only_fields = ['user', 'created_at', 'is_verified']

class ResponseStyleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResponseStyle
        fields = ['id', 'name', 'prompt']