# Thư viện chuẩn Python
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

# Django
from django.conf import settings
from django.contrib import admin  # Bắt buộc phải có để Unfold chạy được
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum, fields
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

# App nội bộ (booking)
from .forms import BookingForm
from .messaging import (
    get_customer_conversations,
    mark_messages_read,
    notify_booking_confirmed,
)
from .models import (
    Booking, Conversation, Coupon, Favorite, Message, Payment,
    RatePlan, Room, RoomCategory, SeasonalPricing, UserProfile,
)
from .vnpay import vnpay

def _get_favorite_room_ids(user):
    if not user.is_authenticated:
        return set()
    return set(Favorite.objects.filter(user=user).values_list('room_id', flat=True))


 
# GIAO DIỆN PHÒNG & ĐẶT PHÒNG
 

def room_list(request):
    """Hiển thị danh sách phòng, hỗ trợ tìm kiếm full text và bộ lọc"""
    auto_cancel_overdue_bookings()
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
        'favorite_room_ids': _get_favorite_room_ids(request.user),
    })

def room_detail(request, room_id):
    """Hiển thị chi tiết một phòng cụ thể"""
    room = get_object_or_404(Room, id=room_id)
    return render(request, 'booking/room_detail.html', {
        'room': room,
        'is_favorite': room.id in _get_favorite_room_ids(request.user),
    })


@login_required(login_url='login')
def book_room(request, room_id):
    """Xử lý logic đặt phòng (Bắt buộc đăng nhập)"""
    auto_cancel_overdue_bookings()
    room = get_object_or_404(Room, id=room_id)
    
    active_bookings = Booking.objects.filter(room=room, is_active=True)
    
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
            
            if booking.check_out <= booking.check_in:
                messages.error(request, 'Ngày trả phòng phải sau ngày nhận phòng!')
                return render(request, 'booking/book_room.html', {
                    'room': room, 'form': form, 'disabled_dates': json.dumps(disabled_dates)
                })

            overlapping_bookings = active_bookings.filter(
                Q(check_in__lt=booking.check_out) & Q(check_out__gt=booking.check_in)
            )

            if overlapping_bookings.exists():
                messages.error(request, 'Phòng này đã có khách đặt trong khoảng thời gian bạn chọn. Vui lòng chọn ngày khác!')
                return render(request, 'booking/book_room.html', {
                    'room': room, 'form': form, 'disabled_dates': json.dumps(disabled_dates)
                })
            
            total_room_price = 0
            current_date = booking.check_in
            base_price = float(room.category.price_per_night)

            while current_date < booking.check_out:
                daily_price = base_price
                season = SeasonalPricing.objects.filter(start_date__lte=current_date, end_date__gte=current_date).first()
                
                if season:
                    if season.is_weekend_only and current_date.weekday() not in [4, 5, 6]:
                        pass 
                    else:
                        daily_price = base_price * (1 + (float(season.percent_adjustment) / 100))

                total_room_price += daily_price
                current_date += timedelta(days=1)

            rate_plan_id = request.POST.get('rate_plan_id')
            if rate_plan_id:
                try:
                    plan = RatePlan.objects.get(id=rate_plan_id, is_active=True)
                    booking.rate_plan = plan
                    total_room_price = total_room_price * (1 - (float(plan.discount_percentage) / 100))
                except RatePlan.DoesNotExist:
                    pass

            coupon_code = request.POST.get('coupon_code', '').strip()
            discount_amt = 0
            if coupon_code:
                try:
                    c = Coupon.objects.get(code__iexact=coupon_code)
                    if c.is_valid():
                        if c.discount_type == 'PERCENT':
                            discount_amt = total_room_price * (float(c.discount_value) / 100)
                        else:
                            discount_amt = float(c.discount_value)
                        
                        booking.coupon = c
                        c.used_count += 1
                        c.save()
                    else:
                        messages.warning(request, "Mã khuyến mãi đã hết hạn hoặc hết lượt!")
                except Coupon.DoesNotExist:
                    messages.warning(request, "Mã khuyến mãi không hợp lệ!")

            final_price = total_room_price - discount_amt
            if final_price < 0: final_price = 0

            booking.total_price = final_price
            booking.discount_amount = discount_amt
            booking.deposit_amount = final_price / 2
            booking.status = 'PENDING'
            booking.save() 
            
            messages.info(request, f'Hệ thống đang chuyển hướng bạn đến cổng thanh toán VNPay để đặt cọc cho phòng {room.room_number}...')
            return redirect('create_payment', booking_id=booking.id)
        else:
            messages.error(request, 'Dữ liệu nhập vào không hợp lệ. Vui lòng kiểm tra lại!')
    else:
        form = BookingForm()

    rate_plans = RatePlan.objects.filter(is_active=True)
    return render(request, 'booking/book_room.html', {
        'room': room, 
        'form': form,
        'rate_plans': rate_plans,
        'disabled_dates': json.dumps(disabled_dates)
    })


 
