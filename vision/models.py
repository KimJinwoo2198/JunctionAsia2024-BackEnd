from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


User = get_user_model()

def validate_prompt_template(value):
    if len(value) < 50:
        raise ValidationError(
            _('%(value)s is too short. Prompt template should be at least 50 characters.'),
            params={'value': value},
        )
        
class PregnancyStage(models.Model):
    name = models.CharField(max_length=50, db_index=True)
    week_start = models.IntegerField()
    week_end = models.IntegerField()

    class Meta:
        indexes = [
            models.Index(fields=['week_start', 'week_end']),
        ]

    def __str__(self):
        return f"{self.name} (Week {self.week_start}-{self.week_end})"

class NutrientRequirement(models.Model):
    pregnancy_stage = models.ForeignKey(PregnancyStage, on_delete=models.CASCADE)
    nutrient_name = models.CharField(max_length=100, db_index=True)
    daily_value = models.FloatField()
    unit = models.CharField(max_length=20)

    class Meta:
        indexes = [
            models.Index(fields=['pregnancy_stage', 'nutrient_name']),
        ]

    def __str__(self):
        return f"{self.nutrient_name} for {self.pregnancy_stage}"

class Food(models.Model):
    name = models.CharField(max_length=200, unique=True, db_index=True)
    description = models.TextField()
    image_url = models.URLField(blank=True)
    nutritional_info = models.JSONField()
    
    def __str__(self):
        return self.name

class FoodLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    food = models.ForeignKey(Food, on_delete=models.CASCADE)
    date = models.DateField(db_index=True)
    portion = models.FloatField(validators=[MinValueValidator(0.1)])
    meal_type = models.CharField(max_length=20, choices=[
        ('breakfast', 'Breakfast'),
        ('lunch', 'Lunch'),
        ('dinner', 'Dinner'),
        ('snack', 'Snack')
    ])

    class Meta:
        indexes = [
            models.Index(fields=['user', 'date']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.food.name} on {self.date}"

class UserPregnancyProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    due_date = models.DateField()
    current_weight = models.FloatField()
    height = models.FloatField()
    pre_pregnancy_weight = models.FloatField()
    
    @property
    def bmi(self):
        return self.current_weight / ((self.height / 100) ** 2)
    
    @property
    def weight_gain(self):
        return self.current_weight - self.pre_pregnancy_weight

    @property
    def current_week(self):
        today = timezone.now().date()
        weeks = (self.due_date - today).days // 7
        return max(40 - weeks, 1)  # Ensure it's at least 1

    def get_pregnancy_stage(self):
        week = self.current_week
        cache_key = f'pregnancy_stage_{week}'
        stage = cache.get(cache_key)
        if not stage:
            stage = PregnancyStage.objects.get(week_start__lte=week, week_end__gte=week)
            cache.set(cache_key, stage, timeout=3600 * 24)  # Cache for 24 hours
        return stage

    def __str__(self):
        return f"Pregnancy Profile for {self.user.username}"

class FoodRecommendation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    food = models.ForeignKey(Food, on_delete=models.CASCADE)
    reason = models.TextField()
    priority = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(10)])
    date = models.DateField(db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'date']),
        ]

    def __str__(self):
        return f"Recommendation for {self.user.username}: {self.food.name}"

class FoodRating(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    food = models.ForeignKey(Food, on_delete=models.CASCADE)
    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True)
    pregnancy_week = models.IntegerField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)

    class Meta:
        unique_together = ('user', 'food')
        indexes = [
            models.Index(fields=['food', 'pregnancy_week']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.food.name} ({self.rating})"

class UserTrustScore(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    trust_score = models.FloatField(default=0.5)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - Trust Score: {self.trust_score}"

class NutritionDatabase(models.Model):
    food_name = models.CharField(max_length=200, unique=True, db_index=True)
    nutrition_data = models.JSONField()
    source = models.CharField(max_length=100)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.food_name} - Source: {self.source}"

class FoodRecognitionLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    image_url = models.URLField()
    recognized_food = models.CharField(max_length=200)
    confidence_score = models.FloatField()
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.recognized_food} on {self.date}"

class ResponseStyle(models.Model):
    name = models.CharField(max_length=50, unique=True)
    prompt = models.TextField()