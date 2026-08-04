from django.utils import timezone
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

# 1. Bảng Loại Phòng
class RoomCategory(models.Model):
    name = models.CharField(max_length=50) 
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2)
    capacity = models.IntegerField(default=2)
    def get_current_season_alert(self):
        
        
        today = timezone.now().date()
        # Lọc các cấu hình giá đang bao trùm ngày hôm nay
        active_seasons = SeasonalPricing.objects.filter(
            start_date__lte=today,
            end_date__gte=today
        )
        
        # Nếu không phải cuối tuần, bỏ qua các mùa "chỉ áp dụng cuối tuần"
        is_weekend = today.weekday() in [4, 5, 6]
        if not is_weekend:
            active_seasons = active_seasons.filter(is_weekend_only=False)
            
        active_season = active_seasons.first()
        
        if active_season:
            percent = float(active_season.percent_adjustment)
            
            # Xử lý định dạng ngày tháng (dd/mm/yyyy)
            start_str = active_season.start_date.strftime('%d/%m/%Y')
            end_str = active_season.end_date.strftime('%d/%m/%Y')
            
            if start_str == end_str:
                date_range = f"trong ngày {start_str}"
            else:
                date_range = f"từ {start_str} đến {end_str}"
                
            if percent > 0:
                return {'type': 'increase', 'message': f"Đang áp dụng phụ thu: {active_season.name} (+{int(percent)}%) {date_range}"}
            elif percent < 0:
                return {'type': 'decrease', 'message': f"Đang có ưu đãi: {active_season.name} ({int(percent)}%) {date_range}"}
        return None
    class Meta:
        verbose_name = "Loại phòng"
        verbose_name_plural = "Các loại phòng"
    
    def __str__(self):
        return self.name

# 2. Bảng Phòng


class Room(models.Model):
    HOUSEKEEPING_STATUS = (
        ('CLEAN', 'Sạch sẽ - Sẵn sàng đón khách'),
        ('DIRTY', 'Chưa dọn - Khách vừa check-out'),
        ('MAINTENANCE', 'Đang bảo trì/Sửa chữa'),
    )

    category = models.ForeignKey(RoomCategory, on_delete=models.CASCADE, verbose_name="Thuộc loại phòng")
    room_number = models.CharField(max_length=10, unique=True, verbose_name="Số phòng")
    is_available = models.BooleanField(default=True, verbose_name="Còn trống")
    
    #Trang thái vật lý
    housekeeping_status = models.CharField(max_length=20, choices=HOUSEKEEPING_STATUS, default='CLEAN', verbose_name="Tình trạng dọn dẹp")
    
    description = models.TextField(default="Phòng sang trọng với đầy đủ tiện nghi.", verbose_name="Mô tả thêm")
    image = models.ImageField(upload_to='rooms/', null=True, blank=True, verbose_name="Ảnh đại diện") 

    class Meta:
        verbose_name = "Phòng"
        verbose_name_plural = "Danh sách phòng"

    def __str__(self) -> str:
        return f"Phòng {self.room_number}"

# 3. Bảng Đặt Phòng

