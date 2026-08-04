from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.contrib import admin
from django.contrib import messages as admin_messages
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseRedirect
from django import forms
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, TabularInline 
from .models import RoomCategory, Room, Booking, RoomImage, Favorite, Conversation, Message
from .messaging import mark_messages_read
from .models import RatePlan, SeasonalPricing, Coupon


@admin.register(RatePlan)
class RatePlanAdmin(ModelAdmin):
    list_display = ('name', 'includes_breakfast', 'cancellation_policy', 'discount_percentage', 'is_active')

@admin.register(SeasonalPricing)
class SeasonalPricingAdmin(ModelAdmin):
    # Đổi price_multiplier thành percent_adjustment
    list_display = ('name', 'start_date', 'end_date', 'percent_adjustment', 'is_weekend_only')



@admin.register(Coupon)
class CouponAdmin(ModelAdmin):
    list_display = ('code', 'discount_type', 'discount_value', 'valid_to', 'is_active')

    
 
# 1. FORM TRUNG GIAN CHO BULK ACTION
 
class BulkRoomForm(forms.Form):
    room_numbers = forms.CharField(
        label="Danh sách số phòng",
        help_text="Nhập các số phòng muốn tạo, cách nhau bằng dấu phẩy (VD: P101, P102, P103)",
        widget=forms.Textarea(attrs={
            'class': 'border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 p-3 w-full rounded-md shadow-sm', 
            'rows': 5
        })
    )


 
# 2. ĐĂNG KÝ ROOM CATEGORY ADMIN
 
@admin.register(RoomCategory)
class RoomCategoryAdmin(ModelAdmin):
    actions = ['bulk_create_rooms']

    @admin.action(description='Thêm phòng hàng loạt cho Loại phòng này')
    
    # Hàm thêm nhiều phòng cùng lúc cho một loại phòng được chọn.
    def bulk_create_rooms(self, request, queryset):
        category = queryset.first()
        
        if 'apply' in request.POST:
            form = BulkRoomForm(request.POST)
            if form.is_valid():
                room_list = form.cleaned_data['room_numbers'].split(',')
                
                rooms_to_create = []
                for num in room_list:
                    num = num.strip()
                    if num:
                        rooms_to_create.append(
                            Room(
                                room_number=num, 
                                category=category, 
                                is_available=True, 
                                description=f"Phòng {num} thuộc loại {category.name}"
                            )
                        )
                
                Room.objects.bulk_create(rooms_to_create, ignore_conflicts=True)
                self.message_user(request, f"Đã tạo thành công {len(rooms_to_create)} phòng!")
                return HttpResponseRedirect(request.get_full_path())
        else:
            form = BulkRoomForm()

        context = {
            'form': form,
            'queryset': queryset,
            'title': f'Thêm nhiều phòng cho loại: {category.name}',
            'opts': self.model._meta,
            **self.admin_site.each_context(request)
        }
        return render(request, "admin/bulk_create_rooms.html", context)


 
# 3. ĐĂNG KÝ ROOM ADMIN (INLINE IMAGES)
 
 
# 3. ĐĂNG KÝ ROOM ADMIN (INLINE IMAGES)
 
class RoomImageInline(TabularInline):
    model = RoomImage
    extra = 0

