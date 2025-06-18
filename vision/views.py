from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from datetime import timedelta
import base64
from django.core.cache import cache
from django.db.models import Prefetch, Avg
from .models import Food, FoodLog, UserPregnancyProfile, FoodRecommendation, FoodRecognitionLog, FoodRating, ResponseStyle
from django.contrib.auth import get_user_model
from .serializers import (
    FoodSerializer, FoodLogSerializer, UserPregnancyProfileSerializer, 
    FoodRecommendationSerializer, FoodRecognitionLogSerializer, FoodRatingSerializer, ResponseStyleSerializer
)
from .food_recognition import process_food_image
from .nutrient_analysis import analyze_nutrients, get_personalized_recommendations
from .rag_utils import get_food_safety_info, get_nutritional_advice
from django.conf import settings

from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
import logging

logger = logging.getLogger(__name__)
CustomUser = get_user_model()

class FoodViewSet(viewsets.ModelViewSet):
    queryset = Food.objects.all()
    serializer_class = FoodSerializer

    @swagger_auto_schema(
        operation_summary="음식 목록 조회 및 생성",
        operation_description="모든 음식 항목을 나열하거나 새로운 음식 항목을 생성합니다. 이 엔드포인트는 임신 중 섭취 가능한 모든 음식 정보를 관리하는 데 사용됩니다.",
        responses={
            200: openapi.Response(
                description="성공적으로 음식 목록을 반환했습니다.",
                schema=FoodSerializer(many=True)
            ),
            201: openapi.Response(
                description="새로운 음식 항목이 성공적으로 생성되었습니다.",
                schema=FoodSerializer()
            ),
            400: "잘못된 요청: 제공된 데이터가 유효하지 않습니다."
        }
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="특정 음식 상세 정보 조회",
        operation_description="지정된 ID를 가진 특정 음식 항목의 상세 정보를 조회합니다. 이 정보는 음식의 영양 성분, 설명, 이미지 URL 등을 포함합니다.",
        responses={
            200: openapi.Response(
                description="성공적으로 음식 정보를 반환했습니다.",
                schema=FoodSerializer()
            ),
            404: "음식을 찾을 수 없음: 지정된 ID의 음식이 존재하지 않습니다."
        }
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        method='post',
        operation_summary="이미지로 음식 인식 및 안전 정보 제공",
        operation_description="사용자가 제공한 Base64 인코딩된 이미지에서 음식을 인식하고, 해당 음식의 임신 중 섭취 안전성 및 영양 정보를 제공합니다.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['image'],
            properties={
                'image': openapi.Schema(type=openapi.TYPE_STRING, description="Base64로 인코딩된 이미지 데이터")
            },
        ),
        responses={
            200: openapi.Response(
                description="성공적으로 음식을 인식하고 관련 정보를 반환했습니다.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'food_name': openapi.Schema(type=openapi.TYPE_STRING, description="인식된 음식의 이름"),
                        'is_safe': openapi.Schema(type=openapi.TYPE_BOOLEAN, description="임신 중 섭취 안전 여부"),
                        'safety_info': openapi.Schema(type=openapi.TYPE_STRING, description="임신 중 섭취에 대한 안전 정보"),
                        'nutritional_advice': openapi.Schema(type=openapi.TYPE_STRING, description="임신 단계별 영양 조언"),
                    }
                )
            ),
            400: "잘못된 요청: 이미지가 제공되지 않았거나 형식이 올바르지 않습니다.",
            404: "음식 인식 실패: 이미지에서 음식을 인식할 수 없습니다.",
            500: "서버 오류: 음식 인식 또는 정보 검색 중 오류가 발생했습니다."
        }
    )
    @action(detail=False, methods=['post'])
    def recognize(self, request):
        user = request.user
        style_name = user.preferred_speaking_style if user.preferred_speaking_style else '표준어'
        try:
            response_style = ResponseStyle.objects.get(name=style_name)
        except ResponseStyle.DoesNotExist:
            response_style = ResponseStyle.objects.get(name='표준어')
        
        image_data = request.data.get('image')

        if not image_data:
            return Response({"error": "이미지가 제공되지 않았습니다."}, status=status.HTTP_400_BAD_REQUEST)
        
        logger.debug(f"Received image data length: {len(image_data)}")
        
        try:
            # Base64 접두사 제거 (만약 포함되어 있다면)
            if 'base64,' in image_data:
                image_data = image_data.split('base64,')[1]
            
            logger.debug(f"Base64 data length after prefix removal: {len(image_data)}")
            
            # 음식 인식 처리 (Base64 인코딩된 이미지 데이터를 직접 전달)
            result = process_food_image(image_data, request.user.id)
            
            if not isinstance(result, dict):
                logger.error(f"Unexpected result type from process_food_image: {type(result)}")
                return Response({"error": "음식 인식 처리 중 예기치 않은 오류가 발생했습니다."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            if 'error' in result:
                logger.error(f"Food recognition error: {result['error']}")
                return Response({"error": result['error']}, status=status.HTTP_400_BAD_REQUEST)
            
            if result.get('food_name') == "Unknown":
                return Response({"error": "음식을 인식할 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)
            
            # 안전 정보 및 영양 조언 추가
            try:
                result['safety_info'] = get_food_safety_info(result['food_name'], response_style)
            except Exception as e:
                logger.error(f"Error getting safety info: {str(e)}")
                result['safety_info'] = "안전 정보를 가져오는 중 오류가 발생했습니다."

            try:
                result['nutritional_advice'] = get_nutritional_advice(result['food_name'], request.user, response_style)
            except Exception as e:
                logger.error(f"Error getting nutritional advice: {str(e)}")
                result['nutritional_advice'] = "영양 조언을 가져오는 중 오류가 발생했습니다."
            
            return Response(result)
        
        except Exception as e:
            logger.exception("Unexpected error in recognize method")
            return Response({"error": f"처리 중 오류가 발생했습니다: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @swagger_auto_schema(
        method='get',
        operation_summary="특정 음식의 안전 정보 조회",
        operation_description="지정된 음식에 대한 임신 중 섭취 안전 정보를 상세히 제공합니다. 이 정보는 최신 의학 연구와 권고사항을 바탕으로 생성됩니다.",
        responses={
            200: openapi.Response(
                description="성공적으로 음식 안전 정보를 반환했습니다.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'food_name': openapi.Schema(type=openapi.TYPE_STRING, description="음식 이름"),
                        'safety_info': openapi.Schema(type=openapi.TYPE_STRING, description="상세한 안전 정보"),
                    }
                )
            ),
            404: "음식을 찾을 수 없음: 지정된 ID의 음식이 존재하지 않습니다."
        }
    )
    @action(detail=True, methods=['get'])
    def safety_info(self, request, pk=None):
        food = self.get_object()
        safety_info = get_food_safety_info(food.name)
        return Response({"food_name": food.name, "safety_info": safety_info})

class FoodLogViewSet(viewsets.ModelViewSet):
    serializer_class = FoodLogSerializer

    def get_queryset(self):
        return FoodLog.objects.filter(user=self.request.user).select_related('food')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @swagger_auto_schema(
        method='get',
        operation_summary="사용자의 영양 섭취 분석",
        operation_description="사용자의 최근 7일간 음식 섭취 기록을 바탕으로 영양 분석을 제공합니다. 이 분석은 임신 중 필요한 주요 영양소의 섭취량과 권장량을 비교하여 보여줍니다.",
        responses={
            200: openapi.Response(
                description="성공적으로 영양 분석 결과를 반환했습니다.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'nutrient_name': openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                'consumed': openapi.Schema(type=openapi.TYPE_NUMBER, description="섭취량"),
                                'required': openapi.Schema(type=openapi.TYPE_NUMBER, description="권장 섭취량"),
                                'unit': openapi.Schema(type=openapi.TYPE_STRING, description="단위"),
                                'percentage': openapi.Schema(type=openapi.TYPE_NUMBER, description="권장량 대비 섭취 비율(%)"),
                            }
                        )
                    }
                )
            )
        }
    )
    @action(detail=False, methods=['get'])
    def nutrient_analysis(self, request):
        start_date = timezone.now().date() - timedelta(days=7)
        cache_key = f'nutrient_analysis_{request.user.id}_{start_date}_{timezone.now().date()}'
        analysis = cache.get(cache_key)
        if not analysis:
            food_logs = self.get_queryset().filter(date__gte=start_date)
            analysis = analyze_nutrients(food_logs)
            cache.set(cache_key, analysis, timeout=3600)  # 1시간 동안 캐시
        return Response(analysis)

