from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from booking import views as booking_views

urlpatterns = [
    # ADMIN ROUTES
    path('admin/dashboard-reports/', booking_views.hotel_dashboard_reports, name='admin_dashboard_reports'),
    path('admin/room-map/', booking_views.admin_room_map_view, name='admin_room_map'), # ROUTE SƠ ĐỒ PHÒNG
    path('admin/', admin.site.urls),
    
    # PUBLIC ROUTES
    path('', booking_views.room_list, name='room_list'),
    path('room/<int:room_id>/', booking_views.room_detail, name='room_detail'),
    path('book/<int:room_id>/', booking_views.book_room, name='book_room'),
    
    # AUTH ROUTES
    path('login/', booking_views.login_user, name='login'),
    path('logout/', booking_views.logout_user, name='logout'),
    path('register/', booking_views.register_user, name='register'),
    path('accounts/', include('allauth.urls')),
    
    # PROFILE & USER ACTIONS
    path('profile/', booking_views.user_profile, name='user_profile'),
    path('favorites/', booking_views.favorite_list, name='favorite_list'),
    path('favorites/toggle/<int:room_id>/', booking_views.toggle_favorite, name='toggle_favorite'),
    path('cancel-booking/<int:booking_id>/', booking_views.cancel_booking, name='cancel_booking'),
    
    # MESSAGING
    path('messages/', booking_views.message_inbox, name='message_inbox'),
    path('messages/new/', booking_views.new_conversation, name='new_conversation'),
    path('messages/<int:conversation_id>/', booking_views.message_thread, name='message_thread'),
    path('messages/<int:conversation_id>/poll/', booking_views.message_poll, name='message_poll'),

    # PAYMENT & API
    path('payment/create/<int:booking_id>/', booking_views.create_payment, name='create_payment'),
    path('payment/vnpay-return/', booking_views.payment_return, name='payment_return'),
    path('api/calculate-price/', booking_views.calculate_price_api, name='calculate_price_api'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)