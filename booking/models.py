from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

# 1. Bảng Loại Phòng
class RoomCategory(models.Model):
    name = models.CharField(max_length=50) 
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2)
    capacity = models.IntegerField(default=2)

    class Meta:
        verbose_name = "Loại phòng"
        verbose_name_plural = "Các loại phòng"

    def __str__(self):
        return self.name

# 2. Bảng Phòng
class Room(models.Model):
    category = models.ForeignKey(RoomCategory, on_delete=models.CASCADE)
    room_number = models.CharField(max_length=10, unique=True)
    is_available = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Phòng"
        verbose_name_plural = "Danh sách Phòng"

    def __str__(self):
        return f"Phòng {self.room_number} - {self.category.name}"

class Room(models.Model):
    category = models.ForeignKey(RoomCategory, on_delete=models.CASCADE)
    room_number = models.CharField(max_length=10, unique=True)
    is_available = models.BooleanField(default=True)
    # Thêm 2 dòng này:
    description = models.TextField(default="Phòng sang trọng với đầy đủ tiện nghi.")
    image = models.ImageField(upload_to='rooms/', null=True, blank=True) 

    def __str__(self):
        return f"Phòng {self.room_number}"

# 3. Bảng Đặt Phòng
class Booking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    check_in = models.DateField()
    check_out = models.DateField()
    total_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Đơn đặt phòng"
        verbose_name_plural = "Các đơn đặt phòng"

    def __str__(self):
        return f"{self.user.username} đặt {self.room.room_number}"

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

# Hàm này giúp tự động tạo Profile rỗng (số dư = 0) mỗi khi có một tài khoản User mới được tạo
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