@admin.register(Room)
class RoomAdmin(ModelAdmin):
    inlines = [RoomImageInline]
    # Thêm các cột hiển thị ra ngoài danh sách, đặc biệt là cột Cảnh báo
    list_display = ('room_number', 'category', 'is_available', 'housekeeping_status', 'canh_bao_tre_hen','thao_tac_dat_phong')
    list_filter = ('category', 'is_available', 'housekeeping_status')
    search_fields = ('room_number', 'category__name')
    
    # Hàm cảnh báo trễ hẹn check-in.
    def canh_bao_tre_hen(self, obj):
        # Lấy ngày hôm nay
        today = timezone.now().date()
        
        # Tìm xem phòng này có đơn nào đã Cọc, tới ngày nhận phòng rồi mà chưa Check-in không
        overdue_booking = Booking.objects.filter(
            room=obj,
            status='CONFIRMED',
            check_in__lte=today,
            is_active=True
        ).select_related('user').order_by('check_in').first()

        if overdue_booking:
            # Ưu tiên lấy SĐT khách nhập lúc đặt form, nếu không có thì lấy SDT trong Profile
            phone = overdue_booking.guest_phone
            if not phone:
                phone = overdue_booking.user.profile.phone_number if hasattr(overdue_booking.user, 'profile') else 'Chưa cập nhật'
            
            # Đường link gọi sang hàm xử lý Hủy bên BookingAdmin
            cancel_url = f"/admin/booking/booking/{overdue_booking.pk}/mark-no-show/"
            
            return format_html(
                '<div style="background:#fef2f2; border: 1px dashed #ef4444; padding:8px 12px; border-radius:6px; display:inline-block; min-width: 180px;">'
                '<strong style="color:#b91c1c; font-size: 13px; display:block; margin-bottom:4px;">⚠️ Khách có thể trễ hẹn</strong>'
                '<span style="font-size:12px; color:#7f1d1d; display:block;">📅 Nhận phòng: {}</span>'
                '<span style="font-size:12px; color:#7f1d1d; display:block;">📞 SĐT: <strong>{}</strong></span>'
                '<a href="{}" style="display:inline-block; margin-top:8px; background:#ef4444; color:white; padding:4px 10px; border-radius:4px; text-decoration:none; font-size:11px; font-weight: bold; width:100%; text-align:center;">Hủy quá hạn (No-Show)</a>'
                '</div>',
                overdue_booking.check_in.strftime('%d/%m/%Y'),
                phone,
                cancel_url
            )
        
        # Nếu phòng không có khách trễ, báo trạng thái bình thường
        if obj.is_available:
            return mark_safe('<span style="color:#10b981; font-weight:bold;">Trống - Sẵn sàng</span>')
        return mark_safe('<span style="color:#6b7280; font-weight:bold;">Đang có khách / Bảo trì</span>')
        
    canh_bao_tre_hen.short_description = "Kiểm soát Nhận phòng"
    
    #Hàm tạo nút "Tạo đơn ngay"
    def thao_tac_dat_phong(self, obj):
        # Chỉ hiện nút đặt phòng nếu phòng đang trống
        if obj.is_available:
            # Dùng reverse để trỏ tới trang "Thêm Đơn Đặt Phòng" mặc định của Django
            # Truyền thêm tham số ?room=id để hệ thống tự động chọn sẵn phòng này cho lễ tân
            add_url = reverse('admin:booking_booking_add') + f'?room={obj.pk}'
            return format_html(
                '<a href="{}" class="bg-blue-600 text-white px-3 py-1.5 rounded-md text-sm font-semibold hover:bg-blue-700 transition shadow-sm" style="text-decoration: none; display: inline-block;">'
                'Tạo đơn ngay'
                '</a>',
                add_url
            )
        return mark_safe('<span class="text-gray-400 font-medium italic">Đang sử dụng</span>')
    
    thao_tac_dat_phong.short_description = "Lễ tân thao tác"
    

    class Media:
        js = ('js/admin_preview.js',)

 
# 4. ĐĂNG KÝ BOOKING ADMIN
 
class CheckInForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = ['guest_full_name', 'guest_cccd', 'guest_phone']
        widgets = {
            'guest_full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Họ và tên khách'}),
            'guest_cccd': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Số CCCD / Passport'}),
            'guest_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Số điện thoại'}),
        }


