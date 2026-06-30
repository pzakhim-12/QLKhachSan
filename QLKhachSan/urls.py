"""
URL configuration for QLKhachSan project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from booking import views

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Thiết lập trang danh sách phòng làm Trang Chủ
    path('', views.room_list, name='room_list'),

    # Thêm dòng này: Link đặt phòng sẽ có dạng /book/1/, /book/2/ (tương ứng với ID phòng)
    path('book/<int:room_id>/', views.book_room, name='book_room'),

    path('room/<int:room_id>/', views.room_detail, name='room_detail'),

    path('login/', views.login_user, name='login'),

    path('logout/', views.logout_user, name='logout'),

    path('register/', views.register_user, name='register'),

    path('accounts/', include('allauth.urls')),

    path('profile/', views.user_profile, name='user_profile'),

    path('cancel-booking/<int:booking_id>/', views.cancel_booking, name='cancel_booking'),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