# QUẢN LÝ TÀI KHOẢN & LỊCH SỬ ĐẶT PHÒNG
 

@login_required(login_url='login') 
def user_profile(request):
    """Trang cá nhân và lịch sử đặt phòng của khách"""
    auto_cancel_overdue_bookings()
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        new_email = request.POST.get('email', '').strip()
        new_phone = request.POST.get('phone', '').strip()
        
        if new_email:
            request.user.email = new_email
            request.user.save()
            
        if new_phone:
            profile.phone_number = new_phone
            profile.save()
            
        messages.success(request, "Cập nhật thông tin cá nhân thành công!")
        return redirect('user_profile')
    
    bookings = Booking.objects.filter(user=request.user).order_by('-check_in')
    
    return render(request, 'booking/profile.html', {
        'profile': profile,
        'bookings': bookings
    })

@login_required(login_url='login')
def favorite_list(request):
    favorites = Favorite.objects.filter(user=request.user).select_related(
        'room', 'room__category'
    )
    return render(request, 'booking/favorite_list.html', {
        'favorites': favorites,
    })


@login_required(login_url='login')
@require_POST
def toggle_favorite(request, room_id):
    room = get_object_or_404(Room, id=room_id)
    favorite, created = Favorite.objects.get_or_create(user=request.user, room=room)

    if not created:
        favorite.delete()
        messages.info(request, f'Đã bỏ phòng {room.room_number} khỏi danh sách yêu thích.')
    else:
        messages.success(request, f'Đã thêm phòng {room.room_number} vào danh sách yêu thích!')

    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
    if not next_url or not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = reverse('room_detail', args=[room.id])
    return redirect(next_url)


@login_required
def cancel_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    
    # 1. Chỉ cho phép hủy nếu ở trạng thái PENDING hoặc CONFIRMED
    if booking.status not in ['PENDING', 'CONFIRMED']:
        messages.error(request, "Đơn đặt phòng này không thể hủy!")
        return redirect('user_profile')

    # 2. BẢO MẬT BACKEND: Chặn đứng nếu khách dùng tool vượt qua nút Disable để cố hủy Gói KHÔNG HOÀN TIỀN
    if booking.rate_plan and booking.rate_plan.cancellation_policy == 'NON_REFUNDABLE' and booking.status == 'CONFIRMED':
        messages.error(request, "Rất tiếc! Đơn này sử dụng Gói Không Hoàn Tiền, bạn không thể hủy.")
        return redirect('user_profile')

    # Lưu lại trạng thái trước khi hủy để quyết định việc gửi mail (Chỉ khách Đã Cọc mới cần báo bảo lưu)
    was_confirmed = (booking.status == 'CONFIRMED')
    
    # 3. Đổi trạng thái thành CANCELLED
    booking.status = 'CANCELLED'
    booking.is_active = False
    booking.save()
    
    # 4. Giải phóng phòng cho khách khác đặt
    booking.room.is_available = True
    booking.room.save()

    # 5. GỬI EMAIL THÔNG BÁO BẢO LƯU CHO KHÁCH
    if was_confirmed:
        subject = f"Xác nhận Hủy phòng & Bảo lưu tiền cọc - Mã đơn #{booking.id}"
        message = f"""Chào {request.user.username},

Bạn vừa thực hiện hủy thành công đơn đặt phòng #{booking.id} (Phòng {booking.room.room_number}) tại ZagoHaven Resort.

CHI TIẾT CHÍNH SÁCH BẢO LƯU:
- Số tiền đã cọc: {booking.deposit_amount:,.0f} VNĐ
- Chính sách áp dụng: Gói Tiêu Chuẩn (Bảo lưu cọc)

Số tiền cọc của bạn đã được hệ thống lưu trữ an toàn. 
Để sử dụng số tiền này cho chuyến đi tiếp theo, bạn vui lòng liên hệ bộ phận CSKH qua Chat/Hotline và cung cấp mã đơn #{booking.id} để chúng tôi khởi tạo Voucher cấn trừ trực tiếp cho bạn nhé!

Hẹn gặp lại bạn tại ZagoHaven trong một dịp gần nhất.
Trân trọng."""
        try:
            send_mail(subject, message, settings.EMAIL_HOST_USER, [request.user.email], fail_silently=True)
        except Exception as e:
            print(f"Lỗi gửi email: {e}")
        
        messages.success(request, "Hủy phòng thành công! Thông báo bảo lưu đã được gửi vào Email của bạn.")
    else:
        # Hủy đơn khi chưa thanh toán (PENDING) thì không cần rườm rà
        messages.success(request, "Hủy đơn đặt phòng thành công.")

    return redirect('user_profile')

 