@admin.register(Booking)
class BookingAdmin(ModelAdmin):
    list_display = ['id', 'user', 'room', 'check_in', 'check_out', 'total_price', 'trang_thai_don', 'thao_tac_nhanh']
    list_filter = ['status', 'cancellation_requested', 'is_active', 'check_in']
    search_fields = ['user__username', 'room__room_number']

    # Hàm điều chỉnh giao diện hiển thị trạng thái đơn.
    def trang_thai_don(self, obj):
        # Nếu đã hủy
        if not obj.is_active or obj.status == 'CANCELLED':
            return mark_safe('<span style="color: #ef4444; font-weight: bold;">Đã hủy</span>') 

        # Nếu khách đang báo yêu cầu hủy
        if obj.cancellation_requested:
            return mark_safe('<span style="color: #ef4444; font-weight: bold;">⚠️ Yêu cầu hủy</span>')

        status_label = obj.get_status_display()
        
        if obj.status == 'PENDING': color = '#f59e0b'
        elif obj.status == 'CONFIRMED': color = '#3b82f6'
        elif obj.status == 'CHECKED_IN': color = '#10b981'
        elif obj.status == 'CHECKED_OUT': color = '#6b7280'
        elif obj.status == 'EXPIRED': color = '#ef4444'
        else: color = '#000000'

        return mark_safe(f'<span style="color: {color}; font-weight: bold;">{status_label}</span>')
    trang_thai_don.short_description = 'Trạng thái'

    # Hàm tạo các nút thao tác nhanh (duyệt, hủy,...)
    def thao_tac_nhanh(self, obj):
        if not obj.is_active or obj.status == 'CANCELLED':
            return mark_safe('<span class="text-gray-400">-</span>')
            
        # Thêm nút Duyệt hủy nếu khách yêu cầu
        if obj.cancellation_requested:
            return format_html(
                '<a href="{}/confirm-cancel/" class="bg-red-600 text-white px-3 py-1 rounded-md text-sm font-semibold hover:bg-red-700 transition" style="text-decoration: none;">✅ Duyệt Hủy</a>',
                obj.pk
            )
            
        if obj.status == 'CONFIRMED':
            today = timezone.now().date()
            html = format_html(
                '<a href="{}/quick-check-in/" class="bg-green-600 text-white px-3 py-1 rounded-md text-sm font-semibold hover:bg-green-700 transition" style="text-decoration: none; display:inline-block; margin-bottom: 4px;">✅ Check-in</a>',
                obj.pk
            )
            # Tự động hiện thêm nút Hủy nếu đến ngày mà chưa tới
            if obj.check_in <= today:
                html += format_html(
                    '<br><a href="{}/mark-no-show/" class="bg-red-600 text-white px-3 py-1 rounded-md text-sm font-semibold hover:bg-red-700 transition" style="text-decoration: none; display:inline-block;">❌ Hủy (No-Show)</a>',
                    obj.pk
                )
            return html
        elif obj.status == 'CHECKED_IN':
            return format_html(
                '<a href="{}/quick-check-out/" class="bg-yellow-500 text-white px-3 py-1 rounded-md text-sm font-semibold hover:bg-yellow-600 transition" style="text-decoration: none;">🚪 Check-out</a>',
                obj.pk
            )
        return mark_safe('<span class="text-gray-400">-</span>')
    thao_tac_nhanh.short_description = 'Thao tác'

    # Hàm đăng ký thêm các đường dẫn (URLs).
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<int:booking_id>/quick-check-in/', self.admin_site.admin_view(self.process_quick_check_in), name='quick-check-in'),
            path('<int:booking_id>/quick-check-out/', self.admin_site.admin_view(self.process_quick_check_out), name='quick-check-out'),
            path('<int:booking_id>/confirm-cancel/', self.admin_site.admin_view(self.process_confirm_cancel), name='confirm-cancel'),
            path('<int:booking_id>/mark-no-show/', self.admin_site.admin_view(self.process_mark_no_show), name='mark-no-show'),
        ]
        return custom_urls + urls

    # Check-in nhanh
    def process_quick_check_in(self, request, booking_id):
        booking = self.get_object(request, str(booking_id))
        
        if request.method == 'POST':
            form = CheckInForm(request.POST, instance=booking)
            if form.is_valid() and booking.status == 'CONFIRMED' and not booking.cancellation_requested:
                booking = form.save()
                booking.status = 'CHECKED_IN'
                booking.actual_check_in = timezone.now()
                booking.save()
                
                booking.room.is_available = False
                booking.room.save()
                
                self.message_user(request, f"Đã Check-in đơn #{booking.id} - {booking.guest_full_name}", 
                                level=admin_messages.SUCCESS)
                return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/admin/'))
        else:
            form = CheckInForm(instance=booking)

        # Render form
        context = {
            'form': form,
            'booking': booking,
            'title': f'Check-in đơn #{booking.id}',
            **self.admin_site.each_context(request)
        }
        return render(request, 'admin/booking_checkin.html', context)

    # Check-out nhanh
    def process_quick_check_out(self, request, booking_id):
        booking = self.get_object(request, str(booking_id))
        if booking and booking.status == 'CHECKED_IN':
            booking.status = 'CHECKED_OUT'
            booking.actual_check_out = timezone.now()
            booking.save()
            booking.room.is_available = True
            booking.room.save()
            
            try:
                tieu_de = 'Cảm ơn bạn đã lưu trú tại ZagoHaven'
                
                # Tạo một biến định dạng lại tiền tệ thành dấu chấm
                total_price_formatted = f"{booking.total_price:,.0f}".replace(',', '.')
                
                noi_dung = f"""Chào {booking.user.username},

Cảm ơn bạn đã lựa chọn lưu trú tại phòng {booking.room.room_number}.
Tổng chi phí cho kỳ nghỉ của bạn là {total_price_formatted} VNĐ.

Hy vọng bạn đã có trải nghiệm tuyệt vời. Xin vui lòng để lại đánh giá để chúng tôi phục vụ tốt hơn vào lần sau!"""
                send_mail(tieu_de, noi_dung, settings.EMAIL_HOST_USER, [booking.user.email], fail_silently=False)
            except Exception as e:
                print(f"Lỗi gửi mail check-out: {e}")
            
            self.message_user(request, f"Đã Check-out đơn #{booking.id}", level=admin_messages.SUCCESS)
        else:
            self.message_user(request, "Không thể Check-out. Đơn phải đang ở trạng thái Khách đang ở.", 
                            level=admin_messages.ERROR)
        return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/admin/'))
    
    # Duyệt hủy đơn
    def process_confirm_cancel(self, request, booking_id):
        booking = self.get_object(request, str(booking_id))
        if booking and booking.cancellation_requested:
            booking.status = 'CANCELLED'
            booking.is_active = False
            booking.cancellation_requested = False
            booking.save()
            # Đảm bảo phòng được trả lại trạng thái trống
            booking.room.is_available = True
            booking.room.save()
            
            try:
                tieu_de = 'Xác nhận hủy phòng thành công - ZagoHaven'
                noi_dung = f"Chào {booking.user.username},\n\nHệ thống đã duyệt yêu cầu hủy phòng thành công cho đơn #{booking.id} (Phòng {booking.room.room_number}).\nChúng tôi sẽ tiến hành xử lý hoàn tiền theo chính sách (nếu có).\nHẹn gặp lại bạn trong tương lai!"
                send_mail(tieu_de, noi_dung, settings.EMAIL_HOST_USER, [booking.user.email], fail_silently=False)
            except Exception as e:
                print(f"Lỗi gửi mail duyệt hủy: {e}")
            
            self.message_user(request, f"Đã duyệt hủy đơn #{booking.id}", level=admin_messages.SUCCESS)
        else:
            # THÊM THÔNG BÁO LỖI Ở ĐÂY
            self.message_user(request, f"Không thể hủy! Đơn #{booking_id} không có yêu cầu hủy hoặc đã thay đổi trạng thái.", level=admin_messages.ERROR)
        return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/admin/'))
    
    # Xử lý khách không đến nhận phòng (No-Show)
    def process_mark_no_show(self, request, booking_id):
        booking = self.get_object(request, str(booking_id))
        
        if booking and booking.status == 'CONFIRMED':
            # 1. Ép trạng thái về EXPIRED (Quá hạn)
            booking.status = 'EXPIRED'
            booking.is_active = False
            booking.save()
            
            # 2. Nhả phòng trống cho Lễ tân bán tiếp
            booking.room.is_available = True
            booking.room.save()
            
            # 3. Gửi Email thông báo xử lý No-show cho khách
            try:
                tieu_de = 'Thông báo hủy phòng do quá hạn (No-Show) - ZagoHaven'
                noi_dung = f"Chào {booking.user.username},\n\nĐơn đặt phòng #{booking.id} (Phòng {booking.room.room_number}) của bạn đã bị hủy do quá thời gian nhận phòng.\n\nVì chúng tôi không thể liên lạc được với bạn, hệ thống đã tự động áp dụng chính sách xử lý tiền cọc của Gói dịch vụ bạn đã chọn.\nNếu có thắc mắc, vui lòng liên hệ Hotline Lễ tân ZagoHaven.\n\nTrân trọng."
                send_mail(tieu_de, noi_dung, settings.EMAIL_HOST_USER, [booking.user.email], fail_silently=False)
            except Exception as e:
                print(f"Lỗi gửi mail No-show: {e}")
            
            self.message_user(request, f"Đã đánh dấu vắng mặt (No-Show) cho đơn #{booking.id} và nhả phòng {booking.room.room_number}.", level=admin_messages.SUCCESS)
        else:
            self.message_user(request, f"Không thể xử lý! Đơn không hợp lệ.", level=admin_messages.ERROR)
            
        # Quay lại trang Admin mà lễ tân vừa đứng (Bảng phòng hoặc Bảng Booking)
        return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/admin/'))
    @admin.action(description='✅ Check-in (Nhận phòng) cho các đơn đã chọn')
    
    # Check-in hàng loạt
    def check_in_booking(self, request, queryset):
        valid_bookings = queryset.filter(status='CONFIRMED', is_active=True, cancellation_requested=False)
        count = valid_bookings.count()

        if count == 0:
            self.message_user(
                request,
                "Không có đơn nào hợp lệ để Check-in. Chỉ chấp nhận đơn 'Đã cọc (Giữ phòng)', chưa hủy và chưa yêu cầu hủy.",
                level=admin_messages.WARNING
            )
            return

        now = timezone.now()
        for booking in valid_bookings:
            booking.status = 'CHECKED_IN'
            booking.actual_check_in = now
            booking.save()
            
            # Cập nhật phòng
            booking.room.is_available = False
            booking.room.save()

        skipped = queryset.count() - count
        msg = f"Đã Check-in thành công {count} đơn."
        if skipped:
            msg += f" (Bỏ qua {skipped} đơn không đủ điều kiện.)"
        self.message_user(request, msg, level=admin_messages.SUCCESS)

    @admin.action(description='🚪 Check-out (Trả phòng) cho các đơn đã chọn')
    
    # Check-out hàng loạt
    def check_out_booking(self, request, queryset):
        valid_bookings = queryset.filter(status='CHECKED_IN', is_active=True)
        count = valid_bookings.count()

        if count == 0:
            self.message_user(
                request,
                "Không có đơn nào hợp lệ để Check-out. Chỉ chấp nhận đơn đang ở trạng thái 'Khách đang ở'.",
                level=admin_messages.WARNING
            )
            return

        now = timezone.now()
        for booking in valid_bookings:
            booking.status = 'CHECKED_OUT'
            booking.actual_check_out = now
            booking.save()
            
            # Trả phòng
            booking.room.is_available = True
            booking.room.save()

        skipped = queryset.count() - count
        msg = f"Đã Check-out thành công {count} đơn."
        if skipped:
            msg += f" (Bỏ qua {skipped} đơn không đủ điều kiện.)"
        self.message_user(request, msg, level=admin_messages.SUCCESS)


