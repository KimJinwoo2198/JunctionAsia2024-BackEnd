from collections import defaultdict
from .models import NutrientRequirement, Food, FoodRecommendation

def analyze_nutrients(food_logs):
    nutrient_totals = defaultdict(float)
    for log in food_logs:
        food = log.food
        for nutrient, amount in food.nutritional_info.items():
            nutrient_totals[nutrient] += amount * log.portion

    # Placeholder for getting nutrient requirements (should be based on pregnancy stage)
    requirements = NutrientRequirement.objects.all()
    analysis = {}
    for req in requirements:
        if req.nutrient_name in nutrient_totals:
            consumed = nutrient_totals[req.nutrient_name]
            analysis[req.nutrient_name] = {
                "consumed": consumed,
                "required": req.daily_value,
                "unit": req.unit,
                "percentage": (consumed / req.daily_value) * 100 if req.daily_value > 0 else 0
            }

    return analysis

def get_personalized_recommendations(profile, food_logs):
    # Placeholder logic for personalized recommendations
    # In a real implementation, this would involve more complex analysis
    consumed_nutrients = analyze_nutrients(food_logs)
    deficient_nutrients = [
        nutrient for nutrient, data in consumed_nutrients.items()
        if data['percentage'] < 70  # Assuming below 70% is deficient
    ]

    recommended_foods = Food.objects.filter(
        nutritional_info__has_any_keys=deficient_nutrients
    )[:5]  # Limit to 5 recommendations for MVP

    recommendations = []
    for food in recommended_foods:
        recommendation = FoodRecommendation.objects.create(
            user=profile.user,
            food=food,
            reason=f"Rich in {', '.join(deficient_nutrients)}",
            priority=5,  # Placeholder priority
            date=profile.due_date  # Using due_date as a placeholder
        )
        recommendations.append(recommendation)

    return recommendations