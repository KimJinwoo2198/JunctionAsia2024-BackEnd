from django.urls import path
from .views import (
    FoodViewSet, FoodLogViewSet, UserPregnancyProfileViewSet, 
    FoodRecommendationViewSet, FoodRecognitionLogViewSet, FoodRatingViewSet, UserStyleViewSet
)

urlpatterns = [
    # Food URLs
    path('foods/', FoodViewSet.as_view({'get': 'list'}), name='food-list'),
    path('foods/<int:pk>/', FoodViewSet.as_view({'get': 'retrieve'}), name='food-detail'),
    path('foods/recognize/', FoodViewSet.as_view({'post': 'recognize'}), name='food-recognize'),
    path('foods/<int:pk>/safety-info/', FoodViewSet.as_view({'get': 'safety_info'}), name='food-safety-info'),

    # FoodLog URLs
    path('food-logs/', FoodLogViewSet.as_view({'get': 'list', 'post': 'create'}), name='foodlog-list'),
    path('food-logs/nutrient-analysis/', FoodLogViewSet.as_view({'get': 'nutrient_analysis'}), name='foodlog-nutrient-analysis'),

    # UserPregnancyProfile URLs
    path('pregnancy-profile/', UserPregnancyProfileViewSet.as_view({'get': 'retrieve', 'post': 'create', 'put': 'update'}), name='pregnancyprofile'),

    # FoodRecommendation URLs
    path('food-recommendations/', FoodRecommendationViewSet.as_view({'get': 'list'}), name='foodrecommendation-list'),
    path('food-recommendations/personalized/', FoodRecommendationViewSet.as_view({'get': 'personalized'}), name='foodrecommendation-personalized'),

    # FoodRecognitionLog URLs
    path('food-recognition-logs/', FoodRecognitionLogViewSet.as_view({'get': 'list'}), name='foodrecognitionlog-list'),

    # FoodRating URLs
    path('food-ratings/', FoodRatingViewSet.as_view({'get': 'list', 'post': 'create'}), name='foodrating-list'),
    path('food-ratings/summary/', FoodRatingViewSet.as_view({'get': 'food_ratings_summary'}), name='foodrating-summary'),

    path('user-styles/list-styles/', UserStyleViewSet.as_view({'get': 'list_styles'}), name='list-styles'),
    path('user-styles/set-preferred-style/', UserStyleViewSet.as_view({'post': 'set_preferred_style'}), name='set-preferred-style'),
]