@admin.register(Favorite)
class FavoriteAdmin(ModelAdmin):
    list_display = ('user', 'room', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'room__room_number')
    readonly_fields = ('created_at',)


class MessageInline(TabularInline):
    model = Message
    extra = 0
    readonly_fields = ('sender', 'content', 'created_at', 'is_read')
    can_delete = False

    # Chặn quyền thêm tin nhắn mới trực tiếp từ giao diện( bắt buộc dùng giao diện chat)
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Conversation)
class ConversationAdmin(ModelAdmin):
    list_display = ('subject', 'customer', 'booking', 'is_closed', 'updated_at', 'unread_from_customer', 'thao_tac_nhanh')
    list_filter = ('is_closed', 'created_at')
    search_fields = ('subject', 'customer__username', 'customer__email')
    readonly_fields = ('customer', 'booking', 'subject', 'created_at', 'updated_at')
    fields = ('subject', 'customer', 'booking', 'is_closed', 'created_at', 'updated_at')

    # Chặn quyền admin tự tạo hội thoại mới
    def has_add_permission(self, request):
        return False

    # Thêm đường dẫn cho trang chat
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:conversation_id>/reply/',
                self.admin_site.admin_view(self.process_reply),
                name='conversation-reply',
            ),
        ]
        return custom_urls + urls

    # Logic giao diện chat
    def process_reply(self, request, conversation_id):
        conversation = get_object_or_404(
            Conversation.objects.select_related('customer', 'booking', 'booking__room'),
            id=conversation_id,
        )

        if request.method == 'POST':
            action = request.POST.get('action', 'reply')
            if action == 'close':
                conversation.is_closed = True
                conversation.save(update_fields=['is_closed'])
                self.message_user(request, f'Đã đóng cuộc hội thoại "{conversation.subject}".', level=admin_messages.SUCCESS)
                return HttpResponseRedirect(reverse('admin:booking_conversation_changelist'))

            content = request.POST.get('content', '').strip()
            if not content:
                self.message_user(request, 'Nội dung tin nhắn không được để trống.', level=admin_messages.ERROR)
            elif conversation.is_closed:
                self.message_user(request, 'Cuộc hội thoại đã được đóng.', level=admin_messages.ERROR)
            else:
                Message.objects.create(
                    conversation=conversation,
                    sender=request.user,
                    content=content,
                )
                conversation.updated_at = timezone.now()
                conversation.save(update_fields=['updated_at'])
                self.message_user(request, 'Đã gửi tin nhắn cho khách hàng.', level=admin_messages.SUCCESS)
                return HttpResponseRedirect(
                    reverse('admin:conversation-reply', args=[conversation.id])
                )

        mark_messages_read(conversation, request.user)
        thread_messages = conversation.messages.select_related('sender').all()

        context = {
            'conversation': conversation,
            'thread_messages': thread_messages,
            'title': f'Trả lời: {conversation.subject}',
            'opts': self.model._meta,
            **self.admin_site.each_context(request),
        }
        return render(request, 'admin/conversation_chat.html', context)

    # Hàm tạo nút trả lời tin nhắn nhanh
    def thao_tac_nhanh(self, obj):
        url = reverse('admin:conversation-reply', args=[obj.pk])
        unread = obj.messages.filter(is_read=False, sender__is_staff=False).count()
        label = f'Trả lời ({unread})' if unread else 'Trả lời'
        btn_color = '#dc2626' if unread else '#2563eb'
        return format_html(
            '<a href="{}" style="background:{};color:white;padding:4px 12px;border-radius:6px;text-decoration:none;font-size:0.85rem;font-weight:600;">{}</a>',
            url, btn_color, label,
        )
    thao_tac_nhanh.short_description = 'Thao tác'

    # Đếm số lượng tin nhắn mới từ khách hàng
    def unread_from_customer(self, obj):
        count = obj.messages.filter(is_read=False, sender__is_staff=False).count()
        if count:
            return format_html('<span style="color:#ef4444;font-weight:bold;">{} tin chưa đọc</span>', count)
        return mark_safe('<span style="color:#94a3b8;">-</span>')
    unread_from_customer.short_description = 'Chưa đọc'


@admin.register(Message)
class MessageAdmin(ModelAdmin):
    list_display = ('conversation', 'sender', 'content_preview', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at', 'sender__is_staff')
    search_fields = ('content', 'sender__username', 'conversation__subject')
    readonly_fields = ('conversation', 'sender', 'content', 'created_at', 'is_read')

    # Chặn quyền tạo tin nhắn mới lẻ tẻ từ trang quản lý.
    def has_add_permission(self, request):
        return False

    # Chặn chỉnh sửa nội dung tn
    def has_change_permission(self, request, obj=None):
        return False

    # Cắt ngắn nội dung tin nhắn để hiển thị gọn.
    def content_preview(self, obj):
        return obj.content[:80] + ('...' if len(obj.content) > 80 else '')
    content_preview.short_description = 'Nội dung'