# XÁC THỰC NGƯỜI DÙNG (AUTH)
 

def login_user(request):
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
    logout(request)
    messages.success(request, "Bạn đã đăng xuất thành công.")
    return redirect('room_list')

def register_user(request):
    if request.user.is_authenticated:
        return redirect('room_list')

    if request.method == 'POST':
        user_name = request.POST.get('username', '').strip()
        e_mail = request.POST.get('email', '').strip()
        pass_word = request.POST.get('password')
        pass_word_confirm = request.POST.get('password_confirm')
        
        if pass_word != pass_word_confirm:
            messages.error(request, "Mật khẩu xác nhận không khớp!")
            return render(request, 'booking/register.html')
            
        if User.objects.filter(username__iexact=user_name).exists():
            messages.error(request, "Tên đăng nhập này đã tồn tại. Vui lòng chọn tên khác!")
            return render(request, 'booking/register.html')
            
        if User.objects.filter(email__iexact=e_mail).exists():
            messages.error(request, "Địa chỉ Email này đã được sử dụng!")
            return render(request, 'booking/register.html')
            
        try:
            user = User.objects.create_user(username=user_name, email=e_mail, password=pass_word)
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            
            messages.success(request, f"Đăng ký tài khoản thành công! Chào mừng {user_name} đến với Zagohaven.")
            return redirect('room_list')
            
        except Exception as e:
            print(f"==== LỖI ĐĂNG KÝ CỤ THỂ: {repr(e)} ====") 
            messages.error(request, "Hệ thống đang bận hoặc thông tin không hợp lệ, vui lòng thử lại!")
            return render(request, 'booking/register.html')

    return render(request, 'booking/register.html')

 
# THANH TOÁN VNPAY
 

