from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.utils import timezone

from .models import Conversation, Message

def get_customer_conversations(user):
    return Conversation.objects.filter(customer=user).select_related(
        'booking', 'booking__room'
    ).annotate(
        unread_count=Count(
            'messages',
            filter=Q(messages__is_read=False, messages__sender__is_staff=True),
        )
    )


def get_staff_conversations():
    return Conversation.objects.select_related(
        'customer', 'booking', 'booking__room'
    ).annotate(
        unread_count=Count(
            'messages',
            filter=Q(messages__is_read=False, messages__sender__is_staff=False),
        )
    )


def mark_messages_read(conversation, reader):
    Message.objects.filter(
        conversation=conversation,
        is_read=False,
    ).exclude(sender=reader).update(is_read=True)


def get_unread_count(user):
    if not user.is_authenticated:
        return 0
    if user.is_staff:
        return Message.objects.filter(is_read=False, sender__is_staff=False).count()
    return Message.objects.filter(
        conversation__customer=user,
        is_read=False,
        sender__is_staff=True,
    ).count()


def _get_system_staff():
    return User.objects.filter(is_staff=True, is_active=True).order_by('pk').first()


def notify_booking_confirmed(booking):
    """Gửi tin nhắn xác nhận đặt phòng cho khách sau khi thanh toán cọc thành công."""
    staff = _get_system_staff()
    if not staff:
        return None

    booking = type(booking).objects.select_related('room', 'room__category', 'user').get(pk=booking.pk)

    subject = f'Đơn đặt phòng #{booking.id} — Phòng {booking.room.room_number}'
    conversation = Conversation.objects.filter(
        customer=booking.user,
        booking=booking,
    ).first()
    if not conversation:
        conversation = Conversation.objects.create(
            customer=booking.user,
            booking=booking,
            subject=subject,
        )

    check_in = booking.check_in.strftime('%d/%m/%Y')
    check_out = booking.check_out.strftime('%d/%m/%Y')
    total = f'{booking.total_price:,.0f}'.replace(',', '.')
    deposit = f'{booking.deposit_amount:,.0f}'.replace(',', '.')
    remaining = f'{(booking.total_price - booking.deposit_amount):,.0f}'.replace(',', '.')

    content = (
        f'Xin chúc mừng! Đơn đặt phòng #{booking.id} của bạn đã được xác nhận thành công.\n\n'
        f'• Phòng: {booking.room.room_number} ({booking.room.category.name})\n'
        f'• Nhận phòng: {check_in}\n'
        f'• Trả phòng: {check_out}\n'
        f'• Tổng tiền: {total}đ\n'
        f'• Đã thanh toán cọc (50%): {deposit}đ\n'
        f'• Còn lại khi nhận phòng: {remaining}đ\n\n'
        'Vui lòng mang CMND/CCCD khi làm thủ tục check-in. '
        'Nếu cần hỗ trợ thêm, bạn có thể trả lời trực tiếp tại đây.'
    )

    Message.objects.create(
        conversation=conversation,
        sender=staff,
        content=content,
    )
    conversation.updated_at = timezone.now()
    conversation.save(update_fields=['updated_at'])
    return conversation