class Booking(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Chờ thanh toán cọc'),
        ('CONFIRMED', 'Đã cọc - Giữ phòng'),
        ('CHECKED_IN', 'Khách đang ở'),
        ('CHECKED_OUT', 'Đã trả phòng'),
        ('CANCELLED', 'Đã hủy'),
        ('EXPIRED', 'Hủy - Quá hạn thanh toán'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    check_in = models.DateField()
    check_out = models.DateField()
    
    total_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    deposit_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Tiền cọc (50%)")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    is_active = models.BooleanField(default=True)


    created_at = models.DateTimeField(auto_now_add=True, null=True)
    actual_check_in = models.DateTimeField(null=True, blank=True, verbose_name="Giờ vào thực tế")
    actual_check_out = models.DateTimeField(null=True, blank=True, verbose_name="Giờ ra thực tế")
    cancellation_requested = models.BooleanField(default=False, verbose_name="Khách yêu cầu hủy")
    
    guest_full_name = models.CharField(max_length=100, blank=True, null=True, 
                                     verbose_name="Tên khách lưu trú")
    guest_cccd = models.CharField(max_length=20, blank=True, null=True, 
                                verbose_name="Số CCCD / CMND / Passport")
    guest_phone = models.CharField(max_length=15, blank=True, null=True, 
                                 verbose_name="Số điện thoại khách")
    
    # thêm ảnh CCCD 
    cccd_image = models.ImageField(upload_to='cccd/', blank=True, null=True)
    #kế hoạch giá
    rate_plan = models.ForeignKey('RatePlan', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Gói giá")
    coupon = models.ForeignKey('Coupon', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Mã KM áp dụng")
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Tiền được giảm") 

    class Meta:
        verbose_name = "Đơn đặt phòng"
        verbose_name_plural = "Các đơn đặt phòng"


    def __str__(self):
        return f"{self.user.username} đặt {self.room.room_number} ({self.get_status_display()})"


class Payment(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='payment')
    vnp_txn_ref = models.CharField(max_length=100, unique=True, verbose_name="Mã giao dịch VNPay")
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Số tiền đã GD")
    vnp_response_code = models.CharField(max_length=10, null=True, blank=True, verbose_name="Mã phản hồi VNPay")
    is_success = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    pay_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Thanh toán VNPay"
        verbose_name_plural = "Lịch sử thanh toán"

    def __str__(self):
        return f"GD {self.vnp_txn_ref} - {self.booking.room.room_number}"

    

class RoomImage(models.Model):
    # Khóa ngoại liên kết với bảng Room
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='rooms/gallery/')
    
    def __str__(self):
        return f"Ảnh chi tiết của phòng {self.room.room_number}"
    

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone_number = models.CharField(max_length=15, blank=True, null=True, default="Chưa cập nhật")
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)

    def __str__(self):
        return f"Hồ sơ của {self.user.username}"


class Favorite(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorites')
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Phòng yêu thích"
        verbose_name_plural = "Danh sách yêu thích"
        unique_together = ('user', 'room')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} thích phòng {self.room.room_number}"


class Conversation(models.Model):
    customer = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='conversations',
        verbose_name="Khách hàng"
    )
    booking = models.ForeignKey(
        Booking, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='conversations', verbose_name="Đơn đặt phòng"
    )
    subject = models.CharField(max_length=200, default='Hỗ trợ khách hàng', verbose_name="Tiêu đề")
    is_closed = models.BooleanField(default=False, verbose_name="Đã đóng")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cuộc hội thoại"
        verbose_name_plural = "Cuộc hội thoại"
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.subject} — {self.customer.username}"

    @property
    def last_message(self):
        return self.messages.order_by('-created_at').first()


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name='messages',
        verbose_name="Cuộc hội thoại"
    )
    sender = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='sent_messages',
        verbose_name="Người gửi"
    )
    content = models.TextField(verbose_name="Nội dung")
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False, verbose_name="Đã đọc")

    class Meta:
        verbose_name = "Tin nhắn"
        verbose_name_plural = "Tin nhắn"
        ordering = ['created_at']

    def __str__(self):
        preview = self.content[:50] + ('...' if len(self.content) > 50 else '')
        return f"{self.sender.username}: {preview}"
 
# CÁC BẢNG QUẢN LÝ GIÁ ĐỘNG & KHUYẾN MÃI
 

class RatePlan(models.Model):
    CANCELLATION_POLICIES = (
        ('FLEXIBLE', 'Tiêu chuẩn (Bảo lưu cọc)'),
        ('NON_REFUNDABLE', 'Không hoàn tiền (Mất cọc)'),
    )
    name = models.CharField(max_length=100, verbose_name="Tên gói giá (VD: Tiêu chuẩn, Kèm ăn sáng)")
    includes_breakfast = models.BooleanField(default=False, verbose_name="Bao gồm ăn sáng")
    cancellation_policy = models.CharField(max_length=20, choices=CANCELLATION_POLICIES)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.0, help_text="Giảm giá % so với giá gốc")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} (-{self.discount_percentage}%)"

class SeasonalPricing(models.Model):
    name = models.CharField(max_length=100, verbose_name="Sự kiện (VD: Lễ 30/4, Tết)")
    start_date = models.DateField()
    end_date = models.DateField()
    # Thay đổi: Chuyển thành nhập Phần trăm
    percent_adjustment = models.DecimalField(max_digits=5, decimal_places=2, default=0.0, verbose_name="Mức điều chỉnh (%)", help_text="Nhập số dương để Tăng giá (VD: 50 là tăng 50%). Nhập số âm để Giảm giá (VD: -20 là giảm 20%)")
    is_weekend_only = models.BooleanField(default=False, verbose_name="Chỉ tăng/giảm cuối tuần (T6, T7, CN)")
    
    def __str__(self):
        sign = "+" if self.percent_adjustment > 0 else ""
        return f"{self.name} ({sign}{self.percent_adjustment}%)"



class Coupon(models.Model):
    code = models.CharField(max_length=20, unique=True, verbose_name="Mã KM")
    discount_type = models.CharField(max_length=10, choices=[('PERCENT', 'Phần trăm (%)'), ('FIXED', 'Số tiền (VNĐ)')])
    discount_value = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Mức giảm")
    valid_from = models.DateTimeField(verbose_name="Bắt đầu")
    valid_to = models.DateTimeField(verbose_name="Kết thúc")
    usage_limit = models.IntegerField(default=100)
    used_count = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def is_valid(self):
        
        return self.is_active and self.valid_from <= timezone.now() <= self.valid_to and self.used_count < self.usage_limit

    def __str__(self):
        return self.code
# Hàm này giúp tự động tạo Profile rỗng (số dư = 0) mỗi khi có một tài khoản User mới được tạo
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


