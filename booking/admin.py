from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline #thêm
from .models import RoomCategory, Room, Booking, RoomImage #thêm

# Tạo một form con (Inline) cho ảnh
class RoomImageInline(TabularInline):
    model = RoomImage
    extra = 0
# Cách đăng ký bảng mới theo chuẩn của Unfold
@admin.register(RoomCategory)
class RoomCategoryAdmin(ModelAdmin):
    pass

@admin.register(Room) #chỉnh sửa
class RoomAdmin(ModelAdmin):
    inlines = [RoomImageInline]
    
    class Media:
        js = ('js/admin_preview.js',)
        
@admin.register(Booking)
class BookingAdmin(ModelAdmin):
    # 1. Hiển thị các cột chi tiết ra ngoài bảng
    list_display = ['id', 'user', 'room', 'check_in', 'check_out', 'total_price', 'trang_thai_don']
    
    # 2. Tạo bộ lọc bên tay phải để lọc nhanh "Đơn đã hủy" hoặc "Đơn thành công"
    list_filter = ['is_active', 'check_in']
    
    # 3. Tạo thanh tìm kiếm để tìm nhanh theo tên khách hoặc mã phòng
    search_fields = ['user__username', 'room__room_number']

    # 4. Hàm tự tạo để hiển thị trạng thái bằng chữ có màu cho đẹp mắt (Thay vì chỉ hiện True/False)
    def trang_thai_don(self, obj):
        from django.utils.safestring import mark_safe # <-- Sửa dòng import này
        if obj.is_active:
            return mark_safe('<span style="color: green; font-weight: bold;">Đang hoạt động</span>') 
        return mark_safe('<span style="color: red; font-weight: bold;">Đã hủy</span>') 
    trang_thai_don.short_description = 'Trạng thái'