@login_required(login_url='login')
def create_payment(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    
    if booking.status != 'PENDING':
        messages.error(request, "Đơn đặt phòng này không ở trạng thái chờ thanh toán.")
        return redirect('user_profile')

    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ipaddr = x_forwarded_for.split(',')[0]
    else:
        ipaddr = request.META.get('REMOTE_ADDR')

    amount = int(booking.deposit_amount * 100)
    vnp_txn_ref = f"{booking.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    vnp = vnpay()
    vnp.requestData['vnp_Version'] = '2.1.0'
    vnp.requestData['vnp_Command'] = 'pay'
    vnp.requestData['vnp_TmnCode'] = settings.VNPAY_TMN_CODE
    vnp.requestData['vnp_Amount'] = str(amount)
    vnp.requestData['vnp_CurrCode'] = 'VND'
    vnp.requestData['vnp_TxnRef'] = vnp_txn_ref
    vnp.requestData['vnp_OrderInfo'] = f"Thanh toan coc cho phong {booking.room.room_number}"
    vnp.requestData['vnp_OrderType'] = 'billpayment'
    vnp.requestData['vnp_Locale'] = 'vn'
    vnp.requestData['vnp_CreateDate'] = datetime.now().strftime('%Y%m%d%H%M%S')
    vnp.requestData['vnp_IpAddr'] = ipaddr
    vnp.requestData['vnp_ReturnUrl'] = settings.VNPAY_RETURN_URL

    vnpay_payment_url = vnp.get_payment_url(settings.VNPAY_PAYMENT_URL, settings.VNPAY_HASH_SECRET_KEY)
    return redirect(vnpay_payment_url)


@login_required(login_url='login')
def payment_return(request):
    inputData = request.GET
    if inputData:
        vnp = vnpay()
        vnp.responseData = inputData.dict()
        
        vnp_ResponseCode = vnp.responseData.get('vnp_ResponseCode')
        vnp_TxnRef = vnp.responseData.get('vnp_TxnRef')
        vnp_Amount = vnp.responseData.get('vnp_Amount')
        
        try:
            booking_id = int(vnp_TxnRef.split('_')[0])
            booking = Booking.objects.get(id=booking_id, user=request.user)
        except (ValueError, Booking.DoesNotExist):
            messages.error(request, "Không tìm thấy thông tin đơn đặt phòng.")
            return redirect('user_profile')

        if vnp.validate_response(settings.VNPAY_HASH_SECRET_KEY):
            if vnp_ResponseCode == "00":
                Payment.objects.create(
                    booking=booking,
                    vnp_txn_ref=vnp_TxnRef,
                    amount=int(vnp_Amount) / 100,
                    vnp_response_code=vnp_ResponseCode,
                    is_success=True,
                    pay_date=datetime.now()
                )
                
                if booking.status == 'PENDING':
                    booking.status = 'CONFIRMED'
                    booking.save()
                    notify_booking_confirmed(booking)
                    # gui mai sau dat phong thanh cong
                    try:
                        customer_email = request.user.email
                        
                        tieu_de = f'Xác nhận đặt phòng thành công - ZagoHaven'
                        noi_dung = f"""Chào {request.user.username},
                        
Bạn đã thanh toán cọc thành công cho đơn đặt phòng #{booking.id}.
- Phòng: {booking.room.room_number}
- Ngày nhận: {booking.check_in.strftime('%d/%m/%Y')}
- Ngày trả: {booking.check_out.strftime('%d/%m/%Y')}

Cảm ơn bạn đã chọn hệ thống của chúng tôi!"""
                        
                        send_mail(
                            tieu_de,
                            noi_dung,
                            settings.EMAIL_HOST_USER,
                            [customer_email],
                            fail_silently=True, 
                        )
                    except Exception as e:
                        print(f"Lỗi gửi mail: {e}")
                
                messages.success(request, "Thanh toán cọc thành công! Phòng của bạn đã được giữ.")
            else:
                messages.error(request, f"Giao dịch thất bại hoặc bị hủy. Mã lỗi: {vnp_ResponseCode}")
        else:
            messages.error(request, "Sai chữ ký bảo mật! Cảnh báo gian lận.")
            
    return redirect('user_profile')


def auto_cancel_overdue_bookings():
    pending_bookings = Booking.objects.filter(status='PENDING', is_active=True)
    now = timezone.now()
    
    for booking in pending_bookings:
        if booking.created_at and booking.check_in:
            days_in_advance = (booking.check_in - booking.created_at.date()).days
            
            if days_in_advance >= 7:
                timeout_limit = timedelta(hours=24)
            elif days_in_advance >= 3:
                timeout_limit = timedelta(minutes=30)
            else:
                timeout_limit = timedelta(minutes=30) 
            
            if now > (booking.created_at + timeout_limit):
                booking.status = 'EXPIRED'
                booking.is_active = False
                booking.save()
                
                booking.room.is_available = True
                booking.room.save()

 
# TRUNG TÂM TIN NHẮN (KHÁCH HÀNG)
 

def _can_access_conversation(user, conversation):
    if user.is_staff:
        return False
    return conversation.customer_id == user.id

def _serialize_message(msg):
    return {
        'id': msg.id,
        'content': msg.content,
        'sender': msg.sender.username,
        'is_staff': msg.sender.is_staff,
        'is_mine': False,
        'created_at': msg.created_at.strftime('%d/%m/%Y %H:%M'),
        'time_short': msg.created_at.strftime('%H:%M'),
    }

@login_required(login_url='login')
def message_inbox(request):
    if request.user.is_staff:
        return redirect('admin:booking_conversation_changelist')
    conversations = get_customer_conversations(request.user)
    active_id = request.GET.get('conversation')
    return render(request, 'booking/messages/inbox.html', {
        'conversations': conversations,
        'active_id': int(active_id) if active_id and active_id.isdigit() else None,
        'is_staff_view': False,
    })

@login_required(login_url='login')
def message_thread(request, conversation_id):
    if request.user.is_staff:
        return redirect('admin:conversation-reply', conversation_id=conversation_id)

    conversation = get_object_or_404(
        Conversation.objects.select_related('customer', 'booking', 'booking__room'),
        id=conversation_id,
    )
    if not _can_access_conversation(request.user, conversation):
        messages.error(request, 'Bạn không có quyền truy cập cuộc hội thoại này.')
        return redirect('message_inbox')

    if request.method == 'POST':
        content = request.POST.get('content', '').strip()
        if not content:
            messages.error(request, 'Nội dung tin nhắn không được để trống.')
        elif conversation.is_closed:
            messages.error(request, 'Cuộc hội thoại đã được đóng.')
        else:
            Message.objects.create(
                conversation=conversation,
                sender=request.user,
                content=content,
            )
            conversation.updated_at = timezone.now()
            conversation.save(update_fields=['updated_at'])
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                msg = conversation.messages.order_by('-created_at').first()
                data = _serialize_message(msg)
                data['is_mine'] = True
                return JsonResponse({'success': True, 'message': data})
            return redirect('message_thread', conversation_id=conversation.id)

    mark_messages_read(conversation, request.user)
    thread_messages = conversation.messages.select_related('sender').all()
    conversations = get_customer_conversations(request.user)

    serialized = []
    for msg in thread_messages:
        data = _serialize_message(msg)
        data['is_mine'] = msg.sender_id == request.user.id
        serialized.append(data)

    return render(request, 'booking/messages/inbox.html', {
        'conversations': conversations,
        'active_conversation': conversation,
        'thread_messages': thread_messages,
        'messages_json': serialized,
        'is_staff_view': False,
    })

@login_required(login_url='login')
def new_conversation(request):
    if request.user.is_staff:
        return redirect('admin:booking_conversation_changelist')

    booking = None
    booking_id = request.GET.get('booking') or request.POST.get('booking_id')
    if booking_id:
        booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    if request.method == 'POST':
        subject = request.POST.get('subject', '').strip()
        content = request.POST.get('content', '').strip()
        if not subject:
            subject = f'Hỗ trợ đơn #{booking.id} — Phòng {booking.room.room_number}' if booking else 'Hỗ trợ khách hàng'
        if not content:
            messages.error(request, 'Vui lòng nhập nội dung tin nhắn.')
            return render(request, 'booking/messages/new_conversation.html', {'booking': booking})

        conversation = Conversation.objects.create(
            customer=request.user,
            booking=booking,
            subject=subject,
        )
        Message.objects.create(
            conversation=conversation,
            sender=request.user,
            content=content,
        )
        messages.success(request, 'Đã gửi tin nhắn! Nhân viên sẽ phản hồi sớm nhất.')
        return redirect('message_thread', conversation_id=conversation.id)

    default_subject = ''
    if booking:
        default_subject = f'Hỗ trợ đơn #{booking.id} — Phòng {booking.room.room_number}'

    return render(request, 'booking/messages/new_conversation.html', {
        'booking': booking,
        'default_subject': default_subject,
    })

@login_required(login_url='login')
@require_GET
def message_poll(request, conversation_id):
    if request.user.is_staff:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    conversation = get_object_or_404(Conversation, id=conversation_id)
    if not _can_access_conversation(request.user, conversation):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    last_id = int(request.GET.get('last_id', 0))
    new_messages = conversation.messages.filter(id__gt=last_id).select_related('sender')
    mark_messages_read(conversation, request.user)

    result = []
    for msg in new_messages:
        data = _serialize_message(msg)
        data['is_mine'] = msg.sender_id == request.user.id
        result.append(data)

    return JsonResponse({'messages': result})



@require_POST
def calculate_price_api(request):
    try:
        data = json.loads(request.body)
        room_id = data.get('room_id')
        check_in_str = data.get('check_in')
        check_out_str = data.get('check_out')
        rate_plan_id = data.get('rate_plan_id')
        coupon_code = data.get('coupon_code', '').strip()

        if not (room_id and check_in_str and check_out_str):
            return JsonResponse({'success': False, 'error': 'Thiếu thông tin ngày'})

        check_in = datetime.strptime(check_in_str, '%Y-%m-%d').date()
        check_out = datetime.strptime(check_out_str, '%Y-%m-%d').date()
        
        if check_out <= check_in:
            return JsonResponse({'success': False, 'error': 'Ngày không hợp lệ'})

        room = Room.objects.get(id=room_id)
        total_room_price = 0
        current_date = check_in
        base_price = float(room.category.price_per_night)
        
        # 1. Biến lưu thông báo mùa
        season_msgs = set()

        while current_date < check_out:
            daily_price = base_price
            season = SeasonalPricing.objects.filter(start_date__lte=current_date, end_date__gte=current_date).first()
            
            if season:
                if season.is_weekend_only and current_date.weekday() not in [4, 5, 6]:
                    pass
                else:
                    percent = float(season.percent_adjustment)
                    daily_price = base_price * (1 + (percent / 100))
                    
                    if percent > 0:
                        season_msgs.add(f"Có phụ thu {season.name}")
                    elif percent < 0:
                        season_msgs.add(f"Ưu đãi {season.name}")
                        
            total_room_price += daily_price
            current_date += timedelta(days=1)

        # 2. XỬ LÝ GÓI GIÁ VÀ THÔNG BÁO GÓI GIÁ (CODE MỚI THÊM VÀO ĐÂY)
        rate_plan_msg = ""
        if rate_plan_id:
            try:
                plan = RatePlan.objects.get(id=rate_plan_id, is_active=True)
                total_room_price = total_room_price * (1 - (float(plan.discount_percentage) / 100))
                
                # Tạo câu thông báo tùy theo chính sách của Gói đó
                if plan.cancellation_policy == 'NON_REFUNDABLE':
                    rate_plan_msg = "GÓI KHÔNG HOÀN HỦY: Bạn sẽ mất 100% tiền cọc nếu xác nhận hủy đơn này."
                else:
                    rate_plan_msg = "GÓI TIÊU CHUẨN: Tiền cọc của bạn sẽ được bảo lưu nếu bạn cần hủy."
            except RatePlan.DoesNotExist:
                pass

        # 3. Xử lý mã khuyến mãi
        discount_amt = 0
        coupon_msg = ""
        is_coupon_valid = False
        if coupon_code:
            try:
                c = Coupon.objects.get(code__iexact=coupon_code)
                if c.is_valid():
                    if c.discount_type == 'PERCENT':
                        discount_amt = total_room_price * (float(c.discount_value) / 100)
                    else:
                        discount_amt = float(c.discount_value)
                    coupon_msg = f"Đã áp dụng mã giảm giá!"
                    is_coupon_valid = True
                else:
                    coupon_msg = "Mã KM đã hết hạn hoặc hết lượt."
            except Coupon.DoesNotExist:
                coupon_msg = "Mã KM không hợp lệ."

        final_price = total_room_price - discount_amt
        if final_price < 0: final_price = 0
        
        season_msg_final = " & ".join(list(season_msgs)) if season_msgs else ""

        # TRẢ VỀ TOÀN BỘ THÔNG BÁO CHO TRANG ĐẶT PHÒNG
        return JsonResponse({
            'success': True,
            'total_price': final_price,
            'discount': discount_amt,
            'coupon_msg': coupon_msg,
            'is_coupon_valid': is_coupon_valid,
            'season_msg': season_msg_final,
            'rate_plan_msg': rate_plan_msg  # Đã thêm biến này
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


 
# MODULE THỐNG KÊ DOANH THU & HIỆU SUẤT (ENTERPRISE DASHBOARD)
 

def calculate_growth(current: float, previous: float) -> float:
    """Hàm phụ trợ tính phần trăm tăng/giảm so với kỳ trước."""
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 2)


@user_passes_test(lambda u: u.is_staff, login_url='login')
def hotel_dashboard_reports(request):
    """
    View thống kê kết hợp tất cả các chỉ số chuyên sâu (ADR, RevPAR, ALOS, Hủy phòng), 
    đồng thời xuất dữ liệu vẽ biểu đồ và bảng công nợ.
    """
    today = timezone.now().date()
    
    # 1. THIẾT LẬP KỲ BÁO CÁO (Mặc định 30 ngày)
    try:
        days = int(request.GET.get('period', 30))
    except ValueError:
        days = 30
        
    current_start = today - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)

    # 2. LẤY DỮ LIỆU KỲ HIỆN TẠI (CURRENT PERIOD)
    current_bookings = Booking.objects.filter(
        created_at__date__gte=current_start,
        created_at__date__lte=today
    )
    
    current_stats = current_bookings.aggregate(
        total_revenue=Coalesce(Sum('total_price', filter=Q(status__in=['CONFIRMED', 'CHECKED_IN', 'CHECKED_OUT'])), Decimal('0.00')),
        total_orders=Count('id'),
        cancelled_orders=Count('id', filter=Q(status='CANCELLED')),
        noshow_orders=Count('id', filter=Q(status='EXPIRED')), 
        booked_nights=Coalesce(Sum(ExpressionWrapper(F('check_out') - F('check_in'), output_field=fields.DurationField())), timedelta(0))
    )
    
    current_booked_nights = current_stats['booked_nights'].days if current_stats['booked_nights'] else 0

    # 3. LẤY DỮ LIỆU KỲ TRƯỚC ĐỂ SO SÁNH (PREVIOUS PERIOD)
    previous_bookings = Booking.objects.filter(
        created_at__date__gte=previous_start,
        created_at__date__lt=current_start
    )
    previous_stats = previous_bookings.aggregate(
        total_revenue=Coalesce(Sum('total_price', filter=Q(status__in=['CONFIRMED', 'CHECKED_IN', 'CHECKED_OUT'])), Decimal('0.00')),
        total_orders=Count('id')
    )

    # 4. TÍNH TOÁN BỘ 3 CHỈ SỐ (HOSPITALITY METRICS)
    total_active_rooms = Room.objects.filter(is_available=True).count()
    total_capacity_nights = total_active_rooms * days
    current_revenue = float(current_stats['total_revenue'])
    
    # ADR (Average Daily Rate) 
    adr = round(current_revenue / current_booked_nights, 0) if current_booked_nights > 0 else 0
    # RevPAR (Revenue Per Available Room)
    revpar = round(current_revenue / total_capacity_nights, 0) if total_capacity_nights > 0 else 0
    # ALOS (Average Length of Stay)
    successful_orders = current_stats['total_orders'] - current_stats['cancelled_orders'] - current_stats['noshow_orders']
    alos = round(current_booked_nights / successful_orders, 1) if successful_orders > 0 else 0

    # 5. TÍNH TỶ LỆ HỦY & NO-SHOW
    total_orders = current_stats['total_orders']
    cancel_rate = round((current_stats['cancelled_orders'] / total_orders) * 100, 1) if total_orders > 0 else 0
    noshow_rate = round((current_stats['noshow_orders'] / total_orders) * 100, 1) if total_orders > 0 else 0

    # 6. TÍNH TĂNG TRƯỞNG (GROWTH)
    revenue_growth = calculate_growth(current_revenue, float(previous_stats['total_revenue']))
    booking_growth = calculate_growth(total_orders, previous_stats['total_orders'])

    # CÁC TRƯỜNG DỮ LIỆU CŨ PHỤC VỤ CHO BẢNG & BIỂU ĐỒ CHART.JS
  
    
    total_cash_received = Payment.objects.filter(
        is_success=True, pay_date__date__gte=current_start
    ).aggregate(
        total=Coalesce(Sum('amount'), 0.00, output_field=DecimalField())
    )['total']

    total_discount_given = Booking.objects.filter(
        created_at__date__gte=current_start, is_active=True
    ).aggregate(
        total=Coalesce(Sum('discount_amount'), 0.00, output_field=DecimalField())
    )['total']

    revenue_by_date = Payment.objects.filter(
        is_success=True, pay_date__date__gte=current_start
    ).annotate(
        date=TruncDate('pay_date')
    ).values('date').annotate(
        daily_revenue=Coalesce(Sum('amount'), Decimal('0.00'))
    ).order_by('date') 

    revenue_by_category = Booking.objects.filter(
        status__in=['CONFIRMED', 'CHECKED_IN', 'CHECKED_OUT'],
        is_active=True,
        check_in__gte=current_start
    ).values('room__category__name').annotate(
       total_revenue=Coalesce(Sum('total_price'), Decimal('0.00'))
    ).order_by('-total_revenue')

    booking_status_counts = Booking.objects.filter(
        created_at__date__gte=current_start
    ).values('status').annotate(count=Count('id')).order_by('-count')

    status_dict = dict(Booking.STATUS_CHOICES)
    status_chart_data = [{'name': status_dict.get(i['status'], i['status']), 'count': i['count']} for i in booking_status_counts]

    top_rooms = Booking.objects.filter(
        status__in=['CONFIRMED', 'CHECKED_IN', 'CHECKED_OUT'],
        is_active=True,
        check_in__gte=current_start
    ).values('room__room_number', 'room__category__name').annotate(
        total_revenue=Sum('total_price'),
        booking_count=Count('id')
    ).order_by('-total_revenue')[:5]

    debt_bookings = Booking.objects.filter(
        status__in=['CONFIRMED', 'CHECKED_IN'],
        is_active=True
    ).annotate(
        remaining_balance=ExpressionWrapper(
            F('total_price') - Coalesce(F('deposit_amount'), 0.00, output_field=DecimalField()),
            output_field=DecimalField()
        )
    ).filter(remaining_balance__gt=0).order_by('check_in')

    total_outstanding_debt = debt_bookings.aggregate(
        total_debt=Coalesce(Sum('remaining_balance'), 0.00, output_field=DecimalField())
    )['total_debt']

    # Dự báo 30 ngày (luôn lấy 30 ngày từ thời điểm hiện tại)
    future_30_days = today + timedelta(days=30)
    future_bookings = Booking.objects.filter(
        check_in__lte=future_30_days,
        check_out__gte=today,
        status__in=['CONFIRMED', 'CHECKED_IN'],
        is_active=True
    )
    
    future_booked_nights = 0
    for b in future_bookings:
        start = max(b.check_in, today)
        end = min(b.check_out, future_30_days)
        nights = (end - start).days
        if nights > 0:
            future_booked_nights += nights
            
    future_capacity = total_active_rooms * 30
    occupancy_rate = round((future_booked_nights / future_capacity) * 100, 2) if future_capacity > 0 else 0

    # ĐÓNG GÓI CONTEXT
    context = {
        'period': str(days),
        
        # Biến mới (Enterprise Metrics)
        'current_revenue': current_revenue,
        'revenue_growth': revenue_growth,
        'total_orders': total_orders,
        'booking_growth': booking_growth,
        'adr': adr,
        'revpar': revpar,
        'alos': alos,
        'cancel_rate': cancel_rate,
        'noshow_rate': noshow_rate,
        'cancelled_orders': current_stats['cancelled_orders'],
        'noshow_orders': current_stats['noshow_orders'],
        
        # Biến cũ (Dành cho Biểu đồ & Bảng của các Frontend cũ)
        'total_cash_received': total_cash_received or 0,
        'total_bookings_count': total_orders,
        'total_discount_given': total_discount_given or 0,
        'total_outstanding_debt': total_outstanding_debt or 0,
        'revenue_by_date': revenue_by_date,
        'revenue_by_category': revenue_by_category,
        'status_chart_data': status_chart_data,
        'top_rooms': top_rooms,
        'debt_bookings': debt_bookings,
        'forecast': {
            'total_rooms': total_active_rooms,
            'booked_nights': future_booked_nights,
            'capacity_nights': future_capacity,
            'occupancy_rate': occupancy_rate
        },
        
        # Dòng lệnh BẮT BUỘC để Unfold không bị trắng màn hình
        **admin.site.each_context(request), 
    }
    
    return render(request, 'dashboard/reports.html', context)

import calendar


@login_required(login_url='login')
def admin_room_map_view(request) -> HttpResponse:
    """
    Sơ đồ trực quan đặt phòng (Timeline / Gantt Chart)
    Hiển thị chính xác tên khách và thanh thời gian lưu trú.
    """
    if not request.user.has_perm('booking.view_room'):
        messages.error(request, 'Bạn không có quyền truy cập sơ đồ phòng.')
        return redirect('room_list')

    # Xử lý ngày tháng theo múi giờ Việt Nam
    today = timezone.localdate()
    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
    except ValueError:
        year, month = today.year, today.month

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    _, num_days = calendar.monthrange(year, month)
    days_in_month = [date(year, month, day) for day in range(1, num_days + 1)]
    start_date = days_in_month[0]
    end_date = days_in_month[-1]

    # Lấy dữ liệu
    rooms = Room.objects.select_related('category').order_by('room_number')
    bookings = Booking.objects.filter(
        status__in=['PENDING', 'CONFIRMED', 'CHECKED_IN'],
        is_active=True,
        check_in__lte=end_date,
        check_out__gte=start_date
    ).select_related('user')

    # Dệt ma trận lưới (Grid Matrix)
    matrix = []
    for room in rooms:
        room_bookings = bookings.filter(room=room).order_by('check_in')
        row_cells = []
        d = 1
        
        while d <= num_days:
            current_date = date(year, month, d)
            active_booking = None
            
            # Khách check_out ngày nào thì ngày đó phòng trống đón khách mới
            for b in room_bookings:
                if b.check_in <= current_date < b.check_out:
                    active_booking = b
                    break
            
            if active_booking:
                end_of_block = min(active_booking.check_out, end_date + timedelta(days=1))
                span = (end_of_block - current_date).days
                if span < 1: span = 1
                
                guest_name = active_booking.guest_full_name or active_booking.user.username
                row_cells.append({
                    'type': 'booking', 'booking': active_booking,
                    'colspan': span, 'guest_name': guest_name
                })
                d += span  
            else:
                row_cells.append({
                    'type': 'empty', 'colspan': 1,
                    'is_weekend': current_date.weekday() >= 5 # 5 là T7, 6 là CN
                })
                d += 1
                
        matrix.append({'room': room, 'cells': row_cells})

    context = {
        'year': year, 'month': month,
        'prev_year': prev_year, 'prev_month': prev_month,
        'next_year': next_year, 'next_month': next_month,
        'days_in_month': days_in_month,
        'matrix': matrix,
        **admin.site.each_context(request), 
    }
    return render(request, 'admin/room_map.html', context)