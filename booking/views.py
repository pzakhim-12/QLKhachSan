import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q

# Import các model và form của app booking
from .models import Room, Booking, UserProfile, RoomCategory
from .forms import BookingForm

# ==========================================
# GIAO DIỆN PHÒNG & ĐẶT PHÒNG
# ==========================================

def room_list(request):
    """Hiển thị danh sách phòng, hỗ trợ tìm kiếm full text và bộ lọc"""
    rooms = Room.objects.select_related('category').all()
    query = request.GET.get('q', '').strip()
    category_id = request.GET.get('category', '').strip()
    min_price = request.GET.get('min_price', '').strip()
    max_price = request.GET.get('max_price', '').strip()
    min_capacity = request.GET.get('capacity', '').strip()
    availability = request.GET.get('availability', '').strip()
    sort = request.GET.get('sort', '').strip()

    if query:
        rooms = rooms.filter(
            Q(room_number__icontains=query) |
            Q(description__icontains=query) |
            Q(category__name__icontains=query)
        )

    if category_id.isdigit():
        rooms = rooms.filter(category_id=int(category_id))

    if min_price:
        try:
            rooms = rooms.filter(category__price_per_night__gte=float(min_price))
        except ValueError:
            min_price = ''

    if max_price:
        try:
            rooms = rooms.filter(category__price_per_night__lte=float(max_price))
        except ValueError:
            max_price = ''

    if min_capacity.isdigit():
        rooms = rooms.filter(category__capacity__gte=int(min_capacity))

    if availability == 'available':
        rooms = rooms.filter(is_available=True)
    elif availability == 'unavailable':
        rooms = rooms.filter(is_available=False)

    if sort == 'price_asc':
        rooms = rooms.order_by('category__price_per_night', 'room_number')
    elif sort == 'price_desc':
        rooms = rooms.order_by('-category__price_per_night', 'room_number')
    else:
        rooms = rooms.order_by('room_number')

    has_active_filters = any([
        query, category_id, min_price, max_price, min_capacity, availability, sort
    ])

    return render(request, 'booking/room_list.html', {
        'rooms': rooms,
        'query': query,
        'categories': RoomCategory.objects.all(),
        'filters': {
            'category': category_id,
            'min_price': min_price,
            'max_price': max_price,
            'capacity': min_capacity,
            'availability': availability,
            'sort': sort,
        },
        'has_active_filters': has_active_filters,
    })

def room_detail(request, room_id):
    """Hiển thị chi tiết một phòng cụ thể"""
    room = get_object_or_404(Room, id=room_id)
    return render(request, 'booking/room_detail.html', {'room': room})

@login_required(login_url='login')
def book_room(request, room_id):
    """Xử lý logic đặt phòng (Bắt buộc đăng nhập)"""
    room = get_object_or_404(Room, id=room_id)
    
    # Lấy danh sách các đơn đặt phòng cũ đang hoạt động của phòng này
    active_bookings = Booking.objects.filter(room=room, is_active=True)
    
    # Tạo một mảng chứa các khoảng ngày đã bị đặt để gửi cho thư viện lịch Flatpickr
    disabled_dates = []
    for b in active_bookings:
        disabled_dates.append({
            'from': str(b.check_in),
            'to': str(b.check_out)
        })
    
    if request.method == 'POST':
        form = BookingForm(request.POST)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.room = room 
            booking.user = request.user 
            
            # Kiểm tra ngày hợp lệ
            if booking.check_out <= booking.check_in:
                messages.error(request, 'Ngày trả phòng phải sau ngày nhận phòng!')
                return render(request, 'booking/book_room.html', {
                    'room': room, 'form': form, 'disabled_dates': json.dumps(disabled_dates)
                })

            # Kiểm tra trùng lịch
            overlapping_bookings = active_bookings.filter(
                Q(check_in__lt=booking.check_out) & Q(check_out__gt=booking.check_in)
            )

            if overlapping_bookings.exists():
                messages.error(request, 'Phòng này đã có khách đặt trong khoảng thời gian bạn chọn. Vui lòng chọn ngày khác!')
                return render(request, 'booking/book_room.html', {
                    'room': room, 'form': form, 'disabled_dates': json.dumps(disabled_dates)
                })
            
            # Tính tiền và lưu
            days = (booking.check_out - booking.check_in).days
            booking.total_price = room.category.price_per_night * days
            booking.save() 
            
            messages.success(request, f'Đặt thành công phòng {room.room_number} từ ngày {booking.check_in} đến {booking.check_out}!')
            return redirect('room_list')
        else:
            messages.error(request, 'Dữ liệu nhập vào không hợp lệ. Vui lòng kiểm tra lại!')
    else:
        form = BookingForm()

    return render(request, 'booking/book_room.html', {
        'room': room, 
        'form': form,
        'disabled_dates': json.dumps(disabled_dates)
    })


# ==========================================
# QUẢN LÝ TÀI KHOẢN & LỊCH SỬ ĐẶT PHÒNG
# ==========================================