class UserPregnancyProfileViewSet(viewsets.ModelViewSet):
    serializer_class = UserPregnancyProfileSerializer

    @swagger_auto_schema(
        operation_summary="임신 프로필 조회 및 생성",
        operation_description="사용자의 임신 관련 정보를 조회하거나 새로운 프로필을 생성합니다. 이 정보는 개인화된 영양 권장사항을 제공하는 데 사용됩니다.",
        responses={
            200: UserPregnancyProfileSerializer(),
            201: UserPregnancyProfileSerializer(),
            400: "잘못된 요청: 제공된 데이터가 유효하지 않습니다."
        }
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        return UserPregnancyProfile.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class FoodRecommendationViewSet(viewsets.ModelViewSet):
    serializer_class = FoodRecommendationSerializer

    def get_queryset(self):
        return FoodRecommendation.objects.filter(user=self.request.user).select_related('food')

    @swagger_auto_schema(
        method='get',
        operation_summary="개인화된 음식 추천",
        operation_description="사용자의 임신 프로필과 최근 식단을 바탕으로 개인화된 음식 추천을 제공합니다. 이 추천은 사용자의 영양 요구사항과 선호도를 고려합니다.",
        responses={
            200: openapi.Response(
                description="성공적으로 개인화된 음식 추천을 반환했습니다.",
                schema=FoodRecommendationSerializer(many=True)
            )
        }
    )
    @action(detail=False, methods=['get'])
    def personalized(self, request):
        cache_key = f'personalized_recommendations_{request.user.id}_{timezone.now().date()}'
        recommendations = cache.get(cache_key)
        if not recommendations:
            profile = UserPregnancyProfile.objects.get(user=request.user)
            food_logs = FoodLog.objects.filter(
                user=request.user, 
                date__gte=timezone.now().date() - timedelta(days=7)
            ).select_related('food')
            recommendations = get_personalized_recommendations(profile, food_logs)
            cache.set(cache_key, recommendations, timeout=3600)  # 1시간 동안 캐시
        serializer = self.get_serializer(recommendations, many=True)
        return Response(serializer.data)

class FoodRecognitionLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FoodRecognitionLogSerializer

    @swagger_auto_schema(
        operation_summary="음식 인식 로그 조회",
        operation_description="사용자의 음식 인식 기록을 조회합니다. 이 로그는 사용자가 이전에 인식한 음식들의 기록을 보여줍니다.",
        responses={
            200: FoodRecognitionLogSerializer(many=True)
        }
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        return FoodRecognitionLog.objects.filter(user=self.request.user)

class FoodRatingViewSet(viewsets.ModelViewSet):
    serializer_class = FoodRatingSerializer

    def get_queryset(self):
        return FoodRating.objects.filter(user=self.request.user).select_related('food')

    @swagger_auto_schema(
        operation_summary="음식 평가 조회 및 생성",
        operation_description="사용자의 음식 평가를 조회하거나 새로운 평가를 생성합니다. 이 기능은 사용자들의 음식 선호도와 경험을 공유하는 데 사용됩니다.",
        responses={
            200: openapi.Response(
                description="성공적으로 음식 평가 목록을 반환했습니다.",
                schema=FoodRatingSerializer(many=True)
            ),
            201: openapi.Response(
                description="새로운 음식 평가가 성공적으로 생성되었습니다.",
                schema=FoodRatingSerializer()
            ),
            400: "잘못된 요청: 제공된 데이터가 유효하지 않습니다."
        }
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="특정 음식 평가 상세 조회",
        operation_description="지정된 ID를 가진 특정 음식 평가의 상세 정보를 조회합니다. 이는 개별 평가의 세부 내용을 확인하는 데 사용됩니다.",
        responses={
            200: openapi.Response(
                description="성공적으로 음식 평가 정보를 반환했습니다.",
                schema=FoodRatingSerializer()
            ),
            404: "평가를 찾을 수 없음: 지정된 ID의 음식 평가가 존재하지 않습니다."
        }
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="새로운 음식 평가 생성",
        operation_description="새로운 음식 평가를 생성합니다. 사용자는 음식에 대한 평점과 코멘트를 제공할 수 있습니다.",
        request_body=FoodRatingSerializer,
        responses={
            201: openapi.Response(
                description="음식 평가가 성공적으로 생성되었습니다.",
                schema=FoodRatingSerializer()
            ),
            400: "잘못된 요청: 제공된 데이터가 유효하지 않습니다."
        }
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @swagger_auto_schema(
        method='get',
        operation_summary="음식 평가 요약 조회",
        operation_description="특정 음식에 대한 평가 요약을 제공합니다. 이 요약에는 평균 평점, 총 평가 수, 긍정적/부정적 평가 비율 등이 포함됩니다.",
        manual_parameters=[
            openapi.Parameter('food_id', openapi.IN_QUERY, description="평가를 요약할 음식의 ID", type=openapi.TYPE_INTEGER, required=True),
        ],
        responses={
            200: openapi.Response(
                description="성공적으로 음식 평가 요약을 반환했습니다.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'average_rating': openapi.Schema(type=openapi.TYPE_NUMBER, description="평균 평점"),
                        'total_ratings': openapi.Schema(type=openapi.TYPE_INTEGER, description="총 평가 수"),
                        'positive_percentage': openapi.Schema(type=openapi.TYPE_NUMBER, description="긍정적 평가 비율 (%)"),
                        'negative_percentage': openapi.Schema(type=openapi.TYPE_NUMBER, description="부정적 평가 비율 (%)"),
                    }
                )
            ),
            400: "잘못된 요청: 음식 ID가 제공되지 않았습니다.",
            404: "음식을 찾을 수 없음: 지정된 ID의 음식이 존재하지 않습니다."
        }
    )
    @action(detail=False, methods=['get'])
    def food_ratings_summary(self, request):
        food_id = request.query_params.get('food_id')
        if not food_id:
            return Response({"error": "음식 ID가 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            food = Food.objects.get(id=food_id)
        except Food.DoesNotExist:
            return Response({"error": "지정된 ID의 음식을 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        ratings = FoodRating.objects.filter(food_id=food_id)
        avg_rating = ratings.aggregate(Avg('rating'))['rating__avg']
        total_ratings = ratings.count()
        positive_ratings = ratings.filter(rating__gte=4).count()
        negative_ratings = ratings.filter(rating__lte=2).count()

        return Response({
            "food_name": food.name,
            "average_rating": round(avg_rating, 2) if avg_rating else 0,
            "total_ratings": total_ratings,
            "positive_percentage": round((positive_ratings / total_ratings) * 100, 2) if total_ratings > 0 else 0,
            "negative_percentage": round((negative_ratings / total_ratings) * 100, 2) if total_ratings > 0 else 0,
        })
        
class UserStyleViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def list_styles(self, request):
        styles = ResponseStyle.objects.all()
        serializer = ResponseStyleSerializer(styles, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def set_preferred_style(self, request):
        style_name = request.data.get('style')
        if not style_name:
            return Response({'error': '스타일 이름이 필요합니다.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            style = ResponseStyle.objects.get(name=style_name)
        except ResponseStyle.DoesNotExist:
            return Response({'error': '해당 스타일을 찾을 수 없습니다.'}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        user.preferred_style = style.name  # Assuming preferred_style is a CharField in CustomUser model
        user.save()

        return Response({'message': '선호 스타일이 설정되었습니다.'})
