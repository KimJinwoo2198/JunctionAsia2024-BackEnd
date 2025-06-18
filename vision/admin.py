from django.contrib import admin
from .models import (
    PregnancyStage, NutrientRequirement, Food, FoodLog, UserPregnancyProfile,
    FoodRecommendation, FoodRating, UserTrustScore, NutritionDatabase,
    FoodRecognitionLog, ResponseStyle
)

@admin.register(PregnancyStage)
class PregnancyStageAdmin(admin.ModelAdmin):
    list_display = ('name', 'week_start', 'week_end')
    search_fields = ('name',)

@admin.register(NutrientRequirement)
class NutrientRequirementAdmin(admin.ModelAdmin):
    list_display = ('pregnancy_stage', 'nutrient_name', 'daily_value', 'unit')
    list_filter = ('pregnancy_stage', 'nutrient_name')
    search_fields = ('nutrient_name',)

@admin.register(Food)
class FoodAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name', 'description')

@admin.register(FoodLog)
class FoodLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'food', 'date', 'portion', 'meal_type')
    list_filter = ('date', 'meal_type', 'user')
    search_fields = ('user__username', 'food__name')
    date_hierarchy = 'date'

@admin.register(UserPregnancyProfile)
class UserPregnancyProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'due_date', 'current_weight', 'height', 'bmi', 'weight_gain', 'current_week')
    search_fields = ('user__username',)

@admin.register(FoodRecommendation)
class FoodRecommendationAdmin(admin.ModelAdmin):
    list_display = ('user', 'food', 'priority', 'date')
    list_filter = ('date', 'priority')
    search_fields = ('user__username', 'food__name')
    date_hierarchy = 'date'

@admin.register(FoodRating)
class FoodRatingAdmin(admin.ModelAdmin):
    list_display = ('user', 'food', 'rating', 'pregnancy_week', 'created_at', 'is_verified')
    list_filter = ('rating', 'pregnancy_week', 'is_verified')
    search_fields = ('user__username', 'food__name', 'comment')
    date_hierarchy = 'created_at'

@admin.register(UserTrustScore)
class UserTrustScoreAdmin(admin.ModelAdmin):
    list_display = ('user', 'trust_score', 'last_updated')
    search_fields = ('user__username',)

@admin.register(NutritionDatabase)
class NutritionDatabaseAdmin(admin.ModelAdmin):
    list_display = ('food_name', 'source', 'last_updated')
    search_fields = ('food_name', 'source')
    date_hierarchy = 'last_updated'

@admin.register(FoodRecognitionLog)
class FoodRecognitionLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'recognized_food', 'confidence_score', 'date')
    list_filter = ('date',)
    search_fields = ('user__username', 'recognized_food')
    date_hierarchy = 'date'

@admin.register(ResponseStyle)
class ResponseStyleAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name', 'prompt')