@login_required(login_url='login') 
def user_profile(request):
    """Trang cá nhân và lịch sử đặt phòng của khách"""
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    
    # Lấy toàn bộ lịch sử đặt phòng của user này, mới nhất lên đầu
    bookings = Booking.objects.filter(user=request.user).order_by('-check_in')
    
    return render(request, 'booking/profile.html', {
        'profile': profile,
        'bookings': bookings
    })

@login_required(login_url='login')
def cancel_booking(request, booking_id):
    """Logic hủy phòng của khách"""
    # Chỉ cho phép hủy đúng đơn của chính user đang đăng nhập
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    
    if booking.is_active:
        booking.is_active = False # Chuyển trạng thái thành đã hủy
        booking.save()
        messages.success(request, f'Đã hủy thành công đơn đặt phòng {booking.room.room_number}.')
    
    return redirect('user_profile')


# ==========================================
# XÁC THỰC NGƯỜI DÙNG (AUTH)
# ==========================================

def login_user(request):
    """Xử lý đăng nhập"""
    if request.user.is_authenticated:
        return redirect('room_list')

    if request.method == 'POST':
        user_name = request.POST.get('username')
        pass_word = request.POST.get('password')
        
        user = authenticate(request, username=user_name, password=pass_word)
        
        if user is not None:
            login(request, user)
            if user.is_staff:
                messages.success(request, f"Chào mừng quản trị viên {user_name} trở lại Zagohaven!")
            else:
                messages.success(request, f"Đăng nhập thành công! Xin chào {user_name}.")
            return redirect('room_list')
        else:
            messages.error(request, "Sai tên đăng nhập hoặc mật khẩu!")

    return render(request, 'booking/login.html')

def logout_user(request):
    """Xử lý đăng xuất"""
    logout(request)
    messages.success(request, "Bạn đã đăng xuất thành công.")
    return redirect('room_list')

def register_user(request):
    """Xử lý đăng ký tài khoản mới"""
    if request.user.is_authenticated:
        return redirect('room_list')

    if request.method == 'POST':
        # 1. Lấy data và DỌN DẸP khoảng trắng thừa bằng .strip()
        user_name = request.POST.get('username', '').strip()
        e_mail = request.POST.get('email', '').strip()
        pass_word = request.POST.get('password')
        pass_word_confirm = request.POST.get('password_confirm')
        
        # 2. Kiểm tra mật khẩu
        if pass_word != pass_word_confirm:
            messages.error(request, "Mật khẩu xác nhận không khớp!")
            return render(request, 'booking/register.html')
            
        # 3. FIX LỖI Ở ĐÂY: Dùng __iexact để không phân biệt hoa thường
        if User.objects.filter(username__iexact=user_name).exists():
            messages.error(request, "Tên đăng nhập này đã tồn tại. Vui lòng chọn tên khác!")
            return render(request, 'booking/register.html')
            
        # [Bổ sung Best Practice]: Nên check luôn trùng Email để tránh lỗi hệ thống
        if User.objects.filter(email__iexact=e_mail).exists():
            messages.error(request, "Địa chỉ Email này đã được sử dụng!")
            return render(request, 'booking/register.html')
            
        # 4. Bọc trong Try-Except để lỡ DB có lỗi ngầm, web cũng tự báo lỗi thân thiện ra màn hình
        try:
            # Bước 1: Vẫn tạo user bình thường (tài khoản đã vào DB)
            user = User.objects.create_user(username=user_name, email=e_mail, password=pass_word)
            
            # Bước 2: FIX LỖI Ở ĐÂY - Phải chỉ định rõ backend mặc định của Django
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            
            messages.success(request, f"Đăng ký tài khoản thành công! Chào mừng {user_name} đến với Zagohaven.")
            return redirect('room_list')
            
        except Exception as e:
            # IN LỖI RA TERMINAL để nếu còn sập, bro nhìn vào màn hình CMD chạy server là biết ngay nguyên nhân
            print(f"==== LỖI ĐĂNG KÝ CỤ THỂ: {repr(e)} ====") 
            
            messages.error(request, "Hệ thống đang bận hoặc thông tin không hợp lệ, vui lòng thử lại!")
            return render(request, 'booking/register.html')

    return render(request, 'booking/register.html')
    """Xử lý đăng ký tài khoản mới"""
    if request.user.is_authenticated:
        return redirect('room_list')

    if request.method == 'POST':
        user_name = request.POST.get('username')
        e_mail = request.POST.get('email')
        pass_word = request.POST.get('password')
        pass_word_confirm = request.POST.get('password_confirm')
        
        if pass_word != pass_word_confirm:
            messages.error(request, "Mật khẩu xác nhận không khớp!")
            return render(request, 'booking/register.html')
            
        if User.objects.filter(username=user_name).exists():
            messages.error(request, "Tên đăng nhập này đã có người sử dụng!")
            return render(request, 'booking/register.html')
            
        user = User.objects.create_user(username=user_name, email=e_mail, password=pass_word)
        user.save()
        
        login(request, user)
        messages.success(request, f"Đăng ký tài khoản thành công! Chào mừng {user_name} đến với Zagohaven.")
        return redirect('room_list')

    return render(request, 'booking/register.html')