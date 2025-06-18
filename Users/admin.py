from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import CustomUser, LoginHistory, EmailVerification

class LoginHistoryInline(admin.TabularInline):
    model = LoginHistory
    extra = 0
    readonly_fields = ('login_time', 'ip_address', 'user_agent', 'success', 'location')
    can_delete = False

@admin.action(description='Lock selected users')
def lock_users(modeladmin, request, queryset):
    queryset.update(is_locked=True)

@admin.action(description='Unlock selected users')
def unlock_users(modeladmin, request, queryset):
    queryset.update(is_locked=False)

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('username', 'email', 'phone_number', 'is_active', 'is_locked', 'last_login', 'failed_login_attempts', 'last_password_change', 'is_2fa_enabled', 'preferred_speaking_style')
    list_filter = ('is_active', 'is_staff', 'is_locked', 'date_joined', 'preferred_speaking_style')
    search_fields = ('username', 'email', 'phone_number', 'social_id', 'preferred_speaking_style')
    ordering = ('date_joined',)
    readonly_fields = ('unique_id', 'last_login', 'date_joined', 'last_password_change')
    actions = [lock_users, unlock_users]
    inlines = [LoginHistoryInline]

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('unique_id', 'email', 'phone_number', 'first_name', 'last_name', 'service_agreement', 'privacy_agreement', 'promotion_agreement','preferred_speaking_style')}),
        ('Social info', {'fields': ('social_type', 'social_id')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined', 'last_password_change')}),
        ('Account security', {'fields': ('failed_login_attempts', 'is_locked', 'security_question', 'security_answer')}),
        ('Two-factor Authentication', {'fields': ('is_2fa_enabled', 'otp_secret')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'phone_number', 'password1', 'password2', 'service_agreement', 'privacy_agreement', 'preferred_speaking_style'),
        }),
    )

    def user_actions(self, obj):
        return format_html(
            '<a class="button" href="{}">Lock</a>&nbsp;'
            '<a class="button" href="{}">Unlock</a>',
            f'/admin/app_name/customuser/{obj.id}/lock/',
            f'/admin/app_name/customuser/{obj.id}/unlock/'
        )
    user_actions.short_description = 'Actions'
    user_actions.allow_tags = True

class LoginHistoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'login_time', 'ip_address', 'user_agent', 'success', 'location')
    list_filter = ('success', 'login_time', 'location')
    search_fields = ('user__username', 'ip_address', 'user_agent', 'location')
    ordering = ('-login_time',)
    readonly_fields = ('user', 'login_time', 'ip_address', 'user_agent', 'success', 'location')

class EmailVerificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'code', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'user__email', 'code')
    ordering = ('-created_at',)
    readonly_fields = ('user', 'code', 'created_at')

admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(LoginHistory, LoginHistoryAdmin)
admin.site.register(EmailVerification, EmailVerificationAdmin)
